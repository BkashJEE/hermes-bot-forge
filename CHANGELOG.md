# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
