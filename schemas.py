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
        "report. Pass `template` to start from a proven design. Load skill 'bot-forge:bot-forge' for role "
        "defaults if unsure."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "template": {"type": "string", "description": (
                "start from a template instead of designing from scratch: a bundled one — 'chief-of-staff', "
                "'morning-brief', 'research-digest', 'competitor-watcher', 'engineering-outer-loop' — or a path to a "
                ".botforge.json file. Any other field you pass overrides the template's.")},
            "display_name": {"type": "string", "description": (
                "a cool, unique, Proper Case name for the Bot, e.g. 'Quill', 'Nova', 'Kairo' — never a generic "
                "role word like 'Writer' or 'Social'. Check list_agents first; if the tool says it's taken, pick another.")},
            "avatar_kind": {"type": "string", "enum": BLOB_KINDS, "description": "blob face silhouette that fits the Bot's vibe"},
            "sandbox": {"type": "string", "enum": ["local", "docker", "singularity", "apptainer"], "description": (
                "where this Bot's shell runs. 'local' (default) shares this machine; 'docker' gives the Bot its own "
                "container, so it cannot touch the user's files and cannot block other Bots. Use a sandbox for any "
                "Bot you give terminal or code_execution, and say so when you report back. The call is refused if "
                "the backend is not usable on this machine.")},
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
                "things this Bot must ask the user before doing. Defaults to sending/publishing, spending money and "
                "deleting data when omitted; pass [] only if the user explicitly wants none. Written into its SOUL.md "
                "and memory as hard checkpoints.")},
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
                        "allow_frequent": {"type": "boolean", "description": (
                            "only when the user explicitly asked for a schedule faster than every 30 minutes")},
                    },
                    "required": ["schedule", "prompt"],
                },
            },
        },
        "required": [],
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
        "Share a Bot as a portable .botforge.json template: persona, its own memory, tools, skill choices, taught "
        "skills and routines — never chat history, facts about the user, or credentials. The file is scanned for "
        "secrets (CLEAN / WARN / BLOCK) and not written on BLOCK. Use mode='backup' only when the user wants a "
        "full private backup of their own Bot (that one includes chat history — tell them)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "the Bot to share"},
            "mode": {"type": "string", "enum": ["template", "backup"], "description": "template (default) or backup"},
            "path": {"type": "string", "description": "optional file name/path under <hermes>/profile-exports (never overwrites)"},
        },
        "required": ["name"],
    },
}

IMPORT_AGENT = {
    "name": "import_agent",
    "description": (
        "Import a Bot from a .botforge.json template (built fresh, secret-scanned, like create_agent) or restore a "
        ".tar.gz backup made with share_agent mode='backup'. Before importing a template from someone else, read "
        "its soul_md and routines and tell the user what the Bot will do."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "path to a .botforge.json template or a .tar.gz backup"},
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


CREATE_TEAM = {
    "name": "create_team",
    "description": (
        "Build a whole team of Bots in one go — use when the user asks for a team, a crew, a department or "
        "several Bots at once ('set me up a content team', 'hire me a marketing team'). Design every member "
        "yourself, one job each, no questions. Give `lead` to build a chief of staff that the others report to, "
        "or `lead_name` to put an existing Bot in charge; the lead learns the roster so it can delegate "
        "immediately. Up to 6 members, built one at a time — a member that fails is rolled back alone and the "
        "rest of the team stands. Takes several minutes; say so before calling."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "team": {"type": "string", "description": "short team label, e.g. 'Content'"},
            "lead": {
    "type": "object",
    "properties": {
        "display_name": {"type": "string"}, "role": {"type": "string"}, "one_job": {"type": "string"},
        "description": {"type": "string"}, "soul_md": {"type": "string"},
        "avatar_kind": {"type": "string", "enum": BLOB_KINDS},
        "sandbox": {"type": "string", "enum": ["local", "docker", "singularity", "apptainer"]},
        "toolsets": {"type": "array", "items": {"type": "string", "enum": TOOLSETS}},
        "skill_categories": {"type": "array", "items": {"type": "string"}},
        "approvals": {"type": "array", "items": {"type": "string"}},
        "memory": {"type": "array", "items": {"type": "string"}},
        "routines": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "schedule": {"type": "string"}, "prompt": {"type": "string"}},
            "required": ["schedule", "prompt"]}},
    },
    "required": ["display_name", "role", "one_job", "soul_md", "toolsets"],
},
            "lead_name": {"type": "string", "description": "profile name of an existing Bot to lead instead"},
            "members": {"type": "array", "maxItems": 6, "items": {
    "type": "object",
    "properties": {
        "display_name": {"type": "string"}, "role": {"type": "string"}, "one_job": {"type": "string"},
        "description": {"type": "string"}, "soul_md": {"type": "string"},
        "avatar_kind": {"type": "string", "enum": BLOB_KINDS},
        "sandbox": {"type": "string", "enum": ["local", "docker", "singularity", "apptainer"]},
        "toolsets": {"type": "array", "items": {"type": "string", "enum": TOOLSETS}},
        "skill_categories": {"type": "array", "items": {"type": "string"}},
        "approvals": {"type": "array", "items": {"type": "string"}},
        "memory": {"type": "array", "items": {"type": "string"}},
        "routines": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "schedule": {"type": "string"}, "prompt": {"type": "string"}},
            "required": ["schedule", "prompt"]}},
    },
    "required": ["display_name", "role", "one_job", "soul_md", "toolsets"],
}},
        },
        "required": ["members"],
    },
}

TEACH_AGENT = {
    "name": "teach_agent",
    "description": (
        "Teach a Bot a repeatable procedure it keeps forever — 'remember how I write my weekly report', "
        "'this is how we onboard a client'. Saves a skill in the Bot's own skills folder that it loads when the "
        "job comes up. Use `steps` for a normal how-to; use `body` only when you have full skill markdown. "
        "Prefer this over stuffing long instructions into its SOUL.md."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "the Bot to teach"},
            "skill": {"type": "string", "description": "short kebab-case skill name, e.g. 'weekly-report'"},
            "description": {"type": "string", "description": "one line: what this skill does"},
            "when": {"type": "string", "description": "when the Bot should reach for it"},
            "steps": {"type": "array", "items": {"type": "string"}, "description": "ordered, concrete steps"},
            "body": {"type": "string", "description": "complete SKILL.md markdown instead of steps"},
        },
        "required": ["name", "skill"],
    },
}


CHECK_AGENTS = {
    "name": "check_agents",
    "description": (
        "Health check for the user's Bots — read-only. Reports each Bot's model, gateway, routines with estimated "
        "runs per day, days since last used, and flags: routines that run too often (every run costs a model "
        "call), paused or never-run routines, unused Bots, a SOUL.md missing the Bot's own name or approval "
        "checkpoints. Use when the user asks 'how are my bots doing', during a weekly review, or before adding "
        "more routines. Suggest fixes; don't apply them without asking."
    ),
    "parameters": {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "optional: check one Bot only"}},
    },
}


CHECK_INSTALL = {
    "name": "check_install",
    "description": (
        "Check whether Bot Forge itself is set up correctly on this machine — read-only. Reports which profiles "
        "have it enabled, whether each gateway is running the current plugin code (if not, its tools are invisible "
        "and a restart is needed), whether Desktop Bot Mode was detected, whether a new Bot's inherited model can "
        "sign in, which sandbox backends are usable, and the bundled templates. Use when the user says the tools "
        "are missing or a new Bot did not work, or right after installing. Report the failing checks and the exact "
        "next commands."
    ),
    "parameters": {"type": "object", "properties": {}},
}


AGENT_JOURNAL = {
    "name": "agent_journal",
    "description": (
        "Maintain a Bot's append-only work journal. New Bot Forge Bots have journaling enabled by default. "
        "Use action='add' after meaningful work to record observable outcomes, evidence, blockers and next steps; "
        "skip routine conversation. Use action='read' when the user asks what a Bot has done, or action='enable' "
        "once for an older Bot. When called inside a Bot's own chat, `name` can be omitted; otherwise pass a Bot "
        "name from list_agents. Never journal credentials, authentication material, facts unrelated to the Bot's "
        "job, private reasoning, or hidden chain-of-thought."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["enable", "add", "read"]},
            "name": {"type": "string", "description": "Bot profile name or title; omit only from that Bot's own chat"},
            "title": {"type": "string", "description": "short factual entry title; required for add"},
            "summary": {"type": "string", "description": "what happened and why it matters; required for add"},
            "status": {"type": "string", "enum": ["planned", "progress", "completed", "blocked", "failed"],
                       "description": "entry outcome; defaults to progress"},
            "evidence": {"type": "array", "items": {"type": "string"},
                         "description": "commands, links, files, measurements, or other user-visible proof"},
            "next_steps": {"type": "array", "items": {"type": "string"}},
            "tags": {"type": "array", "items": {"type": "string"}},
            "date": {"type": "string", "description": "read only: YYYY-MM-DD; omit for newest entries"},
            "query": {"type": "string", "description": "read only: case-insensitive text filter"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "description": "read only; default 10"},
        },
        "required": ["action"],
    },
}
