<p align="center">
  <a href="https://github.com/BkashJEE/hermes-bot-forge/actions/workflows/tests.yml"><img src="https://github.com/BkashJEE/hermes-bot-forge/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
</p>

<p align="center">
  <img src="docs/banner.png" alt="Bot Forge — one sentence to a complete, working Hermes Bot" width="100%">
</p>

# 🧪 Hermes Bot Forge

**Say "make me a social media manager" — your Hermes agent builds that Bot.**

Bot Forge is a [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that lets any agent spawn a complete, working [Bot Mode](https://hermes-agent.nousresearch.com/docs/user-guide/bot-mode) Bot from one sentence — no New Agent dialog, no setup:

| The new Bot gets | |
|---|---|
| 🪪 **Identity** | a unique, Proper Case name and a blob face in the Bots roster |
| 📜 **SOUL.md** | written by your agent for that one job |
| 🧠 **Memory** | starter facts, plus what Hermes already knows about you |
| 🛠️ **Tools & skills** | file, web and browser, plus what the role needs |
| ⏰ **Routines** | optional cron jobs that post into its Bot Chat |
| 💬 **Bot Chat** | opened with the Bot introducing itself |
| 🔌 **Gateway** | a background service, started and enabled on login |

Every step is checked, and the whole Bot is rolled back if one fails.

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
- Linux or macOS for gateway services (on Windows, Bots are created without a gateway)

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
hermes -p ceo gateway restart   # for each profile you enabled
```

Then quit and reopen **Hermes Desktop**.

### 5. Check it's loaded

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

New Bots inherit the model of the Bot that created them. Whether they can use it right away depends on the provider:

| Your model's provider | What happens | What to do |
|---|---|---|
| **API key** (OpenRouter, OpenAI API, Anthropic API, …) | Works immediately — keys are copied to new profiles | Nothing |
| **Local model** (llama.cpp, Ollama, LM Studio) | Works immediately | Nothing |
| **OAuth sign-in** (ChatGPT/Codex, Claude subscription, …) | The Bot is created; the result tells you it needs a sign-in | Run the command it gives you once per Bot, **or** set a `fallback_model`, **or** read about `share_login` below |

---

## Settings

Set per profile under `plugins.entries.bot-forge.settings` in that profile's `config.yaml`:

```yaml
plugins:
  entries:
    bot-forge:
      settings:
        inherit_model: true
        share_login: false
        fallback_model: {}
        probe_local_models: false
        install_gateway: true
        allow_delete: false
```

| Key | Default | Meaning |
|---|---|---|
| `inherit_model` | `true` | New Bots use the model of the profile that asked for them, like Bot Mode's New Agent. |
| `fallback_model` | `{}` | Model to switch a Bot to when its inherited model can't sign in, e.g. `{default: qwen3, provider: custom, base_url: http://127.0.0.1:8080/v1}`. |
| `probe_local_models` | `false` | With no `fallback_model`, look for a local llama.cpp / Ollama / LM Studio server to fall back to. |
| `install_gateway` | `true` | Install and start a gateway service per Bot (skipped on Windows). |
| `allow_delete` | `false` | Let `delete_agent` work at all. Off by default — an agent should not be able to destroy a Bot on its own. |
| `backup_before_delete` | `true` | Export the Bot to a `.tar.gz` before deleting it, so it can be restored. |
| `share_login` | `false` | ⚠️ See below. |

### ⚠️ `share_login`

With `share_login: true`, each new Bot's `auth.json` and `auth.lock` are **symlinked** to your default profile's, so OAuth models work with zero sign-ins.

Hermes deliberately gives every profile its own login. Turning this on means:

- a logout, re-login or auth change in **any** Bot affects **all** of them
- all Bots share every provider login in your default profile
- a future Hermes update may undo or refuse the links

It's POSIX only. Use it on a personal machine where you understand the trade-off.

---

## Tools

Nine tools, all driven by plain requests in chat:

| Tool | Say this | What it does |
|---|---|---|
| `create_agent` | *"make me a bot that writes X posts"* | Builds a Bot: name, face, SOUL.md, memory, tools, skills, routines, approvals, Bot Chat intro, gateway. |
| `update_agent` | *"make Inkwell funnier"*, *"give Atlas the browser"* | Edits a Bot in place — persona, name, description, memory, tools, skills, model, face, routines. Backs up what it replaces. |
| `copy_agent` | *"make another one like Inkwell, for LinkedIn"* | Duplicates a Bot under a new name (no chat history, no routines). |
| `list_agents` | *"what bots do I have?"* | Roster with description, model, routine count and hidden state. |
| `ask_agent` | *"ask Inkwell for 3 post ideas"* | Sends a task to another Bot and returns its reply. |
| `share_agent` | *"export Inkwell so I can send it to a friend"* | Packs the Bot into a `.tar.gz` — persona, memory, skills, config, routines. **No keys or logins.** |
| `import_agent` | *"import this bot"* | Restores a shared Bot and starts it. |
| `hide_agent` | *"hide Inkwell from the list"* | Hides or unhides it in the roster. It keeps running. |
| `delete_agent` | *"delete Inkwell"* | Permanent. **Off unless you enable it**, and it must repeat the Bot's exact name. |

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
5. **Config** — `platform_toolsets.cli`, unrelated skill categories disabled (not deleted), inherited model
6. **Routines** — `hermes cron create … --deliver bot-chat:<id>`
7. **Smoke test** — the kickoff message in its `Bot Chat`
8. **Gateway** — `hermes -p <id> gateway install --start-now --start-on-login`

Any failure after step 2 deletes the profile.

> **Note:** step 3 writes Desktop's Bot Mode metadata directly. It isn't a public API and may change between Hermes releases.

## What makes it different

| | Grok Bots | OpenMausBot | OpenClaw | **Bot Forge** |
|---|---|---|---|---|
| Build a Bot from one sentence, no dialog | partial | roster UI | config/CLI | ✅ |
| Tested before you get it, rolled back on failure | — | — | — | ✅ |
| Persona file you can read and edit | instructions | `SOUL.md` | `SOUL.md` | ✅ `SOUL.md` |
| Edit by chatting | UI | UI | delegation tool | ✅ `update_agent` |
| Share / import a Bot | templates | markdown teams | ClawHub | ✅ `share_agent` |
| Approval checkpoints written in at birth | set later | permission cards | policy | ✅ `approvals` |
| Runs entirely on your machine | — | ✅ | ✅ | ✅ |

## Troubleshooting

| Symptom | Fix |
|---|---|
| Agent asks questions instead of building | Say "bot" or "agent" in the request, e.g. *"make me a bot that…"* |
| Agent doesn't know `create_agent` | Plugin not enabled on **that** profile, or Hermes not restarted (steps 3–4) |
| "name … is taken" | Expected — your agent picks another name automatically |
| New Bot says it needs a sign-in | See step 7 |
| New Bot doesn't appear in the roster | Click another Bot and back, or reopen Hermes Desktop |
| Gateway "not started" | Run `hermes -p <bot> gateway install --start-now` and read its output |
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
