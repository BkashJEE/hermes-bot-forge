"""bot-forge — let a Hermes agent spawn, list and ask other Hermes Bots."""

from pathlib import Path

from . import schemas, tools

_SETTINGS = ("inherit_model", "share_login", "fallback_model", "probe_local_models", "install_gateway")


def register(ctx):
    def settings():
        return {key: ctx.get_config(key, default=None) for key in _SETTINGS}

    ctx.register_tool(name="create_agent", toolset="bot_forge", schema=schemas.CREATE_AGENT,
                      handler=lambda args, **kw: tools.create_agent(args, settings=settings(), **kw),
                      emoji="🧪", description="Spawn a complete, working Hermes Bot from a design")
    ctx.register_tool(name="list_agents", toolset="bot_forge", schema=schemas.LIST_AGENTS,
                      handler=tools.list_agents, emoji="📋", description="List Hermes Bots on this machine")
    ctx.register_tool(name="ask_agent", toolset="bot_forge", schema=schemas.ASK_AGENT,
                      handler=tools.ask_agent, emoji="📨",
                      description="Ask another Hermes Bot something and return its reply")

    skills_dir = Path(__file__).parent / "skills"
    for child in sorted(skills_dir.iterdir()):
        if child.is_dir() and (child / "SKILL.md").exists():
            ctx.register_skill(child.name, child / "SKILL.md")
