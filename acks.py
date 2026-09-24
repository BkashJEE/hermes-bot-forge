#!/usr/bin/env python3
"""Tapback acknowledgements: a Bot reacts to the message it just picked up.

Hermes already carries the mechanism — `react_to_message` in the Desktop's `desktop_ui` toolset (it
defaults to the triggering message), and messaging adapters expose the same through
`send_message(action="react")`. What was missing is a Bot knowing *when* to use it. This writes that
convention into the Bot's persona: one reaction on pickup, one on the outcome, and never a reaction
instead of an answer.
"""

from pathlib import Path

ACK_MARKER = "<!-- bot-forge-acks:v1 -->"

ACKS = [
    ("👀", "you picked up a task and are starting it"),
    ("💬", "you can answer right now, without doing work first"),
    ("✅", "the work is finished"),
    ("✋", "you need the user's approval before going further"),
    ("⚠️", "you are blocked, or something failed"),
    ("⏳", "you scheduled it for later instead of doing it now"),
]

ACK_POLICY = f"""{ACK_MARKER}
## Acknowledge with a reaction
React to the user's message so they can see where their request stands, using `react_to_message` in the
Hermes desktop app, or `send_message(action="react")` on a messaging platform.

""" + "\n".join(f"- {emoji} — {meaning}" for emoji, meaning in ACKS) + """

- React once when you pick the work up, and once when it ends. Not on every message, and never more than
  twice for one request.
- A reaction is never an answer. Always reply as well; if a reaction fails or the surface has no
  reactions, just reply normally and say nothing about it.
"""


def acks_enabled(pdir: Path) -> bool:
    soul = pdir / "SOUL.md"
    return soul.exists() and ACK_MARKER in soul.read_text(errors="ignore")


def apply_policy(soul: str) -> str:
    """Append the convention to a persona that doesn't have it yet."""
    if ACK_MARKER in (soul or ""):
        return soul
    return (soul.rstrip() + "\n\n" if (soul or "").strip() else "") + ACK_POLICY.rstrip() + "\n"


def enable_acks(pdir: Path) -> dict:
    """Turn acknowledgements on for an existing Bot without replacing its persona."""
    soul = pdir / "SOUL.md"
    text = soul.read_text(errors="ignore") if soul.exists() else ""
    if ACK_MARKER in text:
        return {"enabled": True, "changed": False, "backup": None}
    import manage

    backup = manage._backup(pdir, "SOUL.md")
    soul.write_text(apply_policy(text))
    return {"enabled": True, "changed": True, "backup": backup or None}
