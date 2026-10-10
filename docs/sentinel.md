# Sentinel — approvals that are enforced, not requested

> **Status in v0.19.0:** this is a design proposal, not the fresh-Bot creation contract.
> The `sentinel/` hook implementation is present, but `create_agent` does not install or
> enable it, compile `approvals` into policy, or implement `enforce_approvals`.
> Approval wording remains prompt guidance. The compilation and automatic per-Bot
> delivery described below are proposed work; they were not merged with PR #59.
> A separately installed, enabled and configured Sentinel needs runtime verification
> against the Hermes version in use before claiming enforcement. The current policy
> shape is in [sentinel/README.md](../sentinel/README.md).

## The problem

`create_agent` writes a Bot's approval rules into its `SOUL.md`:

```
## Ask first
- send, post or publish anything
- spend money or buy anything
- delete files or data
```

That is **prose in a system prompt**. Nothing checks it. A Bot that ignores it meets no
obstacle, and the failure is silent — there is no record that a rule was crossed, because
nothing was watching.

That was tolerable when a Bot could only write files and answer questions. It is not tolerable
now:

- **`bot_screen`** grants `computer_use` and `browser`. A Bot has a real desktop and a real
  browser session, including whatever the user signed into when they handed control back.
- **`handoff_agent`** lets one Bot pass work to another, which then owns it. The receiving Bot
  acts on instructions it did not get from the user.

So the capability has grown and the guardrail has not. `approvals` is currently a *claim about*
a Bot's behaviour rather than a *property of* it.

## What we were missing

Nothing. Hermes already has the gate.

`hermes_cli/plugins.py` dispatches `pre_tool_call` to every registered plugin hook and reads the
returned directive:

| directive | effect |
|---|---|
| `{"action": "block", "message"}` | the call never runs; `message` becomes the tool result |
| `{"action": "approve", "message", "rule_key"?}` | escalates **any** tool to the human approval gate; `rule_key` picks the `[a]lways` allowlist grain |
| `{"action": "modify", "args": {...}}` | shallow-merges into the arguments before dispatch |

Precedence is `block` > `approve` > none, **not registration order** — one plugin's valid veto
beats another's request for confirmation. `modify` is processed before the gate, so a rewrite is
visible even when a later hook blocks.

Bot Forge registers `pre_llm_call` and `post_llm_call` today, for the acknowledgement tapback.
It has never registered `pre_tool_call`. The enforcement point has been there the whole time.

## The design

### Shape: a companion plugin, like `marks/`

`marks/` already ships a hooks-only plugin into every Bot profile Bot Forge manages — two hooks,
no tools, installed into that profile's `config.yaml`, never the root profile. It is installed,
debugged and running across every Bot on this machine.

`sentinel/` is the same shape:

- **hooks only, no tools.** A policy layer must not widen what a Bot can do. This is the same
  rule `marks/` follows and a test should assert it, as one already does for `marks/`.
- **shipped per Bot, not per machine.** Each Bot's policy lives with that Bot, so two Bots can
  have different reach — which is the point. A researcher Bot and a Bot with a browser session
  into your email should not be governed identically.
- **one `pre_tool_call` hook.**

### Policy lives in the Bot's own config

```yaml
bot_forge:
  sentinel:
    ask:    [send_email, post_message, browser_submit]   # -> action: approve
    refuse: [delete_profile, transfer_funds]             # -> action: block
    allow:  [read_file, web_search]                      # explicit, for a locked-down Bot
    mode: ask            # ask | refuse  — what happens to a tool in none of the lists
```

`approvals` on `create_agent` keeps its current wording and additionally **compiles** to this.
The prose stays — a Bot should still understand its own rules — but the prose stops being the
only thing standing between the Bot and the action.

### Default-deny, and failing closed

The three `DEFAULT_APPROVALS` categories map to `action: "approve"`: *send/post/publish*,
*spend*, *delete*. A Bot asking to do one of those reaches the human gate whether or not the
model intended to ask.

**If the policy cannot be read, the governed categories are refused, not allowed.** A corrupt or
missing policy file is exactly when a Bot should do less, not more. The failure must be loud: the
block message says the policy could not be read, so the user sees a refusal rather than silence.

This is the one place where Bot Forge's usual "never let it stop the plugin loading" instinct is
wrong. Adoption failing open is fine; enforcement failing open is not.

### What it is not

- **Not a sandbox.** It governs tool calls Hermes dispatches. A Bot with shell access can act
  outside it, which is what per-Bot sandboxes are for. Sentinel and the sandbox are different
  layers and the docs must not imply otherwise.
- **Not a secret store.** A Bot still holds its own `auth.json`. Keeping credentials out of a
  Bot's reach is separate work.
- **Not advice to the model.** If a rule only persuades, it belongs in `SOUL.md`, not here.

## Why this is worth doing

Muse ships [Sentinel](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/) —
a separate agent, isolated at system level, approving every internet-bound action — and the
reviewers' favourite features were all security, not capability. Grok Bots have no equivalent.
The most advanced community fork of this plugin built rule *distribution* and its own doc is
explicit that inlining is still prompt text.

So enforcement is unbuilt across all of them, and Hermes hands it to us for the cost of one hook.

The honest claim afterwards is narrow and true: **a Bot's reach is decided outside the model, on
the user's own machine, by a file they can read.**

## Open questions

1. **Tool-name granularity.** Blocking `send_email` is coarse; the user may want "may email
   me, may not email anyone else". `modify` could enforce a recipient allowlist instead of
   refusing outright. Worth it, or is it a rule nobody will write?
2. **Who may edit a policy?** If `update_agent` can widen a Bot's own policy, a Bot that can
   call `update_agent` can widen itself. The policy edit path probably has to be operator-only,
   the way `allow_delete` already is.
3. **`rule_key` grain.** Hermes lets an `approve` directive name the allowlist key behind the
   user's `[a]lways` answer. Choosing it per tool, per tool+argument, or per Bot decides what
   "always allow this" actually means later.

