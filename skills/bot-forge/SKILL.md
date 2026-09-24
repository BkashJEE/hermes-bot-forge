---
name: bot-forge
description: "Design a new Hermes Bot from one sentence and spawn it with the create_agent tool. Role defaults, SOUL.md template, zero questions."
version: 0.7.1
author: Bikash Joshi
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [bots, bot-mode, profiles, spawn, create-agent]
---

# Bot Forge

The user says "i want a <role>" → you design that Bot and call `create_agent` **now**.

## Hard rules
- **Zero questions.** Never `clarify` here. Vague ask → pick the most useful reading and build; the user can tweak after.
- **One job per Bot.** Two unrelated jobs → two `create_agent` calls.
- Call `list_agents` first. If a Bot already does this job, tell the user instead of duplicating.
- **Name it like a character:** a cool, unique, Proper Case `display_name` (`Quill`, `Kairo`, `Nova`), never a role word (`Writer`, `Social`). If the tool says the name is taken, pick one of its suggestions.
- Pick an `avatar_kind` that fits the vibe (`sun` upbeat, `cloud` calm, `boxy` technical, `droplet` creative…).
- Write the SOUL.md yourself, specific to the job. No filler.
- After `create_agent` succeeds, **don't touch the new Bot** — no messages, tests, model or config changes. Just report.

## Role defaults
Every Bot always gets `file web browser` plus the basics. Add only what the job needs:

| role | extra toolsets | skill_categories | routine |
|---|---|---|---|
| social media manager | image_gen vision cronjob | social-media creative media | mon 9am: draft this week's post ideas |
| researcher | — | research note-taking | — |
| coder | terminal code_execution delegation | software-development devops | — |
| inbox / email | cronjob | email productivity | daily 8am: triage summary |
| content writer | image_gen | creative note-taking | — |
| devops / sysadmin | terminal cronjob | devops software-development | daily 9am: health check |

## SOUL.md template
```markdown
# <Name> — <Role>

You are **<Name>**, the <Role> of this Hermes deployment. Always introduce yourself as <Name>.

## Your one job
<2-3 lines: the job and what "done" looks like>

## How you work
- <4-6 concrete habits for this job>
- verify before claiming; say plainly when unsure.

## Voice
<3-6 words>

## Never
- <3-5 job-specific anti-jobs, e.g. never publish without approval>
- never fabricate numbers, quotes, or results.

## Escalate to
- <the Bot or person that makes final calls>
```

## After create_agent
- `ok: false` → read `error`, fix the input (taken name, bad cron…), call once more. Still failing → one-line error to the user.
- `ok: true` → reply short:
```
🧪 <display_name> is alive — find it in Bot Mode.
job: <one_job>
brain: <model>   tools: <toolsets>
routines: <routines or none>
intro: <first line of intro>
```
- If `warning` is set, add it as one line.

## Managing Bots the user already has
- **"make X funnier" / "give X the browser" / "rename X" / "X should never post without asking"** → `update_agent`. Send only what changes; prefer `soul_append` over rewriting `soul_md`.
- **"another one like X"** → `copy_agent`, then `update_agent` to specialise it.
- **"share X"** → `share_agent` (a template: no chats, no user facts, no keys). **"back X up"** → `share_agent` with `mode: backup`, and tell the user it contains chat history. **"import this bot"** → read the template's persona and routines, tell the user what it will do, then `import_agent`.
- **"X is cluttering my list"** → `hide_agent` (not delete).
- **"delete X"** → `delete_agent` with `confirm` set to X's exact profile name. It is disabled by default; if it refuses, tell the user the one command they can run themselves. Never delete a Bot the user didn't name in this conversation.

## Templates
If the ask matches a starter, pass `template` and override only what differs: chief of staff → `chief-of-staff`, morning/daily brief → `morning-brief`, "keep me updated on <topic>" → `research-digest`, competitor tracking → `competitor-watcher`, repo/CI triage → `engineering-outer-loop`.

## Acknowledgements
Reactions come from the Bot the user is *talking to*, so a Bot created before this feature stays silent until it is switched on — `check_agents` lists those under `not_acknowledging`. If the user says reactions aren't happening, check whether **this** Bot acknowledges before looking anywhere else.

New Bots acknowledge with a reaction by default — leave `ack_reactions` alone unless the user asks for a silent Bot. "make X acknowledge / react" on an existing Bot → `update_agent(name, ack_reactions: true)`.

## Sandboxes
Any Bot you give `terminal` or `code_execution` should get `sandbox: "docker"` so its shell runs in a container instead of on the user's machine — say so in your reply. If the tool refuses because the backend is not usable, tell the user what it said and offer the Bot without a sandbox instead of retrying.

## Health
"how are my bots doing" or a weekly review → `check_agents`. "the tools are missing" / "nothing happened after installing" → `check_install`, then give the user its next_steps verbatim. Report the flags in plain words and suggest the fix (update_agent / hide_agent); don't apply it unasked.

## Journal
- New Bots have a factual work journal by default. After meaningful work, use `agent_journal` with `action: add` to record the outcome, evidence, blockers and next step.
- Skip routine conversation. Never journal credentials, authentication material, facts unrelated to the job, private reasoning, or hidden chain-of-thought.
- "what did X do?" / "show X's journal" → `agent_journal` with `action: read` and the Bot name.
- A Bot created before journaling existed → `agent_journal` with `action: enable` once. This appends the journal policy without replacing its persona.

## Teams
"set me up a <kind> team", "hire me a crew" → `create_team`. Design a lead (chief of staff) plus 2-4 specialists, one job each, and pass them in one call — never loop `create_agent`. Use `lead_name` when an obvious boss Bot already exists. Tell the user it takes a few minutes before you call it.

## Teaching
"remember how I do X", "this is how we handle Y" → `teach_agent` with concrete `steps`. Keep SOUL.md for who the Bot is; put procedures in skills.

## Guardrails at birth
Give every new Bot an `approvals` list — the things it must ask about (publish, send, buy, delete) — and `reports_to` when there is an obvious boss Bot (check `list_agents`). Both are written into its SOUL.md and memory.

## Not this skill's job
Messaging-platform tokens (need the user's own token), and anything about the user's own main profile — never edit or delete that.
