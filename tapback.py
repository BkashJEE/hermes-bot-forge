"""Put the acknowledgement on the user's own message, the moment the turn starts.

The persona convention (acks.py) prefixes the reply, which works everywhere but only appears once the
Bot answers. In the Hermes desktop app a Bot can also tapback the user's message — and that should not
depend on the model choosing to: Hermes' own `react_to_message` tells the model it is a human touch,
"never as a status signal", so asking it to signal status fights the tool's own instructions.

Instead the plugin places the reaction itself: 👀 when the turn begins, then the outcome when it ends.
Desktop sessions only (that is where the tool exists), best effort, and never able to break a turn.
"""

WORKING = "👀"
DONE = "✅"
BLOCKED = "⚠️"
NEEDS_YOU = "✋"

# Only these surfaces have the reaction tool (tui_gateway/server.py::_gui_surface_toolsets).
REACTING_PLATFORMS = {"desktop"}
BLOCKED_HINTS = ("i can't", "i cannot", "unable to", "blocked", "failed", "error")
APPROVAL_HINTS = ("your approval", "before i ", "shall i", "do you want me to", "confirm first",
                  "let me know if you want")


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


class Tapback:
    """Hook pair: react when a turn starts, update the reaction when it ends."""

    def __init__(self, ctx, setting):
        self._ctx = ctx
        self._setting = setting

    def _react(self, emoji: str) -> bool:
        try:
            self._ctx.dispatch_tool("react_to_message", {"emoji": emoji})
            return True
        except Exception:  # reactions off, wrong surface, no session — never break the turn
            return False

    def on_turn_start(self, platform=None, **kwargs):
        if should_react(platform, self._setting()):
            self._react(WORKING)
        return None

    def on_turn_end(self, platform=None, assistant_response=None, **kwargs):
        if should_react(platform, self._setting()):
            self._react(outcome_emoji(assistant_response or ""))
        return None
