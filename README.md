# 🧪 Hermes Bot Forge

**Say "make me a social media manager" — your Hermes agent builds that Bot.**

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that lets any agent spawn a complete, working [Bot Mode](https://hermes-agent.nousresearch.com/docs/user-guide/bot-mode) Bot from one sentence, with no setup dialog:

- a unique, Proper Case **name** and a blob **face** in the Bots roster
- a job-specific **SOUL.md** written by the agent
- starter **memory** (and what Hermes already knows about you)
- **tools** (file, web, browser + what the role needs) and matching **skills**
- optional **routines** (cron jobs that post into its Bot Chat)
- its **Bot Chat**, opened with the Bot introducing itself
- a background **gateway** service

It smoke-tests the new Bot and rolls everything back if a step fails.

## Tools

| Tool | What it does |
|---|---|
| `create_agent` | Builds a Bot from the agent's design (name, role, SOUL.md, toolsets, skill categories, routines, face). |
| `list_agents` | Lists Bots with name, description and model — used to avoid duplicates and name clashes. |
| `ask_agent` | Asks another Bot something and waits for the reply. (In Bot Chat, Hermes' built-in `message_agent` is fire-and-forget.) |

Plus a bundled skill, `bot-forge:bot-forge`, with role defaults and a SOUL.md template.

## Install

```bash
hermes plugins install BkashJEE/hermes-bot-forge
hermes plugins enable bot-forge
hermes gateway restart
```

Enable it on the profile you chat with (e.g. `hermes -p ceo plugins enable bot-forge`), then restart Hermes Desktop.

## Use

In any chat — best in a Bot's **Bot Chat**:

> make me a bot that writes x.com posts and threads

The agent calls `list_agents`, then `create_agent`, and replies:

```
🧪 Quill is alive — find it in Bot Mode.
job: turns ideas, links and demo notes into X posts and threads
brain: gpt-6-astra   tools: browser, file, web, …
```

## Settings

Under `plugins.entries.bot-forge.settings` in the profile's `config.yaml`:

| Key | Default | Meaning |
|---|---|---|
| `inherit_model` | `true` | New Bots use the model of the profile that asked for them, like Bot Mode's New Agent. |
| `share_login` | `false` | **Read before enabling.** Symlinks each new Bot's `auth.json`/`auth.lock` to the root profile's, so OAuth models (ChatGPT/Codex, Anthropic) work with no per-Bot sign-in. Hermes deliberately keeps one login per profile; with this on, a logout or auth change in any Bot affects all of them. POSIX only. |
| `fallback_model` | `{}` | Model block to switch to when the inherited model can't sign in, e.g. `{default: my-model, provider: custom, base_url: http://127.0.0.1:8080/v1}`. |
| `probe_local_models` | `false` | With no `fallback_model`, look for a local llama.cpp / Ollama / LM Studio server. |
| `install_gateway` | `true` | Install and start a gateway service per Bot (skipped on Windows). |

**Without `share_login`,** a Bot that inherits an OAuth model is still created, and the result tells you the one command to sign it in (`hermes -p <bot> auth add <provider>`). API-key providers work immediately — clones copy keys.

## How it works

`create_agent` runs `forge.py` in a subprocess with a clean environment (Hermes agent terminals point `HOME`/`HERMES_HOME` at the calling profile):

1. validates the name against existing profiles, display names and Bot titles
2. `hermes profile create <id> --clone-from default` (messaging channels are left behind)
3. writes Bot Mode metadata to `profile.yaml` (`ui_meta.hermes-bots`: title, description, blob face) — the same shape Desktop's New Agent dialog saves
4. writes `SOUL.md` (ensuring it names the Bot), `memories/MEMORY.md`, and `memories/USER.md` minus entries that name the assistant — otherwise the new Bot adopts another Bot's name
5. sets `platform_toolsets.cli`, disables unrelated skill categories, sets the model
6. adds routines with `hermes cron create … --deliver bot-chat:<id>`
7. sends the kickoff message in its `Bot Chat` (the smoke test)
8. `hermes -p <id> gateway install --start-now --start-on-login`

Any failure after step 2 deletes the profile.

**Caveat:** step 3 writes Desktop's Bot Mode metadata directly; it isn't a public API and may change between Hermes releases.

## Development

```bash
python -m unittest discover -s tests
hermes plugins validate .
hermes plugins doctor .
```

## License

MIT © Bikash Joshi
