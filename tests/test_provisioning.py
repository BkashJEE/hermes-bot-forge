"""Issue #23 regressions. No real services, credentials or model calls are used."""
import copy
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import forge
import schemas
import team
import tools
import yaml


class ModelToolBoundary(unittest.TestCase):
    def test_route_is_exposed_for_agent_lead_and_member(self):
        props = schemas.CREATE_TEAM["parameters"]["properties"]
        for model in (schemas.CREATE_AGENT["parameters"]["properties"]["model"],
                      props["lead"]["properties"]["model"],
                      props["members"]["items"]["properties"]["model"]):
            self.assertEqual(model["required"], ["default", "provider"])
            self.assertFalse(model["additionalProperties"])
            self.assertEqual(set(model["properties"]), {"default", "provider", "base_url", "api_mode"})

    def test_invalid_explicit_routes_do_not_launch_a_process_or_echo_values(self):
        invalid = [None, {}, "worker", [], 1, {"default": "worker"},
                   {"default": " ", "provider": "p"}, {"default": "w", "provider": 1},
                   {"default": "w", "provider": "p", "base_url": []},
                   {"default": "w", "provider": "p", "api_key": "DO_NOT_ECHO"}]
        for model in invalid:
            with self.subTest(model_type=type(model).__name__), patch.object(tools.subprocess, "run", return_value=CompletedProcess([], 0, '{"ok":true}', "")) as run:
                result = json.loads(tools.create_agent({"role": "Writer", "model": model}))
                self.assertFalse(result["ok"])
                self.assertNotIn("DO_NOT_ECHO", json.dumps(result))
                run.assert_not_called()

    def test_team_validates_all_routes_before_building_any_member(self):
        for bad_part in ("lead", "member"):
            args = {"lead": {"role": "Lead"}, "members": [{"role": "First"}, {"role": "Second"}]}
            (args["lead"] if bad_part == "lead" else args["members"][1])["model"] = {}
            with self.subTest(part=bad_part), patch.object(tools.subprocess, "run", return_value=CompletedProcess([], 0, '{"ok":true}', "")) as run:
                result = json.loads(tools.create_team(args))
                self.assertFalse(result["ok"])
                run.assert_not_called()

    def test_agent_wrapper_forwards_route_and_keeps_omission(self):
        route = {"default": "worker", "provider": "p", "base_url": "http://localhost:1/v1",
                 "api_mode": "chat_completions"}
        for fields in ({}, {"model": route}):
            args = {"role": "Writer", **fields}
            original = copy.deepcopy(args)
            with patch.object(tools, "hermes_root", return_value=Path("/isolated")), \
                    patch.object(tools, "launch_profile", return_value="manager"), \
                    patch.object(tools.subprocess, "run", return_value=CompletedProcess([], 0, '{"ok":true}', '')) as run:
                self.assertTrue(json.loads(tools.create_agent(args))["ok"])
                spec = json.loads(run.call_args.kwargs["input"])
                self.assertEqual(spec.get("model"), fields.get("model"))
                self.assertEqual("model" in spec, "model" in fields)
                self.assertEqual(spec["launch_profile"], "manager")
                self.assertEqual(args, original)

    def test_team_wrapper_forwards_each_route_without_inventing_a_default(self):
        args = {"lead": {"model": {"default": "lead-model", "provider": "a"}},
                "members": [{"model": {"default": "worker-model", "provider": "b"}}, {"role": "Inherited"}]}
        with patch.object(tools, "hermes_root", return_value=Path("/isolated")), \
                patch.object(tools, "launch_profile", return_value="manager"), \
                patch.object(tools.subprocess, "run", return_value=CompletedProcess([], 0, '{"ok":true}', '')) as run:
            self.assertTrue(json.loads(tools.create_team(args))["ok"])
            spec = json.loads(run.call_args.kwargs["input"])
            self.assertEqual(spec["lead"], args["lead"])
            self.assertEqual(spec["members"], args["members"])
            self.assertNotIn("model", spec["members"][1])


class GatewayTopology(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "custom-hermes-root"
        self.profile = self.root / "profiles" / "quill"
        self.profile.mkdir(parents=True)
        forge.dump_yaml(self.root / "config.yaml", {})
        forge.dump_yaml(self.profile / "config.yaml", {})
        self.records = {}
        self.control = types.ModuleType("gateway.control_socket")
        self.control.identify_gateway = Mock(side_effect=lambda home: copy.deepcopy(self.records.get(str(home))))
        self.control.rescan_gateway_profiles = Mock(return_value=None)
        gateway = types.ModuleType("gateway")
        gateway.__path__ = []
        gateway.control_socket = self.control
        self.modules = patch.dict(sys.modules, {"gateway": gateway, "gateway.control_socket": self.control})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        runner = patch.object(forge, "run")
        self.run = runner.start()
        self.addCleanup(runner.stop)

    def record(self, home, names):
        return {"protocol": 1, "kind": "hermes-gateway", "pid": 42,
                "hermes_home": str(home), "served_profiles": names}

    def provision(self, enabled=True):
        return forge.provision_gateway(self.root, "quill", {"install_gateway": enabled})

    def assert_no_service_changes(self):
        self.run.assert_not_called()

    def test_already_served_without_profile_pid_file(self):
        self.records[str(self.root)] = self.record(self.root, ["default", "quill"])
        self.assertEqual(self.provision(), "served by host gateway")
        self.assert_no_service_changes()
        self.control.rescan_gateway_profiles.assert_not_called()
        self.assertFalse((self.profile / "gateway.pid").exists())

    def test_live_roster_wins_over_stale_config(self):
        for value in (True, False, None):
            with self.subTest(value=value):
                forge.dump_yaml(self.root / "config.yaml", {"gateway": {"multiplex_profiles": value}})
                self.records[str(self.root)] = self.record(self.root, ["default", "quill"])
                self.assertEqual(self.provision(), "served by host gateway")
        self.assert_no_service_changes()

    def test_hot_rescan_then_fresh_identity_proves_serving(self):
        self.records[str(self.root)] = self.record(self.root, ["default"])
        def rescan(home):
            self.records[str(home)]["served_profiles"].append("quill")
            return {"served_profiles": ["default", "quill"]}
        self.control.rescan_gateway_profiles.side_effect = rescan
        self.assertEqual(self.provision(), "served by host gateway")
        self.control.rescan_gateway_profiles.assert_called_once_with(self.root)
        self.assert_no_service_changes()

    def test_ack_without_fresh_served_record_stays_pending(self):
        self.records[str(self.root)] = self.record(self.root, ["default"])
        self.control.rescan_gateway_profiles.return_value = {"served_profiles": ["default", "quill"]}
        self.assertTrue(self.provision().startswith("pending:"))
        self.assertEqual(self.control.rescan_gateway_profiles.call_count, 1)
        self.assert_no_service_changes()

    def test_gateway_disappearing_after_rescan_is_not_reported_served(self):
        self.records[str(self.root)] = self.record(self.root, ["default"])
        self.control.rescan_gateway_profiles.side_effect = lambda home: self.records.clear()
        self.assertTrue(self.provision().startswith("pending:"))
        self.assert_no_service_changes()

    def test_rescan_exception_does_not_trigger_install(self):
        self.records[str(self.root)] = self.record(self.root, ["default"])
        self.control.rescan_gateway_profiles.side_effect = RuntimeError("unsupported")
        self.assertTrue(self.provision().startswith("pending:"))
        self.assert_no_service_changes()

    def test_native_identity_client_without_rescan_can_confirm_existing_serving(self):
        del self.control.rescan_gateway_profiles
        self.records[str(self.root)] = self.record(self.root, ["default", "quill"])
        self.assertEqual(self.provision(), "served by host gateway")
        self.assert_no_service_changes()

    def test_native_identity_client_without_rescan_leaves_unserved_pending(self):
        del self.control.rescan_gateway_profiles
        self.records[str(self.root)] = self.record(self.root, ["default"])
        self.assertTrue(self.provision().startswith("pending:"))
        self.assert_no_service_changes()

    def test_no_host_even_with_explicit_multiplex_flag_stays_pending(self):
        forge.dump_yaml(self.root / "config.yaml", {"gateway": {"multiplex_profiles": True}})
        self.assertTrue(self.provision().startswith("pending:"))
        self.assert_no_service_changes()

    def test_stale_state_file_is_not_liveness(self):
        (self.root / "gateway_state.json").write_text(json.dumps(self.record(self.root, ["default", "quill"])))
        (self.profile / "gateway.pid").write_text("42")
        self.assertTrue(self.provision().startswith("pending:"))
        self.assert_no_service_changes()

    def test_unavailable_client_is_not_permission_for_a_legacy_install(self):
        with patch.dict(sys.modules, {"gateway": None, "gateway.control_socket": None}):
            self.assertTrue(self.provision().startswith("pending:"))
        self.assert_no_service_changes()

    def test_invalid_identity_never_proves_readiness(self):
        valid = self.record(self.root, ["default", "quill"])
        bad = [None, [], {}, {**valid, "protocol": True}, {**valid, "protocol": 99}, {**valid, "kind": "hermes-serve"},
               {**valid, "pid": True}, {**valid, "pid": 0}, {**valid, "hermes_home": "/other-root"},
               {**valid, "served_profiles": "quill"}, {**valid, "served_profiles": [1]}]
        for value in bad:
            with self.subTest(value=value):
                self.records[str(self.root)] = value
                self.assertTrue(self.provision().startswith("pending:"))
        self.assert_no_service_changes()
        self.control.rescan_gateway_profiles.assert_not_called()

    def test_identify_error_is_not_interpreted_as_legacy_mode(self):
        self.control.identify_gateway.side_effect = RuntimeError("DO_NOT_ECHO")
        result = self.provision()
        self.assertTrue(result.startswith("pending:"))
        self.assertNotIn("DO_NOT_ECHO", result)
        self.assert_no_service_changes()

    def test_named_profile_can_own_the_host_gateway(self):
        home = self.root / "profiles" / "manager"
        home.mkdir()
        forge.dump_yaml(home / "config.yaml", {})
        self.records[str(home)] = self.record(home, ["default", "manager"])
        def rescan(owner):
            self.records[str(owner)]["served_profiles"].append("quill")
        self.control.rescan_gateway_profiles.side_effect = rescan
        self.assertEqual(self.provision(), "served by host gateway")
        self.control.rescan_gateway_profiles.assert_called_once_with(home)
        self.assert_no_service_changes()

    def test_explicitly_standalone_other_gateway_is_not_rescanned_as_host(self):
        home = self.root / "profiles" / "other"
        home.mkdir()
        forge.dump_yaml(home / "config.yaml", {"gateway": {"standalone": True}})
        self.records[str(home)] = self.record(home, ["other"])
        self.assertTrue(self.provision().startswith("pending:"))
        self.control.rescan_gateway_profiles.assert_not_called()
        self.assert_no_service_changes()

    def test_parked_profile_is_not_unparked(self):
        marker = self.profile / "gateway.parked"
        marker.touch()
        self.records[str(self.root)] = self.record(self.root, ["default"])
        self.assertTrue(self.provision().startswith("parked:"))
        self.assertTrue(marker.exists())
        self.control.identify_gateway.assert_not_called()
        self.control.rescan_gateway_profiles.assert_not_called()
        self.assert_no_service_changes()

    def test_explicit_standalone_preserves_native_install_without_force(self):
        forge.dump_yaml(self.profile / "config.yaml", {"gateway": {"standalone": True}})
        self.run.return_value = CompletedProcess([], 0, "installed", "")
        self.assertEqual(self.provision(), "started")
        self.run.assert_called_once_with(self.root, "-p", "quill", "gateway", "install",
                                         "--start-now", "--start-on-login", check=False, timeout=120)

    def test_standalone_refusal_is_reported_without_forcing_or_retrying(self):
        forge.dump_yaml(self.profile / "config.yaml", {"gateway": {"standalone": True}})
        self.run.return_value = CompletedProcess([], 78, "", "native refusal")
        self.assertIn("not started: native refusal", self.provision())
        self.assertEqual(self.run.call_count, 1)

    def test_standalone_still_served_by_host_waits_for_detachment(self):
        forge.dump_yaml(self.profile / "config.yaml", {"gateway": {"standalone": True}})
        self.records[str(self.root)] = self.record(self.root, ["default", "quill"])
        self.assertTrue(self.provision().startswith("pending:"))
        self.assert_no_service_changes()

    def test_standalone_own_live_gateway_is_not_misreported_as_host_conflict(self):
        forge.dump_yaml(self.profile / "config.yaml", {"gateway": {"standalone": True}})
        self.records[str(self.profile)] = self.record(self.profile, ["quill"])
        self.assertEqual(self.provision(), "started")
        self.assert_no_service_changes()

    def test_standalone_takes_precedence_over_park_marker_without_removing_it(self):
        forge.dump_yaml(self.profile / "config.yaml", {"gateway": {"standalone": True}})
        marker = self.profile / "gateway.parked"
        marker.touch()
        self.run.return_value = CompletedProcess([], 0, "", "")
        self.assertEqual(self.provision(), "started")
        self.assertTrue(marker.exists())

    def test_disabled_setup_performs_no_probe_or_service_action(self):
        self.assertEqual(self.provision(enabled=False), "skipped")
        self.control.identify_gateway.assert_not_called()
        self.assert_no_service_changes()

    def test_windows_keeps_existing_skip(self):
        with patch.object(forge.os, "name", "nt"):
            self.assertEqual(self.provision(), "skipped")
        self.control.identify_gateway.assert_not_called()
        self.assert_no_service_changes()

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_profile_symlink_outside_root_is_not_probed(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        forge.dump_yaml(outside / "config.yaml", {})
        (self.root / "profiles" / "external").symlink_to(outside, target_is_directory=True)
        self.provision()
        homes = [c.args[0] for c in self.control.identify_gateway.call_args_list]
        self.assertNotIn(self.root / "profiles" / "external", homes)
        self.assert_no_service_changes()


class ForgeModelIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "profiles" / "manager").mkdir(parents=True)
        (self.root / "memories").mkdir()
        self.default_model = {"default": "root-model", "provider": "root-provider"}
        self.manager_model = {"default": "manager-model", "provider": "manager-provider", "api_mode": "responses"}
        forge.dump_yaml(self.root / "config.yaml", {"model": self.default_model})
        forge.dump_yaml(self.root / "profiles" / "manager" / "config.yaml", {"model": self.manager_model})
        self.settings = {"workspace_survey": False, "ack_reactions": False, "ack_tapback": False,
                         "journal_enabled": False, "suggest_connectors": False, "install_gateway": False}
        self.at_inference = []
        self.reply = (True, "Hello")
        runner = patch.object(forge, "run", side_effect=self.fake_run)
        self.run_mock = runner.start()
        self.addCleanup(runner.stop)
        chat = patch.object(forge, "bot_chat", side_effect=self.fake_chat)
        chat.start()
        self.addCleanup(chat.stop)
        process = patch.object(forge.subprocess, "run", return_value=CompletedProcess([], 0, "", ""))
        process.start()
        self.addCleanup(process.stop)

    def fake_run(self, root, *args, **kwargs):
        if args[:2] == ("profile", "create"):
            pdir = root / "profiles" / args[2]
            pdir.mkdir()
            forge.dump_yaml(pdir / "config.yaml", {"model": self.default_model})
        elif args[:2] == ("profile", "delete"):
            shutil.rmtree(root / "profiles" / args[-1])
        else:
            raise AssertionError(f"Unexpected real-work request: {args}")
        return CompletedProcess([], 0, "", "")

    def fake_chat(self, root, profile, message):
        self.at_inference.append((profile, forge.load_yaml(root / "profiles" / profile / "config.yaml")["model"]))
        return self.reply

    def spec(self, **extra):
        return {"hermes_root": str(self.root), "display_name": "Quill", "role": "Writer",
                "settings": self.settings, "launch_profile": "manager", **extra}

    def test_explicit_route_is_in_place_before_first_inference(self):
        route = {"default": "worker", "provider": "other", "base_url": "http://127.0.0.1:1/v1",
                 "api_mode": "chat_completions"}
        out = forge.forge(self.spec(model=route))
        self.assertTrue(out["ok"])
        self.assertEqual(self.at_inference, [("quill", route)])
        self.assertEqual(out["model"], "worker")

    def test_omitted_route_inherits_calling_profile_unchanged(self):
        self.assertTrue(forge.forge(self.spec())["ok"])
        self.assertEqual(self.at_inference, [("quill", self.manager_model)])

    def test_disabled_inheritance_keeps_existing_root_clone_model(self):
        self.settings["inherit_model"] = False
        self.assertTrue(forge.forge(self.spec())["ok"])
        self.assertEqual(self.at_inference, [("quill", self.default_model)])

    def test_explicit_route_wins_even_when_inheritance_disabled(self):
        self.settings["inherit_model"] = False
        route = {"default": "worker", "provider": "other"}
        self.assertTrue(forge.forge(self.spec(model=route))["ok"])
        self.assertEqual(self.at_inference, [("quill", route)])

    def test_configured_fallback_remains_explicit_and_reported(self):
        route = {"default": "worker", "provider": "other"}
        fallback = {"default": "fallback", "provider": "local"}
        self.settings["fallback_model"] = fallback
        def chat(root, profile, message):
            model = forge.load_yaml(root / "profiles" / profile / "config.yaml")["model"]
            self.at_inference.append((profile, model))
            return (False, "401 unauthorized") if len(self.at_inference) == 1 else (True, "Hello")
        with patch.object(forge, "bot_chat", side_effect=chat):
            out = forge.forge(self.spec(model=route))
        self.assertTrue(out["ok"])
        self.assertEqual(self.at_inference, [("quill", route), ("quill", fallback)])
        self.assertEqual(out["model"], "fallback")
        self.assertIn("fallback", out["warning"])

    def test_auth_pending_does_not_claim_an_introduction_happened(self):
        self.reply = (False, "401 unauthorized")
        out = forge.forge(self.spec())
        self.assertTrue(out["ok"])
        self.assertEqual(out["intro"], "")
        self.assertIn("sign-in", out["warning"])
        self.assertNotIn("already introduced", out["note"])

    def test_unknown_gateway_topology_never_requests_a_per_profile_service(self):
        self.settings["install_gateway"] = True
        with patch.dict(sys.modules, {"gateway": None, "gateway.control_socket": None}):
            out = forge.forge(self.spec())
        self.assertTrue(out["ok"])
        self.assertTrue(out["gateway"].startswith("pending:"))
        self.assertEqual(self.run_mock.call_count, 1)

    def test_gateway_setup_failure_preserves_created_profile(self):
        with patch.object(forge, "provision_gateway", side_effect=RuntimeError("diagnostic failed")):
            out = forge.forge(self.spec())
        self.assertTrue(out["ok"])
        self.assertTrue(out["gateway"].startswith("pending:"))
        self.assertTrue((self.root / "profiles" / "quill" / "config.yaml").exists())
        self.assertEqual(self.run_mock.call_count, 1)

    def test_team_routes_are_set_before_each_members_first_inference(self):
        lead = {"display_name": "Atlas", "role": "Lead", "model": {"default": "lead", "provider": "a"}}
        worker = {"display_name": "Quill", "role": "Writer", "model": {"default": "worker", "provider": "b"}}
        inherited = {"display_name": "Nova", "role": "Reviewer"}
        out = team.build_team({"hermes_root": str(self.root), "settings": self.settings,
                               "launch_profile": "manager", "lead": lead, "members": [worker, inherited]})
        self.assertTrue(out["ok"])
        self.assertEqual(self.at_inference, [("atlas", lead["model"]), ("quill", worker["model"]),
                                             ("nova", self.manager_model)])
        self.assertEqual({m["name"]: m["gateway"] for m in out["members"]},
                         {"atlas": "skipped", "quill": "skipped", "nova": "skipped"})

    def test_existing_team_lead_is_reused_not_recreated(self):
        out = team.build_team({"hermes_root": str(self.root), "settings": self.settings,
                               "lead_name": "default", "members": [{"display_name": "Quill", "role": "Writer"}]})
        self.assertTrue(out["ok"])
        self.assertEqual(len(self.at_inference), 1)
        self.assertEqual(out["lead"], "default")

    def test_team_preserves_gateway_pending_status_and_auth_warning(self):
        self.reply = (False, "401 unauthorized")
        with patch.object(forge, "provision_gateway", return_value="pending: no host verified"):
            out = team.build_team({"hermes_root": str(self.root), "settings": self.settings,
                                   "members": [{"display_name": "Quill", "role": "Writer"}]})
        self.assertTrue(out["ok"])
        self.assertTrue(out["members"][0]["gateway"].startswith("pending:"))
        self.assertIn("sign-in", out["members"][0]["warning"])
        self.assertNotIn("each Bot is alive", out["note"])


@unittest.skipIf(os.name == "nt", "POSIX fake CLI fixture; Windows skip covered separately")
class SubprocessConstruction(unittest.TestCase):
    """Real tool -> script -> CLI subprocesses, but the CLI is a local fixture, not Hermes."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "hermes-root"
        self.root.mkdir()
        forge.dump_yaml(self.root / "config.yaml", {"model": {"default": "parent", "provider": "parent-p"}})
        bindir = Path(self.tmp.name) / "bin"
        bindir.mkdir()
        cli = bindir / "hermes"
        cli.write_text(f"#!{sys.executable}\n" + FAKE_HERMES)
        cli.chmod(0o700)
        env = patch.dict(os.environ, {"PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")})
        env.start()
        self.addCleanup(env.stop)
        root = patch.object(tools, "hermes_root", return_value=self.root)
        root.start()
        self.addCleanup(root.stop)
        launcher = patch.object(tools, "launch_profile", return_value="default")
        launcher.start()
        self.addCleanup(launcher.stop)
        self.settings = {"workspace_survey": False, "ack_reactions": False, "ack_tapback": False,
                         "journal_enabled": False, "suggest_connectors": False, "install_gateway": False}

    def test_agent_model_survives_actual_wrapper_and_forge_subprocess(self):
        route = {"default": "worker", "provider": "worker-p", "api_mode": "responses"}
        out = json.loads(tools.create_agent({"display_name": "Quill", "role": "Writer", "model": route},
                                           settings=self.settings))
        self.assertTrue(out["ok"], out)
        self.assertEqual(json.loads(out["intro"]), route)
        self.assertEqual(out["gateway"], "skipped")

    def test_team_member_models_survive_actual_team_subprocess(self):
        members = [{"display_name": "Quill", "role": "Writer", "model": {"default": "writer", "provider": "w"}},
                   {"display_name": "Nova", "role": "Reviewer"}]
        out = json.loads(tools.create_team({"members": members}, settings=self.settings))
        self.assertTrue(out["ok"], out)
        self.assertEqual([(m["name"], m["model"], m["gateway"]) for m in out["members"]],
                         [("quill", "writer", "skipped"), ("nova", "parent", "skipped")])
        self.assertEqual(forge.load_yaml(self.root / "profiles" / "quill" / "config.yaml")["model"],
                         members[0]["model"])


FAKE_HERMES = r'''import json
import os
import shutil
import sys
from pathlib import Path
import yaml

root = Path(os.environ["HERMES_HOME"])
args = sys.argv[1:]
if args[:2] == ["profile", "create"]:
    profile = root / "profiles" / args[2]
    profile.mkdir(parents=True)
    shutil.copyfile(root / "config.yaml", profile / "config.yaml")
elif len(args) >= 3 and args[0] == "-p" and args[2] == "chat":
    cfg = yaml.safe_load((root / "profiles" / args[1] / "config.yaml").read_text())
    print(json.dumps(cfg["model"]))
else:
    raise SystemExit("Unexpected fixture command: " + repr(args))
'''


class AdvisoryGuidance(unittest.TestCase):
    def test_agent_and_team_guidance_offer_all_native_alternatives(self):
        for schema in (schemas.CREATE_AGENT, schemas.CREATE_TEAM):
            text = schema["description"].lower()
            for term in ("reuse", "skill", "delegation", "routine", "persistent", "authorized"):
                self.assertIn(term, text)
            self.assertNotIn("no questions", text)
            self.assertNotIn("do not ask the user questions first", text)

    def test_skill_has_no_forced_creation_or_fixed_team_headcount(self):
        text = (ROOT / "skills" / "bot-forge" / "SKILL.md").read_text()
        self.assertNotIn("**Zero questions.**", text)
        self.assertNotIn("plus 2-4 specialists", text)
        self.assertIn("Only justified, authorized NEW profiles", text)
        self.assertIn("not security sandboxes", text)


if __name__ == "__main__":
    unittest.main()
