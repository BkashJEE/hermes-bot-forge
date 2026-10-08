"""Shared operating policy: write once, every Bot picks it up.

The problem this solves is copy drift. `create_agent` writes each Bot's `SOUL.md` as a
literal file, so a rule that applies to every Bot — spend nothing without asking, never
push to main, don't paste secrets — has to be pasted into each one. The moment a Bot is
rebuilt, updated, or copied, the copies differ, and nothing notices.

`steipete/agent-scripts` solves the same problem for Claude Code and Codex: one canonical
`AGENTS.MD`, symlinked into each agent's expected filename, with a pointer-style line in
downstream repos. That pattern is borrowed here, adapted for two facts about Hermes that
make the naive version wrong:

1. **A whole-file symlink is wrong.** `ensure_identity()` writes the Bot's own name and
   profile id into the first lines of `SOUL.md`. One canonical file symlinked into every
   profile would give every Bot the same identity — they would each introduce themselves
   as whichever Bot was built first. Verified, not assumed: the identity line is required
   to be unique per Bot.
2. **A pointer line is also wrong.** Hermes reads `SOUL.md` straight into the system
   prompt (`prompt_builder._read_context_file`, which follows symlinks and reads through
   them). A line saying "READ ~/policy/AGENTS.MD BEFORE ANYTHING" puts the *instruction* in
   the prompt and the *policy* wherever the agent decides to go look. It follows only if
   the agent chooses to read it — which is exactly the case that matters least, because
   the agent already has everything else.

So the shared policy is **inlined at build time and kept honest by a fingerprint**. The Bot
gets the full text in its own `SOUL.md` (correct prompt semantics, unique identity, no
runtime dependency), and forge records what it injected. `check_policies` then reports any
Bot whose shared block has drifted from the canonical file — the drift becomes visible
instead of silent.

Hermes does follow symlinks when it reads context files (verified against
`prompt_builder._read_context_file` and `context_file_sources`, including the broken-link and
self-referential-loop cases, both of which degrade to empty content rather than hanging). That
is why a symlinked SOUL.md *would* work mechanically — and it is still the wrong default, for
the two reasons above. There is no opt-in symlink mode; inlining is the only mechanism.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

# ── markers ────────────────────────────────────────────────────────────────────
# The injected block is fenced by these so a later check can find, replace, or remove it
# without guessing, and so a human reading SOUL.md can see what is generated.
BEGIN = "<!-- forge:shared-policy:begin -->"
END = "<!-- forge:shared-policy:end -->"

DEFAULT_RELATIVE = "shared/BOT-POLICY.md"

# Written on first use so the shared floor exists without the user having to author it.
# Deliberately opinionated and short: a policy nobody reads is worse than no policy. The
# user is meant to edit this file — `check_policies` then shows which Bots are stale.
STARTER_POLICY = """# Shared operating policy — every Bot on this Hermes deployment

These rules apply to every Bot, regardless of domain. A Bot's own `SOUL.md` adds its
identity, expertise and approvals; this file is the floor they all stand on.

Edit this file, then run `check_policies` (or rebuild the Bots) to propagate.

## Money and external state

- Ask before spending money, buying anything, or opening a paid service — including a free
  trial that will charge later.
- Ask before publishing, sending, or posting anywhere a real person will see it.
- Ask before deleting data, and never delete anything you did not create this session.

## Secrets and privacy

- Never print, log, commit, or paste a secret value, even one that "looks harmless".
  Reference secrets by name.
- Read local data from disk before reaching for an API key or a network fetch.
- Send nothing private to a public audience or external service without approval of both
  the content and the destination.

## Honesty

- Report what you verified and what you did not. "Probably works" and "I could not check"
  are both useful; a confident claim you cannot support is not.
- A missing or skipped check is a finding, not a footnote. Say it plainly.
- If blocked, say what is missing and what would unblock it — do not quietly narrow the
  task to something you can finish.
- Prefer an unmeasured statement over an invented number.

## Working style

- Do the task asked. If a different approach seems better, do the asked task, then say
  what you would change and why.
- Read the project's own instructions and code before inventing a method.
- Make the change, verify it with the project's real checks, and report the real output.
- Prefer deleting an old path over layering a new one beside it.
- Leave the working tree as you found it, apart from what you were asked to change.

## Scope

- Ask before anything that spends, publishes, leaves this machine, or is hard to undo.
  Otherwise act, and report what you did.
"""

_BLOCK = re.compile(
    re.escape(BEGIN) + r"\n?(.*?)" + re.escape(END),
    re.DOTALL,
)

# A real fence is introduced at a document boundary: `inject` puts the block at the very start,
# ahead of the persona, or at the very end for `position="append"`. A canonical policy that
# *mentions* the markers to explain them has prose in front of the opening one. So the
# discriminator is what surrounds the fence -- nothing but whitespace on the far side. For the
# leading form only the start matters, because a top-injected block is followed by the persona.
_BOUNDARY_BLOCK = re.compile(
    r"\A\s*" + re.escape(BEGIN) + r"\n?(.*?)" + re.escape(END)
    + r"|" + re.escape(BEGIN) + r"\n?(.*?)" + re.escape(END) + r"\s*\Z",
    re.DOTALL,
)


def _boundary_block(text: str) -> re.Match[str] | None:
    """The embedded-policy fence, but only when it sits at a document boundary.

    Both alternatives put the policy body in group 1, so callers read one group either way.
    """
    m = _BOUNDARY_BLOCK.search(text or "")
    if m is None:
        return None
    if m.group(1) is not None:
        return m
    # Second alternative: the appended form, body in group 2. Re-match it on its own so
    # callers cannot read the wrong group by accident.
    return re.match(re.escape(BEGIN) + r"\n?(.*?)" + re.escape(END) + r"\s*\Z",
                    m.group(0), re.DOTALL)


# A whole line that is nothing but one of the two markers. Used to strip markers out of a
# canonical policy before it is fenced, so the two can never nest.
_MARKER_LINE = re.compile(
    r"(?m)^[ \t]*(?:" + re.escape(BEGIN) + r"|" + re.escape(END) + r")[ \t]*\n?"
)


class PolicyPathError(ValueError):
    """A shared-policy path that points outside the Hermes root."""


def policy_path(hermes_root: Path, relative: str | None = None) -> Path:
    """Where the canonical shared policy lives for a given Hermes root.

    `relative` is constrained to the Hermes root. It reaches here from a spec, and
    `create_agent` merges template keys over the spec — so a `.botforge.json` downloaded from
    a gist could otherwise name any file on the machine and have its contents copied into a
    new Bot's system prompt, or written to if it did not exist. The policy file is content
    that goes straight into a prompt, so an unconstrained path is a read-and-inline primitive,
    not a convenience.

    Containment is checked on the *lexical* path (what was written in the spec), not on
    `resolve()`. Resolving follows symlinks, and a perfectly legitimate
    `shared/BOT-POLICY.md` that is a symlink into another location — or a Hermes root that is
    itself reached through a symlink, which is common — would then be rejected as an escape,
    breaking the feature for the reason it exists. A symlinked leaf is a deliberate,
    visible choice by the user; a `../` in a downloaded template is not.
    """
    root = Path(hermes_root).expanduser()
    if relative is not None and not isinstance(relative, str):
        # Reachable from a downloaded template, so never assume the type. `root / [...]` on a
        # list or a Path raises TypeError far from here, and an absolute Path in the spec
        # silently replaces the root, discarding the containment check entirely.
        raise PolicyPathError(
            f"shared_policy_path must be a string, got {type(relative).__name__}"
        )
    # `expanduser` must run on the RELATIVE part only. On the joined path it would turn
    # "~/.hermes/shared/BOT-POLICY.md" into a literal "~" directory inside the root, and
    # create_agent would write the starter policy there -- still lexically contained, so the
    # check below would pass, and silently in the wrong place.
    rel = Path(relative).expanduser() if relative is not None else Path(DEFAULT_RELATIVE)
    if rel.is_absolute():
        raise PolicyPathError(
            f"shared_policy_path must be relative to the Hermes root, got {relative!r}"
        )
    # An empty, `.` or `./` path names the root DIRECTORY, which passes every containment
    # check below and then fails much later as `IsADirectoryError` from the write, or as
    # "no shared policy at <root>" from a read. Neither names the actual mistake, so refuse
    # it here where the message can.
    if relative is not None and not rel.parts:
        raise PolicyPathError(
            "shared_policy_path must name a file inside the Hermes root, not the root itself"
        )
    # A NUL byte survives Path() and normpath() untouched, so containment passes and the
    # write then raises `ValueError: embedded null byte` -- an exception the create path
    # does not catch, escaping as a traceback instead of a reported failure. Reject it at the
    # boundary where it arrives from a downloaded spec.
    if chr(0) in str(relative):
        raise PolicyPathError("shared_policy_path must not contain a NUL byte")
    candidate = root / rel
    try:
        lex = Path(os.path.normpath(str(candidate)))
    except (OSError, ValueError) as exc:
        raise PolicyPathError(f"bad shared policy path {candidate}: {exc}") from exc
    root_lex = Path(os.path.normpath(str(root)))
    if lex != root_lex and root_lex not in lex.parents:
        raise PolicyPathError(
            f"shared policy path escapes the Hermes root: {candidate} is outside {root}"
        )
    return candidate


def policy_body(text: str) -> str:
    """The policy text proper, with fence markers and HTML comments removed.

    A canonical policy file has no markers, so its whole text is the body. A Bot's SOUL.md
    has them, so only the fenced interior counts. Hashing the body is what makes a canonical
    file and a Bot's inlined block comparable — hashing either whole file would not, because
    the block additionally carries the Bot's identity and persona.

    The markers only count as a fence when they sit at a document boundary, which is where
    `inject` always puts them (top, or the very end for `position="append"`). A canonical
    file that *documents* the markers — "put the rules between <!-- begin --> and <!-- end
    -->" — has them mid-prose with real rules on both sides. Searching for them anywhere
    truncated such a file to its example: two policies whose rules differed hashed the same,
    every Bot built from one reported STALE against it, and `refresh_shared_policy` could
    never converge because it kept re-injecting the truncated body. A fence that is not at a
    boundary is documentation, not a fence.

    Comments are stripped so that annotating the policy file is not mistaken for changing a
    rule. A drift report that cries wolf on every reworded comment is one people learn to
    ignore, and then it stops being a report.
    """
    raw = text or ""
    m = _boundary_block(raw)
    body = m.group(1) if m else raw
    # A comment is not a rule. Remove whole-line comments along with the line itself, so
    # they don't leave a blank line where a rule used to be; then unwrap any inline comment
    # left over. Two files that state identical rules must hash identically no matter how
    # their comments are placed — a drift report that fires on reformatting is a report
    # people learn to ignore.
    body = re.sub(r"(?m)^[ \t]*<!--.*?-->[ \t]*\n?", "", body)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    # Normalise the remaining cosmetic differences: a CRLF checkout, trailing whitespace, and
    # a different bullet marker all say the same thing. Without this, saving the policy on a
    # Windows editor marked *every* Bot stale, which is the fastest way to make a drift
    # report something people stop reading.
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    body = "\n".join(line.rstrip() for line in body.split("\n"))
    # Collapse runs of blank lines BEFORE dedenting, not after. Dedent splits on blank lines to
    # find block boundaries, so it absorbs a double blank line: normalising once turned
    # `## Money\n\n- a\n\n\n- b` into `## Money\n- a\n\n- b`, and normalising that again dropped the
    # remaining blank too. `policy_body` was therefore not idempotent, and since
    # `ensure_identity` re-injects `policy_body(soul)`, simply renaming a Bot rewrote its
    # inlined policy into a form that no longer hashed like the file it came from — the Bot
    # reported STALE for a policy it had never violated. Collapsing first makes the operation
    # a fixed point, which is the property the drift check actually needs.
    body = re.sub(r"\n{3,}", "\n\n", body)
    # Normalise the bullet marker but KEEP the indentation, normalised to spaces, and only
    # after removing the indentation every line shares. Collapsing `  - sub` to `- sub` would
    # make a nested rule hash identically to a flat one -- a real change to the policy's
    # structure reporting as no drift at all, which is far worse than the cosmetic false
    # positive this normalisation exists to avoid. Dedenting the COMMON margin first keeps the
    # cosmetic case working: a list indented under its heading is the same list, while a
    # sub-bullet stays deeper than its parent.
    body = _dedent(body)
    body = re.sub(r"(?m)^([ \t]*)[-*+][ \t]+", lambda m: m.group(1) + "- ", body)
    body = re.sub(r"(?m)^([ \t]*)(\d+)[.)][ \t]+", lambda m: m.group(1) + f"{m.group(2)}. ", body)
    return body.strip()


_LIST_LINE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+")


def _dedent(text: str) -> str:
    """Strip each block's own baseline indentation and expand tabs; relative depth survives.

    The baseline is the margin a block introduces, not the one it happens to share with the
    lines around it. Two cases pull in opposite directions and both have to hold:

    - A list written two spaces under its heading is the SAME list as one written flush, so
      the block's own margin is cosmetic and is removed.
    - A sub-bullet is a real structural change from a sibling, even when a blank line
      separates them, so a block that CONTINUES a list keeps the depth it was written at.

    The discriminator is whether the previous non-blank line was itself a list item. If it
    was, this block continues that list and inherits its baseline; otherwise this block
    starts something new and its own margin becomes the baseline. A first attempt computed
    the margin per block with no notion of continuation, which made a rule after a blank
    line lose its nesting entirely: flat, nested and sibling all hashed to 8cc247389e36.
    That is the worst failure a drift detector can have — a Bot running different rules
    still reporting `current`.
    """
    blocks: list[list[str]] = [[]]
    for line in text.split("\n"):
        if line.strip():
            blocks[-1].append(line)
        else:
            blocks.append([])
    out: list[str] = []
    baseline = 0  # indentation that carries no meaning in the rules so far
    prev_was_item = False
    for block in blocks:
        if not block:
            out.append("")
            continue
        # Expand tabs FIRST, then measure, so a tab-indented list dedents to nothing
        # instead of to one space.
        flat = [ln.expandtabs(2) for ln in block]
        margin = min(len(ln) - len(ln.lstrip(" ")) for ln in flat)
        # A block only continues the list above it if it is a list AND sits at or below that
        # list's baseline. Without the second half, a flush rule following an indented list is
        # "less indented than its parent", which is not Markdown at all -- and cutting by the
        # baseline consumed the whole line, silently deleting a rule. That is a corruption,
        # not a normalisation, so such a block starts a new list instead.
        continues = (
            prev_was_item
            and margin >= baseline
            and all(_LIST_LINE.match(ln) for ln in flat)
        )
        cut = baseline if continues else margin
        out.extend(ln[cut:] if cut else ln for ln in flat)
        if not continues:
            baseline = margin
        prev_was_item = bool(flat) and bool(_LIST_LINE.match(flat[-1]))
    return "\n".join(out)


def fingerprint(text: str) -> str:
    """Short, stable digest of the policy body.

    Only the policy itself is hashed, not the surrounding file, so adding a comment or
    changing a Bot's persona does not make that Bot look stale — but editing a rule does.
    """
    return hashlib.sha256(policy_body(text).encode("utf-8")).hexdigest()[:12]


def render_block(text: str) -> str:
    """The fenced block to inline into a Bot's SOUL.md.

    Any marker lines already in `text` are removed first, but nothing else is touched: this
    writes the policy exactly as its author wrote it, and normalisation belongs to the
    fingerprint, not to what a Bot reads. A canonical file that *documents* the markers —
    showing what they look like to the person editing it — would otherwise end up nested
    inside the block we add, and a non-greedy fence stops at the inner `END`, cutting the
    Bot's SOUL.md short mid-policy so that every reader (extract, strip, fingerprint)
    disagreed about where the policy ended.
    """
    body = _MARKER_LINE.sub("", text or "").strip()
    return f"{BEGIN}\n{body}\n{END}"


def extract_block(soul: str) -> str | None:
    """The shared-policy block from a SOUL.md, or None if it has none."""
    m = _BLOCK.search(soul or "")
    return m.group(0) if m else None


def strip_block(soul: str) -> str:
    """The SOUL.md with the shared-policy block (markers included) removed.

    Use this before any analysis that assumes the Bot's own content starts at the top —
    heading detection, identity rewriting, role extraction. The block is generated, and a
    reader that treats `<!-- forge:... -->` as the persona's first line silently loses the
    role and can leave a second identity in the file.
    """
    return _BLOCK.sub("", soul or "")


def inject(text: str, soul: str, *, position: str = "top") -> str:
    """Inline `text` into `soul`, replacing any block already there.

    Idempotent: injecting the same policy twice yields byte-identical output, so a rebuild
    does not accumulate copies. `position="top"` puts shared policy ahead of the Bot's own
    identity, which is deliberate — the standing rules should be read before the persona
    that has to follow them.
    """
    block = render_block(text)
    if position == "append":
        body = _BLOCK.sub("", soul or "").rstrip()
        return f"{body}\n\n{block}\n" if body else f"{block}\n"
    body = _BLOCK.sub("", soul or "").lstrip()
    return f"{block}\n\n{body}" if body else f"{block}\n"


def check_soul(soul: str, expected_fp: str | None) -> tuple[bool, str]:
    """Is this Bot's shared block current? Returns (ok, reason)."""
    block = extract_block(soul)
    if block is None:
        return False, "no shared-policy block"
    if not expected_fp:
        return False, "no canonical policy to compare against"
    # fingerprint() strips the fence itself, so the block and the canonical file are
    # compared as policy bodies — no marker juggling here.
    actual = fingerprint(block)
    if actual != expected_fp:
        return False, f"policy drifted (bot {actual}, canonical {expected_fp})"
    return True, "current"


def audit_soul(soul: str, expected_fp: str | None) -> dict:
    """Structured result for one Bot, for the check tool and tests."""
    ok, reason = check_soul(soul, expected_fp)
    block = extract_block(soul)
    return {
        "has_shared_policy": block is not None,
        "current": ok,
        "reason": reason,
        "fingerprint": fingerprint(block) if block else None,
        "canonical_fingerprint": expected_fp,
    }


def policy_dir_note(relative: str) -> str:
    """The one-line pointer a human can put in a repo, mirroring the agent-scripts pattern.

    Not used by the plugin — it is here so a user wiring the same discipline into a
    *repository's* AGENTS.md has the canonical wording to copy, and so the pattern is
    documented in code rather than only in prose.
    """
    return (f"READ ~/.hermes/{relative} BEFORE ANYTHING (skip if missing). "
            f"Repo-specific rules go below this line — do not copy the shared block here.")
