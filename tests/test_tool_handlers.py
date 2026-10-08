"""What the tool handlers do when things go wrong.

Coverage showed tools.py as the thinnest-tested module in the plugin, and the gaps were not
the happy paths — those are exercised end to end by the probes. They were the paths that run
when something has already failed: a creation that times out, a subprocess that prints
something other than JSON, a profile whose config.yaml will not parse.

Those are the ones worth having tests for, because they decide whether a user sees a reason or
a stack trace.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import make_root, tools, yaml


class CreateAgentFailures(unittest.TestCase):
    """create_agent shells out to forge.py. Everything about that can fail."""

    def _run(self, **patch):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            with mock.patch.object(tools, "hermes_root", return_value=root), \
                 mock.patch.object(tools, "launch_profile", return_value="default"), \
                 mock.patch.object(tools.subprocess, "run", **patch):
                return json.loads(tools.create_agent({"role": "writer"}, settings={}))

    def test_a_timeout_is_a_reason_not_a_traceback(self):
        out = self._run(side_effect=subprocess.TimeoutExpired(cmd="forge.py", timeout=900))
        self.assertFalse(out["ok"])
        self.assertIn("timed out", out["error"])

    def test_output_that_is_not_json_comes_back_as_the_error(self):
        """A crash in forge.py puts a traceback on stderr; the user should see it, not lose it."""
        out = self._run(return_value=subprocess.CompletedProcess(
            [], 1, "", "Traceback (most recent call last):\n  RuntimeError: no model configured"))
        self.assertFalse(out["ok"])
        self.assertIn("no model configured", out["error"])

    def test_a_banner_before_the_json_is_tolerated(self):
        """The CLI prints its own noise; the result starts at the first brace."""
        out = self._run(return_value=subprocess.CompletedProcess(
            [], 0, 'Hermes v0.21\nloading...\n{"ok": true, "name": "marlow"}', ""))
        self.assertTrue(out["ok"])
        self.assertEqual(out["name"], "marlow")

    def test_silence_is_reported_rather_than_read_as_success(self):
        out = self._run(return_value=subprocess.CompletedProcess([], 0, "", ""))
        self.assertFalse(out["ok"])


class ProfileInfo(unittest.TestCase):
    """list_agents is how an agent learns which Bots exist. It must survive a broken profile."""

    def _profile(self, tmp, name="quill", config="model:\n  default: m\n", meta=None, jobs=None):
        home = Path(tmp) / name
        home.mkdir(parents=True)
        (home / "config.yaml").write_text(config)
        if meta is not None:
            (home / "profile.yaml").write_text(meta)
        if jobs is not None:
            (home / "cron").mkdir()
            (home / "cron" / "jobs.json").write_text(jobs)
        return home

    def test_a_config_that_will_not_parse_still_yields_a_usable_entry(self):
        """One corrupt profile must not take the whole roster down with it."""
        with tempfile.TemporaryDirectory() as tmp:
            home = self._profile(tmp, config="model: [unclosed\n")
            info = tools._profile_info("quill", home)
            self.assertEqual(info["name"], "quill")
            self.assertEqual(info["display_name"], "quill")

    def test_the_bots_roster_title_wins_over_the_display_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta = yaml.safe_dump({"display_name": "Fallback",
                                   "ui_meta": {"hermes-bots": {"title": "Quill"}}})
            info = tools._profile_info("quill", self._profile(tmp, meta=meta))
            self.assertEqual(info["display_name"], "Quill")

    def test_a_hidden_bot_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta = yaml.safe_dump({"ui_meta": {"hermes-bots": {"hidden": True}}})
            info = tools._profile_info("quill", self._profile(tmp, meta=meta))
            self.assertTrue(info["hidden"])

    def test_a_malformed_ui_meta_block_is_ignored_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta = yaml.safe_dump({"ui_meta": {"hermes-bots": "not a mapping"}})
            info = tools._profile_info("quill", self._profile(tmp, meta=meta))
            self.assertEqual(info["display_name"], "quill")

    def test_routines_are_counted_in_both_shapes_jobs_json_takes(self):
        for jobs, expected in (('{"jobs": [{"id": 1}, {"id": 2}]}', 2), ('[{"id": 1}]', 1)):
            with self.subTest(jobs=jobs), tempfile.TemporaryDirectory() as tmp:
                info = tools._profile_info("quill", self._profile(tmp, jobs=jobs))
                self.assertEqual(info["routines"], expected)

    def test_no_routines_key_when_there_are_none(self):
        for jobs in (None, "[]", "not json at all"):
            with self.subTest(jobs=jobs), tempfile.TemporaryDirectory() as tmp:
                info = tools._profile_info("quill", self._profile(tmp, jobs=jobs))
                self.assertNotIn("routines", info)


class ListAgents(unittest.TestCase):
    def test_the_root_profile_is_listed_alongside_the_bots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), profiles=("quill", "marlow"))
            with mock.patch.object(tools, "hermes_root", return_value=root):
                agents = json.loads(tools.list_agents({}))["agents"]
            self.assertEqual([a["name"] for a in agents], ["default", "marlow", "quill"])

    def test_a_directory_without_a_config_is_not_a_bot(self):
        """profile-exports and stray folders live under profiles/ too."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), profiles=("quill",))
            (root / "profiles" / "not-a-bot").mkdir()
            with mock.patch.object(tools, "hermes_root", return_value=root):
                agents = json.loads(tools.list_agents({}))["agents"]
            self.assertEqual([a["name"] for a in agents], ["default", "quill"])

    def test_an_install_with_no_profiles_directory_still_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".hermes"
            root.mkdir()
            (root / "config.yaml").write_text("{}")
            with mock.patch.object(tools, "hermes_root", return_value=root):
                agents = json.loads(tools.list_agents({}))["agents"]
            self.assertEqual([a["name"] for a in agents], ["default"])


if __name__ == "__main__":
    unittest.main()
