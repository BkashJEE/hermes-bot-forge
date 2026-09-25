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


def reactions_allowed() -> bool:
    """Honour Settings → Appearance → Message Reactions, the same switch the tool itself checks."""
    try:
        from tools import desktop_ui
        return bool(desktop_ui.user_enabled("message_reactions", default=False))
    except Exception:
        return False


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

    def on_turn_start(self, platform=None, **kwargs):
        if self._on(platform):
            self._react(WORKING)
        return None

    def on_turn_end(self, platform=None, assistant_response=None, **kwargs):
        if self._on(platform):
            self._react(outcome_emoji(assistant_response or ""))
        return None
