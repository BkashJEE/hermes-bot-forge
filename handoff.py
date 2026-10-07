#!/usr/bin/env python3
"""Hand a piece of work from one Bot to another, with its context, and keep the record.

usage: handoff.py spec.json   (or: handoff.py - < spec.json)

Spec:
{
  "to": "nova",                      # the Bot that takes the work (profile id or roster title)
  "task": "Draft Thursday's thread", # what it now owns, one sentence or a short paragraph
  "context": "...",                  # optional: what the sender already knows — findings, links, constraints
  "from": "marshal",                 # set by the plugin: the profile whose turn called the tool
  "hermes_root": "...", "settings": {...}
}

`ask_agent` asks a question and gets an answer. A handoff moves ownership: the receiving Bot is told
it now owns the task end to end, the work runs in *its own* Bot Chat so the user can watch it in
Desktop, and the outcome is read from the reply's acknowledgement — the ✅ / ✋ / ⚠️ prefix every Bot
Forge Bot starts its replies with — so the result is a state, not a blob of text to interpret.

The record lives in the receiving Bot's profile (``handoffs/<id>.json``) and both Bots journal it,
so "what did Nova work on" and "anything waiting on me" already know about it. ``check_agents``
lists the handoffs that are still open.

Nothing travels with a handoff but words: no files are copied, no credential or environment leaves
the sending Bot, and the task and context are secret-scanned before anything is sent.
"""
import json
import os
import random
import re
import string
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

if __package__:  # Hermes imports this as a package; the CLI entry points run it as a script
    from . import forge, portable
else:
    import forge
    import portable

MAX_TASK = 2_000
MAX_CONTEXT = 8_000
MAX_TURNS = 30
CHAT_TIMEOUT = 840  # the tool's own subprocess timeout is 960s; leave room to write the record
REPLY_KEEP = 4_000

# What the receiving Bot's first emoji means for the handoff. These are the end states of the
# acknowledgement convention (acks.ACKS); anything else means it replied without finishing.
OUTCOMES = {"✅": "completed", "✋": "needs_you", "⚠️": "blocked", "⏳": "scheduled"}
OPEN_STATES = ("needs_you", "blocked", "scheduled", "replied", "sent")
ICONS = {"completed": "✅", "needs_you": "✋", "blocked": "⚠️", "scheduled": "⏳", "replied": "💬", "sent": "📨"}
MAX_LISTED = 25


def new_id(now: float | None = None) -> str:
    stamp = time.strftime("%Y%m%d", time.gmtime(now or time.time()))
    return "hf-" + stamp + "-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))


def outcome(reply: str) -> str:
    """The handoff's state, read from the acknowledgement the Bot began its reply with."""
    head = (reply or "").lstrip()[:4]
    for emoji, state in OUTCOMES.items():
        if head.startswith(emoji):
            return state
    return "replied" if (reply or "").strip() else "sent"


def display_name(root: Path, profile: str) -> str:
    home = root if profile == "default" else root / "profiles" / profile
    meta = forge.load_yaml(home / "profile.yaml")
    bots = (meta.get("ui_meta") or {}).get("hermes-bots")
    title = (bots.get("title") if isinstance(bots, dict) else None) or meta.get("display_name")
    return str(title) if title else ("you" if profile == "default" else profile)


def compose(handoff_id: str, sender: str, sender_display: str, task: str, context: str) -> str:
    """The message the receiving Bot gets. It says who, what, what is already known, and how to answer."""
    who = f"@{sender} ({sender_display})" if sender != "default" else "the user's main agent"
    lines = [f"🤝 Handoff from {who} — id {handoff_id}.",
             "You own this task now. Finish it end to end; come back to the user only for something that "
             "needs their approval.",
             "", f"Task: {task}"]
    if context:
        lines += ["", f"What {sender_display if sender != 'default' else 'they'} already know:", context]
    lines += ["", "When you stop, begin your reply with ✅ if it is done, ✋ if you need the user's approval, "
                  "or ⚠️ if you are blocked — then the result itself. Record the outcome in your journal with "
                  f"the tag handoff:{handoff_id}."]
    return "\n".join(lines)


def _record_path(pdir: Path, handoff_id: str) -> Path:
    folder = pdir / "handoffs"
    if folder.is_symlink():
        raise ValueError("handoffs directory cannot be a symlink")
    folder.mkdir(mode=0o700, exist_ok=True)
    return folder / f"{handoff_id}.json"


def _write_record(pdir: Path, record: dict) -> Path:
    path = _record_path(pdir, record["id"])
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)
    return path


def _journal(root: Path, profile: str, entry: dict, settings: dict, push: bool) -> dict:
    """Journal one side of the handoff. Never raises: a journal that is off, or a reply the secret
    scanner dislikes, must not undo a handoff that already happened."""
    if __package__:
        from . import journal
    else:
        import journal

    pdir = root / "profiles" / profile
    if profile == "default" or not journal.journaling_enabled(pdir):
        return {"written": False, "reason": "journal not enabled"}
    try:
        if push:  # operate() is what mails the user about a blocked entry
            out = journal.operate({**entry, "action": "add", "name": profile, "hermes_root": str(root),
                                   "settings": settings})
            if not out.get("ok"):
                return {"written": False, "reason": out.get("error", "")[:160]}
            return {"written": True, "path": out.get("path"), "notified": out.get("notified")}
        out = journal.add_entry(pdir, entry)
        return {"written": True, "path": out.get("path")}
    except Exception as exc:
        return {"written": False, "reason": str(exc)[:160]}


def _entry_status(state: str) -> str:
    if state == "completed":
        return "completed"
    if state in ("needs_you", "blocked"):
        return "blocked"
    return "progress"


def handoff(s: dict, now: datetime | None = None) -> dict:
    if __package__:
        from . import manage
    else:
        import manage

    root = Path(s.get("hermes_root") or forge.default_root())
    settings = s.get("settings") or {}
    now = now or datetime.now(UTC)
    task = re.sub(r"\s+", " ", str(s.get("task") or "")).strip()
    context = str(s.get("context") or "").strip()
    if not task:
        return {"ok": False, "error": "a handoff needs a task — what the other Bot now owns"}
    if len(task) > MAX_TASK:
        return {"ok": False, "error": f"task is longer than {MAX_TASK} characters; put the detail in context"}
    if len(context) > MAX_CONTEXT:
        return {"ok": False, "error": f"context is longer than {MAX_CONTEXT} characters — hand over a summary and "
                                      "where the rest is, not the whole thing"}
    try:
        pdir = manage._require_bot(root, str(s.get("to") or ""))
    except ValueError as exc:
        return {"ok": False, "error": f"{exc}. A handoff goes to a Bot (see list_agents), never to your main profile."}
    to = pdir.name
    sender = re.sub(r"[^a-z0-9_-]", "", str(s.get("from") or "default").lower()) or "default"
    if sender == to:
        return {"ok": False, "error": f"@{to} cannot hand work to itself"}
    # Words only cross between Bots, and never a credential: a key pasted into the context would
    # otherwise land in another Bot's chat history and both journals.
    scan = portable.scan_text(f"{task}\n{context}")
    if scan["verdict"] != "CLEAN":
        return {"ok": False, "error": "the task or context looks like it contains a credential — nothing was sent. "
                                      "Hand over where the secret lives, not the secret.", "scan": scan}

    handoff_id = new_id(now.timestamp())
    sender_display = display_name(root, sender)
    to_display = display_name(root, to)
    message = compose(handoff_id, sender, sender_display, task, context)
    started = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    record = {"id": handoff_id, "from": sender, "from_display": sender_display, "to": to, "to_display": to_display,
              "task": task, "context": context, "created": started, "status": "sent", "owner": to}
    # Written before the turn runs, so a crash mid-turn still leaves the user a record of what went where.
    path = _write_record(pdir, record)

    try:
        ok, reply = forge.bot_chat(root, to, message, max_turns=MAX_TURNS, timeout=CHAT_TIMEOUT, env=forge.safe_env(root))
    except Exception as exc:  # the CLI missing, a timeout — the record stays, marked as undelivered
        record.update({"status": "failed", "error": str(exc)[:300]})
        _write_record(pdir, record)
        return {"ok": False, "id": handoff_id, "to": to, "error": f"{to_display} could not run the task: {exc}"[:600],
                "record": str(path)}
    if not ok:
        record.update({"status": "failed", "error": (reply or "no reply")[:300]})
        _write_record(pdir, record)
        return {"ok": False, "id": handoff_id, "to": to, "record": str(path),
                "error": f"{to_display} did not answer: {(reply or '')[-600:]}"}

    state = outcome(reply)
    finished = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    record.update({"status": state, "finished": finished, "reply": reply[-REPLY_KEEP:]})
    _write_record(pdir, record)

    # Both sides remember it. The receiver's entry is the one that counts as "waiting on you" when it
    # needs the user, so it goes through the path that also mails them.
    short = task if len(task) <= 70 else task[:67].rstrip() + "…"
    excerpt = re.sub(r"\s+", " ", reply).strip()[:400]
    receiver_entry = {"title": f"Handoff from {sender_display}: {short}", "status": _entry_status(state),
                      "summary": (f"Needs the user's approval: {excerpt}" if state == "needs_you" else excerpt)
                                 or f"Took over: {task}",
                      "evidence": [f"handoff {handoff_id} from @{sender}"],
                      "tags": ["handoff", handoff_id]}
    sender_entry = {"title": f"Handed off to {to_display}: {short}",
                    "status": "completed" if state == "completed" else "progress",
                    "summary": f"@{to} now owns it. Outcome: {ICONS[state]} {state.replace('_', ' ')}. {excerpt}".strip(),
                    "evidence": [f"handoff {handoff_id} to @{to}"], "tags": ["handoff", handoff_id]}
    journaled = {"to": _journal(root, to, receiver_entry, settings, push=True),
                 "from": _journal(root, sender, sender_entry, settings, push=False)}

    note = {"completed": f"{to_display} finished it.",
            "needs_you": f"{to_display} needs the user's approval before going further — tell them what for.",
            "blocked": f"{to_display} is blocked; it is in the waiting queue. Say what it needs.",
            "scheduled": f"{to_display} scheduled it rather than doing it now.",
            "replied": f"{to_display} replied without a clear end state — read the reply.",
            "sent": f"{to_display} took it but said nothing back."}[state]
    return {"ok": True, "id": handoff_id, "from": sender, "to": to, "to_display": to_display,
            "status": state, "icon": ICONS[state], "owner": to, "reply": reply[-REPLY_KEEP:],
            "journal": journaled, "record": str(path),
            "note": note + " Do not redo the work yourself; report the outcome."}


# ── what is still in flight ──────────────────────────────────────────────────
def _age_days(stamp: str, now: datetime) -> float:
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, (now - when).total_seconds() / 86400)


def open_handoffs(root: Path, now: datetime | None = None) -> dict:
    """Every handoff that has not ended in ✅, across every Bot, newest first. Read-only."""
    root = Path(root)
    now = now or datetime.now(UTC)
    profiles = root / "profiles"
    bots = [d for d in sorted(profiles.iterdir()) if forge.is_live_profile(d)] if profiles.is_dir() else []
    items = []
    for pdir in bots:
        folder = pdir / "handoffs"
        if not folder.is_dir() or folder.is_symlink():
            continue
        for path in folder.glob("hf-*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(record, dict) or record.get("status") == "completed":
                continue
            status = str(record.get("status") or "sent")
            items.append({"id": record.get("id") or path.stem, "from": record.get("from"),
                          "from_display": record.get("from_display") or record.get("from"),
                          "to": pdir.name, "to_display": record.get("to_display") or pdir.name,
                          "task": str(record.get("task") or "")[:200], "status": status,
                          "icon": ICONS.get(status, "⚠️"), "since": record.get("created") or "",
                          "age_days": round(_age_days(str(record.get("created") or ""), now), 1)})
    items.sort(key=lambda i: i["since"], reverse=True)
    items = items[:MAX_LISTED]
    return {"count": len(items), "items": items,
            "summary": ("no handoffs in flight" if not items else
                        "; ".join(f"{i['from_display']} → {i['to_display']}: {i['task'][:60]} ({i['status'].replace('_', ' ')})"
                                  for i in items[:3]) + (f" (+{len(items) - 3} more)" if len(items) > 3 else ""))}


def main():
    raw = sys.stdin.read() if len(sys.argv) < 2 or sys.argv[1] == "-" else Path(sys.argv[1]).read_text()
    result = handoff(json.loads(raw))
    print(json.dumps(result, indent=2))  # ASCII-safe: tools.py reads this through a text pipe on any locale
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
