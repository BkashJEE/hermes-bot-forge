"""Decide what a Bot may do, outside the model.

Hermes dispatches ``pre_tool_call`` to plugin hooks and reads a directive back:
``{"action": "block", "message"}`` refuses the call and the message becomes the tool result;
``{"action": "approve", "message", "rule_key"}`` sends it to the human approval gate. Precedence
is block > approve > none, and one plugin's veto beats another's approve.

Everything here is a pure decision over (tool name, policy). The hook in __init__.py does the
talking to Hermes; this module is what the tests exercise.
"""

# A Bot's own approval wording, as `create_agent` writes it into SOUL.md, names three things.
# These are the tool-name shapes those three cover. They are deliberately about the *name*: a
# tool called `send_email` is asking to send whatever its arguments say, and a policy layer that
# needed to understand every tool's arguments would understand none of them.
SEND = ("send", "post", "publish", "email", "mail", "tweet", "message", "reply", "comment")
SPEND = ("pay", "buy", "purchase", "charge", "checkout", "order", "transfer", "withdraw")
DESTROY = ("delete", "destroy", "remove", "drop", "purge", "wipe", "truncate")

CATEGORIES = (("send, post or publish", SEND),
              ("spend money", SPEND),
              ("delete data", DESTROY))


def _normalise(names):
    """A policy list from config: accept a list of strings, ignore anything else."""
    if not isinstance(names, (list, tuple)):
        return frozenset()
    return frozenset(n.strip().lower() for n in names if isinstance(n, str) and n.strip())


def _category(tool: str):
    """The approval category a tool name falls in, or None.

    Matched on word boundaries rather than substrings, so `undelete_draft` is not a delete and
    `compose_message` is a send only because `message` is a whole word in it.
    """
    parts = set(tool.lower().replace("-", "_").replace(".", "_").split("_"))
    for label, words in CATEGORIES:
        if parts & set(words):
            return label
    return None


def decide(tool: str, policy: dict) -> dict | None:
    """Return the directive for one tool call, or None to stay out of the way.

    `policy` is the plugin's own config in the profile this Bot runs as:

        refuse: [...]   # never, whatever the user says in the moment
        ask:    [...]   # always reach the human approval gate
        allow:  [...]   # explicitly fine, even if it looks like a category
        mode:   ask | allow    # what happens to everything else
        guard_defaults: true   # apply the three built-in categories
    """
    if not isinstance(tool, str) or not tool.strip():
        # A call we cannot even name is not one we can reason about. Hermes will have its own
        # view; ours is to abstain rather than to guess.
        return None
    name = tool.strip().lower()

    if not isinstance(policy, dict):
        # Unreadable policy is exactly when a Bot should do less, not more.
        return _block(name, "its policy could not be read")

    refuse, ask, allow = (_normalise(policy.get(k)) for k in ("refuse", "ask", "allow"))

    if name in refuse:
        return _block(name, "this Bot's policy refuses it")
    if name in ask:
        return _ask(name, "this Bot's policy asks for you on it")
    if name in allow:
        return None

    if policy.get("guard_defaults", True) is not False:
        category = _category(name)
        if category:
            return _ask(name, f"it would {category}, which this Bot asks before doing")

    if str(policy.get("mode", "allow")).strip().lower() == "ask":
        return _ask(name, "this Bot asks before every tool it has not been cleared for")
    return None


def _block(tool: str, why: str) -> dict:
    return {"action": "block",
            "message": f"Refused by Bot Forge Sentinel: `{tool}` was not run because {why}. "
                       f"Nothing happened. Say what you were trying to do and ask the user."}


def _ask(tool: str, why: str) -> dict:
    # rule_key decides what the user's "always allow" later covers. Keyed on the tool, so
    # answering always for one tool does not quietly clear a whole category.
    return {"action": "approve",
            "message": f"Bot Forge Sentinel: `{tool}` needs you — {why}.",
            "rule_key": f"bot-forge-sentinel:{tool}"}
