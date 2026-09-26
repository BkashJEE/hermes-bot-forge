<p align="center">
  <img src="docs/banner.png" alt="Bot Forge — one sentence to a complete, working Hermes Bot" width="100%">
</p>

<p align="center">
  <a href="https://hermes-agent.nousresearch.com/docs/plugins/"><img src="https://img.shields.io/badge/Hermes%20plugin%20catalog-listed-22D3EE?style=flat-square" alt="in the Hermes plugin catalog"></a>
  <a href="https://github.com/BkashJEE/hermes-bot-forge/actions/workflows/tests.yml"><img src="https://img.shields.io/github/actions/workflow/status/BkashJEE/hermes-bot-forge/tests.yml?style=flat-square&label=tests" alt="tests"></a>
  <a href="https://github.com/BkashJEE/hermes-bot-forge/releases"><img src="https://img.shields.io/github/v/release/BkashJEE/hermes-bot-forge?style=flat-square&color=8B5CF6" alt="release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-64748B?style=flat-square" alt="MIT"></a>
</p>

# Hermes Bot Forge

**Describe the job. Reuse what fits; provision a new Bot when it needs its own persistent role.**

```bash
hermes plugins install bot-forge
```

Bot Forge is a [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that lets any agent spawn a complete, working [Bot Mode](https://hermes-agent.nousresearch.com/docs/user-guide/bot-mode) Bot from an authorized design, without the New Agent dialog:

| The new Bot gets | |
|---|---|
| 🪪 **Identity** | a unique, Proper Case name and a blob face in the Bots roster |
| 📜 **SOUL.md** | written by your agent for that one job |
| 🧠 **Memory** | starter facts, plus what Hermes already knows about you |
| 🛠️ **Tools & skills** | file, web and browser, plus what the role needs |
| ⏰ **Routines** | optional cron jobs that post into its Bot Chat |
| 💬 **Bot Chat** | introduction attempted; sign-in may still be needed |
| 🔌 **Gateway** | live host serving checked; a hot-rescan is requested when needed |

Creation failures attempt cleanup of that Bot. Sign-in and gateway readiness may remain
pending; the result says which. A team is not an all-or-nothing transaction.

### Does this job need a new Bot?

For a generic job or team request, the existing bundled skill asks the caller to inspect the
roster and relevant skills/routines first. Reuse an existing owner, a skill, temporary delegation
or a routine when sufficient. Create a new profile for a justified persistent responsibility,
state or configuration difference, not just a new specialty. Profiles are not security sandboxes.

This is advisory guidance, not a deterministic classifier or a new planning service. Explicit
authorized profile creation remains direct, with the existing duplicate and safety checks.
The same decision applies to each proposed team member.

## Demo

**1. Ask any Bot for a new teammate.** It checks the roster, designs the Bot and calls `create_agent` — the new Bot (Inkwell) appears in the roster while it works:

![A CEO Bot receives "make me a bot that writes x.com posts and threads"; Inkwell appears in the Bots roster](docs/demo-create.png)

**2. The new Bot is already alive.** Its Bot Chat opens with it introducing itself:

![Inkwell's Bot Chat: "I'm Inkwell — your X posts and threads writer"](docs/demo-intro.png)

---

## Onboarding

### 1. Requirements

- Hermes Agent **0.21+** with the `hermes` CLI on your `PATH`
- Hermes Desktop for Bot Mode (the CLI works too — Bots are profiles)
- **Linux and macOS are tested.** Windows is not: Bots are still created and work from the CLI, but gateway services and sandboxes are skipped there

### 2. Install

```bash
hermes plugins install BkashJEE/hermes-bot-forge
```

### 3. Enable it where you chat

Plugins are opt-in **per profile**. Enable Bot Forge on each profile that should be able to create Bots — your main profile, and any "manager" Bot:

```bash
hermes plugins enable bot-forge              # the default profile
hermes -p ceo plugins enable bot-forge       # a Bot named "ceo"
```

If `enable` asks to grant tool overrides, answer **no** — Bot Forge doesn't override anything.

### 4. Restart Hermes

```bash
hermes gateway restart
# With independent legacy services, restart their owners instead; do not create new services here.
```

Then quit and reopen **Hermes Desktop**.

### 5. Check it's loaded

```bash
hermes bot-forge-doctor
```

It tells you exactly what is missing — a profile you forgot to enable, a gateway still running the old code (the usual reason the tools never appear), a model that needs a per-Bot sign-in, and which sandbox backends this machine can run. Or, the long way:

```bash
hermes plugins list | grep bot-forge
```

Or ask your agent: *"what tools do you have for creating agents?"* — it should name `create_agent`, `update_agent`, `list_agents` and the rest.

### 6. Make your first Bot

Open **Bot Mode**, click the Bot you enabled, and type:

> make me a bot that writes x.com posts and threads

Wait 1–3 minutes. The reply looks like:

```
🧪 Inkwell is alive — find it in Bot Mode.
job: turns ideas, links and demo notes into X posts and threads
brain: gpt-6-astra   tools: browser, file, web, …
```

Click the new Bot — its Bot Chat already has its introduction.

### 7. Choose how new Bots sign in

Unless given an explicit route, new Bots retain the existing model inheritance behavior.
`create_agent.model`, `create_team.lead.model` and `create_team.members[].model` accept:

```json
{"default": "<model-id>", "provider": "<provider-id>"}
```

Optional `base_url` and `api_mode` travel with that route. The complete block is applied
before the first inference, without carrying over the creator's provider transport settings.
Creation-tool calls reject missing/empty names or providers and unsupported fields before
spawning; credentials must never be supplied here. Omit `model` to inherit, rather than `{}`.
This does not select tiers automatically or authorize changing providers/budgets. An omitted
team-member route inherits the calling profile as before, not the newly configured team lead.

Whether the selected model can be used right away depends on the provider:

| Your model's provider | What happens | What to do |
|---|---|---|
| **API key** (OpenRouter, OpenAI API, Anthropic API, …) | Works immediately — keys are copied to new profiles | Nothing |
| **Local model** (llama.cpp, Ollama, LM Studio) | Works immediately | Nothing |
| **OAuth sign-in** (ChatGPT/Codex, Claude subscription, …) | The Bot is created; the result tells you it needs a sign-in | Run the command it gives you once per Bot, **or** set a `fallback_model`, **or** see *share one login* below |

---

## Settings

Set per profile under `plugins.entries.bot-forge.settings` in that profile's `config.yaml`:

```yaml
plugins:
  entries:
    bot-forge:
      settings:
        inherit_model: true
        fallback_model: {}
        probe_local_models: false
        install_gateway: true
        journal_enabled: true
        suggest_connectors: true
        allow_delete: false
```

| Key | Default | Meaning |
|---|---|---|
| `inherit_model` | `true` | Inherit the calling profile's model unless an explicit creation route is supplied. |
| `fallback_model` | `{}` | Model to switch a Bot to when its inherited model can't sign in, e.g. `{default: qwen3, provider: custom, base_url: http://127.0.0.1:8080/v1}`. |
| `probe_local_models` | `false` | With no `fallback_model`, look for a local llama.cpp / Ollama / LM Studio server to fall back to. |
| `install_gateway` | `true` | Verify live host serving and request a hot-rescan if needed. Install a dedicated service only for an explicitly standalone profile. Skipped on Windows. |
| `journal_enabled` | `true` | Give new Bots a private, append-only work journal for outcomes, evidence and next steps. |
| `allow_delete` | `false` | Let `delete_agent` work at all. Off by default — an agent should not be able to destroy a Bot on its own. |
| `backup_before_delete` | `true` | Export the Bot to a `.tar.gz` before deleting it, so it can be restored. If the backup fails, the delete is refused. |
| `allow_secrets` | `false` | Let `share_agent` write / `import_agent` accept a template the secret scanner marked BLOCK. Operator-only; the model cannot pass it as an argument. |
| `suggest_connectors` | `true` | After building a Bot, suggest matching servers from Hermes' MCP catalog. Suggestion only — connecting an account always needs you. |

### Optional: share one login across Bots

The plugin itself never touches credentials. If you want OAuth models to work in new Bots with no per-Bot sign-in, there is an **unsupported** helper you run yourself:

```bash
python extras/share_login.py <bot-name>
```

It points that Bot's `auth.json`/`auth.lock` at the root profile's. Hermes deliberately gives every profile its own login, so understand the trade-off first: a logout in any linked Bot affects all of them, every linked Bot can use every provider login in your root profile, and a Hermes update may undo the links. POSIX only. Undo with `rm <profile>/auth.json <profile>/auth.lock`.

---

## Tools

Fourteen tools, all driven by plain requests in chat:

| Tool | Say this | What it does |
|---|---|---|
| `create_team` | *"set me up a content team"* | Builds a whole team at once: a lead plus up to 6 specialists, each reporting to it. The lead learns the roster and delegates. |
| `teach_agent` | *"remember how I write my weekly report"* | Saves a procedure as a skill the Bot keeps and loads when the job comes up. |
| `create_agent` | *"make me a bot that writes X posts"* | Builds a Bot: name, face, SOUL.md, memory, tools, skills, routines, approvals, Bot Chat intro, gateway. |
| `update_agent` | *"make Inkwell funnier"*, *"give Atlas the browser"* | Edits a Bot in place — persona, name, description, memory, tools, skills, model, face, routines. Backs up what it replaces. |
| `copy_agent` | *"make another one like Inkwell, for LinkedIn"* | Duplicates a Bot under a new name (no chat history, no routines). |
| `list_agents` | *"what bots do I have?"* | Roster with description, model, routine count and hidden state. |
| `check_install` | *"the tools aren't showing up"* | Checks the install itself: enabled profiles, whether each gateway runs the current code, Bot Mode, model sign-in, sandbox backends. |
| `check_agents` | *"anything waiting on me?"* | Leads with `waiting_on_you` — every Bot blocked on something only you can do, with its age. Then the read-only health check: routines that run too often (and their cost in runs/day), paused or never-run routines, unused Bots, stopped gateways, a persona missing its name or approvals. |
| `agent_journal` | *"what did Inkwell work on this week?"* | Enables, appends to, and reads a Bot's dated work journal. Entries capture outcomes and evidence, never credentials or private reasoning. |
| `ask_agent` | *"ask Inkwell for 3 post ideas"* | Sends a task to another Bot and returns its reply. |
| `share_agent` | *"share Inkwell with a friend"* | Writes a readable `.botforge.json` template — persona, its own memory, tools, skills, routines. **Never chat history, facts about you, or keys**, and secret-scanned (CLEAN / WARN / BLOCK). `mode: backup` makes a full private backup instead. |
| `import_agent` | *"import this bot"* | Builds a Bot from a `.botforge.json` template (scanned again), or restores a backup. |
| `hide_agent` | *"hide Inkwell from the list"* | Hides or unhides it in the roster. It keeps running. |
| `delete_agent` | *"delete Inkwell"* | Permanent. **Off unless you enable it**, and it must repeat the Bot's exact name. |

### Start from a proven template

Five starters, modelled on the most-used Grok Bot patterns:

| Template | Bot | What it does | Routine |
|---|---|---|---|
| `chief-of-staff` | Marshal | Routes work to specialists, keeps open loops, pings you only when you must act | 7:00 brief, 18:00 handoff (weekdays), Friday 16:00 review |
| `morning-brief` | Dawn | Calendar, what's waiting on you, 3 headlines — drafts only | 7:30 weekdays |
| `research-digest` | Scout | What changed on your topics in the last 24 hours, sourced | 8:00 daily |
| `competitor-watcher` | Lookout | Reports real changes on competitors' pricing, product and hiring pages | 9:00 weekdays |
| `engineering-outer-loop` | Foreman | Failing checks, stuck PRs, new issues → small tasks. Never writes or merges code | 9:30 weekdays |

> make me a chief of staff from the template

Any field you give overrides the template's, so *"a morning brief bot called Sol that also covers crypto"* works.

### A team in one sentence

> set me up a content team

first considers what already exists. Only justified, authorized new profiles go into
`members`; use `lead_name` to reuse an existing lead. The tool does not enroll arbitrary
existing members. If no new profiles are needed, no team creation call is needed.
For a multi-Bot creation, each new member gets its own role and optional model route.
Failed members are cleaned up individually; successful members remain. Inspect each
member's `warning` and `gateway`, rather than assuming the whole team is online.

### A Bot that tells you where your request stands

Every new Bot starts its reply with one emoji for the state of your request:

| | |
|---|---|
| 👀 | picked it up, working on it |
| 💬 | answering now |
| ✅ | done |
| ✋ | needs your approval before going further |
| ⚠️ | blocked, or something failed |
| ⏳ | scheduled for later |

**In Hermes Desktop the same status lands on your own message as a tapback**, the moment you send it: 👀 while the Bot works, then ✅ / ✋ / ⚠️ for how it ended. The reaction is placed by a hook, not by the model — and because a Hermes hook only runs in the profile running the turn, that hook ships *inside each Bot* as a tiny companion plugin (`bot-forge-marks`: two hooks, no tools, so a Bot never gains the power to create or delete Bots). New Bots get it automatically; for a Bot made before it, ask an agent to *"turn on reactions for <name>"*. It needs *Settings → Appearance → Message Reactions* on, and switches off with `ack_tapback: false`. `check_install` reports which Bots can react and which cannot.

Everywhere else, the state rides on the reply: one emoji, at the very start, then the answer as normal — it is never the whole reply. Because it rides on the reply itself, it works the same in Hermes Desktop, an editor client, the CLI, a cron run or a messaging platform.

> This deliberately does **not** use Hermes' emoji tapbacks: `react_to_message` is documented as a human touch, "never as a status signal", and a Bot told to do both follows neither.

Turn it off for a Bot with `create_agent(ack_reactions=false)`, or on for an older Bot:

> turn on acknowledgements for Inkwell

### Give a Bot its own computer

A Bot with `terminal` or `code_execution` runs commands on **your** machine by default — the same weakness people hit with other bot platforms, where every Bot shares one computer and one set of logins. Ask for a sandbox instead:

> make me a coding bot, sandboxed

`create_agent(sandbox="docker")` puts that Bot's shell in its own container: it cannot read your files and cannot block the other Bots. `singularity` and `apptainer` work too. If the backend is not usable on this machine, the call is **refused before any Bot is created**, with the reason. `check_agents` reports each Bot's sandbox and flags shell-capable Bots that run on the real machine.
### A journal for work that survives the chat

Every new Bot gets a private `journal/YYYY-MM-DD.md` log. After meaningful work it records a short factual entry:

- what it tried and the observable outcome
- evidence such as a file, command, link or measurement
- blockers and the next step

Routine conversation is skipped. Credentials, facts unrelated to the Bot's job, private reasoning and hidden chain-of-thought are refused. Journals stay local, are excluded from shareable `.botforge.json` templates, and are included only in explicit private backups.

For a Bot created before this feature:

> enable journaling for Inkwell

Then ask *"what did Inkwell work on this week?"* to read recent entries.

### What's waiting on you

A blocked Bot writes the blocker in its journal and then goes quiet — so blockers pile up unseen, one Bot at a time. Ask once:

> anything waiting on me?

`check_agents` answers with `waiting_on_you`: every unresolved blocked or failed entry across every Bot, newest first, each with the Bot's name, what it needs and how many days it has sat there.

```
2 waiting on you — Marlow: Need the Stripe API key to pull invoices; Nova: Weekly post draft could not publish
```

The item closes itself when the Bot records the same piece of work as completed — nothing to tick off by hand.

### It knows where it landed

A new Bot normally arrives knowing its job and nothing about your machine, so the first thing you do is explain your own workspace to it. Bot Forge reads that once, at birth:

> make me a social media manager

```
🧪 Quill is alive — find it in Bot Mode.
fits: x-content — X Content Studio (~/work/x-content)
already here: social-media, media-use
heads up: Nova already works in this territory
```

It scores the Bot's own SOUL.md and one-job against the directory Hermes is running in, the repos under it, and this install's Bots, skills and plugins — then writes the answer into the Bot's memory, so it knows on turn one and never researches your machine again. Deterministic word matching, not a model call: no tokens, no waiting, no questions.

**It also refuses to build a Bot you already have.** If an existing Bot's job covers the new one, `create_agent` stops and names it, so a roster of twenty Bots doesn't quietly become a roster of twenty overlapping ones.

Read-only and shallow — directory names, git remotes, and the head of a README / AGENTS.md / CLAUDE.md. Never your source files, never your home directory unless you point `workspace_roots` at it, and anything that looks like a credential never reaches a Bot's memory. Off with `workspace_survey: false`.

### Cost and safety built in

- **Draft-first by default.** Every Bot is born with approval checkpoints — sending/publishing, spending money, deleting data — unless you explicitly ask for none.
- **No runaway routines.** Schedules faster than every 30 minutes are refused unless you explicitly ask (every run is a model call; every 15 minutes is 96 runs a day).
- **Nothing private leaves in a share.** Templates carry the Bot's design, never your chats, your facts or your keys — and they're scanned for secrets on the way out and on the way in.
- **One identity per Bot.** Renaming, copying or importing rewrites the persona's name instead of stacking a second one, so a Bot never introduces itself as another.

### Guardrails a new Bot is born with

`create_agent` takes an `approvals` list and a `reports_to` Bot, written into the new Bot's SOUL.md and memory:

> **Ask first** — never do these without the user saying yes: publish or send anything; spend money; delete files.
> **Escalate to** — @ceo for scope, priorities and final calls.

So a Bot that drafts posts never publishes one, and knows who to escalate to.

Bundled skill: `bot-forge:bot-forge` — role defaults, naming rules and a SOUL.md template your agent follows.

## How it works

`create_agent` runs `forge.py` in a subprocess with a clean environment (Hermes agent terminals point `HOME`/`HERMES_HOME` at the calling profile):

1. **Name check** — against live profiles, display names and Bot titles; generic or taken names are refused with suggestions *before* anything is created
2. `hermes profile create <id> --clone-from default` — messaging channels are left behind
3. **Bot Mode metadata** in `profile.yaml` (`ui_meta.hermes-bots`: title, description, blob face) — the same shape Desktop's New Agent dialog saves
4. **SOUL.md** (guaranteed to state the Bot's own name), `memories/MEMORY.md`, and `memories/USER.md` minus entries that name the assistant — otherwise the new Bot adopts another Bot's name
5. **Journal** — private, dated Markdown entries plus a concise factual journaling policy
6. **Config**: `platform_toolsets.cli`, unrelated skill categories disabled (not deleted), explicit or inherited model before the first inference
7. **Routines** — `hermes cron create … --deliver bot-chat:<id>`
8. **Smoke test** — the kickoff message in its `Bot Chat`
9. **Gateway**: query the live host, request one native hot-rescan if needed, and verify the fresh served roster; no automatic per-profile service in multiplex mode

Failures during creation attempt to delete that profile. An authentication failure can instead
leave it waiting for sign-in. Gateway setup is best-effort and does not delete a created Bot.

The gateway check uses the installed `gateway.control_socket` client with an explicit home,
including named-profile host owners. It does not treat a config flag, stale PID file or rescan
ACK as proof of serving, and never restarts/migrates the host or uses `--force`. An explicitly
standalone profile keeps the native installation path and its refusal rules; parked profiles
are not unparked. `install_gateway: false` skips this setup, not the host's own discovery.
Older Hermes versions or unavailable control clients return `pending`, not an automatic
legacy-service fallback. Consult the installed Hermes documentation for operator setup.
The existing general `check_agents`/`check_install` diagnostics are outside this change.

> **Note:** step 3 writes Desktop's Bot Mode metadata directly. It isn't a public API and may change between Hermes releases.

## What makes it different

| | Grok Bots | OpenMausBot | OpenClaw | **Bot Forge** |
|---|---|---|---|---|
| Build a Bot from one sentence, no dialog | partial | roster UI | config/CLI | ✅ |
| Creation checks and failure cleanup | — | — | — | ✅; pending sign-in/gateway reported separately |
| Persona file you can read and edit | instructions | `SOUL.md` | `SOUL.md` | ✅ `SOUL.md` |
| Edit by chatting | UI | UI | delegation tool | ✅ `update_agent` |
| Share / import a Bot | templates | markdown teams | ClawHub | ✅ `share_agent` |
| Approval checkpoints written in at birth | set later | permission cards | policy | ✅ `approvals` |
| Whole team from one sentence | — | markdown file | — | ✅ `create_team` |
| Teach a skill by chatting | ✅ | playbooks | ClawHub | ✅ `teach_agent` |
| Connector suggestions for the job | ✅ | ✅ | — | ✅ from Hermes' MCP catalog |
| Routine cost health check | community bots | — | — | ✅ `check_agents` |
| Secret scan on shared templates | community bots (Bouncer, Vet) | — | — | ✅ built in |
| Chat history excluded from shares | ✅ | — | — | ✅ |
| Runs entirely on your machine | — | ✅ | ✅ | ✅ |
| Per-Bot sandbox chosen at creation | — (one shared computer) | — | — | ✅ `sandbox` |
| Every reply says where the request stands | — | — | — | ✅ built into every Bot |
| Install doctor | — | — | — | ✅ `hermes bot-forge-doctor` |

## Troubleshooting

| Symptom | Fix |
|---|---|
| Agent suggests reuse or asks a relevant question | Expected for a generic/ambiguous job; explicitly request a new persistent profile when that is the intended design. |
| Agent doesn't know `create_agent` | Run `hermes bot-forge-doctor` — usually the profile isn't enabled or the gateway still runs the old code |
| "name … is taken" | Expected — your agent picks another name automatically |
| New Bot says it needs a sign-in | See step 7 |
| New Bot doesn't appear in the roster | Click another Bot and back, or reopen Hermes Desktop |
| Gateway pending/not started | Read the reason and `hermes gateway status`; do not force a per-profile service or unpark a Bot to hide a warning. |
| An edit didn't take | Changes apply on the Bot's next turn; send it a message. Previous files are in `<profile>/backups/bot-forge/` |
| `delete_agent` refuses | By design: set `allow_delete: true`, or run `hermes profile delete <name>` yourself |

## Uninstall

```bash
hermes plugins disable bot-forge
hermes plugins remove bot-forge
```

Bots you created stay. Remove one with `hermes profile delete <name>`.

## Development

```bash
python -m unittest discover -s tests
hermes plugins validate .
hermes plugins doctor .
```

## License

MIT © Bikash Joshi
