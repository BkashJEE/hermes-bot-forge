"""Handing work from one Bot to another: ownership, the record, both journals, the in-flight list.

The receiving Bot's turn is the real `hermes -p <bot> chat` and is mocked at forge.run; everything
around it — the record, the journals, the outcome read from the acknowledgement — is real.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import forge, journal, make_root, tools, yaml

import handoff  # noqa: E402  (support.py put the plugin on sys.path)
import health  # noqa: E402


def _bot(root, name, title, journaling=True):
    d = root / "profiles" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.yaml").write_text(yaml.safe_dump({"model": {"default": "m"}}))
    (d / "profile.yaml").write_text(yaml.safe_dump({"ui_meta": {"hermes-bots": {"title": title}}}))
    (d / "SOUL.md").write_text(f"# {title} — Bot\n\nYou are **{title}**.\n")
    if journaling:
        journal.enable_journal(d)
    return d


def _reply(text):
    """A forge.run stand-in that records the chat call and answers with `text`."""
    calls = []

    def fake(root, *args, **kw):
        calls.append((args, kw))
        return subprocess.CompletedProcess(["hermes", *args], 0, text, "")

    return fake, calls


class Handoff(unittest.TestCase):
    def _spec(self, root, **extra):
        return {"to": "nova", "task": "Draft Thursday's launch thread", "from": "marshal",
                "context": "Audience: indie devs. Three posts, the hook first.", "hermes_root": str(root), **extra}

    def test_completed_handoff_is_recorded_and_journaled_on_both_sides(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            _bot(root, "marshal", "Marshal")
            nova = _bot(root, "nova", "Nova")
            fake, calls = _reply("✅ Drafted three posts in drafts/thread.md.")
            with mock.patch.object(forge, "run", side_effect=fake):
                out = handoff.handoff(self._spec(root))
            self.assertTrue(out["ok"], out)
            self.assertEqual(out["status"], "completed")
            self.assertEqual(out["owner"], "nova")
            self.assertTrue(out["id"].startswith("hf-"))
            # the turn ran in Nova's own Bot Chat, as Nova, not in the caller's session
            chat = next(a for a, _k in calls if "chat" in a)
            self.assertEqual(chat[:2], ("-p", "nova"))
            message = chat[-1]
            self.assertIn("Handoff from @marshal (Marshal)", message)
            self.assertIn("Draft Thursday's launch thread", message)
            self.assertIn("indie devs", message)
            self.assertIn(f"handoff:{out['id']}", message)
            # the record lives with the Bot that owns the work
            record = json.loads((nova / "handoffs" / f"{out['id']}.json").read_text())
            self.assertEqual(record["status"], "completed")
            self.assertEqual(record["from"], "marshal")
            self.assertIn("Drafted three posts", record["reply"])
            # both journals know
            self.assertTrue(out["journal"]["to"]["written"], out["journal"])
            self.assertTrue(out["journal"]["from"]["written"], out["journal"])
            received = journal.read_entries(nova, {"query": "handoff from marshal"})
            self.assertEqual(received["count"], 1)
            self.assertIn("completed", received["entries"][0]["entry"])
            sent = journal.read_entries(root / "profiles" / "marshal", {"query": "handed off to nova"})
            self.assertEqual(sent["count"], 1)

    def test_outcome_is_read_from_the_acknowledgement(self):
        self.assertEqual(handoff.outcome("✅ done"), "completed")
        self.assertEqual(handoff.outcome("  ✋ I need you to approve the budget"), "needs_you")
        self.assertEqual(handoff.outcome("⚠️ the portal is down"), "blocked")
        self.assertEqual(handoff.outcome("⏳ scheduled for 9am"), "scheduled")
        self.assertEqual(handoff.outcome("Sure, here it is"), "replied")
        self.assertEqual(handoff.outcome(""), "sent")

    def test_a_handoff_that_needs_the_user_lands_in_the_waiting_queue(self):
        """✋ from the receiving Bot is the user's to answer, so the queue must show it without being told."""
        import waiting
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            _bot(root, "marshal", "Marshal")
            _bot(root, "nova", "Nova")
            fake, _calls = _reply("✋ The thread mentions pricing — approve the $49 figure before I post it.")
            with mock.patch.object(forge, "run", side_effect=fake):
                out = handoff.handoff(self._spec(root))
            self.assertEqual(out["status"], "needs_you")
            queue = waiting.waiting_on_user(root)
            self.assertEqual(queue["count"], 1)
            self.assertEqual(queue["items"][0]["bot"], "nova")
            self.assertIn("Handoff from Marshal", queue["items"][0]["title"])
            # and it is still in flight
            open_ = handoff.open_handoffs(root)
            self.assertEqual(open_["count"], 1)
            self.assertEqual(open_["items"][0]["status"], "needs_you")
            self.assertIn("Marshal → Nova", open_["summary"])

    def test_completed_handoffs_leave_the_in_flight_list(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            _bot(root, "marshal", "Marshal")
            _bot(root, "nova", "Nova")
            fake, _calls = _reply("✅ done")
            with mock.patch.object(forge, "run", side_effect=fake):
                handoff.handoff(self._spec(root))
            self.assertEqual(handoff.open_handoffs(root)["count"], 0)
            self.assertEqual(handoff.open_handoffs(root)["summary"], "no handoffs in flight")

    def test_check_agents_reports_handoffs_in_flight(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            _bot(root, "marshal", "Marshal")
            _bot(root, "nova", "Nova")
            fake, _calls = _reply("⚠️ Blocked: the drafts folder is read-only.")
            with mock.patch.object(forge, "run", side_effect=fake):
                handoff.handoff(self._spec(root))
            with mock.patch.object(health, "_gateways", return_value={}):
                report = health.check({"hermes_root": str(root)})
            self.assertEqual(report["handoffs_count"], 1)
            self.assertEqual(report["handoffs"][0]["to"], "nova")
            self.assertEqual(report["handoffs"][0]["status"], "blocked")
            self.assertIn("handoff in flight", report["summary"])
            self.assertIn("Marshal → Nova", report["summary"])

    def test_a_credential_in_the_context_is_refused_before_anything_is_sent(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            _bot(root, "marshal", "Marshal")
            nova = _bot(root, "nova", "Nova")
            fake, calls = _reply("✅ done")
            secret = "sk-proj-" + "Q" * 30
            with mock.patch.object(forge, "run", side_effect=fake):
                out = handoff.handoff(self._spec(root, context=f"use {secret} for the API"))
            self.assertFalse(out["ok"])
            self.assertIn("credential", out["error"])
            self.assertNotIn(secret, json.dumps(out))
            self.assertEqual(calls, [], "nothing may run when the context carries a secret")
            self.assertFalse((nova / "handoffs").exists())

    def test_refuses_the_root_profile_an_unknown_bot_and_itself(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            _bot(root, "nova", "Nova")
            with mock.patch.object(forge, "run", side_effect=AssertionError("must not run")):
                self.assertFalse(handoff.handoff(self._spec(root, to="default"))["ok"])
                self.assertIn("no Bot named", handoff.handoff(self._spec(root, to="ghost"))["error"])
                self.assertIn("itself", handoff.handoff(self._spec(root, **{"from": "nova"}))["error"])
                self.assertIn("needs a task", handoff.handoff(self._spec(root, task="  "))["error"])

    def test_a_failed_turn_keeps_the_record_and_says_so(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            _bot(root, "marshal", "Marshal")
            nova = _bot(root, "nova", "Nova")

            def failing(root_, *args, **kw):
                return subprocess.CompletedProcess(["hermes", *args], 1, "", "model refused")

            with mock.patch.object(forge, "run", side_effect=failing):
                out = handoff.handoff(self._spec(root))
            self.assertFalse(out["ok"])
            self.assertIn("did not answer", out["error"])
            record = json.loads((nova / "handoffs" / f"{out['id']}.json").read_text())
            self.assertEqual(record["status"], "failed")
            # a failed handoff is still in flight: the user should see it went nowhere
            self.assertEqual(handoff.open_handoffs(root)["count"], 1)

    def test_a_bot_without_a_journal_still_gets_the_handoff(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            _bot(root, "marshal", "Marshal", journaling=False)
            _bot(root, "nova", "Nova", journaling=False)
            fake, _calls = _reply("✅ done")
            with mock.patch.object(forge, "run", side_effect=fake):
                out = handoff.handoff(self._spec(root))
            self.assertTrue(out["ok"], out)
            self.assertFalse(out["journal"]["to"]["written"])
            self.assertFalse(out["journal"]["from"]["written"])

    def test_the_receiving_bot_never_inherits_the_callers_secrets(self):
        """The same contract ask_agent has: the other Bot's turn gets network and config, never authority."""
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            _bot(root, "marshal", "Marshal")
            _bot(root, "nova", "Nova")
            fake, calls = _reply("✅ done")
            with mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://proxy.corp:3128", "SSH_AUTH_SOCK": "/run/agent.sock",
                                              "OPENAI_API_KEY": "sk-do-not-inherit", "HERMES_HOME": "/caller/profiles/x"}), \
                 mock.patch.object(forge, "run", side_effect=fake):
                handoff.handoff(self._spec(root))
            env = next(k["env"] for a, k in calls if "chat" in a)
            self.assertEqual(env["HTTPS_PROXY"], "http://proxy.corp:3128")
            self.assertEqual(env["HERMES_HOME"], str(root))
            self.assertNotIn("SSH_AUTH_SOCK", env)
            self.assertNotIn("OPENAI_API_KEY", env)

    def test_the_tool_identifies_the_sender_from_the_calling_profile(self):
        """`from` is never a tool argument: the calling profile is the sender, so a Bot cannot speak as another."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), profiles=("nova",))
            with mock.patch.object(tools, "hermes_root", return_value=root), \
                 mock.patch.object(tools, "launch_profile", return_value="marshal"), \
                 mock.patch.object(tools.subprocess, "run",
                                   return_value=subprocess.CompletedProcess([], 0, '{"ok": true}', "")) as run:
                tools.handoff_agent({"to": "nova", "task": "x", "from": "ceo"}, settings={})
            spec = json.loads(run.call_args.kwargs["input"])
            self.assertEqual(spec["from"], "marshal")
            self.assertEqual(Path(run.call_args.args[0][1]).name, "handoff.py")


if __name__ == "__main__":
    unittest.main()
