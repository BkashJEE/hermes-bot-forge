"""Put the acknowledgement on the user's own message, the moment the turn starts.

The persona convention (acks.py) prefixes the reply, which works everywhere but only appears once the
Bot answers. In the Hermes desktop app a Bot can also tapback the user's message — and that should not
depend on the model choosing to: Hermes' own `react_to_message` tells the model it is a human touch,
"never as a status signal", so asking it to signal status fights the tool's own instructions.

Instead the plugin places the reaction itself: 👀 when the turn begins, then the outcome when it ends.
Desktop sessions only, best effort, and never able to break a turn.

Two things this has to get right, both learned the hard way:

* `react_to_message` registers itself when its module is imported, and that import is lazy — in a
  turn's own process the registry usually has no such entry, so the call comes back "Unknown tool".
  Importing it here is what makes it dispatchable.
* `dispatch_tool` returns failures as a *value*, never as an exception. Catching only exceptions
  made every failed reaction look like a success, which is how a reaction that never once appeared
  still reported as working. `_react` reads the result and says what actually happened.
"""

import json
import re

WORKING = "👀"
DONE = "✅"
BLOCKED = "⚠️"
NEEDS_YOU = "✋"

# What the Bot just picked up, read from the message itself. One 👀 for everything says only "I am
# alive"; this says "I understood what you asked" — which is the whole point of reacting before the
# answer exists. First match wins, so the more specific asks come first, and anything unrecognised
# falls back to 👀 rather than guessing.
PICKUP = (
    ("🔧", r"\b(fix|bug|broken|crash|error|failing|fails|debug|regress|not work|doesn'?t work)"),
    ("🔎", r"\b(research|find|search|look up|look into|investigat|check (on|the|if|whether)|who is|what'?s new|dig into|digging)"),
    ("✍️", r"\b(write|writing|draft|post|thread|tweet|blog|newsletter|caption|copy|rephrase|reword)"),
    ("📊", r"\b(report|analys|analyz|metric|number|revenue|cost|budget|compare|forecast|how many|how much)"),
    ("⏳", r"\b(schedule|remind|every (day|morning|week|monday)|daily|weekly|cron|tomorrow|later|at \d)"),
    ("📋", r"\b(review|read (this|the|through)|look at|take a look|check this|feedback on|pr #?\d|diff)"),
    ("🛠️", r"\b(build|create|make me|implement|add|set ?up|ship|deploy|refactor|migrat|install)"),
    ("👋", r"^\s*(hi|hey|hello|yo|gm|good morning|good evening|thanks|thank you|ta|nice|great|perfect)\b"),
    ("💬", r"(\?\s*$|^\s*(what|why|how|when|where|who|which|is|are|can|should|do|does|did)\b)"),
)

# Only these surfaces have the reaction tool (tui_gateway/server.py::_gui_surface_toolsets).
REACTING_PLATFORMS = {"desktop"}
BLOCKED_HINTS = ("i can't", "i cannot", "unable to", "blocked", "failed", "error")
APPROVAL_HINTS = ("your approval", "before i ", "shall i", "do you want me to", "confirm first",
                  "let me know if you want")


def _text(message) -> str:
    """The user's words, whatever shape the host handed them in."""
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        content = message.get("content") or message.get("text") or ""
        if isinstance(content, list):  # content blocks
            content = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
        return content if isinstance(content, str) else ""
    return str(getattr(message, "content", "") or "")


def pickup_emoji(user_message) -> str:
    """The kind of work that just arrived, from what the user actually wrote."""
    text = _text(user_message).strip().lower()[:400]
    if not text:
        return WORKING
    for emoji, pattern in PICKUP:
        if re.search(pattern, text):
            return emoji
    return WORKING


def outcome_emoji(reply: str) -> str:
    """The state a finished turn ended in, read from what the Bot actually said."""
    text = (reply or "").strip().lower()[:600]
    if any(h in text for h in APPROVAL_HINTS):
        return NEEDS_YOU
    if any(h in text for h in BLOCKED_HINTS):
        return BLOCKED
    return DONE


def should_react(platform: str, enabled: bool) -> bool:
    return bool(enabled) and (platform or "") in REACTING_PLATFORMS


def _ensure_tool() -> bool:
    """Import the tool so it is registered in this process; it is loaded lazily otherwise."""
    try:
        from tools.registry import registry
    except Exception:
        return False
    if registry.get_entry("react_to_message") is not None:
        return True
    try:
        import tools.react_to_message_tool  # noqa: F401 — registers on import
    except Exception:
        return False
    return registry.get_entry("react_to_message") is not None


def _succeeded(result) -> bool:
    """A dispatch result only counts when it says so — errors arrive as ordinary values."""
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (ValueError, TypeError):
            return False
    if not isinstance(result, dict):
        return False
    return bool(result.get("success")) and not result.get("error")


def reactions_setting():
    """Settings → Appearance → Message Reactions: True, False, or None when it cannot be read.

    None is not False. Reporting "the setting is off" when the answer was really "this process
    cannot see Hermes' settings" is the same kind of confident wrong answer as a failed reaction
    reporting success, so the two are kept apart.
    """
    try:
        from tools import desktop_ui
        return bool(desktop_ui.user_enabled("message_reactions", default=False))
    except Exception:
        return None


def reactions_allowed() -> bool:
    """Honour the user's switch; unreadable means don't place a reaction they may not want."""
    return reactions_setting() is True


class Tapback:
    """Hook pair: react when a turn starts, update the reaction when it ends."""

    def __init__(self, ctx, setting):
        self._ctx = ctx
        self._setting = setting

    def _react(self, emoji: str) -> bool:
        """Place the reaction; report truthfully whether it landed."""
        if not _ensure_tool():
            return False
        try:
            result = self._ctx.dispatch_tool("react_to_message", {"emoji": emoji})
        except Exception:  # no session, wrong surface — never break the turn
            return False
        return _succeeded(result)

    def _on(self, platform) -> bool:
        return should_react(platform, self._setting()) and reactions_allowed()

    def on_turn_start(self, platform=None, user_message=None, **kwargs):
        if self._on(platform):
            self._react(pickup_emoji(user_message))
        return None

    def on_turn_end(self, platform=None, assistant_response=None, **kwargs):
        if self._on(platform):
            self._react(outcome_emoji(assistant_response or ""))
        return None
