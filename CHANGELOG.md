# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.9.0] - 2026-09-24

### Added
- **The acknowledgement now lands on your own message in Hermes Desktop**, the moment you send it: 👀 while the Bot works, then ✅ / ✋ / ⚠️ for how the turn ended. The plugin places it through `react_to_message` itself rather than leaving it to the model — that tool tells the model it is a human touch, "never as a status signal", so a Bot asked to signal status with it did nothing. Desktop sessions only, needs Settings → Appearance → Message Reactions, off with `ack_tapback: false`, and a failed reaction can never break a turn. The reply prefix still covers every other surface.

## [0.8.0] - 2026-09-24

### Changed
- **Acknowledgements now ride on the reply**, not on an emoji tapback: a Bot begins its answer with 👀 / 💬 / ✅ / ✋ / ⚠️ / ⏳ and then answers as normal. Reactions could not do this job — Hermes' own `react_to_message` is documented as a human touch and "never as a status signal", so a Bot told to use it for status followed neither instruction, and it existed only in Desktop sessions with an opt-in setting enabled. The reply prefix works in Desktop, editor clients, the CLI, cron and messaging alike, with no setting.
- Enabling acknowledgements on a Bot that carries the old convention replaces that block instead of stacking a second one, and reports `upgraded`.

## [0.7.2] - 2026-09-24

### Fixed
- A Bot created by Bot Forge could never react in Hermes Desktop. Its canonical Bot Chat was created through `chat -c "Bot Chat" --create-if-missing`, which hardcodes `source="cli"` upstream, and a session's stored source is what decides its client surface — so the Desktop toolset holding `react_to_message` was never offered. On a Bot Mode install the chat is now started with `--source desktop` and then given the canonical title, matching what Desktop itself creates.

## [0.7.1] - 2026-09-24

### Fixed
- Acknowledgements only reached newly created Bots, so the Bot a user actually talks to stayed silent and the feature looked broken. `check_agents` now reports `acknowledges` per Bot and lists `not_acknowledging`, the doctor counts how many Bots acknowledge and names the ones that don't, and the skill tells an agent to check the current Bot first when reactions aren't happening. Switch one on with `update_agent(ack_reactions: true)`.

## [0.7.0] - 2026-09-24

### Added
- Acknowledgement reactions — a Bot taps back on the message it picked up: 👀 started, 💬 answering now, ✅ done, ✋ needs your approval, ⚠️ blocked, ⏳ scheduled. Once on pickup, once on the outcome, and never instead of a reply. On by default (`ack_reactions`); `update_agent(ack_reactions: true)` adds it to a Bot created earlier.

## [0.6.0] - 2026-09-24

### Added
- `agent_journal` — enable, append to, and read a Bot's private dated work journal. Entries capture outcomes, evidence, blockers and next steps while refusing credential-shaped content.
- New Bots receive concise journaling guidance by default (`journal_enabled: true`); older Bots can be enabled without replacing their persona.

### Changed
- Shareable `.botforge.json` templates continue to exclude activity history, now explicitly including Bot work journals. Full private backups retain them.
- The doctor no longer warns about profiles that deliberately don't have Bot Forge enabled, and says plainly on Windows that the platform is untested.
- README states which platforms are tested.

## [0.5.0] - 2026-09-23

### Added
- `hermes bot-forge-doctor` (and the `check_install` tool) — checks the install itself: which profiles have Bot Forge enabled, whether each gateway is running the current plugin code (the usual reason the tools never appear), Desktop Bot Mode, whether a new Bot's inherited model can sign in, usable sandbox backends, bundled templates, and version drift between profiles. Read-only, and it prints the exact next commands.
- `create_agent(sandbox=...)` — give a Bot its own computer: `docker`, `singularity` or `apptainer` put its shell in a container instead of on the user's machine. The call is refused before anything is created when the backend is not usable here. Also available per member in `create_team`.
- `check_agents` reports each Bot's sandbox and flags Bots with `terminal` / `code_execution` / `computer_use` that run directly on the real machine.

## [0.4.1] - 2026-09-19

### Fixed
- `delete_agent` now takes a real `.tar.gz` backup (`mode=backup`) before deleting and refuses to delete when that backup fails; before, it silently wrote a design-only template or nothing at all.
- `allow_secrets` is now an operator setting (`config_schema`), not a tool argument — a model could previously pass it to `share_agent` / `import_agent` and bypass the BLOCK verdict of the secret scanner.
- `share_agent` `path` must stay under `<hermes>/profile-exports` and never overwrites an existing file; before, it could write anywhere the process could.

## [0.4.0] - 2026-09-19

### Added
- `check_agents` — read-only health check: routines with estimated runs/day, too-frequent / paused / never-run routines, unused Bots, stopped gateways, and personas missing their own name or approval checkpoints.
- Starter templates: `chief-of-staff`, `morning-brief`, `research-digest`, `competitor-watcher`, `engineering-outer-loop` — `create_agent(template=...)`, overridable field by field.
- Portable `.botforge.json` templates with a secret scanner (CLEAN / WARN / BLOCK) on export and import. Findings report the kind and line of a secret, never its value.
- Draft-first defaults: every new Bot gets approval checkpoints for sending/publishing, spending and deleting unless `approvals: []` is passed explicitly.
- Routine guard: schedules faster than every 30 minutes are refused unless `allow_frequent` is set.

### Fixed
- **Privacy:** `share_agent` exported the whole profile, including the Bot's chat history (`state.db`) and facts about the user (`USER.md`). It now writes a design-only template; a full backup is an explicit `mode: backup`, labelled as private.
- Renaming, copying or importing a Bot stacked a second "You are **Name**" line on top of the old one, so the Bot could introduce itself by its previous name. The persona now has exactly one identity, and its heading is renamed too.
- `update_agent` with a new `display_name` renamed the roster entry but not the persona.
- `create_team` dropped each member's warnings and connector suggestions from its result.
- Guardrail sections no longer leave stray blank lines in SOUL.md.

## [0.3.0] - 2026-09-17

### Added
- `create_team` — build a lead plus up to six specialists in one request. Each member reports to the lead, the lead learns the roster so it can delegate, and a member that fails is rolled back on its own.
- `teach_agent` — save a procedure as a skill in the Bot's own skills folder ("remember how I write my weekly report"), and re-enable it if that skill was disabled.
- `create_agent` now suggests matching servers from Hermes' MCP catalog for the Bot's job (`suggest_connectors`, on by default; suggestion only).

### Changed
- **The plugin no longer touches credentials.** `share_login` is gone; sharing one login across Bots now lives in `extras/share_login.py`, an optional script the user runs themselves, with the trade-offs documented.

## [0.2.0] - 2026-09-17

### Added
- `update_agent` — edit a Bot by chatting: persona (append or replace), name, description, memory, toolsets, skill categories, model, face and routines. Replaced files are backed up under `<profile>/backups/bot-forge/`.
- `copy_agent` — duplicate a Bot under a new name.
- `share_agent` / `import_agent` — export a Bot to a `.tar.gz` and import it back. Credentials are never included.
- `hide_agent` — hide or unhide a Bot in the Desktop roster without touching it.
- `delete_agent` — permanent delete, disabled unless `allow_delete` is set, requiring the Bot's exact name and backing it up first.
- `create_agent` now takes `approvals` (checkpoints written into SOUL.md and memory) and `reports_to` (its chief of staff).
- `list_agents` also reports display name, hidden state and routine count.
- CI: unit tests on Python 3.11 and 3.12.

### Fixed
- Rewriting a Bot's `config.yaml` kept the default umask, which could widen the file's permissions; the original mode is now preserved and the write is flushed to disk.
- Sharing the root login no longer creates or modifies any file inside the root profile, and swaps the link atomically.
- Rollback now reports whether the half-built profile was really deleted, and tells the user the cleanup command if not.
- Windows: the fallback Hermes root is `%LOCALAPPDATA%\hermes`.
- SQLite connections used to find the calling profile are closed (they blocked profile deletion on Windows).
- `profile create` gets a longer timeout, since it copies the whole skills tree.

### Changed
- `plugin.yaml` declares `requires_hermes: ">=0.21"`.

## [0.1.1] - 2026-09-17

### Fixed
- `hermes plugins install` refused the plugin: Hermes' installer supports `manifest_version` 1 only, so the v2 manifest markers were dropped.
- Deleted Bots no longer reserve their name — a tombstoned profile directory made a freed name look taken.

## [0.1.0] - 2026-09-17

### Added
- `create_agent` — build a complete Hermes Bot from one sentence: unique Proper Case name, blob face, SOUL.md, memory, toolsets, skill categories, routines, Bot Chat self-introduction and gateway service, with rollback on failure.
- `list_agents`, `ask_agent`.
- Bundled skill `bot-forge:bot-forge` with role defaults and a SOUL.md template.
- Settings: `inherit_model`, `fallback_model`, `probe_local_models`, `install_gateway`, and opt-in `share_login`.
