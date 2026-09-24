#!/usr/bin/env python3
"""Tapback acknowledgements: a Bot reacts to the message it just picked up.

Hermes already carries the mechanism — `react_to_message` in the Desktop's `desktop_ui` toolset (it
defaults to the triggering message), and messaging adapters expose the same through
`send_message(action="react")`. What was missing is a Bot knowing *when* to use it. This writes that
convention into the Bot's persona: one reaction on pickup, one on the outcome, and never a reaction
instead of an answer.
"""

from pathlib import Path

ACK_MARKER = "<!-- bot-forge-acks:v2 -->"
LEGACY_MARKERS = ("<!-- bot-forge-acks:v1 -->",)

ACKS = [
    ("👀", "you picked the work up and are starting it"),
    ("💬", "you are answering right now, no work needed first"),
    ("✅", "the work is finished"),
    ("✋", "you need the user's approval before going further"),
    ("⚠️", "you are blocked, or something failed"),
    ("⏳", "you scheduled it for later instead of doing it now"),
]

ACK_POLICY = f"""{ACK_MARKER}
## Say where the request stands
Begin every reply with one emoji that shows the state of the user's request, then a space, then your
answer as normal.

""" + "\n".join(f"- {emoji} — {meaning}" for emoji, meaning in ACKS) + """

- One emoji, at the very start, and nothing else about it: no "reacting now", no explanation.
- The emoji is never the whole reply. Answer as you otherwise would.
- If a single turn starts work and finishes it, use the end state (✅, ✋ or ⚠️).

(Emoji tapbacks are a separate, human thing in Hermes — use `react_to_message` only when a person
genuinely would, never as a status signal.)
"""


def acks_enabled(pdir: Path) -> bool:
    soul = pdir / "SOUL.md"
    return soul.exists() and ACK_MARKER in soul.read_text(errors="ignore")


def _strip_legacy(soul: str) -> str:
    """Remove an older convention block so a Bot never carries two contradictory ones."""
    for marker in LEGACY_MARKERS:
        while marker in soul:
            start = soul.index(marker)
            nxt = soul.find("\n## ", soul.index("\n", start))
            end = len(soul)
            while nxt != -1:
                heading = soul[nxt + 1:soul.find("\n", nxt + 1)]
                if not heading.startswith("## Acknowledge") and not heading.startswith("## Say where"):
                    end = nxt + 1
                    break
                nxt = soul.find("\n## ", nxt + 1)
            soul = (soul[:start].rstrip() + "\n\n" + soul[end:].lstrip()).strip() + "\n"
    return soul


def apply_policy(soul: str) -> str:
    """Add the convention, replacing any older version of it."""
    if ACK_MARKER in (soul or ""):
        return soul
    soul = _strip_legacy(soul or "")
    return (soul.rstrip() + "\n\n" if soul.strip() else "") + ACK_POLICY.rstrip() + "\n"


def enable_acks(pdir: Path) -> dict:
    """Turn acknowledgements on for an existing Bot without replacing its persona."""
    soul = pdir / "SOUL.md"
    text = soul.read_text(errors="ignore") if soul.exists() else ""
    if ACK_MARKER in text:
        return {"enabled": True, "changed": False, "backup": None}
    upgraded = any(m in text for m in LEGACY_MARKERS)
    import manage

    backup = manage._backup(pdir, "SOUL.md")
    soul.write_text(apply_policy(text))
    return {"enabled": True, "changed": True, "upgraded": upgraded, "backup": backup or None}
