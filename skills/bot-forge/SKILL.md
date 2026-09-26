---
name: bot-forge
description: "Choose the smallest sufficient setup for a job, then provision authorized persistent Bots or teams. Role defaults and SOUL.md template."
version: 0.12.0
author: Bikash Joshi
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [bots, bot-mode, profiles, spawn, create-agent]
---

# Bot Forge

Choose the smallest sufficient setup before provisioning. This is an advisory decision in the
calling agent, not an extra planner, model call, registry or approval service.

## Before creating a profile
Call `list_agents` and inspect relevant existing skills/routines through the installed Hermes
surfaces. Inspect only what the request needs, not the whole machine. If a required surface is
unavailable, say what could not be checked rather than claiming the job is uncovered.

| Need | First choice |
|---|---|
| Existing owner can do the job | Reuse its profile |
| Repeatable method or specialty | Reuse or add a skill within scope |
| Temporary work | Native delegation |
| Recurring work without a new owner/state boundary | Routine on an existing owner |
| Justified persistent responsibility, state or configuration | New Bot/profile |

A different specialty or name is not enough. Profiles separate configuration and state;
they are **not security sandboxes**. Explain the chosen shape briefly. An explicit authorized
request for a new Bot/profile stays direct, subject to duplicate and safety checks. Ask only
about material ambiguity or missing authority; do not add a mandatory interview. A generic
job request does not itself authorize extra profiles, changed models or recurring work.

## Hard rules
- **One coherent responsibility per new Bot.** Do not turn every subtask into a permanent profile.
- If a Bot already covers the job, reuse it unless the user explicitly wants a distinct profile.
- **Name it like a character:** a cool, unique, Proper Case `display_name` (`Quill`, `Kairo`, `Nova`), never a role word (`Writer`, `Social`). If the tool says the name is taken, pick one of its suggestions.
- Pick an `avatar_kind` that fits the vibe (`sun` upbeat, `cloud` calm, `boxy` technical, `droplet` creative…).
- Write the SOUL.md yourself, specific to the job. No filler.
- After `create_agent` succeeds, **don't touch the new Bot** — no messages, tests, model or config changes. Just report.

## Role defaults
Every Bot always gets `file web browser` plus the basics. Add only what the job needs.
The routines below are examples, not permission to schedule them:

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
🧪 <display_name> was created. Check the readiness below.
job: <one_job>
brain: <model>   tools: <toolsets>
routines: <routines or none>
intro: <first line of intro, or not yet available>
gateway: <gateway>
```
- If `warning` is set, include it. `ok: true` means the profile was created, not that
  sign-in, gateway serving or real work has been verified. Never call a pending Bot fully ready.

## Managing Bots the user already has
- **"make X funnier" / "give X the browser" / "rename X" / "X should never post without asking"** → `update_agent`. Send only what changes; prefer `soul_append` over rewriting `soul_md`.
- **"another one like X"** → `copy_agent`, then `update_agent` to specialise it.
- **"share X"** → `share_agent` (a template: no chats, no user facts, no keys). **"back X up"** → `share_agent` with `mode: backup`, and tell the user it contains chat history. **"import this bot"** → read the template's persona and routines, tell the user what it will do, then `import_agent`.
- **"X is cluttering my list"** → `hide_agent` (not delete).
- **"delete X"** → `delete_agent` with `confirm` set to X's exact profile name. It is disabled by default; if it refuses, tell the user the one command they can run themselves. Never delete a Bot the user didn't name in this conversation.

## Templates
Once a new profile is justified and authorized, a matching starter can supply `template`; override only what differs: chief of staff → `chief-of-staff`, morning/daily brief → `morning-brief`, "keep me updated on <topic>" → `research-digest`, competitor tracking → `competitor-watcher`, repo/CI triage → `engineering-outer-loop`.

## Acknowledgements
Reactions come from the Bot the user is *talking to*, so a Bot created before this feature stays silent until it is switched on — `check_agents` lists those under `not_acknowledging`. If the user says reactions aren't happening, check whether **this** Bot acknowledges before looking anywhere else.

The acknowledgement is an emoji at the **start of the reply** — it works on every surface. New Bots acknowledge by default; leave `ack_reactions` alone unless the user asks for a silent Bot.

In the **desktop app** the same status also lands on the user's own message as a tapback. That is placed by a hook that lives inside the Bot itself (a hook only runs in the profile running the turn), installed with every new Bot. A Bot made before that shipped cannot react until it gets it: `update_agent(name, ack_tapback: true)` — same call for "make X acknowledge / react", which also turns on the reply prefix via `ack_reactions: true`. `check_install` says which Bots can react, and warns when Message Reactions is off in Settings → Appearance (with it off, no tapback appears for any Bot).

## Where the new Bot fits
`create_agent` surveys the workspace it was born into — the directory Hermes runs in and the repos under it, plus this install's own Bots, skills and plugins — and writes the result into the new Bot's memory. This shallow survey supplies hints, not proof that a new profile was necessary. Use the preflight
above for that decision. Do not repeat a broad directory hunt or treat unverified matches as facts.

The result's `workspace` block is what you report: `fits` (the places it belongs, most relevant first), `covered_by` (Bots already working in that territory), `skills_here` (already installed and worth giving it), `next_steps`. Give the user the top fit and at most two next steps — not the whole list.

**If the tool refuses with `covered_by`,** an existing Bot already does this job. Do not retry blindly. Tell the user which Bot holds it and offer the two real choices: a narrower job for the new Bot, or `update_agent` on the existing one. Only pass `allow_overlap: true` after they say they want both.

## Sandboxes
Any Bot you give `terminal` or `code_execution` should get `sandbox: "docker"` so its shell runs in a container instead of on the user's machine — say so in your reply. If the tool refuses because the backend is not usable, tell the user what it said and offer the Bot without a sandbox instead of retrying.

## What needs the user
"what needs me", "anything waiting on me", a morning or weekly check → `check_agents` and lead with `waiting_on_you`: each item is a Bot that got blocked and wrote it down, with how many days it has sat there. Name the Bot and the ask in one line each; don't bury them under healthy-Bot noise.

## Health
"how are my bots doing" or a weekly review → `check_agents`. "the tools are missing" / "nothing happened after installing" → `check_install`, then give the user its next_steps verbatim. Report the flags in plain words and suggest the fix (update_agent / hide_agent); don't apply it unasked.

## Journal
- New Bots have a factual work journal by default. After meaningful work, use `agent_journal` with `action: add` to record the outcome, evidence, blockers and next step.
- Skip routine conversation. Never journal credentials, authentication material, facts unrelated to the job, private reasoning, or hidden chain-of-thought.
- "what did X do?" / "show X's journal" → `agent_journal` with `action: read` and the Bot name.
- A Bot created before journaling existed → `agent_journal` with `action: enable` once. This appends the journal policy without replacing its persona.

## Teams
Apply the same preflight to each proposed responsibility, including the lead. A request for a
team does not prescribe a fixed headcount: existing Bots, skills, delegation and routines may
already cover it. Only justified, authorized NEW profiles go in `create_team.members`.
Use `lead_name` for an existing lead; the tool does not enroll arbitrary existing members.
If no new profiles are needed, do not call `create_team`. If just one is needed, `create_agent`
is sufficient. Preserve the tool's existing maximum of six new members; do not fill it.

For an authorized multi-Bot creation, pass the new members together and tell the user it takes
a few minutes. Report failures and each member's readiness. Cleanup is per failed Bot, not a
transaction that rolls back the whole team.

## Model route at creation
`create_agent.model`, `create_team.lead.model` and each `create_team.members[].model` accept
`default` and `provider`, plus optional `base_url` and `api_mode`. Use an authorized route
appropriate for the role, never credentials in the tool call. The route is written before the
first model call. Omit it to keep existing inheritance; do not use `{}` to request inheritance.
Per-profile sign-in and configured fallback behavior still apply. Report fallback warnings;
this feature is explicit configuration, not an automatic model-tiering service.

## Gateway topology
When `install_gateway` is enabled, a live host gateway's served roster determines readiness.
Bot Forge requests a native hot-rescan when necessary, without restarting the host or forcing
a new per-profile service. Pending means not yet verified, not necessarily broken. Do not
unpark a profile or enable standalone mode to turn a warning green. Older/unavailable control
support also stays unverified; follow the installed Hermes docs for operator setup.
`install_gateway: false` skips Bot Forge's gateway setup; it does not park a profile or stop
the host's independent discovery. Windows retains the existing gateway-setup skip.

## Teaching
"remember how I do X", "this is how we handle Y" → `teach_agent` with concrete `steps`. Keep SOUL.md for who the Bot is; put procedures in skills.

## Guardrails at birth
Give every new Bot an `approvals` list — the things it must ask about (publish, send, buy, delete) — and `reports_to` when there is an obvious boss Bot (check `list_agents`). Both are written into its SOUL.md and memory.

## Not this skill's job
Messaging-platform tokens (need the user's own token), and anything about the user's own main profile — never edit or delete that.
