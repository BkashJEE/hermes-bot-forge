#!/usr/bin/env python3
"""Human-readable, append-only work journals for Bot Forge Bots.

The journal records observable work: goal, outcome, evidence and next steps. It
must never contain credentials or private chain-of-thought. Each Bot owns dated
Markdown files under ``<profile>/journal/``.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import forge
import portable

JOURNAL_MARKER = "<!-- bot-forge-journal:v1 -->"
JOURNAL_POLICY = f"""{JOURNAL_MARKER}
## Work journal
- After meaningful work, use `agent_journal` to record the goal, observable result, evidence, and next step.
- Journal completed work, material decisions, failures, and blockers. Skip routine conversation.
- Never store credentials, private reasoning, hidden chain-of-thought, or facts about the user that are unrelated to the job.
- Keep entries concise and factual so the user and future sessions can audit what happened.
"""

README = """# Bot work journal

This directory is maintained by Bot Forge. Files are append-only daily Markdown logs.

Entries contain user-visible facts: the goal, outcome, evidence, and next step. They must
not contain credentials, authentication material, private reasoning, or hidden chain-of-thought.
Use the `agent_journal` tool to add or read entries.
"""

STATUSES = {"planned", "progress", "completed", "blocked", "failed"}
MAX_SUMMARY = 4_000
MAX_ITEM = 500
MAX_ITEMS = 20
MAX_READ = 50
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _safe_journal_dir(pdir: Path) -> Path:
    """Return the journal directory, refusing a symlink escape."""
    pdir = pdir.resolve()
    folder = pdir / "journal"
    if folder.is_symlink():
        raise ValueError("journal directory cannot be a symlink")
    folder.mkdir(mode=0o700, exist_ok=True)
    resolved = folder.resolve()
    if not resolved.is_relative_to(pdir):
        raise ValueError("journal directory escaped the Bot profile")
    try:
        os.chmod(resolved, 0o700)
    except OSError:
        pass
    return resolved


def ensure_journal(pdir: Path) -> Path:
    folder = _safe_journal_dir(pdir)
    readme = folder / "README.md"
    if not readme.exists():
        readme.write_text(README)
        try:
            os.chmod(readme, 0o600)
        except OSError:
            pass
    return folder


def journaling_enabled(pdir: Path) -> bool:
    soul = pdir / "SOUL.md"
    return soul.exists() and JOURNAL_MARKER in soul.read_text(errors="ignore")


def enable_journal(pdir: Path) -> dict:
    """Enable journal guidance without replacing the Bot's existing persona."""
    folder = ensure_journal(pdir)
    soul = pdir / "SOUL.md"
    text = soul.read_text(errors="ignore") if soul.exists() else ""
    changed = JOURNAL_MARKER not in text
    backup = ""
    if changed:
        import manage

        backup = manage._backup(pdir, "SOUL.md")
        soul.write_text((text.rstrip() + "\n\n" if text.strip() else "") + JOURNAL_POLICY.rstrip() + "\n")
    return {"enabled": True, "changed": changed, "path": str(folder), "backup": backup or None}


def _clean_line(value: object, limit: int = MAX_ITEM) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _items(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [item for item in (_clean_line(v) for v in values[:MAX_ITEMS]) if item]


def _entry_markdown(spec: dict, now: datetime) -> tuple[str, dict]:
    status = _clean_line(spec.get("status") or "progress", 20).lower()
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(sorted(STATUSES))}")
    title = _clean_line(spec.get("title"), 120)
    summary = str(spec.get("summary") or "").strip()
    if not title or not summary:
        raise ValueError("journal add needs a title and summary")
    if len(summary) > MAX_SUMMARY:
        raise ValueError(f"summary is longer than {MAX_SUMMARY} characters")
    evidence = _items(spec.get("evidence"))
    next_steps = _items(spec.get("next_steps"))
    tags = sorted(set(_clean_line(v, 40).lower() for v in (spec.get("tags") or []) if _clean_line(v, 40)))[:12]
    scan_blob = "\n".join([title, summary, *evidence, *next_steps, *tags])
    scan = portable.scan_text(scan_blob)
    if scan["verdict"] != "CLEAN":
        raise ValueError("journal entry looks like it contains sensitive or credential-like text; nothing was written")

    stamp = now.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    lines = [f"## {stamp} · {status} · {title}", "", summary]
    if evidence:
        lines += ["", "**Evidence**", *[f"- {v}" for v in evidence]]
    if next_steps:
        lines += ["", "**Next steps**", *[f"- {v}" for v in next_steps]]
    if tags:
        lines += ["", "**Tags:** " + ", ".join(tags)]
    return "\n".join(lines).rstrip() + "\n", {"timestamp": stamp, "status": status, "title": title,
                                                   "scan": scan, "tags": tags}


def add_entry(pdir: Path, spec: dict, now: datetime | None = None) -> dict:
    if not journaling_enabled(pdir):
        raise ValueError("journaling is not enabled for this Bot; call agent_journal with action='enable' first")
    now = now or datetime.now(timezone.utc)
    folder = ensure_journal(pdir)
    utc_date = now.astimezone(timezone.utc).date().isoformat()
    path = folder / f"{utc_date}.md"
    if path.exists() and path.is_symlink():
        raise ValueError("journal file cannot be a symlink")
    entry, meta = _entry_markdown(spec, now)
    prefix = "" if path.exists() and path.stat().st_size else f"# Work journal — {utc_date}\n\n"
    payload = (prefix + ("\n---\n\n" if not prefix else "") + entry).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        remaining = memoryview(payload)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                raise OSError("journal append wrote no data")
            remaining = remaining[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    return {"written": True, "path": str(path), **meta}


def read_entries(pdir: Path, spec: dict) -> dict:
    folder = pdir.resolve() / "journal"
    if not folder.exists():
        return {"entries": [], "count": 0, "query": str(spec.get("query") or "").strip().lower() or None,
                "enabled": journaling_enabled(pdir)}
    if not folder.is_dir() or folder.is_symlink() or not folder.resolve().is_relative_to(pdir.resolve()):
        raise ValueError("journal directory is not a safe directory inside the Bot profile")
    date = _clean_line(spec.get("date"), 10)
    if date and not DATE_RE.fullmatch(date):
        raise ValueError("date must be YYYY-MM-DD")
    try:
        limit = max(1, min(int(spec.get("limit") or 10), MAX_READ))
    except (TypeError, ValueError):
        raise ValueError(f"limit must be an integer from 1 to {MAX_READ}")
    query = str(spec.get("query") or "").strip().lower()
    paths = [folder / f"{date}.md"] if date else sorted(folder.glob("????-??-??.md"), reverse=True)
    entries = []
    for path in paths:
        if not path.is_file() or path.is_symlink():
            continue
        text = path.read_text(errors="ignore")
        for block in reversed(re.split(r"\n---\n", text)):
            block = block.strip()
            if not block or block.startswith("# Work journal —") and "\n## " not in block:
                continue
            if block.startswith("# Work journal —"):
                block = block.split("\n", 2)[-1].strip()
            if query and query not in block.lower():
                continue
            entries.append({"date": path.stem, "entry": block})
            if len(entries) >= limit:
                return {"entries": entries, "count": len(entries), "query": query or None,
                        "enabled": journaling_enabled(pdir)}
    return {"entries": entries, "count": len(entries), "query": query or None,
            "enabled": journaling_enabled(pdir)}


def _target(root: Path, spec: dict) -> Path:
    import manage

    name = str(spec.get("name") or spec.get("launch_profile") or "").strip()
    if not name or name == "default":
        raise ValueError("choose a Bot name, or call this from that Bot's own chat")
    return manage._require_bot(root, name)


def operate(spec: dict) -> dict:
    root = Path(spec.get("hermes_root") or forge.default_root())
    try:
        pdir = _target(root, spec)
        action = _clean_line(spec.get("action"), 20).lower()
        if action == "enable":
            result = enable_journal(pdir)
        elif action == "add":
            result = add_entry(pdir, spec)
        elif action == "read":
            result = read_entries(pdir, spec)
        else:
            return {"ok": False, "error": "action must be enable, add, or read"}
        return {"ok": True, "name": pdir.name, "action": action, **result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main() -> None:
    raw = sys.stdin.read() if len(sys.argv) < 2 or sys.argv[1] == "-" else Path(sys.argv[1]).read_text()
    result = operate(json.loads(raw))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
