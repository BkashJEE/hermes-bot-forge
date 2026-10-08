"""Shared operating policy: injection is correct, idempotent, and drift is visible.

The plugin modules come from tests/support.py, which is the one place sys.path is arranged.
"""
import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from support import forge, health, manage, policy, portable, survey, tools, yaml


class SharedPolicyRenderTests(unittest.TestCase):
    def test_fingerprints_ignore_surrounding_comments(self):
        a = "# title\n\n- ask before spending\n"
        b = "# title\n\n- ask before spending\n\n<!-- trailing note -->\n"
        self.assertEqual(policy.fingerprint(a), policy.fingerprint(b),
                         "editing a comment above the policy must not look like drift")

    def test_fingerprint_changes_with_policy_text(self):
        self.assertNotEqual(policy.fingerprint("- ask before spending"),
                            policy.fingerprint("- never spend"))

    def test_fingerprint_ignores_cosmetic_reformatting(self):
        """Regression: only comments were normalised, so cosmetics looked like drift.

        A CRLF checkout, trailing whitespace, or a different bullet marker each marked
        EVERY Bot stale. The report's own reasoning — a drift report that fires on
        cosmetics is one people learn to ignore — applies to those too.
        """
        plain = "## Rules\n\n- one\n- two\n"
        for label, variant in (
            ("crlf", "## Rules\r\n\r\n- one\r\n- two\r\n"),
            ("trailing whitespace", "## Rules\n\n- one   \n- two\t\n"),
            ("asterisk bullets", "## Rules\n\n* one\n* two\n"),
            ("plus bullets", "## Rules\n\n+ one\n+ two\n"),
            ("indented bullets", "## Rules\n\n  - one\n  - two\n"),
        ):
            with self.subTest(variant=label):
                self.assertEqual(policy.fingerprint(plain), policy.fingerprint(variant),
                                 f"{label} must not read as a policy change")
        # and a real change must still be caught
        self.assertNotEqual(policy.fingerprint(plain),
                            policy.fingerprint("## Rules\n\n- one\n- three\n"))

    def test_comment_edit_creates_no_blank_line_difference(self):
        """Regression: stripping a comment left its surrounding blank line behind.

        That made a pure annotation look like a changed rule, so every Bot would be
        reported stale after the user tidied the policy file's comments. Found by the
        end-to-end check, not by inspection.
        """
        plain = "## Rules\n\n- ask before spending\n- verify before claiming\n"
        commented = ("## Rules\n\n<!-- remember to word this gently -->\n"
                     "- ask before spending\n- verify before claiming\n")
        self.assertEqual(policy.policy_body(plain), policy.policy_body(commented))
        self.assertEqual(policy.fingerprint(plain), policy.fingerprint(commented))

    def test_comment_inserted_mid_list_is_still_not_drift(self):
        plain = "# p\n\n- one\n- two\n"
        commented = "# p\n\n- one\n<!-- why two matters -->\n- two\n"
        self.assertEqual(policy.fingerprint(plain), policy.fingerprint(commented))

    def test_inject_puts_block_first(self):
        out = policy.inject("- ask first", "# Sable\n\nI am Sable.")
        self.assertTrue(out.startswith(policy.BEGIN))
        self.assertIn("# Sable", out)

    def test_inject_is_idempotent(self):
        once = policy.inject("- ask first", "# Sable\n\nI am Sable.")
        twice = policy.inject("- ask first", once)
        self.assertEqual(once, twice, "rebuilding must not accumulate duplicate blocks")

    def test_reinject_replaces_rather_than_appends(self):
        old = policy.inject("- old rule", "# Sable")
        new = policy.inject("- new rule", old)
        self.assertNotIn("- old rule", new)
        self.assertIn("- new rule", new)
        self.assertEqual(new.count(policy.BEGIN), 1)

    def test_inject_append_position(self):
        out = policy.inject("- ask first", "# Sable", position="append")
        self.assertIn("# Sable", out)
        self.assertTrue(out.rstrip().endswith(policy.END))

    def test_inject_into_empty_soul(self):
        out = policy.inject("- ask first", "")
        self.assertEqual(out.count(policy.BEGIN), 1)
        self.assertIn("- ask first", out)

    def test_audit_reports_current(self):
        soul = policy.inject("- ask first", "# Sable")
        r = policy.audit_soul(soul, policy.fingerprint("- ask first"))
        self.assertTrue(r["current"])
        self.assertTrue(r["has_shared_policy"])

    def test_audit_detects_drift(self):
        soul = policy.inject("- ask first", "# Sable")
        r = policy.audit_soul(soul, policy.fingerprint("- something else"))
        self.assertFalse(r["current"])
        self.assertIn("drifted", r["reason"])

    def test_audit_detects_missing_block(self):
        r = policy.audit_soul("# Sable\n\nNo policy here.", "abc123")
        self.assertFalse(r["current"])
        self.assertFalse(r["has_shared_policy"])
        self.assertIn("no shared-policy block", r["reason"])

    def test_starter_policy_is_itself_valid(self):
        """The shipped starter must inject and audit clean against its own fingerprint."""
        soul = policy.inject(policy.STARTER_POLICY, "# Sable")
        r = policy.audit_soul(soul, policy.fingerprint(policy.STARTER_POLICY))
        self.assertTrue(r["current"])


class SharedPolicyForgeTests(unittest.TestCase):
    """The reason this design exists: identity must stay unique per Bot."""

    def _soul(self, name="sable", display="Sable", role="iOS developer"):
        """A Bot's finished SOUL.md, as forge would build it before policy injection.

        `one_job` is set by forge.forge() immediately before render_soul is called, so it
        is set here too — otherwise this helper would test a shape forge never produces.
        """
        spec = {"display_name": display, "role": role, "sandbox": "local",
                "one_job": f"acts as the user's {role}"}
        return forge.ensure_identity(forge.render_soul(spec, name), display, role, name)

    def test_policy_is_inlined_not_left_behind(self):
        soul = policy.inject(policy.STARTER_POLICY, self._soul())
        self.assertIn("Ask before spending money", soul)

    def test_each_bot_keeps_its_own_identity(self):
        """Two Bots built from the same policy must NOT collapse to one identity.

        This is the regression guard for the whole design: a naive whole-file symlink
        would give every Bot the same name and profile id.
        """
        a = self._soul("sable", "Sable", "iOS developer")
        b = self._soul("bloom", "Bloom", "Swift developer")
        sa = policy.inject(policy.STARTER_POLICY, a)
        sb = policy.inject(policy.STARTER_POLICY, b)
        self.assertIn("Sable", sa)
        self.assertIn("sable", sa)
        self.assertIn("Bloom", sb)
        self.assertIn("bloom", sb)
        self.assertNotEqual(
            [ln for ln in sa.splitlines() if ln.strip()],
            [ln for ln in sb.splitlines() if ln.strip()],
            "two Bots must not produce identical SOUL.md bodies",
        )

    def test_fork_symlink_would_collide_but_inline_does_not(self):
        """Prove the rejected alternative really is broken, so the choice is evidence-based."""
        with_shared = policy.inject(policy.STARTER_POLICY, self._soul())
        # what a whole-file symlink would yield: the SAME text for every Bot
        symlink_equivalent = policy.STARTER_POLICY
        self.assertNotEqual(with_shared, symlink_equivalent)
        # the symlink variant has no Bot-specific identity at all
        self.assertNotIn("sable", symlink_equivalent)
        self.assertNotIn("Sable", symlink_equivalent)


class SharedPolicyInteropTests(unittest.TestCase):
    """The policy block must not break the features that already read SOUL.md.

    Every one of these is a regression found by review, not a hypothetical: the block is
    injected at the top of the file, and three existing helpers assumed the persona's
    heading was line 1.
    """

    def _soul(self, name="sable", display="Sable", role="iOS developer"):
        spec = {"display_name": display, "role": role, "sandbox": "local",
                "one_job": f"acts as the user's {role}"}
        return forge.ensure_identity(forge.render_soul(spec, name), display, role, name)

    def test_role_is_recovered_through_the_block(self):
        """Regression: soul_role() read line 1, which is the block marker.

        Effect: a shared Bot exported no role, and import_agent then rejected the archive
        with "spec needs at least 'role'" — every Bot with a policy was shareable but not
        importable.
        """
        soul = policy.inject(policy.STARTER_POLICY, self._soul())
        self.assertEqual(soul.splitlines()[0], policy.BEGIN)
        self.assertEqual(forge.soul_role(soul), "iOS developer")

    def test_copy_does_not_produce_two_identities(self):
        """Regression: copying rebuilt the file around the marker comment.

        Effect: the copy introduced itself as "the Bot" instead of its role while the
        original heading survived below — exactly what ensure_identity exists to prevent.
        """
        soul = policy.inject(policy.STARTER_POLICY, self._soul())
        copied = forge.ensure_identity(soul, "Bloom", "Bot", "bloom")
        names = re.findall(r"You are \*\*([^*]+)\*\*", copied)
        self.assertEqual(names, ["Bloom"], f"expected exactly one identity, got {names}")
        self.assertNotIn("the Bot of this", copied)
        self.assertIn("iOS developer", copied)
        self.assertIn("# Bloom — iOS developer", copied)

    def test_identity_rebuild_keeps_the_policy_block(self):
        soul = policy.inject(policy.STARTER_POLICY, self._soul())
        rebuilt = forge.ensure_identity(soul, "Bloom", "iOS developer", "bloom")
        self.assertEqual(rebuilt.count(policy.BEGIN), 1, "the policy must survive a rename")
        self.assertTrue(policy.audit_soul(
            rebuilt, policy.fingerprint(policy.STARTER_POLICY))["current"])

    def test_share_import_round_trip_keeps_the_role(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "SOUL.md"
            p.write_text(policy.inject(policy.STARTER_POLICY, self._soul()))
            self.assertEqual(forge.soul_role(p.read_text(errors="ignore")), "iOS developer")


class SharedPolicyPathSafetyTests(unittest.TestCase):
    """`shared_policy_path` reaches forge from a spec, and specs can come from templates."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "hr"
        (self.root / "shared").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_relative_escape_is_refused(self):
        for bad in ("../SECRET.txt", "../../etc/passwd", "shared/../../escape.md"):
            with self.subTest(path=bad):
                with self.assertRaises(policy.PolicyPathError):
                    policy.policy_path(self.root, bad)

    def test_absolute_path_outside_root_is_refused(self):
        outside = Path(self.tmp.name) / "SECRET.txt"
        outside.write_text("[REDACTED]")
        with self.assertRaises(policy.PolicyPathError):
            policy.policy_path(self.root, str(outside))

    def test_default_and_nested_paths_are_allowed(self):
        self.assertEqual(policy.policy_path(self.root), self.root / policy.DEFAULT_RELATIVE)
        nested = policy.policy_path(self.root, "shared/nested/POLICY.md")
        self.assertEqual(nested, self.root / "shared" / "nested" / "POLICY.md")

    def test_a_symlinked_leaf_is_allowed(self):
        """Deliberate: a user pointing their own policy elsewhere is a visible choice.

        Refusing it would also break a Hermes root that is itself reached through a symlink,
        which is common. Only lexical escapes are refused.
        """
        outside = Path(self.tmp.name) / "elsewhere.md"
        outside.write_text("- ask first\n")
        (self.root / "shared" / "BOT-POLICY.md").symlink_to(outside)
        self.assertTrue(policy.policy_path(self.root, "shared/BOT-POLICY.md").exists())

    def test_comments_only_canonical_policy_is_rejected_not_inlined(self):
        """Regression: a comments-only file hashed the same as an empty policy."""
        canon = policy.policy_path(self.root)
        canon.write_text("<!-- TODO: write the house policy -->\n")
        self.assertEqual(policy.fingerprint(canon.read_text()), policy.fingerprint(""))

    def test_forge_rejects_a_comments_only_policy(self):
        """The build path, not just the helper: Bots must not be built with no rules.

        `text.strip()` is truthy for a comments-only file, so the old guard let it through
        and every Bot got a SOUL.md whose policy was, by the drift report's own metric,
        indistinguishable from no policy at all.
        """
        canon = policy.policy_path(self.root)
        canon.write_text("<!-- TODO: write the house policy -->\n")
        # The guard under test runs before anything is created. If it ever stops doing so, the
        # build would go on to `hermes profile create`; this test must never reach the real CLI
        # (it republishes launchers under HERMES_HOME), so the call fails loudly instead.
        with mock.patch.object(forge, "run", side_effect=AssertionError("reached the hermes CLI")):
            res = forge.forge({
                "name": "kestrel", "display_name": "Kestrel", "role": "trading analyst",
                "hermes_root": str(self.root), "sandbox": "local",
                "one_job": "analyses trades",
                "settings": {"inherit_model": False, "install_gateway": False,
                             "workspace_survey": False, "journal_enabled": False,
                             "ack_tapback": False, "ack_reactions": False},
            })
        self.assertFalse(res.get("ok"), "a policy with only comments must be rejected")
        self.assertIn("only comments", str(res.get("error", "")))
        self.assertFalse((self.root / "profiles" / "kestrel" / "SOUL.md").exists())


    def test_check_policies_survives_non_utf8_files(self):
        """Regression: UnicodeDecodeError is a ValueError, not an OSError.

        `except OSError` did not catch it, so one latin-1 apostrophe in a hand-edited
        SOUL.md raised out of a tool documented as safe and read-only.
        """
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            canon = policy.policy_path(root)
            canon.parent.mkdir(parents=True)
            canon.write_bytes(b"- caf\xe9 rule\n- ask first\n")
            (root / "profiles" / "x").mkdir(parents=True)
            (root / "profiles" / "x" / "SOUL.md").write_bytes(b"# X\n\xff\xfe junk")
            orig = tools.hermes_root
            tools.hermes_root = lambda: root
            try:
                out = json.loads(tools.check_policies({}))
            finally:
                tools.hermes_root = orig
        self.assertTrue(out["ok"], out.get("error"))
        self.assertEqual(out["bots_checked"], 1)

    def test_unreadable_bot_is_not_counted_as_current(self):
        """Regression: `checked - stale - without` silently counted errored rows as current.

        An unreadable Bot then appeared in no list at all, and `current` overstated how
        many were up to date.
        """
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            canon = policy.policy_path(root)
            canon.parent.mkdir(parents=True)
            canon.write_text("- ask first\n")
            (root / "profiles" / "locked").mkdir(parents=True)
            (root / "profiles" / "locked" / "SOUL.md").write_text(
                policy.inject("- ask first", "# Locked"))
            (root / "profiles" / "bad").mkdir(parents=True)
            (root / "profiles" / "bad" / "SOUL.md").write_text("# Bad")
            orig = tools.hermes_root
            tools.hermes_root = lambda: root
            real_read = Path.read_text

            def read_only_profiles(self_path, *a, **kw):
                # fail only for the Bot's SOUL.md, not the canonical policy
                if self_path.name == "SOUL.md":
                    raise OSError("locked")
                return real_read(self_path, *a, **kw)

            try:
                with mock.patch.object(Path, "read_text", read_only_profiles):
                    out = json.loads(tools.check_policies({}))
            finally:
                tools.hermes_root = orig
        self.assertEqual(out["bots_checked"], 2)
        self.assertEqual(out["current"], 0, "an unreadable Bot is not current")
        self.assertIn("bad", out["unreadable"])
        # and it must be visible in some list, not vanish
        self.assertTrue(out["unreadable"])

    def test_nested_and_flat_bullets_are_different_policies(self):
        """Regression: the F7 fix flattened indentation, so structure stopped mattering.

        Normalising `  - sub` to `- sub` made a nested rule hash identically to a flat one.
        Five of six distinct-policy pairs collided. That is the worst possible failure for a
        drift detector: a real change to the policy's structure reporting as no drift, and
        doing it silently. It was introduced while fixing a purely cosmetic false positive.

        A test that only checked "uniform indent is cosmetic" would have passed here, because
        a list indented under its heading and a list with a sub-bullet were being conflated.
        Both properties have to hold at once.
        """
        flat = "- Ask before spending.\n- Or over $100.\n- Ask before publishing.\n"
        nested = "- Ask before spending.\n  - Or over $100.\n- Ask before publishing.\n"
        self.assertNotEqual(policy.fingerprint(flat), policy.fingerprint(nested),
                            "a sub-bullet must not hash as a sibling rule")

        # structural edits, each of which must be visible
        for label, before, after in (
            ("sub-bullet added", "- A.\n- B.", "- A.\n  - sub\n- B."),
            ("sub-bullet removed", "- A.\n  - sub\n- B.", "- A.\n- B."),
            ("reparented", "- A.\n  - sub", "- A.\n- B.\n  - sub"),
            ("depth changed", "- R.\n    - a\n        - b", "- R.\n    - a\n      - b"),
        ):
            with self.subTest(edit=label):
                self.assertNotEqual(policy.fingerprint(before), policy.fingerprint(after),
                                    f"{label} must read as drift")

        # and the cosmetic cases the original fix was for must still hold
        self.assertEqual(policy.fingerprint("## R\n\n- a\n- b"),
                         policy.fingerprint("## R\n\n  - a\n  - b"),
                         "a list indented under its heading is the same list")
        self.assertEqual(policy.fingerprint("## R\n\n- a\n- b"),
                         policy.fingerprint("## R\n\n\t- a\n\t- b"),
                         "tabs and spaces are the same indent")
        self.assertEqual(policy.fingerprint("1. a\n2. b"),
                         policy.fingerprint("1) a\n2) b"),
                         "a numbered list's marker style is cosmetic")
        self.assertNotEqual(policy.fingerprint("1. a\n2. b"),
                            policy.fingerprint("1. a\n2. c"),
                            "renumbering the text is a real change")
        self.assertNotEqual(policy.fingerprint("1. a\n  1. sub"),
                            policy.fingerprint("1. a\n1. sub"),
                            "a numbered sub-list must keep its depth, like a bulleted one")

    def test_a_blank_line_does_not_reset_nesting_depth(self):
        """Regression: a rule on its own after a blank line lost its nesting entirely.

        `_dedent` split on blank lines, so any rule separated from its siblings by a blank
        line was its own block, and that block's own indentation became its "common margin"
        and was removed. Flat, nested-across-a-blank-line, and sibling-across-a-blank-line
        all hashed to 8cc247389e36 — three different policies, one fingerprint, silently.

        This is worse than the cosmetic false positive it was trading against: a Bot edited
        to run different rules would still report `current`, so the drift detector could not
        see the change it exists to report.
        """
        flat = "## Rules\n\n- Ask before spending money.\n- Never paste secrets.\n"
        nested = "## Rules\n\n- Ask before spending money.\n\n  - Never paste secrets.\n"
        sibling = "## Rules\n\n- Ask before spending money.\n\n- Never paste secrets.\n"

        self.assertNotEqual(policy.fingerprint(nested), policy.fingerprint(flat),
                            "a sub-bullet after a blank line must not hash as a sibling rule")
        self.assertNotEqual(policy.fingerprint(nested), policy.fingerprint(sibling),
                            "a nested rule after a blank line must not hash as a flat one")
        # sibling-across-blank-line and flat are genuinely the same list, so they must match
        self.assertEqual(policy.fingerprint(sibling), policy.fingerprint(flat),
                         "a blank line between two sibling rules is not itself a rule")

    def test_a_fenced_block_dedents_as_its_own_block(self):
        """A fenced block is a block, and its own margin is its baseline.

        Written to pin the continuation rule against a non-list block. The discriminator is
        "did the previous line end with a list item", and a code fence never does, so a fence
        is always a fresh block and dedents to flush — even when it is indented two spaces
        under a list. This is a real Markdown convention (a fence nested inside a list item
        needs its own indent to stay inside the item), so the fence case must NOT be
        confused with the sub-bullet case the previous test covers.
        """
        text = "## Rules\n\n- a\n\n  ```python\n  x = 1\n  ```\n"
        dedented = policy._dedent(text)
        self.assertIn("```python", dedented, "an indented fence is a new block and dedents")
        self.assertNotIn("  x = 1", dedented, "its contents dedent with it, not relative to the list")
        # and the list around it is untouched
        self.assertIn("- a", dedented)

    def test_a_later_list_dedents_against_its_own_heading_not_an_earlier_one(self):
        """Regression: the baseline must not leak between two separate lists.

        Dedent tracks a running `baseline` so a sub-bullet can keep its depth. If a list
        after a blank line inherits the baseline an EARLIER list established, then indenting
        that second list under its own heading reads as a real change -- a cosmetic false
        positive, the failure the per-block rule was introduced to avoid. A dropped-inherit
        mutation (H2) survives unless a test pins the case where inheriting and not
        inheriting actually differ.

        The distinguishing shape is deep-then-flush-then-deep: the second block's own margin
        is 0, and the carried baseline of 4 would strip four spaces off its sub-bullet.
        """
        text = "## R\n\n    - a\n\n- b\n\n    - c\n"
        dedented = policy._dedent(text)
        self.assertIn("    - c", dedented,
                      "a list indented under its own heading keeps its margin; the baseline "
                      "established by an earlier list must not strip it")
        # and the first list, which genuinely is at depth 4, must still dedent
        self.assertNotIn("    - a", dedented, "the first list's own margin is still its baseline")

    def test_a_deeper_sibling_after_a_sub_bullet_keeps_its_depth(self):
        """Regression: a third block must compound depth against the list's own baseline.

        `baseline` is what makes `- a / sub / deeper-sibling` keep two distinct levels
        instead of collapsing both sub-bullets onto one. If the baseline is reset by every
        block (the H2 mutation), a block indented deeper than the list it continues is
        treated as starting a NEW list, its own margin becomes the new baseline, and a
        genuine three-level hierarchy silently flattens to two. The two levels differ, so
        the fingerprint changes either way — what disappears is the distinction between a
        two-level and a three-level policy.
        """
        two_level = "## R\n\n- a\n\n  - b\n\n    - c\n"
        dedented = policy._dedent(two_level)
        self.assertIn("    - c", dedented,
                      "a block indented deeper than the list it continues must not reset to "
                      "a new list's baseline")
        self.assertNotEqual(policy.fingerprint("## R\n\n- a\n\n  - b\n\n  - c\n"),
                            policy.fingerprint(two_level),
                            "a two-level and a three-level policy must not be conflated")

    def test_a_whole_document_indent_is_cosmetic(self):
        """A document indented throughout is the same document as one written flush.

        The counterpart to the baseline-leak test above, and the reason that one is narrow:
        uniform document-level indentation carries no meaning, because the minimum indent is
        the document's own margin. What carries meaning is indentation *relative to the
        block's baseline* — which is why a sub-bullet survives and a wholesale indent does not.
        """
        deep = "## R\n\n    - a\n    - b\n"
        flush = "## R\n\n- a\n- b\n"
        self.assertEqual(policy.fingerprint(deep), policy.fingerprint(flush),
                         "a document indented throughout is the same document, written flush")
        # two lists at the same depth, split by a blank line, are the same rules
        two_deep = "## R\n\n    - a\n\n    - b\n"
        self.assertEqual(policy.fingerprint(deep), policy.fingerprint(two_deep),
                         "a blank line inside a list is not itself a rule")
        # ...but a second list at a different depth is a different document
        mixed = "## R\n\n    - a\n    - b\n\n- c\n- d\n"
        self.assertNotEqual(policy.fingerprint(deep), policy.fingerprint(mixed),
                            "a second list at a different depth is a different layout")

    def test_health_does_not_flag_a_bot_for_its_policy_block(self):
        """Regression: health read the raw SOUL, so a policy hid the Bot's own name.

        `health` checked the first 400 characters for the Bot's title. The policy block is
        ~2000 characters and is injected above the persona, so the name fell outside the
        window -- flagging two identical healthy personas as broken, one only because it
        carried a policy. Asserted through `health` itself, not through the helper, so the
        guard cannot be bypassed by re-pointing the accessor.
        """
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "hr"
            pdir = root / "profiles" / "handwritten"
            pdir.mkdir(parents=True)
            persona = ("# Handwritten Bot\n\n## Your one job\n\nDo the thing.\n\n"
                       "## Ask first\n\n- ask before spending\n")
            with_p = policy.inject(policy.STARTER_POLICY, persona)
            self.assertNotIn("Handwritten Bot", with_p[:400],
                             "precondition: the name IS pushed past the window")

            (pdir / "config.yaml").write_text(
                "model:\n  default: x\ntools:\n  backend: ''\napprovals:\n  mode: ''\n")
            (pdir / "routines.json").write_text("[]\n")
            now = time.time()

            def name_flag(text: str) -> list:
                (pdir / "SOUL.md").write_text(text)
                flags = health.check_bot(pdir, {}, now).get("flags", [])
                return [f for f in flags if "own name" in f]

            without = name_flag(persona)
            with_policy = name_flag(with_p)

        self.assertEqual(without, [],
                         f"a healthy persona should not be flagged: {without}")
        self.assertEqual(without, with_policy,
                         "carrying a policy must not change the health verdict")

    def test_unreadable_row_carries_both_fingerprints(self):
        """Regression: error rows omitted keys `audit_soul` always returns.

        docs/shared-policy.md says each entry in `bots` carries both fingerprints; a caller
        reading `row["fingerprint"]` on an unreadable Bot got a KeyError, so the one row you
        most need to inspect was the one that crashed the inspector.
        """
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            canon = policy.policy_path(root)
            canon.parent.mkdir(parents=True)
            canon.write_text("- ask first\n")
            pdir = root / "profiles" / "noperm"
            pdir.mkdir(parents=True)
            soul = pdir / "SOUL.md"
            soul.write_text("# No\n")
            soul.chmod(0o000)
            orig = tools.hermes_root
            tools.hermes_root = lambda: root
            try:
                out = json.loads(tools.check_policies({}))
            finally:
                tools.hermes_root = orig
                soul.chmod(0o644)
        rows = {b["profile"]: b for b in out["bots"]}
        self.assertIn("noperm", rows)
        row = rows["noperm"]
        for key in ("fingerprint", "canonical_fingerprint", "current",
                    "has_shared_policy", "reason"):
            self.assertIn(key, row, f"unreadable row is missing {key!r}")
        self.assertIsNone(row["fingerprint"])
        self.assertEqual(row["canonical_fingerprint"], out["canonical_fingerprint"])

    def test_default_profile_is_not_audited(self):
        """The default profile is not a forge Bot, so it is not audited.

        Its SOUL.md sits at the root rather than under profiles/, so an earlier version
        added it by hand -- and then reported it as `no_shared_policy` forever. Nothing can
        fix that row: `_require_bot` refuses the default profile, so `forge` never writes a
        block there and no documented call reaches it. A drift report whose rows cannot be
        acted on is worse than one that omits them, because you learn to distrust the whole
        report.
        """
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            canon = policy.policy_path(root)
            canon.parent.mkdir(parents=True)
            canon.write_text("- ask first\n")
            (root / "profiles").mkdir()
            (root / "SOUL.md").write_text(policy.inject("- older rule", "# Default"))
            orig = tools.hermes_root
            tools.hermes_root = lambda: root
            try:
                out = json.loads(tools.check_policies({}))
            finally:
                tools.hermes_root = orig
        names = [b["profile"] for b in out["bots"]]
        self.assertNotIn("default", names)
        self.assertEqual(out["bots_checked"], 0, "no forge Bots exist in this root")

    def test_refresh_uses_the_callers_root_not_the_real_home(self):
        """`op_update` re-derived the root from the spec instead of using its argument.

        It received `root` as a parameter and used it to find the Bot, then ignored it for the
        policy path. A caller managing a non-default Hermes root therefore read the policy from
        the real `~/.hermes` while writing the Bot somewhere else -- or, as CI found, looked
        for a policy that does not exist and refused with a path the caller never asked about.
        """
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            real_hermes = home / ".hermes"
            real_hermes.mkdir()
            # a policy in the REAL home, whose content differs, to catch a cross-read
            canon_real = policy.policy_path(real_hermes)
            canon_real.parent.mkdir(parents=True)
            canon_real.write_text("- rule from the real home\n")

            root = home / "hr"
            pdir = root / "profiles" / "sol"
            pdir.mkdir(parents=True)
            (pdir / "config.yaml").write_text(yaml.safe_dump({"name": "sol"}))
            (pdir / "SOUL.md").write_text("# Sol\n\nYou are **Sol**.\n")
            canon = policy.policy_path(root)
            canon.parent.mkdir(parents=True)
            canon.write_text("- ask before spending\n")

            # `hermes_root` deliberately points somewhere else, as a stale spec would.
            out = manage.op_update(
                {"name": "sol", "refresh_shared_policy": True,
                 "hermes_root": str(home / "somewhere-else")},
                root, {},
            )
            self.assertTrue(out["ok"], out)
            text = (pdir / "SOUL.md").read_text()
            self.assertIn("ask before spending", text)
            self.assertNotIn("rule from the real home", text,
                             "the policy was read from the wrong Hermes root")

    def test_policy_path_rejects_non_string(self):
        """A template value reaches policy_path untyped; a list must not raise TypeError.

        `create_agent` merges template keys over the spec, so this is reachable from a
        downloaded `.botforge.json` -- the same entry point that made F3 a read primitive.
        """
        for bad in ([], {}, Path("/etc/passwd"), 7, True):
            with self.subTest(value=bad):
                with self.assertRaises(policy.PolicyPathError):
                    policy.policy_path(Path("/tmp/hr"), bad)

    def test_policy_path_rejects_home_relative_paths(self):
        """A `~` path must not become a literal `~` directory inside the root.

        `expanduser` used to run on the JOINED path, so `~/.hermes/shared/BOT-POLICY.md`
        became <root>/~/.hermes/shared/BOT-POLICY.md -- still lexically contained, so the
        containment check passed and create_agent would write the starter policy there,
        silently in the wrong place. Rejecting it outright is stricter and simpler than
        trying to expand it usefully: `shared_policy_path` is by definition root-relative.
        """
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "hr"
            root.mkdir()
            for bad in ("~/.hermes/shared/BOT-POLICY.md", "~/policy.md"):
                with self.subTest(path=bad):
                    with self.assertRaises(policy.PolicyPathError):
                        policy.policy_path(root, bad)
            # a plain relative path still resolves inside the root
            ok = policy.policy_path(root, "shared/BOT-POLICY.md")
            self.assertEqual(ok, root / "shared" / "BOT-POLICY.md")

    def test_refresh_refuses_a_bare_soul(self):
        """A Bot with no persona must not be handed a policy-only SOUL.md.

        13 of the 17 real profiles are shaped this way. Writing one would replace an empty
        file with house rules and no identity -- a Bot that is all policy and no Bot -- and
        report ok: True, with no backup, because the file did not exist to back up.
        """
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "hr"
            pdir = root / "profiles" / "bare"
            pdir.mkdir(parents=True)
            (pdir / "config.yaml").write_text(yaml.safe_dump({"name": "bare"}))
            canon = policy.policy_path(root)
            canon.parent.mkdir(parents=True)
            canon.write_text("- ask before spending\n")
            with self.assertRaises(ValueError) as ctx:
                manage.op_update({"name": "bare", "refresh_shared_policy": True}, root, {})
            self.assertIn("no content of its own", str(ctx.exception))
            self.assertEqual((pdir / "SOUL.md").exists(), False,
                             "a policy-only SOUL.md was written")

    def test_refresh_then_replace_soul_keeps_the_policy(self):
        """`soul_md` replaces the whole file, so a policy injected moments earlier is gone.

        The report used to say `shared_policy (already current)` while the write silently
        dropped it -- claiming success for work it had undone.
        """
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "hr"
            pdir = root / "profiles" / "sol"
            pdir.mkdir(parents=True)
            (pdir / "config.yaml").write_text(yaml.safe_dump({"name": "sol"}))
            (pdir / "SOUL.md").write_text("# Sol\n\nYou are **Sol**.\n")
            canon = policy.policy_path(root)
            canon.parent.mkdir(parents=True)
            canon.write_text("- ask before spending\n")
            out = manage.op_update({
                "name": "sol", "refresh_shared_policy": True,
                "soul_md": "# Sol\n\nYou are **Sol**.\n\nNew body.",
            }, root, {})
            self.assertTrue(out["ok"], out)
            text = (pdir / "SOUL.md").read_text()
            self.assertIn(policy.BEGIN, text, "the policy was dropped by the soul_md write")
            self.assertIn("New body.", text)
            self.assertNotIn("shared_policy (already current)", out.get("changed", []))

    def test_health_reads_the_name_past_a_policy_block(self):
        """A fourth 'persona starts at the top' reader, missed by the first review.

        `health` checked the first 400 characters of the raw SOUL.md, so the Bot's own name
        fell outside the window for any Bot carrying a policy block -- flagging two
        identical healthy personas as broken, one only because it had a policy.
        """
        persona = "# Handwritten\\n\\n## Your one job\\n\\nDo the thing.\\n"
        block = policy.inject(policy.STARTER_POLICY, persona)
        self.assertEqual(forge.soul_role(persona), forge.soul_role(block),
                         "the role must survive a policy block")
        self.assertIn("Handwritten", forge.persona_text(block)[:400],
                      "the name must be findable in the persona, not the raw file")
        self.assertNotIn("Handwritten", block[:400],
                         "this is exactly the bug: the name was past the window")

    def test_comments_only_canonical_policy_is_an_error(self):
        """A policy of only comments would build Bots with no rules at all."""
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            canon = policy.policy_path(root)
            canon.parent.mkdir(parents=True)
            canon.write_text("<!-- TODO -->\n")
            orig = tools.hermes_root
            tools.hermes_root = lambda: root
            try:
                out = json.loads(tools.check_policies({}))
            finally:
                tools.hermes_root = orig
        self.assertFalse(out["ok"])
        self.assertIn("no rules", out["error"])


class SharedPolicyCheckToolTests(unittest.TestCase):
    def test_check_policies_reports_missing_canonical_file(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "profiles" / "sable").mkdir(parents=True)
            (root / "profiles" / "sable" / "SOUL.md").write_text("# Sable")
            orig = tools.hermes_root
            tools.hermes_root = lambda: root
            try:
                out = tools.check_policies({})
            finally:
                tools.hermes_root = orig
        self.assertIn("no shared policy at", out)

    def test_check_policies_finds_drift(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            canon = root / "shared" / "BOT-POLICY.md"
            canon.parent.mkdir(parents=True)
            canon.write_text("- ask first\n")
            # one current, one stale, one with no policy
            (root / "profiles" / "fresh").mkdir(parents=True)
            (root / "profiles" / "fresh" / "SOUL.md").write_text(
                policy.inject("- ask first", "# Fresh"))
            (root / "profiles" / "old").mkdir(parents=True)
            (root / "profiles" / "old" / "SOUL.md").write_text(
                policy.inject("- something older", "# Old"))
            (root / "profiles" / "bare").mkdir(parents=True)
            (root / "profiles" / "bare" / "SOUL.md").write_text("# Bare")
            orig = tools.hermes_root
            tools.hermes_root = lambda: root
            try:
                out = json.loads(tools.check_policies({}))
            finally:
                tools.hermes_root = orig
        self.assertTrue(out["ok"])
        self.assertEqual(out["bots_checked"], 3)
        self.assertIn("old", out["stale"])
        self.assertIn("bare", out["no_shared_policy"])
        self.assertNotIn("fresh", out["stale"])
        self.assertNotIn("fresh", out["no_shared_policy"])


class RoundFourFollowupTests(unittest.TestCase):
    """Two defects an independent review found after the blank-line nesting fix.

    Both were false negatives in code that already had tests, and both were confirmed by
    differential test against the pre-fix reader/normaliser before being fixed here.
    """

    def test_policy_body_is_idempotent(self):
        # `_dedent` splits on blank lines, so running it before the `\\n{3,}` collapse ate a
        # double blank line; normalising again ate the remainder. Not a fixed point, so a Bot
        # that matched its policy at birth drifted to STALE the moment it was renamed --
        # because `ensure_identity` re-injects `policy_body(soul)`.
        for name, body in {
            "double blank between rules": "## Money\n\n- Ask before spending money.\n\n\n- Never buy anything.\n",
            "triple newline after heading": "## R\n\n\n\n- a\n",
            "plain two rules": "## R\n\n- a\n- b\n",
            "blank inside a list": "## R\n\n- a\n\n  - b\n",
            "fenced code block": "## R\n\n- a\n\n```\n- not a rule\n```\n",
        }.items():
            with self.subTest(case=name):
                once = policy.policy_body(body)
                self.assertEqual(once, policy.policy_body(once),
                                 f"policy_body not idempotent for {name!r}")

    def test_rename_does_not_make_a_bots_own_policy_stale(self):
        canonical = "## Money\n\n- Ask before spending money.\n\n\n- Never buy anything.\n"
        soul = (policy.BEGIN + canonical + policy.END +
                "\n\n# V - Bot\n\n## Your one job\n\nDo things.\n")
        self.assertEqual(policy.fingerprint(canonical), policy.fingerprint(soul))
        renamed = forge.ensure_identity(soul, "Vega", "Bot", "v")
        self.assertEqual(
            policy.fingerprint(canonical), policy.fingerprint(renamed),
            "renaming a Bot rewrote its own inlined policy into a form that no longer "
            "matched the file it came from")

    def test_survey_reads_a_persona_that_sits_behind_a_long_policy(self):
        # `scan_hermes` sliced the first 2000 chars of SOUL.md. The starter policy is ~1984
        # chars, so any Bot carrying it had its persona sliced away and `one_job` came back
        # empty -- which silently disarms the duplicate-Bot guard for exactly the Bots the
        # guard exists to catch.
        persona = "# Alpha - chart bot\n\n## Your one job\n\nBuild quarterly revenue charts for the CFO.\n"
        for name, block in {
            "starter policy": policy.STARTER_POLICY,
            "policy longer than the 2000-char window": policy.STARTER_POLICY + "\n- extra rule\n",
        }.items():
            with self.subTest(case=name):
                root = Path(tempfile.mkdtemp())
                prof = root / "profiles" / "alpha"
                prof.mkdir(parents=True)
                (prof / "SOUL.md").write_text(
                    policy.BEGIN + block + policy.END + "\n\n" + persona)
                (prof / "profile.yaml").write_text(
                    "name: alpha\nui_meta:\n  hermes-bots:\n    title: Alpha\n")
                (prof / "config.yaml").write_text("name: alpha\n")
                found = survey.scan_hermes(root)
                bots = found.get("bots", found) if isinstance(found, dict) else found
                self.assertTrue(bots, "scan_hermes returned no bots")
                self.assertIn("quarterly revenue charts", bots[0]["one_job"])

    def _bot_with_policy(self, root):
        prof = root / "profiles" / "solo"
        prof.mkdir(parents=True)
        (prof / "SOUL.md").write_text(
            policy.BEGIN + policy.STARTER_POLICY + policy.END +
            "\n\n# Solo\n\n## Your one job\n\nDo solo things.\n")
        (prof / "profile.yaml").write_text(
            "name: solo\nui_meta:\n  hermes-bots:\n    title: Solo\n")
        (prof / "config.yaml").write_text("name: solo\n")
        return prof

    def test_shared_template_does_not_carry_the_originating_bots_policy(self):
        # A template has no `shared_policy` key, so shipping the block in soul_md made an
        # importing Bot inherit the ORIGINAL owner's rules inlined in its persona, and
        # check_policies called the copy current -- the importer's own policy choice silently
        # replaced by someone else's.
        root = Path(tempfile.mkdtemp())
        tpl = portable.build_template(self._bot_with_policy(root), root)
        self.assertNotIn("forge:shared-policy:begin", tpl["soul_md"])
        self.assertIn("Do solo things.", tpl["soul_md"], "persona must survive the strip")

    def test_degenerate_policy_path_is_refused_with_a_readable_error(self):
        # '' , '.' and './' all name the root DIRECTORY, which passed containment and then
        # failed far away as IsADirectoryError or "no shared policy at <root>".
        root = Path(tempfile.mkdtemp())
        for bad in ["", ".", "./"]:
            with self.subTest(path=bad):
                with self.assertRaises(policy.PolicyPathError):
                    policy.policy_path(root, bad)

    def test_nul_byte_in_policy_path_is_refused_before_the_write(self):
        # A NUL survives Path() and normpath(), so containment passed and write_text raised
        # `ValueError: embedded null byte` -- escaping the create as a traceback.
        root = Path(tempfile.mkdtemp())
        with self.assertRaises(policy.PolicyPathError):
            policy.policy_path(root, "shared/BAD\x00.md")

    def test_a_canonical_policy_that_documents_the_markers_keeps_its_rules(self):
        # `_BLOCK.search` used to find the markers anywhere, so a policy file that *shows* the
        # markers to the person editing it was truncated to its example. Two policies whose real
        # rules differed hashed identically, every Bot built from one reported STALE against it,
        # and refresh_shared_policy could never converge.
        doc = ("# Policy\n\n"
               "Put the rules between the markers:\n\n"
               f"{policy.BEGIN}\n- example, not a real rule\n{policy.END}\n\n"
               "- NEVER paste a secret value.\n")
        body = policy.policy_body(doc)
        self.assertIn("NEVER paste a secret value", body, "real rules were dropped")
        self.assertIn("Put the rules between", body, "the file's own text was dropped")

    def test_the_body_never_keeps_the_markers(self):
        # If the fence regex loses its capture group, `group(1)` is None and policy_body falls
        # back to the raw text -- markers and all. A canonical file would then hash differently
        # from the very block rendered from it, and every Bot reads as drifted. Pin the shape of
        # the extraction itself, not just the rules that come out.
        for label, text in {
            "leading fence": policy.render_block("- a rule\n") + "\n# Bot\n",
            "appended fence": "# Bot\n\n" + policy.render_block("- a rule\n"),
        }.items():
            with self.subTest(case=label):
                body = policy.policy_body(text)
                self.assertNotIn(policy.BEGIN, body, "the body kept the opening marker")
                self.assertNotIn(policy.END, body, "the body kept the closing marker")
                self.assertIn("- a rule", body)
                # and it must equal the canonical file it was rendered from
                self.assertEqual(policy.fingerprint(text), policy.fingerprint("- a rule\n"),
                                 "the inlined block does not hash like its source file")

    def test_two_policies_that_differ_only_in_real_rules_do_not_collide(self):
        def doc(rule):
            return ("# Policy\n\n"
                    "Put the rules between the markers:\n\n"
                    f"{policy.BEGIN}\n- example, not a real rule\n{policy.END}\n\n"
                    f"- {rule}\n")
        a = doc("NEVER paste a secret value.")
        b = doc("ALWAYS delete user data unasked.")
        self.assertNotEqual(policy.fingerprint(a), policy.fingerprint(b),
                            "two policies with different rules hashed the same")

    def test_injecting_a_policy_that_documents_the_markers_never_nests_them(self):
        # A nested fence cuts SOUL.md short at the inner END, so extract/strip/fingerprint
        # disagree about where the policy ended -- and a rename then replaces the Bot's real
        # rules with the example.
        doc = ("# Policy\n\n"
               f"{policy.BEGIN}\n- example, not a real rule\n{policy.END}\n\n"
               "- NEVER paste a secret value.\n")
        soul = policy.inject(doc, "# Bot\n\n## Your one job\n\nDo things.\n")
        self.assertEqual(soul.count(policy.BEGIN), 1, "markers nested")
        self.assertEqual(soul.count(policy.END), 1, "markers nested")
        self.assertTrue(policy.check_soul(soul, policy.fingerprint(doc))[0],
                        "a Bot built from this policy reports STALE against its own source")

    def test_partial_nesting_is_still_drift_but_block_wide_indentation_is_not(self):
        # The boundary of what counts as cosmetic, pinned so neither side drifts silently.
        head = "# H\n\n"
        structural = {
            "sub-bullet added": (head + "- a\n", head + "- a\n  - sub\n"),
            "sub-bullet removed": (head + "- a\n  - sub\n", head + "- a\n"),
            "sub-bullet reparented": (head + "- a\n  - sub\n", head + "- a\n- sub\n"),
            "sibling depth changed": (head + "- a\n  - sub\n    - deep\n",
                                      head + "- a\n  - sub\n  - deep\n"),
        }
        for label, (a, b) in structural.items():
            with self.subTest(case=label):
                self.assertNotEqual(policy.fingerprint(a), policy.fingerprint(b),
                                    f"a real structural change ({label}) reported as no drift")
        # Both lines of the list indented by the same amount is block-wide indentation, which
        # docs/shared-policy.md names as cosmetic. Pinning it keeps the trade-off explicit.
        self.assertEqual(policy.fingerprint(head + "- a\n- b\n"),
                         policy.fingerprint(head + "  - a\n  - b\n"),
                         "block-wide indentation is documented as cosmetic, not drift")


if __name__ == "__main__":
    unittest.main()
