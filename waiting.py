"""What is waiting on the user, across every Bot.

A Bot that gets blocked writes it in its own journal and then goes quiet: the user has to open each
Bot to find out. This reads every Bot's journal and returns the open items — the ones a person still
has to answer — newest first, so an agent can say "three things need you" without being asked twice.

Read-only. An item is open until the same Bot writes a later entry that resolves it.
"""
import re
from datetime import datetime, timezone
from pathlib import Path

import forge

# `## <timestamp> · <status> · <title>` — written by journal.py
ENTRY = re.compile(r"^##\s+(?P<stamp>\S+)\s+·\s+(?P<status>\w+)\s+·\s+(?P<title>.+)$", re.M)
OPEN_STATUSES = {"blocked": "⚠️", "failed": "⚠️"}
RESOLVING = {"completed"}
MAX_ITEMS = 25


def _entries(pdir: Path) -> list:
    """Every journal entry for a Bot, oldest first: (stamp, status, title, body)."""
    folder = pdir / "journal"
    if not folder.is_dir() or folder.is_symlink():
        return []
    found = []
    for path in sorted(folder.glob("????-??-??.md")):
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        marks = list(ENTRY.finditer(text))
        for i, m in enumerate(marks):
            body = text[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(text)]
            found.append((m.group("stamp"), m.group("status").lower(), m.group("title").strip(),
                          body.strip()[:400]))
    return found


def _age_days(stamp: str, now: datetime) -> float:
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, (now - when).total_seconds() / 86400)


def open_items(pdir: Path, now: datetime | None = None) -> list:
    """Blocked or failed entries a later entry hasn't resolved."""
    now = now or datetime.now(timezone.utc)
    entries = _entries(pdir)
    items = []
    for index, (stamp, status, title, body) in enumerate(entries):
        if status not in OPEN_STATUSES:
            continue
        resolved = any(later_status in RESOLVING and later_title.lower() == title.lower()
                       for _s, later_status, later_title, _b in entries[index + 1:])
        if not resolved:
            items.append({"title": title, "status": status, "since": stamp,
                          "age_days": round(_age_days(stamp, now), 1),
                          "detail": body.splitlines()[0][:200] if body else "",
                          "icon": OPEN_STATUSES[status]})
    return items


def waiting_on_user(root: Path, now: datetime | None = None) -> dict:
    """Every open item across every Bot, newest first."""
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    profiles = root / "profiles"
    bots = [d for d in sorted(profiles.iterdir()) if forge.is_live_profile(d)] if profiles.is_dir() else []
    items = []
    for pdir in bots:
        meta = forge.load_yaml(pdir / "profile.yaml")
        title = ((meta.get("ui_meta") or {}).get("hermes-bots") or {}).get("title") or pdir.name
        for item in open_items(pdir, now):
            items.append({"bot": pdir.name, "display_name": title, **item})
    items.sort(key=lambda i: i["since"], reverse=True)
    items = items[:MAX_ITEMS]
    oldest = max((i["age_days"] for i in items), default=0)
    return {"count": len(items), "items": items, "oldest_days": oldest,
            "summary": ("nothing is waiting on you" if not items else
                        "; ".join(f"{i['display_name']}: {i['title']}" for i in items[:3])
                        + (f" (+{len(items) - 3} more)" if len(items) > 3 else ""))}
