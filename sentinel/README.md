# bot-forge-sentinel

A Bot's reach, decided outside the model.

## Why

`create_agent` writes a Bot's approval rules into its `SOUL.md`:

```
## Ask first
- send, post or publish anything
- spend money or buy anything
- delete files or data
```

That is prose in a system prompt. Nothing checks it, and a Bot that ignores it meets no
obstacle and leaves no record.

That was tolerable when a Bot could write files and answer questions. It is not now:
`bot_screen` gives a Bot `computer_use` and `browser` — a real desktop and a real browser
session, including whatever the user signed into when they handed control back — and a Bot can
hand work to another Bot, which then acts on instructions it did not get from the user.

Sentinel evaluates a separately configured policy and returns directives for Hermes.
In v0.19.0, `create_agent` does not install or enable this plugin or convert those
approval lines into its policy. The hook must be installed, enabled and configured
separately; its presence in this repository does not establish live enforcement.

## How

Hermes dispatches `pre_tool_call` to plugin hooks and reads the directive back:

| directive | effect |
|---|---|
| `block` | the call never runs; the message becomes the tool result |
| `approve` | the call reaches the human approval gate, whatever the model intended |

Precedence is `block` > `approve` > none, and one plugin's veto beats another's approve.
Sentinel registers that hook and answers it from the Bot's own policy. It provides **no tools**:
a policy layer must not widen what a Bot can do.

## Policy

Per Bot, in that profile's `config.yaml`:

```yaml
plugins:
  enabled: [bot-forge-sentinel]
bot-forge-sentinel:
  refuse: [delete_profile]        # never, whatever is said in the moment
  ask:    [send_email]            # always reach the human gate
  allow:  [post_update]           # fine without asking, even though it looks like a category
  mode: allow                     # or: ask — gate everything not cleared above
  guard_defaults: true            # apply the three categories below
```

With `guard_defaults` on, a tool whose **name** contains a send, spend or delete word reaches
the human gate. The match is on word parts, not substrings, so `undelete_draft` and
`posture_report` are not caught.

## "May email me, not anyone else"

A tool-name gate cannot say that, so limits name the argument and the values that are fine:

```yaml
bot-forge-sentinel:
  limits:
    send_email:
      to: ["me@example.com"]
```

A call whose limited arguments are all within their lists is **allowed without asking** — the
user already said that shape is fine, and asking again just trains them to click yes. One
outside its list is refused, and the message names the argument and the offending value.

Limits are checked before the name lists, because they are the more specific statement:
"send_email is fine, to this address" has to beat "ask about send_email", or naming the address
would buy nothing. `refuse` still wins over everything.

An argument that cannot be read — a nested object, a number, a list with a non-string in it —
falls through to the ordinary gate rather than being permitted. **A value we cannot read is a
question, not a yes.** An absent argument does not satisfy a limit either, so omitting `to` is
not a way to skip the check on `to`.

## It fails closed

If the policy cannot be read — missing, malformed, or the config call raises — the answer is
**refuse**, with a message saying why. The user sees a refusal rather than silence.

This is the one place Bot Forge's usual "never let it stop the plugin loading" instinct is
wrong. Adoption failing open is fine. Enforcement failing open is not.

## What it is not

- **Not a sandbox.** It governs tool calls Hermes dispatches. A Bot with shell access can act
  outside it; that is what per-Bot sandboxes are for.
- **Not a secret store.** A Bot still holds its own `auth.json`.
- **Not advice to the model.** A rule that only persuades belongs in `SOUL.md`.

Design note and open questions: [`docs/sentinel.md`](../docs/sentinel.md).

MIT © Bikash Joshi
