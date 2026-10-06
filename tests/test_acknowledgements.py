"""Reacting to a message: the reply prefix and the Desktop tapback.

Split out of tests/test_forge.py, which had grown past 2,300 lines; the shared helpers
and the sys.path setup Hermes-style imports need live in tests/support.py.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import FakeCtx, forge, make_root, yaml


class Acknowledgements(unittest.TestCase):
    def test_policy_lists_each_state_once(self):
        import acks
        emojis = [e for e, _ in acks.ACKS]
        self.assertEqual(len(emojis), len(set(emojis)))
        for emoji, meaning in acks.ACKS:
            self.assertIn(f"- {emoji} — {meaning}", acks.ACK_POLICY)

    def test_policy_asks_for_a_prefix_not_a_reaction(self):
        import acks
        self.assertIn("Begin every reply with one emoji", acks.ACK_POLICY)
        self.assertIn("never the whole reply", acks.ACK_POLICY)
        # Hermes' own react_to_message says "never as a status signal" — don't fight it
        self.assertIn("never as a status signal", acks.ACK_POLICY)

    def test_an_older_convention_block_is_replaced_not_stacked(self):
        import acks
        legacy = acks.LEGACY_MARKERS[0]
        soul = (f"# Quill — Writer\n\nYou are **Quill**.\n\n{legacy}\n## Acknowledge with a reaction\n"
                "React to the message.\n\n- 👀 — picked up\n\n## Never\n- never publish\n")
        out = acks.apply_policy(soul)
        self.assertNotIn(legacy, out)
        self.assertEqual(out.count(acks.ACK_MARKER), 1)
        self.assertIn("You are **Quill**", out)
        self.assertIn("never publish", out)
        self.assertNotIn("## Acknowledge with a reaction", out)

    def test_re_enabling_journal_repairs_orphaned_policy_text(self):
        """A Bot left with the guidance but no marker gets one clean section, not two."""
        import acks
        import journal
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = root / "profiles" / "quill"
            d.mkdir(parents=True)
            (d / "SOUL.md").write_text("# Quill\n\nYou are **Quill**.\n\n" +
                                       journal.JOURNAL_POLICY.replace(journal.JOURNAL_MARKER + "\n", "") +
                                       f"\n{acks.ACK_MARKER}\n## Say where\n- x\n")
            self.assertFalse(journal.journaling_enabled(d))
            out = journal.enable_journal(d)
            self.assertTrue(out["changed"])
            soul = (d / "SOUL.md").read_text()
            self.assertEqual(soul.count("## Work journal"), 1)
            self.assertEqual(soul.count(journal.JOURNAL_MARKER), 1)
            self.assertIn("You are **Quill**", soul)
            self.assertIn(acks.ACK_MARKER, soul)
            self.assertTrue(journal.journaling_enabled(d))

    def test_upgrading_acks_leaves_the_journal_block_alone(self):
        """Regression: the v1->v2 upgrade used to cut to the next heading, eating the marker
        comment above it — journal text stayed, the marker vanished, journaling silently died."""
        import acks
        import journal
        soul = (f"# Quill — Writer\n\nYou are **Quill**.\n\n{acks.LEGACY_MARKERS[0]}\n"
                "## Acknowledge with a reaction\nReact to the message.\n\n- 👀 — picked up\n\n"
                f"{journal.JOURNAL_MARKER}\n## Work journal\n- record what you did.\n\n"
                "## Never\n- never publish\n")
        out = acks.apply_policy(soul)
        self.assertIn(journal.JOURNAL_MARKER, out)
        self.assertIn("## Work journal", out)
        self.assertIn("record what you did", out)
        self.assertNotIn("## Acknowledge with a reaction", out)
        self.assertIn("never publish", out)

    def test_enabling_acks_keeps_a_bot_journaling(self):
        import acks
        import journal
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = root / "profiles" / "quill"
            d.mkdir(parents=True)
            (d / "SOUL.md").write_text("# Quill\n\nYou are **Quill**.\n")
            journal.enable_journal(d)
            (d / "SOUL.md").write_text(
                (d / "SOUL.md").read_text().replace(acks.ACK_MARKER, acks.LEGACY_MARKERS[0])
                if acks.ACK_MARKER in (d / "SOUL.md").read_text() else
                (d / "SOUL.md").read_text() + f"\n{acks.LEGACY_MARKERS[0]}\n## Acknowledge\n- x\n")
            self.assertTrue(journal.journaling_enabled(d))
            acks.enable_acks(d)
            self.assertTrue(journal.journaling_enabled(d), "upgrading acks disabled journaling")

    def test_enable_reports_an_upgrade_from_the_old_convention(self):
        import acks
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = root / "profiles" / "quill"
            d.mkdir(parents=True)
            (d / "SOUL.md").write_text(f"# Quill\n\nYou are **Quill**.\n\n{acks.LEGACY_MARKERS[0]}\n## Acknowledge\n- x\n")
            out = acks.enable_acks(d)
            self.assertTrue(out["changed"])
            self.assertTrue(out["upgraded"])
            self.assertTrue(acks.acks_enabled(d))

    def test_apply_is_idempotent_and_keeps_the_persona(self):
        import acks
        soul = "# Quill — Writer\n\nYou are **Quill**.\n\n## Never\n- never publish\n"
        once = acks.apply_policy(soul)
        self.assertIn("## Never", once)
        self.assertIn("You are **Quill**", once)
        self.assertEqual(acks.apply_policy(once), once)
        self.assertEqual(once.count(acks.ACK_MARKER), 1)

    def test_enable_on_an_existing_bot_backs_up_and_is_repeatable(self):
        import acks
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = root / "profiles" / "quill"
            d.mkdir(parents=True)
            (d / "SOUL.md").write_text("# Quill — Writer\n\nYou are **Quill**.\n")
            first = acks.enable_acks(d)
            self.assertTrue(first["changed"])
            self.assertTrue(Path(first["backup"]).exists())
            self.assertTrue(acks.acks_enabled(d))
            second = acks.enable_acks(d)
            self.assertFalse(second["changed"])
            self.assertEqual((d / "SOUL.md").read_text().count(acks.ACK_MARKER), 1)

    def test_new_bots_acknowledge_unless_asked_not_to(self):
        import acks
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            spec = {"hermes_root": str(root), "role": "Writer", "one_job": "writes",
                    "soul_md": "# Kairo — Writer\n\nYou are **Kairo**.\n", "display_name": "Kairo"}
            out = forge.forge({**spec, "sandbox": "nope"})  # refused before creation, but the soul is built first
            self.assertFalse(out["ok"])
            # the policy decision is what we assert, without creating a profile:
            self.assertIn(acks.ACK_MARKER, acks.apply_policy(spec["soul_md"]))
            self.assertNotIn(acks.ACK_MARKER, spec["soul_md"])



class AckVisibility(unittest.TestCase):
    """A Bot created before acknowledgements stays silent — that must be visible, not a mystery."""

    def _bot(self, root, name, acking):
        import acks
        d = root / "profiles" / name
        (d / "cron").mkdir(parents=True)
        (d / "config.yaml").write_text(yaml.safe_dump({"platform_toolsets": {"cli": ["web"]}}))
        (d / "profile.yaml").write_text(yaml.safe_dump({"ui_meta": {"hermes-bots": {"title": name.title()}}}))
        soul = f"# {name.title()}\n\nYou are **{name.title()}**.\n\n## Ask first\n- x"
        (d / "SOUL.md").write_text(acks.apply_policy(soul) if acking else soul)
        return d

    def test_health_lists_bots_that_do_not_acknowledge(self):
        import health
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            self._bot(root, "newbie", acking=True)
            self._bot(root, "oldtimer", acking=False)
            with mock.patch.object(health, "_gateways", return_value={}):
                out = health.check({"hermes_root": str(root)})
            self.assertEqual(out["not_acknowledging"], ["Oldtimer"])
            by_name = {b["name"]: b for b in out["report"]}
            self.assertTrue(by_name["newbie"]["acknowledges"])
            self.assertFalse(by_name["oldtimer"]["acknowledges"])

    def test_doctor_counts_acknowledging_bots(self):
        import doctor
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            (root / "config.yaml").write_text(yaml.safe_dump(
                {"model": {"default": "m", "provider": "custom"}, "plugins": {"enabled": ["bot-forge"]}}))
            self._bot(root, "newbie", acking=True)
            self._bot(root, "oldtimer", acking=False)
            with mock.patch.object(doctor, "_gateway_pids", return_value={}), \
                    mock.patch.object(doctor, "sandbox_backends", return_value={}):
                out = doctor.check(root)
            line = next(c for c in out["checks"] if c["check"] == "acknowledgements")
            self.assertEqual(line["status"], "warn")
            self.assertIn("1/2", line["detail"])
            self.assertIn("oldtimer", line["detail"])



class BotChatSource(unittest.TestCase):
    """A Bot Chat's stored source decides its client surface — stamped `cli`, the Bot can never react."""

    def _root(self, bot_mode: bool):
        t = tempfile.mkdtemp()
        root = make_root(Path(t), profiles=["quill"])
        if bot_mode:
            (root / "profiles" / "quill" / "profile.yaml").write_text(
                yaml.safe_dump({"ui_meta": {"hermes-bots": {"title": "Quill"}}}))
        return root

    def test_bot_mode_install_is_detected_from_the_marker(self):
        self.assertTrue(forge.bot_mode_install(self._root(bot_mode=True)))
        self.assertFalse(forge.bot_mode_install(self._root(bot_mode=False)))

    def test_new_chat_on_a_bot_mode_install_is_stamped_desktop_then_titled(self):
        root = self._root(bot_mode=True)
        calls = []

        def fake_run(r, *args, **kw):
            calls.append(args)
            return type("P", (), {"returncode": 0, "stdout": "hello", "stderr": ""})()

        with mock.patch.object(forge, "run", side_effect=fake_run), \
                mock.patch.object(forge, "has_bot_chat", return_value=False), \
                mock.patch.object(forge, "newest_session", return_value="s1"):
            ok, _ = forge.bot_chat(root, "quill", "hi")
        self.assertTrue(ok)
        self.assertIn("--source", calls[0])
        self.assertEqual(calls[0][calls[0].index("--source") + 1], "desktop")
        self.assertNotIn("--create-if-missing", calls[0])  # that path hardcodes source="cli" upstream
        self.assertEqual(calls[1][:3], ("-p", "quill", "sessions"))
        self.assertEqual(calls[1][3:], ("rename", "s1", "Bot Chat"))

    def test_existing_chat_is_continued_not_recreated(self):
        root = self._root(bot_mode=True)
        calls = []
        with mock.patch.object(forge, "run", side_effect=lambda r, *a, **k: calls.append(a) or
                               type("P", (), {"returncode": 0, "stdout": "hi", "stderr": ""})()), \
                mock.patch.object(forge, "has_bot_chat", return_value=True):
            forge.bot_chat(root, "quill", "hi")
        self.assertEqual(len(calls), 1)
        self.assertIn("--create-if-missing", calls[0])

    def test_without_bot_mode_the_chat_stays_a_cli_session(self):
        root = self._root(bot_mode=False)
        calls = []
        with mock.patch.object(forge, "run", side_effect=lambda r, *a, **k: calls.append(a) or
                               type("P", (), {"returncode": 0, "stdout": "hi", "stderr": ""})()), \
                mock.patch.object(forge, "has_bot_chat", return_value=False):
            forge.bot_chat(root, "quill", "hi")
        self.assertIn("--create-if-missing", calls[0])
        self.assertNotIn("--source", calls[0])



class TapbackHooks(unittest.TestCase):
    """The plugin places the reaction itself — the model is told not to use reactions for status."""

    FakeCtx = FakeCtx

    def _marks(self, ctx, allowed=True, registered=True):
        """A Tapback with the environment stubbed: reactions allowed, tool registered."""
        import tapback
        marks = tapback.Tapback(ctx, lambda: True)
        self.addCleanup(setattr, tapback, "reactions_allowed", tapback.reactions_allowed)
        self.addCleanup(setattr, tapback, "_ensure_tool", tapback._ensure_tool)
        tapback.reactions_allowed = lambda: allowed
        tapback._ensure_tool = lambda: registered
        return marks

    def test_reacts_only_on_desktop_and_only_when_enabled(self):
        import tapback
        self.assertTrue(tapback.should_react("desktop", True))
        for platform in ("cli", "acp", "tui", "api_server", "", None):
            self.assertFalse(tapback.should_react(platform, True), platform)
        self.assertFalse(tapback.should_react("desktop", False))

    def test_turn_start_marks_working_and_end_marks_the_outcome(self):
        import tapback
        ctx = self.FakeCtx()
        marks = self._marks(ctx)
        marks.on_turn_start(platform="desktop")
        marks.on_turn_end(platform="desktop", assistant_response="All done.")
        self.assertEqual([a["emoji"] for _n, a in ctx.calls], [tapback.WORKING, tapback.DONE])
        self.assertEqual({n for n, _a in ctx.calls}, {"react_to_message"})

    def test_the_pickup_reaction_fits_what_was_asked(self):
        """One 👀 for everything says "I am alive"; this says "I understood what you asked"."""
        import tapback
        cases = {
            "fix the failing build": "🔧",
            "the deploy is broken": "🔧",
            "research what our competitor shipped": "🔎",
            "dig into the churn numbers": "🔎",
            "draft the launch thread": "✍️",
            "write me a newsletter": "✍️",
            "how many followers did we gain?": "📊",
            "compare last month's revenue": "📊",
            "schedule a daily 8am digest": "⏳",
            "remind me tomorrow at 9": "⏳",
            "review this diff": "📋",
            "build me a competitor watcher": "🛠️",
            "set up a sandbox": "🛠️",
            "thanks!": "👋",
            "hey": "👋",
            "why did it fail?": "💬",
            "what is bot forge?": "💬",
        }
        for message, expected in cases.items():
            self.assertEqual(tapback.pickup_emoji(message), expected, message)

    def test_an_unreadable_ask_still_gets_picked_up(self):
        import tapback
        for message in ("ok go", "", None, "   ", 42):
            self.assertEqual(tapback.pickup_emoji(message), tapback.WORKING, repr(message))

    def test_the_message_is_read_whatever_shape_it_arrives_in(self):
        import tapback
        self.assertEqual(tapback.pickup_emoji({"content": "fix the build"}), "🔧")
        self.assertEqual(tapback.pickup_emoji({"text": "draft a post"}), "✍️")
        self.assertEqual(tapback.pickup_emoji(
            {"content": [{"type": "text", "text": "review this diff"}]}), "📋")

    def test_a_pickup_never_collides_with_an_outcome(self):
        """Hermes clears a reaction when the same emoji is set twice, so the two sets must not meet."""
        import tapback
        pickups = {emoji for emoji, _pattern in tapback.PICKUP} | {tapback.WORKING}
        outcomes = ({emoji for emoji, _pattern in tapback.OUTCOME}
                    | {tapback.DONE, tapback.BLOCKED, tapback.NEEDS_YOU})
        self.assertEqual(pickups & outcomes, set())

    def test_the_turn_start_reaction_comes_from_the_message(self):
        import tapback
        ctx = self.FakeCtx()
        marks = self._marks(ctx)
        marks.on_turn_start(platform="desktop", user_message="fix the failing build")
        marks.on_turn_end(platform="desktop", assistant_response="Done — the build is green.")
        self.assertEqual([a["emoji"] for _n, a in ctx.calls], ["🔧", tapback.DONE])

    def test_the_plugin_stands_down_when_the_companion_is_here(self):
        """Two placements of the same emoji cancel — Hermes reads that as a tapback toggle."""
        import companion as plugin
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profiles" / "ceo"
            forge_dir = profile / "plugins" / "bot-forge"
            marks_dir = profile / "plugins" / "bot-forge-marks"
            forge_dir.mkdir(parents=True)
            self.assertFalse(plugin.companion_running(forge_dir), "no companion installed")

            marks_dir.mkdir(parents=True)
            (marks_dir / "plugin.yaml").write_text("name: bot-forge-marks\n")
            (profile / "config.yaml").write_text(yaml.safe_dump(
                {"plugins": {"enabled": ["bot-forge", "bot-forge-marks"]}}))
            self.assertTrue(plugin.companion_running(forge_dir), "installed and enabled")

            (profile / "config.yaml").write_text(yaml.safe_dump(
                {"plugins": {"enabled": ["bot-forge"]}}))
            self.assertFalse(plugin.companion_running(forge_dir),
                             "installed but switched off — this plugin must cover the reaction")

    def test_outcome_reads_the_reply(self):
        import tapback
        self.assertEqual(tapback.outcome_emoji("All done."), tapback.DONE)
        self.assertEqual(tapback.outcome_emoji("I can't publish for you."), tapback.BLOCKED)
        self.assertEqual(tapback.outcome_emoji("Ready. Shall I post it?"), tapback.NEEDS_YOU)

    def test_the_ending_reaction_says_what_happened(self):
        """"Done" is the fallback, not the answer: the reply usually says what kind of done."""
        import tapback
        cases = {
            "Fixed and deployed — the build is green.": "🚀",
            "Published the thread just now.": "🚀",
            "Here's the draft, five posts.": "📝",
            "I rewrote the opening line.": "📝",
            "You gained 412 followers, up 18% on last week.": "📈",
            "Here is the breakdown by source.": "📈",
            "Scheduled for every morning at 8.": "🗓️",
            "Turns out the token expired overnight.": "💡",
            "Removed 14 stale sessions.": "🧹",
            "All done.": "✅",
        }
        for reply, expected in cases.items():
            self.assertEqual(tapback.outcome_emoji(reply), expected, reply)

    def test_state_beats_the_kind_of_work(self):
        """A draft that needs sign-off is ✋, not 📝 — one needs the user, the other does not."""
        import tapback
        self.assertEqual(tapback.outcome_emoji("Here's the draft — shall I post it?"), tapback.NEEDS_YOU)
        self.assertEqual(tapback.outcome_emoji("I wrote it but the deploy failed."), tapback.BLOCKED)

    def test_an_error_payload_is_a_failure_not_a_success(self):
        """The bug that hid a reaction that never appeared: dispatch returns errors as a value."""
        import tapback
        self.assertFalse(tapback._succeeded('{"error": "Unknown tool: react_to_message"}'))
        self.assertFalse(tapback._succeeded('{"error": "No active session"}'))
        self.assertFalse(tapback._succeeded("{}"))
        self.assertFalse(tapback._succeeded("not json at all"))
        self.assertFalse(tapback._succeeded(None))
        self.assertTrue(tapback._succeeded('{"success": true, "row_id": 31}'))
        self.assertTrue(tapback._succeeded({"success": True}))

    def test_the_hook_reports_whether_the_reaction_landed(self):
        import tapback
        ctx = self.FakeCtx(result='{"error": "Unknown tool: react_to_message"}')
        marks = self._marks(ctx)
        self.assertFalse(marks._react(tapback.WORKING))
        ok = self._marks(self.FakeCtx())
        self.assertTrue(ok._react(tapback.WORKING))

    def test_an_unregistered_tool_is_not_dispatched_at_all(self):
        ctx = self.FakeCtx()
        marks = self._marks(ctx, registered=False)
        marks.on_turn_start(platform="desktop")
        self.assertEqual(ctx.calls, [])

    def test_the_users_reaction_setting_is_honoured(self):
        ctx = self.FakeCtx()
        marks = self._marks(ctx, allowed=False)
        marks.on_turn_start(platform="desktop")
        marks.on_turn_end(platform="desktop", assistant_response="done")
        self.assertEqual(ctx.calls, [])

    def test_an_unreadable_setting_is_not_reported_as_off(self):
        """"Cannot tell" must not be rendered as "off" — that is the same confident wrong answer."""
        import tapback
        self.addCleanup(setattr, tapback, "reactions_setting", tapback.reactions_setting)
        tapback.reactions_setting = lambda: None
        self.assertFalse(tapback.reactions_allowed())
        tapback.reactions_setting = lambda: True
        self.assertTrue(tapback.reactions_allowed())
        tapback.reactions_setting = lambda: False
        self.assertFalse(tapback.reactions_allowed())

    def test_a_failing_reaction_never_breaks_the_turn(self):
        ctx = self.FakeCtx(raises=True)
        marks = self._marks(ctx)
        self.assertIsNone(marks.on_turn_start(platform="desktop"))
        self.assertIsNone(marks.on_turn_end(platform="desktop", assistant_response="x"))

    def test_nothing_is_dispatched_off_desktop(self):
        ctx = self.FakeCtx()
        marks = self._marks(ctx)
        marks.on_turn_start(platform="cli")
        marks.on_turn_end(platform="acp", assistant_response="x")
        self.assertEqual(ctx.calls, [])


