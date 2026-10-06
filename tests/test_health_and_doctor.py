"""Reporting on an install: health checks, sandboxes, gateways, Bot Screen.

Split out of tests/test_forge.py, which had grown past 2,300 lines; the shared helpers
and the sys.path setup Hermes-style imports need live in tests/support.py.
"""
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from support import forge, make_root, yaml


class Health(unittest.TestCase):
    def _bot(self, root, name, title, soul):
        d = root / "profiles" / name
        (d / "cron").mkdir(parents=True)
        (d / "config.yaml").write_text(yaml.safe_dump({"model": {"default": "m"}}))
        (d / "profile.yaml").write_text(yaml.safe_dump({"ui_meta": {"hermes-bots": {"title": title}}}))
        (d / "SOUL.md").write_text(soul)
        return d

    def test_single_bot_filter_returns_only_that_bot(self):
        import health
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            self._bot(root, "alpha", "Alpha", "# Alpha\n\nYou are **Alpha**.\n\n## Ask first\n- x")
            self._bot(root, "zeta", "Zeta", "# Zeta\n\nYou are **Zeta**.")
            health._gateways = lambda root: {}
            out = health.check({"hermes_root": str(root), "name": "Zeta"})
            self.assertEqual([b["name"] for b in out["report"]], ["zeta"])

    def test_frequent_routine_is_flagged(self):
        import json as _json
        import health
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = self._bot(root, "alpha", "Alpha", "# Alpha\n\nYou are **Alpha**.\n\n## Ask first\n- x")
            (d / "cron" / "jobs.json").write_text(_json.dumps({"jobs": [
                {"id": "j1", "name": "poll", "schedule": {"kind": "interval", "minutes": 10}, "enabled": True}]}))
            bot = health.check_bot(d, {}, 0)
            self.assertEqual(bot["routines"][0]["runs_per_day"], 144.0)
            self.assertTrue(any("144" in f for f in bot["flags"]))

    def test_runs_per_day_estimates(self):
        self.assertEqual(forge.runs_per_day("every 15m"), 96)
        self.assertAlmostEqual(forge.runs_per_day("0 9 * * 1-5"), 5 / 7)
        self.assertEqual(forge.runs_per_day("0 7,18 * * *"), 2)
        self.assertTrue(forge.check_routine({"schedule": "*/5 * * * *"}))
        self.assertFalse(forge.check_routine({"schedule": "*/5 * * * *", "allow_frequent": True}))


class Sandbox(unittest.TestCase):
    def test_unknown_sandbox_is_rejected(self):
        self.assertIn("unknown sandbox", forge.sandbox_error("vm"))
        self.assertEqual(forge.sandbox_error("local"), "")
        self.assertEqual(forge.sandbox_error(""), "")

    def test_missing_backend_is_refused_with_a_way_out(self):
        import doctor
        from unittest import mock
        with mock.patch.object(doctor, "sandbox_backends", return_value={}):
            msg = forge.sandbox_error("docker")
        self.assertIn("not installed", msg)
        self.assertIn("local", msg)

    def test_unusable_backend_reports_its_hint(self):
        import doctor
        from unittest import mock
        with mock.patch.object(doctor, "sandbox_backends",
                               return_value={"docker": {"usable": False, "hint": "daemon is down"}}):
            self.assertEqual(forge.sandbox_error("docker"), "daemon is down")
        with mock.patch.object(doctor, "sandbox_backends", return_value={"docker": {"usable": True, "hint": ""}}):
            self.assertEqual(forge.sandbox_error("docker"), "")

    def test_forge_refuses_before_creating_the_profile(self):
        import doctor
        from unittest import mock
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            with mock.patch.object(doctor, "sandbox_backends", return_value={}):
                out = forge.forge({"hermes_root": str(root), "role": "Coder", "display_name": "Kairo",
                                   "one_job": "writes code", "soul_md": "# Kairo\n", "sandbox": "docker"})
            self.assertFalse(out["ok"])
            self.assertFalse(out["rolled_back"])
            self.assertEqual(list((root / "profiles").iterdir()), [])


class HealthSandbox(unittest.TestCase):
    def _bot(self, root, cfg):
        import yaml as y
        d = root / "profiles" / "alpha"
        (d / "cron").mkdir(parents=True)
        (d / "config.yaml").write_text(y.safe_dump(cfg))
        (d / "profile.yaml").write_text(y.safe_dump({"ui_meta": {"hermes-bots": {"title": "Alpha"}}}))
        (d / "SOUL.md").write_text("# Alpha\n\nYou are **Alpha**.\n\n## Ask first\n- x")
        return d

    def test_shell_bot_without_a_sandbox_is_flagged(self):
        import health
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = self._bot(root, {"platform_toolsets": {"cli": ["terminal", "web"]}})
            bot = health.check_bot(d, {}, 0)
            self.assertEqual(bot["sandbox"], "local")
            self.assertTrue(any("directly on this machine" in f for f in bot["flags"]))

    def test_sandboxed_bot_is_not_flagged(self):
        import health
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = self._bot(root, {"platform_toolsets": {"cli": ["terminal"]}, "terminal": {"backend": "docker"}})
            bot = health.check_bot(d, {}, 0)
            self.assertEqual(bot["sandbox"], "docker")
            self.assertEqual(bot["flags"], [])

    def test_bot_without_shell_tools_is_not_flagged(self):
        import health
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = self._bot(root, {"platform_toolsets": {"cli": ["web", "file"]}})
            self.assertEqual(health.check_bot(d, {}, 0)["flags"], [])


class Doctor(unittest.TestCase):
    def _root(self, enabled: bool):
        import yaml as y
        t = tempfile.mkdtemp()
        root = make_root(Path(t))
        cfg = {"model": {"default": "m", "provider": "custom"}}
        if enabled:
            cfg["plugins"] = {"enabled": ["bot-forge"]}
        (root / "config.yaml").write_text(y.safe_dump(cfg))
        return root

    def test_not_enabled_anywhere_fails_with_the_enable_command(self):
        import doctor
        from unittest import mock
        with mock.patch.object(doctor, "_gateway_pids", return_value={}), \
                mock.patch.object(doctor, "sandbox_backends", return_value={}):
            out = doctor.check(self._root(enabled=False))
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], "fail")
        self.assertTrue(any("plugins enable bot-forge" in s for s in out["next_steps"]))

    def test_stale_gateway_is_reported_with_a_restart_step(self):
        import doctor
        from unittest import mock
        root = self._root(enabled=True)
        with mock.patch.object(doctor, "_gateway_pids", return_value={"default": 123}), \
                mock.patch.object(doctor, "_proc_start", return_value=0.0), \
                mock.patch.object(doctor, "_code_mtime", return_value=time.time()), \
                mock.patch.object(doctor, "sandbox_backends", return_value={}):
            out = doctor.check(root)
        gateway = next(c for c in out["checks"] if c["check"] == "gateway")
        self.assertEqual(gateway["status"], "fail")
        self.assertIn("hermes gateway restart", out["next_steps"])

    def test_healthy_install_passes(self):
        import doctor
        from unittest import mock
        root = self._root(enabled=True)
        with mock.patch.object(doctor, "_gateway_pids", return_value={"default": 123}), \
                mock.patch.object(doctor, "_proc_start", return_value=time.time()), \
                mock.patch.object(doctor, "_code_mtime", return_value=0.0), \
                mock.patch.object(doctor, "sandbox_backends", return_value={"docker": {"usable": True, "hint": ""}}):
            out = doctor.check(root)
        self.assertTrue(out["ok"])
        self.assertEqual(out["next_steps"], [])
        self.assertIn("docker", next(c for c in out["checks"] if c["check"] == "sandboxes")["detail"])
        self.assertIn("Bot Forge doctor", doctor.render(out))



class GatewayReporting(unittest.TestCase):
    """What create_agent claims about the gateway has to be what happened."""

    def test_the_multiplexer_is_not_reported_as_a_started_service(self):
        """Real output from `hermes -p <bot> gateway install` on a multiplexed host: exit 0,
        nothing installed. Calling that "started" put a service in the result that did not exist."""
        real = ("A host gateway already serves this profile.\n"
                "  (HERMES_HOME outside profiles/) needs --force:  hermes -p ruthcfo gateway "
                "install --force\n\n  Temporary compatibility path while multiplexing gaps are "
                "closed: set gateway.standalone: true")
        self.assertEqual(forge.gateway_state(0, real), "served by the host gateway")

    def test_a_real_install_still_reads_as_started(self):
        self.assertEqual(
            forge.gateway_state(0, "Installed hermes-gateway-quill.service and started it"),
            "started")

    def test_a_failure_is_never_dressed_up(self):
        self.assertEqual(forge.gateway_state(1, "permission denied"), "not started")
        self.assertEqual(forge.gateway_state(2, ""), "not started")


class BotScreenPreflight(unittest.TestCase):
    """A screen this host cannot give is refused before a half-usable Bot exists.

    NOT VERIFIED ON REAL HARDWARE — the macOS and Windows cases below patch `sys.platform` and
    `os.name`, so they prove *this* code refuses, not that Hermes behaves on those hosts the way
    its Bot Screen documentation says. Everything here was developed and exercised on Linux.
    Before anyone claims support for a Mac or Windows gateway, run a real one: confirm the pane is
    genuinely absent, confirm `computer-use screen status` says what we expect, and confirm nothing
    offers the user's own display as a substitute. Until then this refusal is the safe default,
    deliberately chosen over granting computer_use and hoping.
    """

    def _probe(self, driver_out="cua-driver: installed at /x (0.21.0)", screen_out="installed, not running",
               driver_rc=0, screen_rc=0):
        """Stand in for the two `hermes computer-use` probes screen_error runs."""

        def fake_run(root, *args, **kwargs):
            if args[:2] == ("computer-use", "status"):
                return subprocess.CompletedProcess(args, driver_rc, driver_out, "")
            return subprocess.CompletedProcess(args, screen_rc, screen_out, "")
        return fake_run

    def test_not_asking_for_one_is_never_an_error(self):
        self.assertEqual(forge.screen_error(Path("/x"), False), "")

    def test_a_ready_linux_host_passes(self):
        self.addCleanup(setattr, forge, "run", forge.run)
        forge.run = self._probe()
        root = Path("/x")
        with mock.patch.object(forge.sys, "platform", "linux"), \
             mock.patch.object(forge.os, "name", "posix"):
            self.assertEqual(forge.screen_error(root, True), "")

    def test_macos_is_refused_rather_than_pointed_at_your_own_display(self):
        """The dangerous silent behaviour: granting computer_use where the only screen is the user's."""
        with mock.patch.object(forge.sys, "platform", "darwin"):
            problem = forge.screen_error(Path("/x"), True)
        self.assertIn("Linux gateway host", problem)
        self.assertIn("your own display", problem)

    def test_windows_is_refused_too(self):
        # Build the Path before patching os.name: pathlib picks its flavour at construction, so a
        # Path() created while os.name == "nt" raises NotImplementedError on Linux under 3.11.
        root = Path("/x")
        with mock.patch.object(forge.os, "name", "nt"):
            self.assertIn("Linux gateway host", forge.screen_error(root, True))

    def test_a_host_without_the_driver_says_so(self):
        self.addCleanup(setattr, forge, "run", forge.run)
        forge.run = self._probe(driver_out="cua-driver: not installed", driver_rc=1)
        root = Path("/x")
        with mock.patch.object(forge.sys, "platform", "linux"), \
             mock.patch.object(forge.os, "name", "posix"):
            problem = forge.screen_error(root, True)
        self.assertIn("cua-driver", problem)
        self.assertIn("hermes computer-use install", problem)

    def test_a_host_missing_the_packages_relays_what_it_said(self):
        self.addCleanup(setattr, forge, "run", forge.run)
        forge.run = self._probe(screen_out="Bot Desktop: not installed. apt-get install -y tigervnc-standalone-server xfce4-panel")
        root = Path("/x")
        with mock.patch.object(forge.sys, "platform", "linux"), \
             mock.patch.object(forge.os, "name", "posix"):
            problem = forge.screen_error(root, True)
        self.assertIn("TigerVNC", problem)
        self.assertIn("hermes computer-use screen install", problem)
        self.assertIn("tigervnc-standalone-server", problem, "relay what the host actually reported")

    def test_an_older_hermes_without_the_command_is_explained(self):
        self.addCleanup(setattr, forge, "run", forge.run)
        forge.run = self._probe(screen_out="", screen_rc=2)
        root = Path("/x")
        with mock.patch.object(forge.sys, "platform", "linux"), \
             mock.patch.object(forge.os, "name", "posix"):
            self.assertIn("no Bot Screen support", forge.screen_error(root, True))


