"""bot-forge-sentinel — a Bot's reach, decided outside the model.

Hooks only, no tools. A policy layer must not widen what a Bot can do, which is the same rule
the acknowledgement companion in marks/ follows.
"""

if __package__:
    from . import guard
else:  # loaded by path rather than as a package
    import guard


def register(ctx):
    def policy():
        """This Bot's own policy: the plugin's config in the profile it runs as."""
        return {key: ctx.get_config(key, default=None)
                for key in ("refuse", "ask", "allow", "mode", "guard_defaults")}

    def on_tool_call(tool_name=None, args=None, **_kw):
        # Hermes reads the returned directive; None means we have no opinion. Never raise:
        # an exception here would be a policy layer that fails open.
        try:
            return guard.decide(tool_name, policy())
        except Exception:
            return guard.decide(tool_name, None)

    ctx.register_hook("pre_tool_call", on_tool_call)
