"""A Bot stuck at a sign-in asks for you, rather than failing at the wall where nobody sees it.

Hermes already owns the mechanics: `tools/bot_desktop/lease.py` refuses the Bot while a human
holds the desktop, and discards any frame captured across the transition so the Bot never sees
what was typed. What was missing was the Bot being able to *ask*, and the user being told.

These tests are mostly about the ways asking could go wrong: asking for a screen that does not
exist, asking without saying what for, or claiming the work will resume by itself.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import forge, make_root, takeover


def _proc(stdout="screen: running", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class WhoMayAsk(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = make_root(Path(self.tmp.name), profiles=("marlow",))

    def _ask(self, **over):
        spec = {"hermes_root": str(self.root), "from": "marlow",
                "reason": "the site wants a 2FA code sent to your phone", **over}
        return takeover.request(spec, runner=lambda: _proc())

    def test_a_bot_with_a_screen_can_ask(self):
        out = self._ask()
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["open_screen"], "hermes -p marlow computer-use screen open")

    def test_the_main_profile_cannot_ask(self):
        """It is already talking to the user; a blocked entry would be theatre."""
        out = self._ask(**{"from": "default"})
        self.assertFalse(out["ok"])
        self.assertIn("already has the user's attention", out["error"])

    def test_a_bot_that_does_not_exist_cannot_ask(self):
        out = self._ask(**{"from": "ghost"})
        self.assertFalse(out["ok"])
        self.assertIn("no Bot named", out["error"])

    def test_asking_without_a_reason_is_refused(self):
        """The reason is the whole message: it is what the user reads before getting up."""
        for reason in ("", "   ", None, 42):
            with self.subTest(reason=reason):
                out = self._ask(reason=reason)
                self.assertFalse(out["ok"], reason)
                self.assertIn("say what you are stuck on", out["error"])


class ThereHasToBeAScreen(unittest.TestCase):
    """Sending someone to look at a screen that is not running wastes their trip."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = make_root(Path(self.tmp.name), profiles=("marlow",))

    def _ask(self, runner):
        return takeover.request({"hermes_root": str(self.root), "from": "marlow",
                                 "reason": "needs a login"}, runner=runner)

    def test_no_screen_running_is_refused_with_the_command_that_starts_one(self):
        out = self._ask(lambda: _proc("screen: not running", 0))
        self.assertFalse(out["ok"])
        self.assertIn("computer-use screen start", out["error"])

    def test_a_hermes_without_bot_screen_support_is_refused(self):
        out = self._ask(lambda: _proc("", 1, ""))
        self.assertFalse(out["ok"])
        self.assertIn("no Bot Screen support", out["error"])

    def test_a_status_call_that_raises_refuses_rather_than_assuming_a_screen(self):
        def boom():
            raise OSError("hermes not on PATH")
        out = self._ask(boom)
        self.assertFalse(out["ok"])
        self.assertIn("could not read the screen status", out["error"])


class WhatTheUserIsTold(unittest.TestCase):
    def test_the_entry_carries_the_reason_the_command_and_the_limit(self):
        entry = takeover.compose("marlow", "Marlow", "the site wants a 2FA code",
                                 "booking the Lisbon flight", "retry the checkout")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("2FA code", entry["title"])
        self.assertIn("booking the Lisbon flight", entry["summary"])
        self.assertIn("hermes -p marlow computer-use screen open", entry["summary"])
        self.assertIn("retry the checkout", entry["summary"])

    def test_it_says_plainly_that_the_bot_will_not_resume_on_its_own(self):
        """Resuming on hand-back is unbuilt. Implying otherwise is the promise to avoid."""
        entry = takeover.compose("marlow", "Marlow", "needs a login", "", "")
        self.assertIn("will not pick this up by itself", entry["summary"])

    def test_the_bot_is_told_not_to_ask_for_the_password(self):
        """The user types it on the Bot's screen, where the lease keeps it out of the Bot's frames."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), profiles=("marlow",))
            out = takeover.request({"hermes_root": str(root), "from": "marlow",
                                    "reason": "needs a login"}, runner=lambda: _proc())
        self.assertIn("do not ask for their password", out["note"].lower().replace("—", "-"))
        self.assertIn("✋", out["note"])

    def test_a_reason_is_flattened_and_bounded(self):
        """It reaches an email subject line and a journal heading."""
        entry = takeover.compose("m", "M", "line one\n\nline two\x00", "", "")
        self.assertNotIn("\n", entry["title"])
        self.assertNotIn("\x00", entry["title"])
        self.assertLessEqual(len(takeover.clean("x" * 900, takeover.MAX_REASON)), takeover.MAX_REASON)


class TheJournalIsWhatNotifies(unittest.TestCase):
    """A blocked entry is already what mails the user and what the waiting queue reads."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = make_root(Path(self.tmp.name), profiles=("marlow",))

    def test_a_blocked_entry_is_pushed_so_the_user_is_mailed(self):
        with mock.patch.object(takeover.journal, "journaling_enabled", return_value=True), \
             mock.patch.object(takeover.journal, "operate",
                               return_value={"ok": True, "notified": {"sent": True}}) as op:
            out = takeover.request({"hermes_root": str(self.root), "from": "marlow",
                                    "reason": "needs a login"}, runner=lambda: _proc())
        self.assertTrue(out["journal"]["written"])
        self.assertEqual(op.call_args[0][0]["status"], "blocked")
        self.assertEqual(op.call_args[0][0]["action"], "add")

    def test_a_journal_that_is_off_does_not_fail_the_ask(self):
        """The user still gets the answer in chat; losing the mail must not lose the request."""
        with mock.patch.object(takeover.journal, "journaling_enabled", return_value=False):
            out = takeover.request({"hermes_root": str(self.root), "from": "marlow",
                                    "reason": "needs a login"}, runner=lambda: _proc())
        self.assertTrue(out["ok"])
        self.assertFalse(out["journal"]["written"])

    def test_a_journal_that_raises_does_not_fail_the_ask(self):
        with mock.patch.object(takeover.journal, "journaling_enabled", return_value=True), \
             mock.patch.object(takeover.journal, "operate", side_effect=RuntimeError("disk full")):
            out = takeover.request({"hermes_root": str(self.root), "from": "marlow",
                                    "reason": "needs a login"}, runner=lambda: _proc())
        self.assertTrue(out["ok"])
        self.assertIn("disk full", out["journal"]["reason"])


class TheManifestIsTrue(unittest.TestCase):
    def test_the_tool_is_declared_and_the_schema_matches(self):
        import yaml as y
        manifest = y.safe_load((Path(forge.__file__).parent / "plugin.yaml").read_text(encoding="utf-8"))
        self.assertIn("request_takeover", manifest["provides_tools"])
        import schemas
        self.assertEqual(schemas.REQUEST_TAKEOVER["name"], "request_takeover")
        self.assertEqual(schemas.REQUEST_TAKEOVER["parameters"]["required"], ["reason"])


if __name__ == "__main__":
    unittest.main()
