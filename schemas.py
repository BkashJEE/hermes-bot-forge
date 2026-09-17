"""Tool schemas — what the LLM sees."""

TOOLSETS = ["browser", "code_execution", "computer_use", "connections", "cronjob", "delegation", "file",
            "image_gen", "terminal", "tts", "vision", "web"]
BLOB_KINDS = ["round", "organic", "boxy", "capsule", "nub", "cloud", "droplet", "hexagon", "sun", "triangle"]

CREATE_AGENT = {
    "name": "create_agent",
    "description": (
        "Spawn a brand-new, fully working Hermes Bot (its own profile) right now. Use whenever the user asks to "
        "make/create/spawn/build/hire a bot, agent, assistant or 'someone to handle' a job (e.g. 'make me a "
        "social media manager'). Do NOT ask the user questions first: design the Bot yourself and call this. "
        "Write the full SOUL.md in `soul_md` (sections: '# <Name> — <Role>', 'You are **<Name>**…', "
        "'## Your one job', '## How you work', '## Voice', '## Never', '## Escalate to'), specific to the job. "
        "One job per Bot; for two unrelated jobs call this twice. The tool creates the profile, writes SOUL.md "
        "and memories, sets tools and skills, adds routines, opens its Bot Chat with a self-introduction, starts "
        "its gateway, and rolls everything back on failure. The Bot appears in Desktop Bot Mode with its name "
        "and face. Takes 1-3 minutes. After it succeeds, do not message, test or change the new Bot — just "
        "report. Load skill 'bot-forge:bot-forge' for role defaults if unsure."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "display_name": {"type": "string", "description": (
                "a cool, unique, Proper Case name for the Bot, e.g. 'Quill', 'Nova', 'Kairo' — never a generic "
                "role word like 'Writer' or 'Social'. Check list_agents first; if the tool says it's taken, pick another.")},
            "avatar_kind": {"type": "string", "enum": BLOB_KINDS, "description": "blob face silhouette that fits the Bot's vibe"},
            "role": {"type": "string", "description": "role title, e.g. 'Social Media Manager'"},
            "description": {"type": "string", "description": "1-2 sentences on what it is good at (used for routing)"},
            "one_job": {"type": "string", "description": "the Bot's single job in one sentence"},
            "soul_md": {"type": "string", "description": "complete SOUL.md markdown you wrote for this Bot"},
            "memory": {"type": "array", "items": {"type": "string"}, "description": "2-5 starter facts useful for the job"},
            "toolsets": {"type": "array", "items": {"type": "string", "enum": TOOLSETS}, "description": (
                "extra toolsets the job needs (file, web, browser, clarify, memory, session_search, skills, todo "
                "are always included)")},
            "skill_categories": {"type": "array", "items": {"type": "string"}, "description": (
                "skill category folders to keep enabled, e.g. ['social-media','creative']; research and web stay "
                "on, others are disabled (not deleted)")},
            "routines": {
                "type": "array",
                "description": "optional recurring jobs, only when the job is naturally recurring",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "schedule": {"type": "string", "description": "cron expression like '0 9 * * 1' or 'every 2h'"},
                        "prompt": {"type": "string", "description": "self-contained instruction the Bot runs each time"},
                    },
                    "required": ["schedule", "prompt"],
                },
            },
        },
        "required": ["display_name", "role", "one_job", "soul_md", "toolsets"],
    },
}

LIST_AGENTS = {
    "name": "list_agents",
    "description": (
        "List every Hermes Bot (profile) on this machine with its name, description and model. Use before "
        "creating a Bot to avoid duplicates or name clashes, or to pick who to delegate to."
    ),
    "parameters": {"type": "object", "properties": {}},
}

ASK_AGENT = {
    "name": "ask_agent",
    "description": (
        "Ask another Hermes Bot something by profile name and wait for its reply (synchronous). In a Bot Chat "
        "session prefer the built-in message_agent for fire-and-forget delivery."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "profile name from list_agents"},
            "message": {"type": "string", "description": "self-contained message or task"},
        },
        "required": ["name", "message"],
    },
}
