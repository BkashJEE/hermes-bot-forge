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
            "approvals": {"type": "array", "items": {"type": "string"}, "description": (
                "things this Bot must ask the user before doing, e.g. ['publish or send anything', 'spend money', "
                "'delete files']. Written into its SOUL.md and memory as hard checkpoints.")},
            "reports_to": {"type": "string", "description": (
                "profile name of the Bot it escalates scope and priority calls to (its chief of staff), e.g. 'ceo'")},
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


UPDATE_AGENT = {
    "name": "update_agent",
    "description": (
        "Edit an existing Bot in place — use whenever the user wants one changed: 'make Inkwell funnier', "
        "'give Atlas the browser', 'Nova should never post without asking', 'rename it', 'add a Monday routine'. "
        "Pass only what changes. Use `soul_append` for a tweak and `soul_md` only when rewriting the whole "
        "persona (the previous file is backed up either way). Changes apply on the Bot's next turn; its chat "
        "history is kept. Never use this on the user's own main profile."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "profile name or Bot title from list_agents"},
            "soul_append": {"type": "string", "description": "markdown appended to its SOUL.md (preferred for small changes)"},
            "soul_md": {"type": "string", "description": "complete replacement SOUL.md — only for a full rewrite"},
            "role": {"type": "string", "description": "role title, used if the identity line has to be rewritten"},
            "display_name": {"type": "string", "description": "new Proper Case display name in the roster"},
            "description": {"type": "string", "description": "new one-two sentence description"},
            "memory": {"type": "array", "items": {"type": "string"}, "description": "facts to append to its memory"},
            "add_toolsets": {"type": "array", "items": {"type": "string", "enum": TOOLSETS}},
            "remove_toolsets": {"type": "array", "items": {"type": "string", "enum": TOOLSETS}},
            "skill_categories": {"type": "array", "items": {"type": "string"},
                                 "description": "replacement set of enabled skill categories"},
            "avatar_kind": {"type": "string", "enum": BLOB_KINDS},
            "model": {"type": "object", "description": "model block {default, provider, base_url} — only when asked"},
            "add_routines": {"type": "array", "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "schedule": {"type": "string"}, "prompt": {"type": "string"}},
                "required": ["schedule", "prompt"]}},
            "remove_routines": {"type": "array", "items": {"type": "string"}, "description": "cron job ids to remove"},
        },
        "required": ["name"],
    },
}

COPY_AGENT = {
    "name": "copy_agent",
    "description": (
        "Duplicate an existing Bot under a new name — 'make another one like Inkwell but for LinkedIn'. Copies "
        "its persona, memory, skills, tools and model; no chat history and no routines. Follow with update_agent "
        "to specialise the copy."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "the Bot to copy"},
            "display_name": {"type": "string", "description": "cool, unique Proper Case name for the copy"},
            "description": {"type": "string"},
            "role": {"type": "string"},
            "avatar_kind": {"type": "string", "enum": BLOB_KINDS},
        },
        "required": ["name", "display_name"],
    },
}

SHARE_AGENT = {
    "name": "share_agent",
    "description": (
        "Export a Bot to a .tar.gz archive the user can share — persona, memory, skills, config and routines. "
        "API keys and logins are NOT included. Use when the user asks to share, back up or move a Bot."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "the Bot to export"},
            "path": {"type": "string", "description": "optional output path for the .tar.gz"},
        },
        "required": ["name"],
    },
}

IMPORT_AGENT = {
    "name": "import_agent",
    "description": (
        "Import a Bot from a .tar.gz archive made by share_agent (or `hermes profile export`) and start it. "
        "Read the archive's SOUL.md afterwards if the user wants to know what it does."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "path to the .tar.gz archive"},
            "display_name": {"type": "string", "description": "optional new Proper Case name for the imported Bot"},
        },
        "required": ["path"],
    },
}

HIDE_AGENT = {
    "name": "hide_agent",
    "description": (
        "Hide a Bot from the Desktop roster, or unhide it with hidden=false. Display only: the Bot keeps running "
        "and its routines keep firing. Prefer this over deleting when the user says a Bot is cluttering the list."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "hidden": {"type": "boolean", "description": "true to hide (default), false to bring it back"},
        },
        "required": ["name"],
    },
}

DELETE_AGENT = {
    "name": "delete_agent",
    "description": (
        "Permanently delete a Bot and all its chats. Disabled unless the operator turned it on, and it needs "
        "`confirm` to equal the Bot's exact profile name. Prefer hide_agent. Only call this when the user has "
        "clearly asked to delete that specific Bot in this conversation — never to tidy up on your own."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "the Bot to delete"},
            "confirm": {"type": "string", "description": "must equal the Bot's profile name exactly"},
        },
        "required": ["name", "confirm"],
    },
}
