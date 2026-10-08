"""Regression mutation check for the shared-policy feature (groups G, H, J, K).

Each entry reverts one fix for a defect an independent review found in this feature, and the
whole suite must then fail. A fix with no failing test is not a fix. G is the review of the
original change; H, J and K are what later reviews found in the fixes themselves -- most
seriously a drift normaliser that hashed a nested rule identically to a flat one, and a
canonical policy that documents the fence markers hashing to its own example.

Run directly, or as a CI step. Restores every touched file on all paths, including failure.
"""
from __future__ import annotations

import ast
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (id, label, file, old, new)
MUTATIONS: list[tuple[str, str, str, str, str]] = [
    (
        "G1", "policy_body drops indentation again (nested == flat)",
        "policy.py",
        '    body = _dedent(body)\n',
        '    body = _dedent(body)\n    body = re.sub(r"(?m)^[ \\t]*[-*+][ \\t]+", "- ", body)\n',
    ),
    (
        "G2", "policy_path accepts a non-string (template TypeError)",
        "policy.py",
        '    if relative is not None and not isinstance(relative, str):',
        '    if False:',
    ),
    (
        "G3", "policy_path expands ~ on the joined path again",
        "policy.py",
        "    rel = Path(relative).expanduser() if relative is not None else Path(DEFAULT_RELATIVE)\n"
        "    if rel.is_absolute():\n",
        "    rel = Path(relative or DEFAULT_RELATIVE)\n"
        "    if rel.is_absolute():\n",
    ),
    (
        "G4", "health reads the raw SOUL again (name pushed past 400 chars)",
        "health.py",
        "forge.persona_text(soul).lower()[:400]",
        "soul.lower()[:400]",
    ),
    (
        "G5", "check_policies audits the un-actionable default profile again",
        "tools.py",
        "    for prof in candidates:\n        name = prof.name\n",
        '    if (root / "SOUL.md").exists():\n        candidates.append(root)\n'
        "    for prof in candidates:\n"
        '        name = "default" if prof == root else prof.name\n',
    ),
    (
        "G6", "unreadable rows drop the documented fingerprint keys",
        "tools.py",
        '                         "has_shared_policy": False, "reason": "unreadable",\n'
        '                         "fingerprint": None, "canonical_fingerprint": expected})',
        '                         "has_shared_policy": False, "reason": "unreadable"})',
    ),
    (
        "G7", "refresh overwrites a persona-less SOUL with policy only",
        "manage.py",
        "        if not forge.persona_text(soul).strip():\n",
        "        if False:\n",
    ),
    (
        "G8", "refresh + soul_md silently drops the policy again",
        "manage.py",
        "        if refresh_policy and pol_text:\n",
        "        if False:\n",
    ),
    (
        "G9", "op_update re-derives the root from the spec (wrong Hermes root)",
        "manage.py",
        "        pol_root = Path(root)\n",
        '        pol_root = Path(s.get("hermes_root") or Path.home() / ".hermes")\n',
    ),
    (
        "H1", "per-block dedent returns: a rule after a blank line loses its nesting",
        "policy.py",
        "        continues = (\n"
        "            prev_was_item\n"
        "            and margin >= baseline\n"
        "            and all(_LIST_LINE.match(ln) for ln in flat)\n"
        "        )\n",
        "        continues = False\n",
    ),
    (
        "H2", "the continuation rule is dropped: baseline never inherits",
        "policy.py",
        "        if not continues:\n            baseline = margin\n",
        "        baseline = margin\n",
    ),
    (
        "H3", "a flush rule after an indented list is cut to nothing (rule deleted)",
        "policy.py",
        "            and margin >= baseline\n",
        "            and margin >= 0\n",
    ),
    (
        "H4", "a fence is treated as list continuation (keeps the list's depth)",
        "policy.py",
        "            and all(_LIST_LINE.match(ln) for ln in flat)\n",
        "            and True\n",
    ),
    (
        "J1", "blank-line collapse runs after dedent again: policy_body is not a fixed point",
        "policy.py",
        '    body = re.sub(r"\\n{3,}", "\\n\\n", body)' + "\n",
        "",
    ),
    (
        "J2", "survey reads the raw SOUL head again: persona behind a policy is invisible",
        "survey.py",
        "        soul = policy.strip_block(raw_soul)[:2000]",
        "        soul = raw_soul[:2000]",
    ),
    (
        "J3", "an exported template carries the originating Bot's policy again",
        "portable.py",
        '        "soul_md": policy.strip_block((pdir / "SOUL.md").read_text(errors="ignore")).lstrip()'
        ' if (pdir / "SOUL.md").exists() else "",',
        '        "soul_md": (pdir / "SOUL.md").read_text(errors="ignore")'
        ' if (pdir / "SOUL.md").exists() else "",',
    ),
    (
        "J4", "a NUL byte in shared_policy_path is accepted again (write raises ValueError)",
        "policy.py",
        '    if chr(0) in str(relative):\n'
        '        raise PolicyPathError("shared_policy_path must not contain a NUL byte")\n',
        "",
    ),
    (
        "K1", "the fence matches anywhere again: a policy that documents the markers is truncated",
        "policy.py",
        "    m = _boundary_block(raw)\n",
        "    m = _BLOCK.search(raw)\n",
    ),
    (
        "K2", "render_block no longer strips pre-existing markers (they nest and cut SOUL.md short)",
        "policy.py",
        '    body = _MARKER_LINE.sub("", text or "").strip()\n',
        '    body = (text or "").strip()\n',
    ),
]

TESTS = "tests"


def run_suite() -> tuple[bool, str]:
    # unittest writes its report to stderr, and in this environment the exit status is not a
    # reliable pass/fail signal on its own -- so read the report, not just the return code.
    # -B: never write __pycache__, or a stale .pyc from the previous run would shadow the
    # mutation and make it look like the suite still passed.
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "discover", "-s", TESTS, "-q"],
        cwd=ROOT, capture_output=True, text=True,
    )
    out = proc.stdout + proc.stderr
    passed = proc.returncode == 0 and "OK" in out and "FAILED" not in out
    return passed, out[-3000:]


def main() -> int:
    print("baseline: running the suite unmodified")
    ok, out = run_suite()
    if not ok:
        print("baseline FAILED -- fix the suite before trusting these results:\n", out)
        return 1
    print("baseline: PASS\n")

    print(f"{len(MUTATIONS)} mutations, each reverting one fix.\n")
    missed: list[str] = []
    for mid, label, filename, old, new in MUTATIONS:
        with tempfile.TemporaryDirectory() as tmp:
            backup = Path(tmp) / filename
            target = ROOT / filename
            shutil.copy(target, backup)
            src = target.read_text()
            if old not in src:
                print(f"{mid} STALE     {label} -- pattern not found in {filename}")
                missed.append(mid)
                continue
            target.write_text(src.replace(old, new, 1))
            try:
                ast.parse(target.read_text())  # a mutation that cannot parse proves nothing
            except SyntaxError:
                shutil.copy(backup, target)
                print(f"{mid} BROKEN    {label} -- the mutation did not parse")
                missed.append(mid)
                continue
            try:
                # suite_passed must be True for the mutation to have SURVIVED. Inverting
                # this is the easy mistake: the names below read as "caught"/"missed", and
                # getting it backwards turns every caught mutation into a false MISSED.
                suite_passed, out = run_suite()
            finally:
                shutil.copy(backup, target)

        caught = not suite_passed
        if caught:
            print(f"{mid} CAUGHT    {label}")
        else:
            print(f"{mid} *** MISSED *** {label}")
            print("             the suite still passed with this fix reverted")
            missed.append(mid)

    print()
    if missed:
        print(f"result: FAIL -- {len(missed)} of {len(MUTATIONS)} mutations survived: "
              f"{', '.join(missed)}")
        return 1
    print(f"result: PASS -- caught {len(MUTATIONS)}/{len(MUTATIONS)}: "
          f"{', '.join(m[0] for m in MUTATIONS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
