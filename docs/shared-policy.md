# Shared operating policy

One file, `~/.hermes/shared/BOT-POLICY.md`, holds the rules that apply to **every** Bot.
`create_agent` inlines it into each Bot's `SOUL.md`, fenced by HTML markers, so a rule you
edit once reaches every Bot on the next build.

## Why not just symlink it

The obvious design — and the one `steipete/agent-scripts` uses for Claude Code and Codex —
is to symlink one canonical `AGENTS.MD` into each agent's expected filename. Bot Forge
borrows the *discipline* (one canonical file, change once) but not the mechanism, because two
facts about Hermes make a symlink the wrong default here.

**A whole-file symlink would give every Bot the same identity.** `ensure_identity()` writes
the Bot's own name and profile id into the first lines of `SOUL.md`, and the identity line
is required to be unique. One canonical file symlinked into every profile means every Bot
introduces itself as whichever Bot was built first. There is a test for exactly this:
`test_each_bot_keeps_its_own_identity`, and `test_fork_symlink_would_collide_but_inline_does_not`
which asserts the rejected alternative really is broken rather than merely disfavoured.

**A pointer line would put the rule outside the prompt.** Hermes reads `SOUL.md` straight
into the system prompt. A line saying "READ ~/policy/AGENTS.MD BEFORE ANYTHING" puts the
*instruction* in the prompt and the *policy* wherever the agent chooses to look — enforced
only if the agent decides to read it, which is exactly the case that matters least because
it already has everything else. This is the one case where "it depends on the model
choosing" is the wrong trade.

So the policy is **inlined at build time and kept honest by a fingerprint**. Correct prompt
semantics, unique identity per Bot, no runtime dependency. The cost is that a Bot built
before your edit holds the old text — so drift has to be *visible*, which is what
`check_policies` is for.

Hermes does follow symlinks when it reads context files (verified against
`prompt_builder._read_context_file` and `context_file_sources`, including the broken-link and
self-referential-loop cases, both of which degrade to empty content rather than hanging). That
is why a symlinked `SOUL.md` *would* work mechanically — and it is still the wrong default, for
the two reasons above. There is no opt-in symlink mode; inlining is the only mechanism.

## What reads a SOUL.md

Because the block sits above the persona, anything that assumes the `# Name — Role` heading is
line 1 has to skip it. `forge.soul_role()` and `forge.ensure_identity()` both do, via
`forge.persona_text()`, and `ensure_identity` re-injects the block afterwards so a rename never
drops a Bot's house rules. A `SOUL.md` with no block is treated as all-persona, so a Bot built
before this feature does not acquire one on its next edit.

This is not hypothetical: with the block on line 1 and no skip, `copy_agent` produced a Bot
that introduced itself as "the Bot" instead of its role, and `share_agent` exported no role at
all, so the archive could not be imported. Both are regression-tested.

## Refreshing a stale Bot

`create_agent` refuses a name that is already taken, so re-running it does **not** refresh an
existing Bot. To bring one up to date after editing the policy file, use
`update_agent` with `refresh_shared_policy`:

```json
{"op": "update", "name": "sable", "refresh_shared_policy": true}
```

That re-injects the current policy into that Bot's `SOUL.md` in place, keeping its identity,
persona, approvals and journal block, and backing up the file first. It is idempotent — a Bot
that is already current reports `already current` and nothing is written. It refuses a policy
path that points outside the Hermes root, and refuses a policy file with no rules in it.

`update_agent(soul_md=...)` is *not* a way to refresh the policy: it replaces the whole file
and the block goes with it.

## What the drift check reports

`check_policies` compares each Bot's inlined block against the canonical file by
fingerprint, and returns:

- `stale` — built before your latest edit
- `no_shared_policy` — built with `shared_policy: false`, or before this feature existed
- `unreadable` — the file could not be read; these are reported, not silently counted as fine
- `bots` — per-Bot `current`, `reason`, and both fingerprints

The `default` profile is **not** audited. Its `SOUL.md` lives at the Hermes root rather than
under `profiles/`, and `_require_bot` refuses it, so `forge` never writes a block there and no
documented call could ever bring it current. Reporting a row that cannot be acted on is worse
than omitting it — you stop trusting the rows you *can* act on.

Only the policy **body** is hashed. Fence markers and comments are removed, blank-line runs
are collapsed, and cosmetic differences are normalised — CRLF line endings, trailing
whitespace, `-` / `*` / `+` bullet markers, and the indentation shared by a whole block all
hash the same. Indentation *relative to a sibling* is preserved, so adding, removing or
re-nesting a sub-bullet is a real change and does show up as drift. Two consequences:

- Editing a comment, or saving the file from an editor that uses CRLF, is not a policy change.
  A drift report that fires on cosmetics is one people learn to ignore, and then it stops
  being a report.
- A Bot's persona, identity, and approvals are *outside* the fence, so giving a Bot a new
  name or role does not make it look stale, and a shared rule that happens to mention a Bot
  name does not pin that Bot's copy to a particular edit.

A file containing **only comments** is rejected rather than inlined: it would build Bots with
no rules at all, and by the metric above it is indistinguishable from an empty policy.

## Opting out

Pass `"shared_policy": false` in a spec to build a Bot with no shared block at all. Useful
for a Bot you deliberately want to run unconstrained by the house rules.

## Using it

```json
{
  "name": "kestrel",
  "role": "trading analyst",
  "shared_policy": true
}
```

`shared_policy_path` points at a different canonical file (relative to the Hermes root) if
you want, say, a stricter policy for production Bots than for throwaway ones.
`shared_policy_create: false` makes a missing policy file a hard error instead of seeding
the starter — the right setting for a machine where an unwritten policy should fail loudly.

The starter policy ships in `policy.py` as `STARTER_POLICY` and is written on first use. It
is deliberately short and opinionated; edit it to match how you actually want to work. It is
seeded, not enforced — nothing checks that you kept it, and nothing stops you replacing it.
