# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.19.0] - 2026-10-10

### Added
- **Sentinel hook implementation (manual setup required).** The repository includes a hooks-only `sentinel/` plugin with tool-name policy rules and argument limits. When separately installed, enabled and configured in a profile, its `pre_tool_call` hook returns block or approval directives for Hermes to handle. In v0.19.0, `create_agent` does not install or enable Sentinel and does not derive a Sentinel policy from `approvals`; those approvals remain guidance in `SOUL.md`. The advertised `enforce_approvals` setting is not implemented in this release. Hook unit tests do not establish activation or enforcement in a running Bot. See `sentinel/README.md` for the policy shape and `docs/sentinel.md` for the design proposal.
- **Limits on arguments, not just tool names (when Sentinel is separately active).** `limits: {tool: {argument: [permitted values]}}` expresses the rule a name gate cannot — *"may email me, not anyone else"*. A call within its limits runs without asking, because the user already said that shape is fine; one outside is refused and the message names the argument and the value. Unreadable input is a question, not a yes: a nested object, a malformed rule or an absent argument falls through to the ordinary gate rather than permitting the call.
- **`check_agents` says which Bots hold a readable login.** A Bot with its own `auth.json` can read that token — that is how an independent login works, and it was invisible. A private copy is reported as reach; one other users can read is a finding, with the fix.
- **A demo loop in the README.** `docs/demo.gif` — one sentence becoming a complete Bot, built as `videos/bot-spawn/`.

- **Shared operating policy: write a rule once, every Bot picks it up.** `~/.hermes/shared/BOT-POLICY.md` holds the rules that apply to every Bot; `create_agent` inlines it into each new Bot's `SOUL.md` between `<!-- forge:shared-policy:begin -->` / `<!-- forge:shared-policy:end -->` markers, so a rule is edited in one place instead of pasted into N drifting copies. A short starter policy is written on first use; `shared_policy: false` opts a Bot out, `shared_policy_path` points at a different file (relative to the Hermes root, containment-checked) and `shared_policy_create: false` makes a missing file an error instead of seeding the starter. Design and rejected alternatives (symlink, pointer line): `docs/shared-policy.md`.
- **New tool `check_policies` (read-only).** Fingerprints each Bot's inlined block against the canonical file and reports `stale`, `no_shared_policy` and `unreadable` Bots. Only the policy body is hashed — comments, CRLF, trailing whitespace, bullet marker and block-wide indentation are cosmetic; a sub-bullet added, removed or re-nested is drift. The tool only reads `SOUL.md` files under the Hermes root; it has no network or write path.
- **`update_agent` takes `refresh_shared_policy`.** Re-injects the current policy into an existing Bot in place (backs `SOUL.md` up first, idempotent, keeps identity and persona). Needed because `create_agent` refuses a taken name, so it cannot refresh a Bot.
- `tests/test_shared_policy.py` (58 tests) covers the above.

- **Bots hand work to each other.** `handoff_agent(to, task, context)` moves a task from the Bot the user is talking to onto another Bot, which then owns it. The receiving Bot is told who handed it over, what it owns, what is already known and what "done" looks like, and the work runs in **its own Bot Chat**, so the user can watch it in Desktop rather than find it buried in a lead Bot's transcript. `ask_agent` stays what it was — a question and an answer — this is ownership moving.
- **The outcome is a state, not prose.** Every Bot Forge Bot already begins its replies with one acknowledgement emoji; the handoff reads it. ✅ is `completed`, ✋ is `needs_you`, ⚠️ is `blocked`, ⏳ is `scheduled`, and a reply with none of them is reported as such instead of guessed at. A ✋ or ⚠️ writes a `blocked` entry in the receiving Bot's journal, so it is already in *what's waiting on you* and already mailed, with nothing extra to wire.
- **The record survives the chat.** Each handoff is written to the receiving Bot's `handoffs/<id>.json` before the turn runs, updated with the outcome after, and both Bots journal it (*Handed off to Inkwell* / *Handoff from Marshal*). `check_agents` lists every handoff that has not ended in ✅ under `handoffs`, newest first, with its age — the first answer to "where did that task go?".

### Changed
- Anything that assumed the `# Name — Role` heading is line 1 of `SOUL.md` now skips the policy block (`forge.persona_text`): `soul_role`, `ensure_identity` (which re-injects the block so a rename never drops a Bot's rules, and adds none to a Bot that had none), the `health` check that a SOUL.md states the Bot's name, the workspace survey's duplicate-Bot guard, and `share_agent` (an exported template no longer carries the originating Bot's inlined rules).
- The inlined policy is prompt text the model is asked to follow, not enforcement. Nothing blocks a tool call that breaks a rule.

### Fixed
- README said "Thirteen tools"; the manifest already listed fourteen before this change, and lists fifteen with `check_policies`.

- The platform claim is derived from CI rather than asserted. The previous check compared the skill's `platforms:` against a constant in the test file — two values the maintainer typed — and went green while every job ran `ubuntu-latest` and a test failed deterministically on macOS. The workflow is now the evidence, and **macOS actually runs**: it joined the matrix and passes on 3.11 and 3.12.
- Two bugs reported from macOS: `ask_agent` dropped `USER` from the child environment, so the Claude CLI reported no login (found by @akinduroifedayo), and a credential-copy test compared an unresolved temp path against a resolved one, failing on every fresh macOS checkout (found by @ChrisCarlCao).

### Security
- **Only words cross between Bots.** The receiving Bot's turn runs with the same environment allowlist `ask_agent` has used since #22 (network and config, never `SSH_AUTH_SOCK` or the caller's `.env`), now shared as `forge.safe_env` rather than duplicated. The task and context are secret-scanned before anything is sent; a credential in either is refused with the reason and nothing runs. The sender is the profile whose turn called the tool, never a tool argument, so a Bot cannot hand work over in another Bot's name.

### Internal
- Coverage is reported per module in CI — never gated, because subprocess probes and a deliberately duplicated file make the number a floor rather than a measurement.
- `tools.py` coverage 39% → 60%, by testing what the handlers do when creation times out, when the subprocess prints something other than JSON, and when a profile's config will not parse.

## [0.18.0] - 2026-10-06

### Added
- **The waiting queue can deliver itself.** `notify.py schedule "0 8 * * *"` writes a small launcher into the running profile's `scripts/` and creates a Hermes cron job for it with `--no-agent` — so it costs no model turn, and Hermes delivers the output wherever that profile already delivers. **No email configuration is needed**, which matters because the mail path needs SMTP credentials and the queue was otherwise only visible when someone remembered to ask.
- An empty queue prints nothing at all. A digest that greets you every morning with "nothing is waiting" is one you stop reading, so silence is the default rather than a cheerful all-clear.
- `check_install` reports whether anything delivers the queue, with the command when nothing does.

### Fixed
- The digest's closing line was written for email ("this address does not take replies"). Delivered through Hermes' cron it can land in Telegram or a Bot Chat, where that sentence means nothing; the scheduled form says "Answer any of them in Hermes."
- **Share a Bot as a link, not a file.** `share_agent` with `publish: true` posts the secret-scanned template as an unlisted gist and returns the URL; `import_agent` now takes an https link as well as a path, so sharing a Bot is "here, click this" rather than "download this and tell me where you put it". The round trip is verified end to end, not only mocked.
- Publishing goes through the user's own `gh` CLI, which already holds their GitHub auth: the plugin stores no token and asks for none, and when `gh` is missing or signed out it says which and still writes the file. A link is reported as **unlisted, not private** every time — anyone holding the URL can read the Bot's design, and "secret gist" reads as private when it is not.
- An imported link is read defensively: https only, size-capped, never executed, parsed from the first brace so a gist description or a pasted heading does not break it, rejected when it is not a Bot, and secret-scanned so someone else's leaked credential is refused on the way in.

## [0.17.1] - 2026-10-06

### Fixed
- **The plugin failed to load at all on an install without PyYAML.** `forge.py`, `manage.py`, `companion.py` and `tools.py` all `import yaml`, but no manifest ever declared it — so Hermes never installed it, and the plugin only worked on a machine where some unrelated package happened to drag PyYAML in. On a clean install the loader logged `Failed to load plugin 'bot-forge': No module named 'yaml'` and dropped all 14 tools and both hooks. `plugin.yaml` now declares `python_dependencies: [PyYAML>=6.0,<7]`, which Hermes installs into the environment the plugin runs in and keeps across later dependency syncs. Reported with a full reproduction on Windows.
- **CI could not have caught it.** The workflow ran a hardcoded `pip install pyyaml==6.0.2` instead of installing from the manifest, so the declaration was never exercised — and the plugin's own manifest-parsing step imports yaml, so the test job itself supplied the missing dependency. Test dependencies now come from `requirements-dev.txt`, and `tests/test_declared_dependencies.py` asserts every third-party import in the shipped plugin is declared in `plugin.yaml` with an upper bound.
- **`hermes bot-forge-doctor` crashed on Windows reading the plugin's own manifest.** `forge.load_yaml()` read every manifest with `Path.read_text()` and no encoding, so on Windows it used the ANSI code page; `plugin.yaml` and `marks/plugin.yaml` both carry emoji, so it raised `UnicodeDecodeError` immediately — and that is a `ValueError`, not an `OSError`, so it escaped the `except` clause and took the caller with it. Manifests are read as UTF-8 and the decode error is caught. Found and fixed by @Plub-Supanut.

## [0.17.0] - 2026-10-04

### Added
- **A Bot can have a screen of its own.** `bot_screen: true` on `create_agent` (or `update_agent` for one that already exists) gives the Bot its own Xfce desktop on the gateway host, granting `computer_use` and `browser`: it browses and clicks there, the user watches in Hermes Desktop, takes over for a login, 2FA prompt or CAPTCHA, and hands control back so the Bot continues with the session the user just signed in to. The screen lives on the gateway, so the work survives closing the laptop. Off by default — a screen costs about 1.1-1.5 GB while open — and meant for jobs that need a real browser session a human may have to rescue.
- **It refuses rather than half-delivering.** On macOS and Windows there is no separate screen, so the Bot would act on the *user's own* display; that is declined with the reason instead of being granted by implication. A Linux host missing TigerVNC/Xfce or the cua-driver is told which, with the command that fixes it, and no Bot is created — the same contract the sandbox option has always had.

## [0.16.0] - 2026-10-02

### Added
- **A Bot can inherit the root profile's plugins, when asked.** `inherit_plugins` — opt-in, default off — copies named plugins from the root profile into a new Bot and enables them there, as a setting or per `create_agent` / `update_agent` call. It runs on the same install path as the reaction companion, so it inherits that path's hardening, and no `.env`, `auth.json`, key or certificate travels with a plugin.
- **`["all"]` stops at anything that needs credentials.** A plugin whose manifest declares `requires_env` is skipped under a blanket request and has to be named, with the reason reported rather than dropped silently. "Give it everything" should not hand a new Bot reach into a mail account as a side effect; asking for that plugin by name is how a user says yes to it.

## [0.15.4] - 2026-10-02

### Fixed
- **`create_agent` claimed it had started a background gateway when it had not.** Current Hermes serves every profile from one multiplexed host gateway, so `hermes -p <bot> gateway install` exits 0 while installing nothing and saying `--force` would be needed. The result mapped exit 0 to "started", putting a service in the report that does not exist. It now says `served by the host gateway` when that is what happened, keeps `started` for a real install, and never dresses up a failure. The underlying point — that a successful creation should not claim more than it did — is from #24 by @sealca.

## [0.15.3] - 2026-10-02

### Changed
- Credited the people outside this repo who found what is fixed in 0.15.1 and 0.15.2. Both of @samideckers-cmd's fixes reached `main` through rebuilt branches rather than their own commits, so git attributes their work to the maintainer; README now records what each person found.

## [0.15.2] - 2026-10-01

### Fixed
- **`hermes bot-forge-doctor` failed with `ModuleNotFoundError: doctor`.** v0.15.1 converted every module-level in-package import, but not the deferred ones inside functions — and the doctor CLI command is registered in-process, so its `import doctor` resolved only when the gateway happened to be running from the plugin's own directory. Twenty-eight deferred imports across nine modules are now package-aware. Reported as the same class of problem in #21 by @samideckers-cmd, five days before the catalog review found the module-level case.
- The import test now checks both forms. The first version grepped for `^import x` only, so a deferred `import doctor` passed it, and a probe run from inside the repo passed as well because the current directory is on `sys.path`. It now scans every occurrence and loads the plugin as a package from a different working directory, the way Hermes does.

## [0.15.1] - 2026-10-01

### Fixed
- **The plugin stopped loading at all in v0.15.0, and with it all 14 tools.** `register()` reached `companion.py`, whose module-level `import forge` was unprefixed; Hermes imports a plugin as a package without putting its directory on `sys.path`, so `ModuleNotFoundError` escaped `register()` and the loader dropped every tool and hook. The tests missed it because they add the plugin directory to `sys.path` themselves. Every in-package import now resolves package-relative, with a fallback for the modules that are also run as scripts, and a test asserts no bare in-package import can come back. Reported in catalog review by @teknium1.
- **The SMTP password could be sent in the clear.** `starttls()` ran with no SSL context (no certificate or hostname verification) and a failed upgrade was swallowed, so `login()` could proceed unencrypted. TLS is now verified, implicit TLS is used on port 465, and a server that cannot do STARTTLS is refused before any credential is sent.
- **The mail switches were ignored.** `agent_journal` was registered without the settings wrapper the other tools get, so its settings were always `{}` and `notify_blocked: false`, `notify_email: false` and a custom address never took effect — a blocked entry mailed the default address whenever SMTP was configured. `check_install` had the same gap and could report that a blocked Bot would email the user when they had switched that off.
- **Adoption is opt-in.** `adopt_bots` defaulted to on while being absent from the settings list, so the opt-out could never fire and every load wrote into every profile on the machine, including ones Bot Forge never created. It now defaults to off and is honoured.
- **Sharing a login copies it instead of symlinking.** A link made the Bot's profile *be* the root profile's credential store: a token refreshed or revoked in one silently rewrote the other. `extras/share_login.py` now copies `auth.json` at mode 0600, replaces a link left by an older version, and says it is a snapshot.

### Added
- `notify.py digest` and `notify.py status` as plain subcommands, so scheduling the digest needs no shell pipe.

## [0.15.0] - 2026-09-30

### Added
- **Every profile gets the reaction, however it was made.** A Bot created through Hermes' own New Agent dialog or `hermes profile create` never heard of this plugin, and stayed silent while Bot Forge's own Bots acknowledged. The plugin now adopts every live profile on load: it installs the hook and switches on Hermes' `message_reactions` setting, does nothing when both are already in place, and never blocks loading if a profile is broken. `adopt_bots: false` switches it off.
- **The ending reaction says what happened, not just that something did** — 🚀 shipped, 📝 written, 📈 numbers, 🗓️ scheduled, 💡 found out, 🧹 cleaned up, with ✅ as the fallback. State still wins over kind: a draft that needs sign-off is ✋, and a write that ended in a failed deploy is ⚠️.

### Fixed
- **A new Bot could be created with the hook installed and still never react**, because `create_agent` set up the hook but not Hermes' `message_reactions` setting — and an unset value reads as off. Creation now does both.
- The numbers rule never matched a percentage: the pattern ended in a word boundary right after `%`, which is already a non-word character, so `up 18%` silently fell through to the generic ✅.

## [0.14.1] - 2026-09-30

### Fixed
- **A Bot in the profile that also runs Bot Forge itself never appeared to react at all.** Both the plugin and its `bot-forge-marks` companion register the same pair of turn hooks, so in a profile holding both, the reaction was placed twice — and Hermes reads a second identical emoji as a tapback toggle, clearing it. The reaction was being placed and instantly removed on every turn. The plugin now stands down when the companion is installed and enabled beside it, since the companion is the copy that ships inside every Bot.

## [0.14.0] - 2026-09-29

### Changed
- **The pickup reaction now fits what was asked.** Every turn used to open with the same 👀, which only told the user the Bot was alive. The reaction is now chosen from the message itself — 🔧 a fix, 🔎 research, ✍️ writing, 📊 numbers, ⏳ something scheduled, 📋 a review, 🛠️ something to build, 👋 a greeting, 💬 a question — and falls back to 👀 when the ask is not recognisable rather than guessing. The end of the turn still replaces it with ✅ / ✋ / ⚠️, so the two sets are kept disjoint: Hermes clears a reaction when the same emoji is set twice.
### Added
- **A Bot can inherit your plugins — when you say so.** `hermes profile create --clone-from` copies the root profile's `config.yaml`, with its `plugins.enabled` list, but not the plugin directories, so a plugin you run on your main profile was silently *enabled but inert* in every Bot. `inherit_plugins` (the plugin setting for every new Bot, or the `create_agent` / `update_agent` argument for one) copies the named plugins — or `["all"]` of the enabled ones — into the Bot on the same path the reaction companion already uses, and enables them. Default off: a Bot gets only what it was asked for. Bot Forge itself is never copied into a Bot, the companion is never copied twice, and no `.env`, key or credential file travels with a plugin. Rollback still removes the whole profile. (#25, reported by @thealps01-netizen)
- `check_agents` flags a Bot whose config enables a plugin that has no directory in that profile — enabled but inert — and says how to fix it. Hermes' own bundled plugins are never flagged.

## [0.13.0] - 2026-09-28

### Added
- **A blocked Bot emails you instead of waiting to be asked.** `check_agents` gathers what needs you when you think to ask; this is the push half. When a Bot journals a `blocked` or `failed` entry it sends one plain-text message, and `notify.py --action digest` sends the whole queue on a schedule. It reuses the email Hermes already has (`EMAIL_SMTP_HOST` / `EMAIL_ADDRESS` / `EMAIL_PASSWORD`) — no new credential, no new service, nothing to sign up for. `notify_email` redirects it or switches it off; `notify_blocked` controls the per-blocker message.
- `check_install` now reports whether a blocked Bot can reach you, or is waiting silently.

### Security
- **Outbound only, and the recipient is resolved from config alone** — never from a tool argument, a persona, or any text a model produced. A Bot can write to the user's own address and no other, so it cannot be talked into mailing a third party, and two Bots cannot start a reply loop. Nothing in the plugin reads a mailbox. Messages are rate limited per Bot, secret-scanned before sending, and skipped silently when mail is unconfigured or the server is unreachable — a failed send can never break a turn, a journal write, or a routine.

## [0.12.1] - 2026-09-25

### Fixed
- **The survey is useful on a real machine, not just a tidy one.** Three faults, all found by running it against a workspace with ten roots and thirty near-identical checkouts:
  - One crowded root ate the whole scan budget, so the nine roots after it were never looked at and a Bot was pointed at whatever sorted first. Each root now gets its own share.
  - A directory with almost no words in it matched anything it shared one word with — a folder named `omarchy` scored a perfect 1.00 against a theming Bot on the strength of its own name. A place now needs real vocabulary and at least two shared terms before it can be recommended.
  - Nested copies of the same checkout appeared three times; the shallowest path now wins.
- **A job and a directory rarely use the same word for the same thing.** The job's vocabulary is widened with related terms before places are searched, so a Bot whose job says "x.com posts" finds the repo that holds that work even when it never uses the word "social", and an inbox Bot finds the repo that watches mail. The widening applies only to the job and only when matching places — never to the corpus, and never to the duplicate guard, which still compares what two Bots actually say.

## [0.12.0] - 2026-09-25

### Added
- **A new Bot knows where it landed.** `create_agent` now surveys the workspace the Bot was born into — the directory Hermes is running in and the repos under it, plus this install's own Bots, skills and plugins — scores it against the Bot's own SOUL.md and one-job, and writes the result into the Bot's memory. The Bot knows which repo holds its work on its first turn, and neither it nor the calling agent has to research the user's machine. Deterministic word matching, no model call. The result's `workspace` block carries `fits`, `covered_by`, `skills_here` and `next_steps` for the reply.
- **A Bot that already exists is not built twice.** When an existing Bot's job covers the new one, `create_agent` refuses and names it, rather than letting the roster fill with overlapping Bots. `allow_overlap: true` is the way past it, once the user has said they want both.
- `workspace_survey` (default on) and `workspace_roots` configure the scan. It is read-only and shallow: directory names, git remotes, and the head of a README / AGENTS.md / CLAUDE.md — never source files, never the home directory unless it is named in `workspace_roots`, never inside dependency trees, capped at 3s and cached so the tenth Bot costs nothing. Anything the secret scanner flags never reaches a Bot's memory.

## [0.11.0] - 2026-09-24

### Fixed
- **The desktop tapback shipped in 0.9.0 never worked, anywhere.** Three faults stacked, and the third hid the other two:
  - A Hermes hook runs in the profile that runs the turn. Bot Forge lives in the profile that *creates* Bots, so when the user talked to a Bot, none of this plugin's code was loaded — the reaction could not be placed no matter what.
  - `react_to_message` registers itself when its module is imported, and that import is lazy. In a turn's process the registry had no such entry, so the call returned `Unknown tool: react_to_message`.
  - `dispatch_tool` returns failures as a **value**, never as an exception. The hook caught only exceptions, so every failed reaction was recorded as a success — a feature that had never once worked reported as working, in the tests too, because the test double could not fail either.

  The reaction now ships *inside* each Bot as `bot-forge-marks`: two hooks and no tools, so a Bot gains the acknowledgement and not the ability to create or delete Bots. It is installed with every new Bot, imports the tool before dispatching, reads the dispatch result and honours Settings → Appearance → Message Reactions.

### Added
- `update_agent(name, ack_tapback: true)` installs the reaction hook into a Bot made before this release.
- `check_install` reports how many Bots can react, names those that cannot and why, and says when Message Reactions is off in Settings — so a silent reaction is visible instead of invisible.

## [0.10.0] - 2026-09-24

### Added
- **`check_agents` now leads with what is waiting on you.** A Bot that gets blocked writes it in its journal and goes quiet, so the user had to open each Bot to find out. The new `waiting_on_you` list gathers every unresolved blocked or failed entry across every Bot — which Bot, what it needs, and how many days it has sat there — and the summary reads "2 waiting on you — Marlow: Need the Stripe key…". An item closes itself when the Bot later records the same title as completed.

### Fixed
- **Upgrading acknowledgements could silently switch a Bot's journal off.** Replacing the old acknowledgement block cut everything up to the next heading, which swallowed the `<!-- bot-forge-journal:v1 -->` marker sitting on the line above it: the guidance text stayed, the marker went, and `agent_journal` then answered "journaling is not enabled for this Bot". Stripping now stops at the next heading *or* the next marker comment, and re-enabling a journal clears guidance text left orphaned by the old bug instead of appending a second copy. Affected Bots are repaired by calling `agent_journal` with `action: enable` once.

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
