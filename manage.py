#!/usr/bin/env python3
"""Manage existing Hermes Bots: edit, duplicate, hide, export, import, delete.

usage: manage.py spec.json   (or: manage.py - < spec.json)

Spec: {"op": "update"|"copy"|"hide"|"show"|"export"|"import"|"delete", "hermes_root": "...",
       "settings": {...}, ...op-specific fields}

Every op prints one JSON result. Nothing here creates a Bot — that is forge.py.
"""
import json
import os
import re
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
        if meta_changes.get("title") and soul_path.exists():
            backups.setdefault("SOUL.md", _backup(pdir, "SOUL.md"))
            soul_path.write_text(forge.ensure_identity(soul_path.read_text(), meta_changes["title"],
                                                       s.get("role") or "Bot", name))

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
        problem = forge.check_routine(r)
        if problem:
            raise ValueError(problem)
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
        # A copy gets a fresh work history. Private backups, not copies/templates,
        # are the mechanism for preserving a Bot's journal.
        shutil.rmtree(pdir / "journal", ignore_errors=True)
        forge.write_bot_meta(pdir, display, description, s.get("avatar_kind") or "")
        soul = (pdir / "SOUL.md").read_text() if (pdir / "SOUL.md").exists() else ""
        (pdir / "SOUL.md").write_text(forge.ensure_identity(soul, display, s.get("role") or "Bot", new_id))
        if settings.get("journal_enabled", True):
            import journal

            journal.enable_journal(pdir)
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


def _export_target(root: Path, requested, default_name: str):
    """Resolve an export path: always under <root>/profile-exports, never over an existing file.
    Returns (path, None) or (None, error)."""
    allowed = (root / "profile-exports").resolve()
    out = (allowed / default_name) if not requested else Path(requested).expanduser()
    if not out.is_absolute():
        out = allowed / out
    out = out.resolve()
    if not out.is_relative_to(allowed):
        return None, f"exports must stay under {allowed} — pass a file name or a path inside that directory"
    if out.exists():
        return None, f"{out} already exists — pick another name (nothing was overwritten)"
    return out, None


def op_export(s: dict, root: Path, settings: dict) -> dict:
    """Share a Bot. Default: a portable .botforge.json template (design only, secret-scanned).
    mode=backup: a full `hermes profile export` for the user's own safekeeping — includes chat history."""
    import portable
    pdir = _require_bot(root, s.get("name"))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if (s.get("mode") or "template") == "backup":
        out, err = _export_target(root, s.get("path"), f"{pdir.name}-{stamp}.tar.gz")
        if err:
            return {"ok": False, "name": pdir.name, "error": err}
        out.parent.mkdir(parents=True, exist_ok=True)
        forge.run(root, "profile", "export", pdir.name, "-o", str(out), timeout=600)
        if not out.exists():
            raise RuntimeError("export produced no archive")
        return {"ok": True, "name": pdir.name, "mode": "backup", "path": str(out),
                "size_mb": round(out.stat().st_size / 1e6, 1),
                "note": "full backup INCLUDING chat history and facts about the user — keep it private; "
                        "use the default template mode to share a Bot with someone"}

    tpl = portable.build_template(pdir, root)
    text = json.dumps(tpl, indent=2, ensure_ascii=False)
    scan = portable.scan_text(text)
    if scan["verdict"] == "BLOCK" and not settings.get("allow_secrets"):
        return {"ok": False, "name": pdir.name, "scan": scan,
                "error": "the Bot's persona, memory or skills contain what looks like a credential — nothing was "
                         "written. Remove it with update_agent, then share again."}
    out, err = _export_target(root, s.get("path"), f"{pdir.name}.botforge.json")
    if err:
        return {"ok": False, "name": pdir.name, "error": err}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
    return {"ok": True, "name": pdir.name, "mode": "template", "path": str(out), "scan": scan,
            "size_kb": round(out.stat().st_size / 1000, 1),
            "contains": ["persona", "its own memory", "tools", "skill choices",
                         f"{len(tpl['taught_skills'])} taught skill(s)", f"{len(tpl['routines'])} routine(s)"],
            "never_contains": ["chat history", "work journal", "facts about the user", "API keys or logins"],
            "note": "a readable JSON file — safe to post as a gist or commit to a repo"
                    + (" (review the WARN findings first)" if scan["verdict"] == "WARN" else "")}


def op_import(s: dict, root: Path, settings: dict) -> dict:
    """Import a Bot: a .botforge.json template (built fresh, like create_agent) or a .tar.gz backup (restored)."""
    path = Path(s.get("path") or "").expanduser()
    if not path.is_file():
        return {"ok": False, "error": f"no file at {path}"}
    if path.name.endswith(".json"):
        spec = {"template": str(path), "display_name": s.get("display_name"), "hermes_root": str(root),
                "settings": settings, "launch_profile": s.get("launch_profile") or "default"}
        return forge.forge(spec)

    taken = forge.existing_bot_names(root)
    display, new_id, err = forge.pick_name(s.get("display_name") or path.stem.split("-")[0], taken)
    if err:
        return {"ok": False, "error": err}
    forge.run(root, "profile", "import", str(path), "--name", new_id, timeout=600)
    pdir = root / "profiles" / new_id
    if not (pdir / "config.yaml").exists():
        return {"ok": False, "error": "import did not produce a usable profile"}
    if s.get("display_name"):
        _save_bot_meta(pdir, {"title": display})
    if settings.get("install_gateway", True) and os.name != "nt":
        forge.run(root, "-p", new_id, "gateway", "install", "--start-now", "--start-on-login", check=False, timeout=120)
    return {"ok": True, "name": new_id, "display_name": _bot_meta(pdir).get("title") or display, "mode": "backup",
            "note": "restored from a full backup, including its chat history"}


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
            res = op_export({"name": pdir.name, "mode": "backup"}, root, settings)
        except Exception as exc:
            res = {"ok": False, "error": str(exc)}
        if not res.get("ok"):
            return {"ok": False, "name": pdir.name, "deleted": False,
                    "error": f"backup failed, so {pdir.name} was NOT deleted: {res.get('error')}. Fix the export, "
                             "turn off plugins.entries.bot-forge.settings.backup_before_delete, or run "
                             f"`hermes profile delete {pdir.name}` by hand."}
        backup = res.get("path")
    forge.run(root, "profile", "delete", "-y", pdir.name, timeout=300)
    return {"ok": True, "name": pdir.name, "deleted": True, "backup": backup,
            "note": "restore with `hermes profile import <backup>`" if backup else "no backup was made"}


def op_teach(s: dict, root: Path, settings: dict) -> dict:
    """Save a repeatable procedure as a skill the Bot loads on demand — 'remember how I do X'."""
    pdir = _require_bot(root, s.get("name"))
    skill = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s.get("skill") or "").lower())).strip("-")[:48]
    if not skill:
        raise ValueError("need a short skill name, e.g. 'weekly-report'")
    steps = [str(x).strip() for x in (s.get("steps") or []) if str(x).strip()]
    body = (s.get("body") or "").strip()
    if not steps and not body:
        raise ValueError("need either `steps` or a full `body`")
    description = (s.get("description") or f"How to {skill.replace('-', ' ')}.").strip()
    when = (s.get("when") or "").strip()
    if len(body.encode()) > MAX_SOUL_BYTES:
        raise ValueError(f"body is larger than {MAX_SOUL_BYTES} bytes")

    doc = body or "\n".join([
        f"# {skill.replace('-', ' ').title()}", "",
        "## Overview", description, "",
        "## When to use", when or f"When the user asks about {skill.replace('-', ' ')}.", "",
        "## Steps", *[f"{i}. {step}" for i, step in enumerate(steps, 1)], "",
    ])
    front = (f"---\nname: {skill}\ndescription: \"{description}\"\nversion: 1.0.0\n"
             f"metadata:\n  hermes:\n    tags: [taught]\n---\n\n")
    dest = pdir / "skills" / "taught" / skill
    dest.mkdir(parents=True, exist_ok=True)
    existing = (dest / "SKILL.md").exists()
    if existing:
        _backup(pdir, f"skills/taught/{skill}/SKILL.md")
    (dest / "SKILL.md").write_text(front + doc.strip() + "\n")

    # a taught skill is useless if the category sits in the disabled list
    cfg_path = pdir / "config.yaml"
    cfg = forge.load_yaml(cfg_path)
    skills_cfg = cfg.get("skills") if isinstance(cfg.get("skills"), dict) else {}
    disabled = [d for d in (skills_cfg.get("disabled") or []) if d != skill]
    if disabled != (skills_cfg.get("disabled") or []):
        skills_cfg["disabled"] = disabled
        cfg["skills"] = skills_cfg
        forge.dump_yaml(cfg_path, cfg)
    return {"ok": True, "name": pdir.name, "skill": skill, "updated": existing,
            "path": str(dest / "SKILL.md"),
            "note": f"{pdir.name} can now load this with skill_view('{skill}') — try asking it to use it"}


OPS = {"teach": op_teach, "update": op_update, "copy": op_copy, "export": op_export, "import": op_import, "delete": op_delete,
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
