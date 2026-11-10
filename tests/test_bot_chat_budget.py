"""The introduction must not set a permanent iteration cap on the Bot Chat (#101)."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import forge


class BotChatBudget(unittest.TestCase):
    def _chat(self, *, existing, desktop, **kwargs):
        root = Path("unused-hermes-root")
        with mock.patch.object(forge, "run", return_value=subprocess.CompletedProcess(
                [], 0, "Hello", "")) as run, \
                mock.patch.object(forge, "has_bot_chat", return_value=existing), \
                mock.patch.object(forge, "bot_mode_install", return_value=desktop), \
                mock.patch.object(forge, "newest_session", return_value="new-session"):
            result = forge.bot_chat(root, "quill", "Introduce yourself", **kwargs)
        self.assertEqual(result, (True, "Hello"))
        return run.call_args_list

    def test_default_budget_is_inherited_on_creation_and_resume(self):
        for existing in (False, True):
            for desktop in (False, True):
                with self.subTest(existing=existing, desktop=desktop):
                    calls = self._chat(existing=existing, desktop=desktop)
                    self.assertNotIn("--max-turns", calls[0].args)
                    self.assertEqual(len(calls), 2 if desktop and not existing else 1)

    def test_none_explicitly_inherits_the_profile_budget(self):
        for existing, desktop in ((False, True), (False, False), (True, True)):
            with self.subTest(existing=existing, desktop=desktop):
                calls = self._chat(existing=existing, desktop=desktop, max_turns=None)
                self.assertNotIn("--max-turns", calls[0].args)

    def test_explicit_budget_and_launch_options_are_preserved(self):
        env = {"HERMES_HOME": "unused-hermes-root"}
        for existing, desktop in ((False, True), (False, False), (True, True)):
            for budget in (3, 90, 500):
                with self.subTest(existing=existing, desktop=desktop, budget=budget):
                    calls = self._chat(existing=existing, desktop=desktop, max_turns=budget,
                                       timeout=42, env=env, reading_only=True)
                    chat = calls[0]
                    self.assertEqual(chat.args.count("--max-turns"), 1)
                    self.assertEqual(chat.args[chat.args.index("--max-turns") + 1], str(budget))
                    self.assertIn("-t", chat.args)
                    self.assertEqual(chat.args[chat.args.index("-t") + 1], "web,vision")
                    self.assertEqual(chat.kwargs["timeout"], 42)
                    self.assertIs(chat.kwargs["env"], env)
                    self.assertFalse(chat.kwargs["check"])
                    if desktop and not existing:
                        self.assertIs(calls[1].kwargs["env"], env)
                        self.assertEqual(calls[1].args[1:],
                                         ("-p", "quill", "sessions", "rename", "new-session", "Bot Chat"))


if __name__ == "__main__":
    unittest.main()
