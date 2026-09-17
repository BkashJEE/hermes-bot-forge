#!/usr/bin/env python3
"""Manage existing Hermes Bots: edit, duplicate, hide, export, import, delete.

usage: manage.py spec.json   (or: manage.py - < spec.json)

Spec: {"op": "update"|"copy"|"hide"|"show"|"export"|"import"|"delete", "hermes_root": "...",
       "settings": {...}, ...op-specific fields}

Every op prints one JSON result. Nothing here creates a Bot — that is forge.py.
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

import yaml

import forge

MAX_SOUL_BYTES = 64_000


def _pdir(root: Path, name: str) -> Path:
    return root if name == "default" else root / "profiles" / name


def _require_bot(root: Path, name: str) -> Path:
    """Resolve a Bot by profile id or Bot Mode title; never the root profile (it is the user's own agent)."""
    name = (name or "").strip()
    if not name:
        raise ValueError("need a Bot name")
    profiles = root / "profiles"
    if profiles.is_dir():
        for d in sorted(profiles.iterdir()):
            if not forge.is_live_profile(d):
                continue
            meta = forge.load_yaml(d / "profile.yaml")
            title = ((meta.get("ui_meta") or {}).get("hermes-bots") or {}).get("title") or meta.get("display_name") or ""
            if name.lower() in {d.name.lower(), str(title).lower(), forge.slug(str(title))}:
                return d
    raise ValueError(f"no Bot named '{name}' (the root profile cannot be managed here)")


def _bot_meta(pdir: Path) -> dict:
    meta = forge.load_yaml(pdir / "profile.yaml")
    bots = (meta.get("ui_meta") or {}).get("hermes-bots")
    return bots if isinstance(bots, dict) else {}


def _save_bot_meta(pdir: Path, changes: dict):
    """Merge changes into ui_meta['hermes-bots'] and bump its revision, like Desktop's profiles.configure."""
    path = pdir / "profile.yaml"
    data = forge.load_yaml(path)
    ui_meta = data.get("ui_meta") if isinstance(data.get("ui_meta"), dict) else {}
    bots = ui_meta.get("hermes-bots") if isinstance(ui_meta.get("hermes-bots"), dict) else {}
    bots.update({k: v for k, v in changes.items() if v is not None})
    ui_meta["hermes-bots"] = bots
    revisions = data.get("_ui_meta_revisions") if isinstance(data.get("_ui_meta_revisions"), dict) else {}
    revisions["hermes-bots"] = int(revisions.get("hermes-bots", 0)) + 1
    data["ui_meta"] = ui_meta
    data["_ui_meta_revisions"] = revisions
    if changes.get("title"):
        data["display_name"] = changes["title"]
    if changes.get("description") is not None:
        data["description"] = changes["description"]
    forge.dump_yaml(path, data)


def _backup(pdir: Path, relpath: str) -> str:
    """Timestamped copy under <profile>/backups/bot-forge/ so an edit is always undoable."""
    src = pdir / relpath
    if not src.exists():
        return ""
    dest = pdir / "backups" / "bot-forge" / f"{Path(relpath).name}.{time.strftime('%Y%m%d-%H%M%S')}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return str(dest)


# ── ops ──────────────────────────────────────────────────────────────────────
def op_update(s: dict, root: Path, settings: dict) -> dict:
    """Edit a Bot in place: persona, title/description, tools, skills, model, face, routines."""
    pdir = _require_bot(root, s.get("name"))
    name = pdir.name
    changed, backups = [], {}

    # persona
    soul_path = pdir / "SOUL.md"
    soul = soul_path.read_text() if soul_path.exists() else ""
    new_soul = s.get("soul_md")
    append = s.get("soul_append")
    if new_soul or append:
        if new_soul and len(new_soul.encode()) > MAX_SOUL_BYTES:
            raise ValueError(f"soul_md is larger than {MAX_SOUL_BYTES} bytes")
        backups["SOUL.md"] = _backup(pdir, "SOUL.md")
        title = _bot_meta(pdir).get("title") or name.capitalize()
        soul = new_soul if new_soul else (soul.rstrip() + "\n\n" + append.strip() + "\n")
        soul_path.write_text(forge.ensure_identity(soul, title, s.get("role") or "Bot", name))
        changed.append("soul")

    # roster identity
    meta_changes = {k: s.get(k) for k in ("description",) if s.get(k) is not None}
    if s.get("display_name"):
        meta_changes["title"] = forge.proper_case(s["display_name"])
    if s.get("avatar_kind") in forge.BLOB_KINDS:
        seed = (_bot_meta(pdir).get("shape") or "blobatar::").split(":")[1] or ""
        meta_changes["shape"] = f"blobatar:{seed}:{s['avatar_kind']}"
    if meta_changes:
        _save_bot_meta(pdir, meta_changes)
        changed.append("identity")

    # memory
    if s.get("memory"):
        mem = pdir / "memories" / "MEMORY.md"
        mem.parent.mkdir(exist_ok=True)
        backups["MEMORY.md"] = _backup(pdir, "memories/MEMORY.md")
        existing = mem.read_text().rstrip() if mem.exists() else ""
        mem.write_text((existing + "\n§\n" if existing else "") + "\n§\n".join(s["memory"]) + "\n")
        changed.append("memory")

    # config: tools, skills, model
    cfg_path = pdir / "config.yaml"
    cfg = forge.load_yaml(cfg_path)
    cfg_touched = False
    tools = set((cfg.get("platform_toolsets") or {}).get("cli") or forge.BASE_TOOLSETS)
    add = {t for t in (s.get("add_toolsets") or []) if t in forge.ALL_TOOLSETS}
    remove = {t for t in (s.get("remove_toolsets") or []) if t not in forge.BASE_TOOLSETS}
    if add or remove:
        cfg.setdefault("platform_toolsets", {})["cli"] = sorted((tools | add) - remove)
        cfg_touched = True
        changed.append("tools")
    if s.get("skill_categories"):
        disabled = forge.disabled_skills(pdir / "skills", set(s["skill_categories"]) | forge.ALWAYS_KEEP_CATEGORIES)
        skills_cfg = cfg.get("skills") if isinstance(cfg.get("skills"), dict) else {}
        skills_cfg["disabled"] = sorted(disabled)
        cfg["skills"] = skills_cfg
        cfg_touched = True
        changed.append("skills")
    if s.get("model"):
        cfg["model"] = s["model"]
        cfg_touched = True
        changed.append("model")
    if cfg_touched:
        backups["config.yaml"] = _backup(pdir, "config.yaml")
        forge.dump_yaml(cfg_path, cfg)

    # routines
    routines_added, routines_removed = [], []
    for r in s.get("add_routines") or []:
        forge.run(root, "-p", name, "cron", "create", r["schedule"], r["prompt"],
                  "--name", r.get("name") or "routine", "--deliver", r.get("deliver") or f"bot-chat:{name}")
        routines_added.append(r.get("name") or r["schedule"])
    for job_id in s.get("remove_routines") or []:
        forge.run(root, "-p", name, "cron", "remove", job_id, check=False)
        routines_removed.append(job_id)
    if routines_added or routines_removed:
        changed.append("routines")

    if not changed:
        return {"ok": False, "name": name, "error": "nothing to update — pass soul_md/soul_append, display_name, "
                                                    "description, memory, add_toolsets, skill_categories, model, "
                                                    "avatar_kind or routines"}
    return {"ok": True, "name": name, "display_name": _bot_meta(pdir).get("title") or name, "changed": changed,
            "routines_added": routines_added, "routines_removed": routines_removed,
            "backups": {k: v for k, v in backups.items() if v},
            "note": "changes apply to the Bot's next turn; its open Bot Chat keeps its history"}


def op_copy(s: dict, root: Path, settings: dict) -> dict:
    """Duplicate a Bot under a new name (config, skills, SOUL.md, memory — not its chat history)."""
    src = _require_bot(root, s.get("name"))
    display, new_id, err = forge.pick_name(s.get("display_name"), forge.existing_bot_names(root))
    if err:
        return {"ok": False, "error": err}
    meta = _bot_meta(src)
    description = s.get("description") or meta.get("description") or ""
    forge.run(root, "profile", "create", new_id, "--clone-from", src.name, "--description", description)
    pdir = root / "profiles" / new_id
    try:
        if settings.get("share_login"):
            forge.share_root_login(root, pdir)
        forge.write_bot_meta(pdir, display, description, s.get("avatar_kind") or "")
        soul = (pdir / "SOUL.md").read_text() if (pdir / "SOUL.md").exists() else ""
        old_title = meta.get("title") or src.name
        (pdir / "SOUL.md").write_text(forge.ensure_identity(soul.replace(old_title, display), display,
                                                            s.get("role") or "Bot", new_id))
        if settings.get("install_gateway", True) and os.name != "nt":
            forge.run(root, "-p", new_id, "gateway", "install", "--start-now", "--start-on-login", check=False, timeout=120)
        return {"ok": True, "name": new_id, "display_name": display, "copied_from": src.name,
                "note": "a fresh copy — no chat history, no routines"}
    except Exception as exc:
        forge.run(root, "profile", "delete", "-y", new_id, check=False)
        return {"ok": False, "name": new_id, "error": str(exc), "rolled_back": True}


def op_hide(s: dict, root: Path, settings: dict, hidden=True) -> dict:
    """Hide/unhide a Bot in the Desktop roster. Display-only: routines and mentions keep working."""
    pdir = _require_bot(root, s.get("name"))
    _save_bot_meta(pdir, {"hidden": hidden})
    return {"ok": True, "name": pdir.name, "hidden": hidden,
            "note": "roster only — the Bot keeps running, and its routines keep firing"}


def op_export(s: dict, root: Path, settings: dict) -> dict:
    """Export a Bot to a .tar.gz archive someone else can import (credentials are not included)."""
    pdir = _require_bot(root, s.get("name"))
    out = Path(s.get("path") or (root / "profile-exports" / f"{pdir.name}-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz")).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    forge.run(root, "profile", "export", pdir.name, "-o", str(out), timeout=600)
    if not out.exists():
        raise RuntimeError("export produced no archive")
    return {"ok": True, "name": pdir.name, "path": str(out), "size_mb": round(out.stat().st_size / 1e6, 1),
            "note": "shareable: SOUL.md, memory, skills, config and routines. API keys and logins are not included."}


def op_import(s: dict, root: Path, settings: dict) -> dict:
    """Import a Bot from a .tar.gz archive produced by export."""
    archive = Path(s.get("path") or "").expanduser()
    if not archive.is_file():
        return {"ok": False, "error": f"no archive at {archive}"}
    taken = forge.existing_bot_names(root)
    display, new_id, err = forge.pick_name(s.get("display_name") or archive.stem.split("-")[0], taken)
    if err:
        return {"ok": False, "error": err}
    forge.run(root, "profile", "import", str(archive), "--name", new_id, timeout=600)
    pdir = root / "profiles" / new_id
    if not (pdir / "config.yaml").exists():
        return {"ok": False, "error": "import did not produce a usable profile"}
    if settings.get("share_login"):
        forge.share_root_login(root, pdir)
    if s.get("display_name"):
        _save_bot_meta(pdir, {"title": display})
    if settings.get("install_gateway", True) and os.name != "nt":
        forge.run(root, "-p", new_id, "gateway", "install", "--start-now", "--start-on-login", check=False, timeout=120)
    return {"ok": True, "name": new_id, "display_name": _bot_meta(pdir).get("title") or display,
            "note": "imported. It has no credentials of its own — check its model before relying on it."}


def op_delete(s: dict, root: Path, settings: dict) -> dict:
    """Delete a Bot permanently. Off unless the operator sets allow_delete, and needs the exact name twice."""
    if not settings.get("allow_delete"):
        return {"ok": False, "error": "deleting Bots is disabled. The user can run `hermes profile delete <name>` "
                                      "themselves, or enable plugins.entries.bot-forge.settings.allow_delete"}
    pdir = _require_bot(root, s.get("name"))
    if (s.get("confirm") or "").strip().lower() != pdir.name:
        return {"ok": False, "error": f"confirm must be exactly '{pdir.name}' to delete this Bot"}
    backup = None
    if settings.get("backup_before_delete", True):
        try:
            backup = op_export({"name": pdir.name}, root, settings).get("path")
        except Exception:
            backup = None
    forge.run(root, "profile", "delete", "-y", pdir.name, timeout=300)
    return {"ok": True, "name": pdir.name, "deleted": True, "backup": backup,
            "note": "restore with `hermes profile import <backup>`" if backup else "no backup was made"}


OPS = {"update": op_update, "copy": op_copy, "export": op_export, "import": op_import, "delete": op_delete,
       "hide": lambda s, r, st: op_hide(s, r, st, True), "show": lambda s, r, st: op_hide(s, r, st, False)}


def manage(s: dict) -> dict:
    root = Path(s.get("hermes_root") or Path.home() / ".hermes")
    settings = {**forge.DEFAULT_SETTINGS, "allow_delete": False, "backup_before_delete": True,
                **{k: v for k, v in (s.get("settings") or {}).items() if v is not None}}
    op = OPS.get((s.get("op") or "").strip().lower())
    if not op:
        return {"ok": False, "error": f"unknown op; use one of {', '.join(sorted(OPS))}"}
    try:
        return op(s, root, settings)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main():
    raw = sys.stdin.read() if len(sys.argv) < 2 or sys.argv[1] == "-" else Path(sys.argv[1]).read_text()
    result = manage(json.loads(raw))
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
