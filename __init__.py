"""bot-forge — let a Hermes agent spawn, list and ask other Hermes Bots."""

from pathlib import Path

from . import schemas, tools

_SETTINGS = ("inherit_model", "fallback_model", "probe_local_models", "install_gateway",
             "allow_delete", "backup_before_delete", "suggest_connectors", "allow_secrets")


def register(ctx):
    def settings():
        return {key: ctx.get_config(key, default=None) for key in _SETTINGS}

    ctx.register_tool(name="create_agent", toolset="bot_forge", schema=schemas.CREATE_AGENT,
                      handler=lambda args, **kw: tools.create_agent(args, settings=settings(), **kw),
                      emoji="🧪", description="Spawn a complete, working Hermes Bot from a design")
    ctx.register_tool(name="list_agents", toolset="bot_forge", schema=schemas.LIST_AGENTS,
                      handler=tools.list_agents, emoji="📋", description="List Hermes Bots on this machine")
    ctx.register_tool(name="check_install", toolset="bot_forge", schema=schemas.CHECK_INSTALL,
                      handler=tools.check_install, emoji="🩹",
                      description="Check that Bot Forge itself is set up correctly (read-only)")
    ctx.register_tool(name="check_agents", toolset="bot_forge", schema=schemas.CHECK_AGENTS,
                      handler=tools.check_agents, emoji="🩺", description="Health check for all Bots (read-only)")
    ctx.register_tool(name="ask_agent", toolset="bot_forge", schema=schemas.ASK_AGENT,
                      handler=tools.ask_agent, emoji="📨",
                      description="Ask another Hermes Bot something and return its reply")

    for name, schema, handler, emoji, blurb in (
        ("create_team", schemas.CREATE_TEAM, tools.create_team, "🧬", "Build a team of Bots with a lead"),
        ("teach_agent", schemas.TEACH_AGENT, tools.teach_agent, "🎓", "Teach a Bot a repeatable skill"),
        ("update_agent", schemas.UPDATE_AGENT, tools.update_agent, "✏️", "Edit an existing Bot"),
        ("copy_agent", schemas.COPY_AGENT, tools.copy_agent, "👯", "Duplicate a Bot under a new name"),
        ("share_agent", schemas.SHARE_AGENT, tools.share_agent, "📦", "Export a Bot as a shareable archive"),
        ("import_agent", schemas.IMPORT_AGENT, tools.import_agent, "📥", "Import a Bot from an archive"),
        ("hide_agent", schemas.HIDE_AGENT, tools.hide_agent, "🙈", "Hide or unhide a Bot in the roster"),
        ("delete_agent", schemas.DELETE_AGENT, tools.delete_agent, "🗑️", "Delete a Bot (off unless enabled)"),
    ):
        ctx.register_tool(name=name, toolset="bot_forge", schema=schema,
                          handler=(lambda h: lambda args, **kw: h(args, settings=settings(), **kw))(handler),
                          emoji=emoji, description=blurb)

    def _doctor_setup(parser):
        parser.add_argument("--json", action="store_true", help="machine-readable output")

    def _doctor_handler(args):
        import doctor
        return doctor.cli(args)

    try:
        ctx.register_cli_command(name="bot-forge-doctor", help="Check that Bot Forge is set up correctly",
                                 setup_fn=_doctor_setup, handler_fn=_doctor_handler,
                                 description="Report which profiles have Bot Forge enabled, whether their gateways "
                                             "run the current code, model sign-in, sandbox backends and templates.")
    except Exception:  # older Hermes without plugin CLI commands: the tool and `python doctor.py` still work
        pass

    skills_dir = Path(__file__).parent / "skills"
    for child in sorted(skills_dir.iterdir()):
        if child.is_dir() and (child / "SKILL.md").exists():
            ctx.register_skill(child.name, child / "SKILL.md")
