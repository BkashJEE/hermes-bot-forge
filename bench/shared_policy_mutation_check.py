"""Mutation check: revert each shared-policy fix and require the suite to catch it.

Every entry here is a defect an independent review actually found in this feature — two
data-corruption regressions in copy_agent and share_agent, an unconstrained policy path, and
several ways check_policies lied or crashed. Reverting any one of them must fail the suite;
a fix with no failing test is not a fix.

Run directly, or as a CI step. Restores every touched file on all paths.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = ROOT
POL, FORGE, TOOLS = R / "policy.py", R / "forge.py", R / "tools.py"
ORIG = {p: p.read_text() for p in (POL, FORGE, TOOLS)}

MUTATIONS = [
    ("F1a", FORGE, "soul_role reads line 1 again (block hides the heading)",
     "    first = persona_text(soul).lstrip().split(\"\\n\", 1)[0]",
     "    first = (soul or \"\").lstrip().split(\"\\n\", 1)[0]"),

    ("F1b", FORGE, "ensure_identity rebuilds around the whole file, stacking identity",
     "    persona = persona_text(soul)",
     "    persona = soul or \"\""),

    ("F1c", FORGE, "re-inject policy even when there was no block",
     "    if not had_block:\n        return rebuilt",
     "    if False:\n        return rebuilt"),

    ("F3", POL, "policy_path does no containment check",
     "    if lex != root_lex and root_lex not in lex.parents:",
     "    if False:"),

    ("F4", TOOLS, "check_policies reads without errors=replace",
     "            text = soul.read_text(errors=\"replace\")",
     "            text = soul.read_text()"),

    ("F5", TOOLS, "current counted by subtraction again",
     "        \"current\": sum(1 for b in bots if b.get(\"current\")),",
     "        \"current\": len(bots) - len(stale) - len(without),"),

    # F5b (the default-profile audit) was intentionally REMOVED in round 3: `_require_bot`
    # refuses the default profile, so that row could never be acted on. Reinstating it is
    # no longer a mutation to catch -- the current tests assert its absence, so a mutation
    # that adds it back is caught by `test_default_profile_is_not_audited`.

    # Not one contiguous run: the dedent has a comment above it. Match the two halves that
    # carry the behaviour, so a comment edit doesn't invalidate this check.
    ("F8a", POL, "bullet marker not normalised",
     '    body = re.sub(r"(?m)^([ \\t]*)[-*+][ \\t]+", lambda m: m.group(1) + "- ", body)',
     '    body = re.sub(r"(?m)^([ \\t]*)[-*+][ \\t]+", "- ", body)'),

    # `r"\1. "` looks like a revert but isn't: the capture group numbering differs, so it
    # silently discards the indent. That is the bug the numbered branch is guarding against,
    # so mutate to something that really does drop it.
    ("F8b", POL, "numbered sub-list loses its indent (same class of bug as G1)",
     '    body = re.sub(r"(?m)^([ \\t]*)(\\d+)[.)][ \\t]+", lambda m: m.group(1) + f"{m.group(2)}. ", body)',
     '    body = re.sub(r"(?m)^[ \\t]*(\\d+)[.)][ \\t]+", r"\\1. ", body)'),

    ("F8c", POL, "common indent not removed (a whole block shifts = cosmetic)",
     "    body = _dedent(body)\n",
     "    pass\n"),

    ("F8d", POL, "CRLF / trailing whitespace not normalised",
     '    body = body.replace("\\r\\n", "\\n").replace("\\r", "\\n")\n'
     '    body = "\\n".join(line.rstrip() for line in body.split("\\n"))\n',
     "    pass\n"),

    ("F9", FORGE, "comments-only policy accepted",
     "        if not policy_mod.policy_body(text):",
     "        if False:"),
]


def run():
    p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
                       cwd=R, capture_output=True, text=True, timeout=900)
    return p.returncode, p.stdout + p.stderr


rc, out = run()
print(f"baseline: {'PASS' if rc == 0 else 'FAIL'}")
if rc != 0:
    print(out[-2500:])
    sys.exit(1)

caught, unmatched = [], []
for mid, path, desc, find, repl in MUTATIONS:
    src = ORIG[path]
    if find not in src:
        unmatched.append(mid)
        print(f"{mid}: PATTERN NOT FOUND")
        continue
    path.write_text(src.replace(find, repl, 1))
    try:
        rc, out = run()
    finally:
        path.write_text(src)
    if rc != 0:
        caught.append(mid)
        print(f"{mid} CAUGHT   {desc}")
    else:
        print(f"{mid} *** MISSED *** {desc}  <-- untested")

rc, _ = run()
print(f"\nrestored: {'PASS' if rc == 0 else 'FAIL'}")
print(f"caught {len(caught)}/{len(MUTATIONS)}: {', '.join(caught) or 'none'}")
if unmatched:
    print(f"unmatched: {', '.join(unmatched)}")
sys.exit(0 if len(caught) == len(MUTATIONS) and rc == 0 and not unmatched else 1)
