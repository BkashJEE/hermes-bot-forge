"""Editing, copying, sharing, teaching and asking a Bot that already exists.

Split out of tests/test_forge.py, which had grown past 2,300 lines; the shared helpers
and the sys.path setup Hermes-style imports need live in tests/support.py.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import forge, make_root, manage, team, tools, yaml


class AskAgentEnvironment(unittest.TestCase):
    def test_profile_root_and_secrets_are_not_inherited(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), profiles=("kairo",))
            with mock.patch.object(tools, "hermes_root", return_value=root), \
                 mock.patch.dict(os.environ, {"HOME": "/different-user",
                                              "HERMES_HOME": "/caller/profiles/other",
                                              "PRIVATE_TOKEN": "do-not-inherit"}), \
                 mock.patch.object(tools.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "done", "")) as run:
                result = json.loads(tools.ask_agent({"name": "kairo", "message": "Review only"}))
            self.assertTrue(result["ok"])
            args, kwargs = run.call_args
            self.assertEqual(args[0][:3], ["hermes", "-p", "kairo"])
            self.assertEqual(kwargs["env"]["HERMES_HOME"], str(root))
            self.assertNotIn("PRIVATE_TOKEN", kwargs["env"])
            self.assertEqual(kwargs["env"]["HOME"], "/different-user")

    def test_the_bot_can_still_reach_the_network_and_its_vault(self):
        """An allowlist that is too narrow fails silently: the Bot simply cannot reach the model
        behind a proxy, or cannot find keys kept in 1Password or Bitwarden."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), profiles=("kairo",))
            carried = {"HTTPS_PROXY": "http://proxy.corp:3128", "NO_PROXY": "localhost",
                       "NODE_EXTRA_CA_CERTS": "/etc/ssl/corp.pem",
                       "XDG_CONFIG_HOME": "/home/u/.config"}
            with mock.patch.object(tools, "hermes_root", return_value=root), \
                 mock.patch.dict(os.environ, {**carried, "SSH_AUTH_SOCK": "/run/agent.sock",
                                              "OPENAI_API_KEY": "sk-do-not-inherit"}), \
                 mock.patch.object(tools.subprocess, "run",
                                   return_value=subprocess.CompletedProcess([], 0, "done", "")) as run:
                tools.ask_agent({"name": "kairo", "message": "Review only"})
            env = run.call_args.kwargs["env"]
            for key, value in carried.items():
                self.assertEqual(env.get(key), value, key)
            # reaching the network is not the same as carrying authority
            self.assertNotIn("SSH_AUTH_SOCK", env)
            self.assertNotIn("OPENAI_API_KEY", env)

    def test_the_account_name_travels_so_an_existing_login_is_found(self):
        """Reported from macOS (#43): without USER the Claude CLI saw no login at all.

        The account name is not a credential and opens nothing on its own, but a tool that
        already holds a login looks it up to find that login. Dropping it failed silently —
        ask_agent simply could not consult a Bot on a working Claude subscription.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), profiles=("kairo",))
            identity = {"USER": "bkash86", "LOGNAME": "bkash86", "USERNAME": "bkash86"}
            with mock.patch.object(tools, "hermes_root", return_value=root), \
                 mock.patch.dict(os.environ, identity), \
                 mock.patch.object(tools.subprocess, "run",
                                   return_value=subprocess.CompletedProcess([], 0, "done", "")) as run:
                tools.ask_agent({"name": "kairo", "message": "Review only"})
            env = run.call_args.kwargs["env"]
            for key, value in identity.items():
                self.assertEqual(env.get(key), value, key)


class Manage(unittest.TestCase):
    def _bot(self, root, name="quill", title="Quill"):
        d = root / "profiles" / name
        (d / "memories").mkdir(parents=True, exist_ok=True)
        (d / "config.yaml").write_text(yaml.safe_dump({"platform_toolsets": {"cli": ["web", "file"]}}))
        (d / "profile.yaml").write_text(yaml.safe_dump({"ui_meta": {"hermes-bots": {"title": title,
                                                                                    "shape": "blobatar:abc:sun"}}}))
        (d / "SOUL.md").write_text(f"# {title} — Writer\n\nYou are **{title}**, a writer.\n")
        return d

    def test_unknown_op_is_reported(self):
        self.assertIn("unknown op", manage.manage({"op": "nope"})["error"])

    def test_bot_lookup_by_title_and_refusal_of_root(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            self._bot(root)
            self.assertEqual(manage._require_bot(root, "Quill").name, "quill")
            with self.assertRaises(ValueError):
                manage._require_bot(root, "default")

    def test_update_appends_soul_and_backs_up(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            pdir = self._bot(root)
            out = manage.manage({"op": "update", "hermes_root": str(root), "name": "quill",
                                 "soul_append": "## Voice\nterse."})
            self.assertTrue(out["ok"], out)
            self.assertIn("soul", out["changed"])
            self.assertIn("terse.", (pdir / "SOUL.md").read_text())
            self.assertTrue(out["backups"]["SOUL.md"])

    def test_update_toolsets_keeps_base_and_adds(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            pdir = self._bot(root)
            out = manage.manage({"op": "update", "hermes_root": str(root), "name": "quill",
                                 "add_toolsets": ["image_gen"], "remove_toolsets": ["web"]})
            self.assertTrue(out["ok"], out)
            tools_now = yaml.safe_load((pdir / "config.yaml").read_text())["platform_toolsets"]["cli"]
            self.assertIn("image_gen", tools_now)
            self.assertIn("web", tools_now)  # base toolsets can't be removed

    def test_update_without_changes_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            self._bot(root)
            self.assertFalse(manage.manage({"op": "update", "hermes_root": str(root), "name": "quill"})["ok"])

    def test_hide_and_show_roundtrip(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            pdir = self._bot(root)
            manage.manage({"op": "hide", "hermes_root": str(root), "name": "quill"})
            meta = yaml.safe_load((pdir / "profile.yaml").read_text())
            self.assertTrue(meta["ui_meta"]["hermes-bots"]["hidden"])
            self.assertEqual(meta["_ui_meta_revisions"]["hermes-bots"], 1)
            manage.manage({"op": "show", "hermes_root": str(root), "name": "quill"})
            self.assertFalse(yaml.safe_load((pdir / "profile.yaml").read_text())["ui_meta"]["hermes-bots"]["hidden"])

    def test_delete_is_off_by_default_and_needs_exact_confirm(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            self._bot(root)
            off = manage.manage({"op": "delete", "hermes_root": str(root), "name": "quill", "confirm": "quill"})
            self.assertFalse(off["ok"])
            self.assertIn("disabled", off["error"])
            wrong = manage.manage({"op": "delete", "hermes_root": str(root), "name": "quill",
                                   "confirm": "nope", "settings": {"allow_delete": True}})
            self.assertFalse(wrong["ok"])
            self.assertIn("confirm", wrong["error"])
            self.assertTrue((root / "profiles" / "quill").exists())

    def test_delete_takes_a_real_backup_and_refuses_when_it_fails(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            self._bot(root)
            spec = {"op": "delete", "hermes_root": str(root), "name": "quill", "confirm": "quill",
                    "settings": {"allow_delete": True}}
            calls = []
            def record_export(s, r, st):
                calls.append(s)
                return {"ok": True, "path": "/x.tar.gz"}
            with mock.patch.object(manage, "op_export", side_effect=record_export), \
                    mock.patch.object(manage.forge, "run", side_effect=lambda root, *a, **k: calls.append(a)):
                out = manage.manage(spec)
            self.assertTrue(out["ok"])
            self.assertEqual(calls[0]["mode"], "backup")
            self.assertEqual(calls[1][:2], ("profile", "delete"))
            self.assertEqual(out["backup"], "/x.tar.gz")
            for failing in (lambda s, r, st: {"ok": False, "error": "scan BLOCK"},
                            mock.Mock(side_effect=RuntimeError("hermes died"))):
                with mock.patch.object(manage, "op_export", side_effect=failing), \
                        mock.patch.object(manage.forge, "run") as run:
                    out = manage.manage(spec)
                self.assertFalse(out["ok"])
                self.assertIn("NOT deleted", out["error"])
                self.assertIn("backup_before_delete", out["error"])
                run.assert_not_called()
            self.assertTrue((root / "profiles" / "quill").exists())

    def test_allow_secrets_is_operator_only(self):
        from unittest import mock
        fake = "sk-proj-" + "B" * 30
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = self._bot(root)
            (d / "SOUL.md").write_text(f"# Quill — Writer\n\nYou are **Quill**. Use {fake} for the API.\n")
            spec = {"op": "export", "hermes_root": str(root), "name": "quill", "allow_secrets": True}
            out = manage.manage(spec)
            self.assertFalse(out["ok"])
            self.assertIn("credential", out["error"])
            self.assertEqual(list((root / "profile-exports").glob("*")) if (root / "profile-exports").exists() else [], [])
            out = manage.manage({**spec, "settings": {"allow_secrets": True}})
            self.assertTrue(out["ok"])
            self.assertTrue(Path(out["path"]).exists())
            # the tool layer drops the argument before it reaches manage.py
            if tools is not None:
                with mock.patch.object(tools, "_manage", side_effect=lambda op, args, st: "{}") as m:
                    tools.share_agent({"name": "quill", "allow_secrets": True}, settings={})
                    tools.import_agent({"path": "x.json", "allow_secrets": True}, settings={})
                for call in m.call_args_list:
                    self.assertNotIn("allow_secrets", call.args[1])
            # importing a BLOCK template: the model argument is ignored, the setting is honoured
            tpl = Path(t) / "leaky.botforge.json"
            tpl.write_text(f'{{"format": "bot-forge/template", "version": 1, "role": "writer", "soul_md": "use {fake}"}}')
            out = manage.manage({"op": "import", "hermes_root": str(root), "path": str(tpl), "allow_secrets": True,
                                 "display_name": "Writer"})
            self.assertIn("credential", out["error"])
            out = manage.manage({"op": "import", "hermes_root": str(root), "path": str(tpl), "display_name": "Writer",
                                 "settings": {"allow_secrets": True}})
            self.assertNotIn("credential", out["error"])  # got past the scan (then refused for the generic name)

    def test_export_path_stays_under_profile_exports(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            self._bot(root)
            base = {"op": "export", "hermes_root": str(root), "name": "quill"}
            for bad in (str(root / "config.yaml"), str(Path(t) / "elsewhere.json"), "../config.yaml"):
                out = manage.manage({**base, "path": bad})
                self.assertFalse(out["ok"], bad)
                self.assertIn("profile-exports", out["error"])
            self.assertIn("root-model", (root / "config.yaml").read_text())
            out = manage.manage({**base, "path": "quill-copy.json"})
            self.assertTrue(out["ok"])
            self.assertEqual(Path(out["path"]).parent, (root / "profile-exports").resolve())
            again = manage.manage({**base, "path": out["path"]})
            self.assertFalse(again["ok"])
            self.assertIn("already exists", again["error"])
            self.assertTrue(manage.manage(base)["ok"])  # default name still works

    def test_import_rejects_missing_archive(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            out = manage.manage({"op": "import", "hermes_root": str(root), "path": str(Path(t) / "nope.tar.gz")})
            self.assertFalse(out["ok"])


class Connectors(unittest.TestCase):
    def test_no_suggestions_without_meaningful_words(self):
        self.assertEqual(forge.suggest_connectors(Path("/nonexistent"), ""), [])


class Teach(unittest.TestCase):
    def _bot(self, root):
        d = root / "profiles" / "quill"
        (d / "memories").mkdir(parents=True, exist_ok=True)
        (d / "config.yaml").write_text(yaml.safe_dump({"skills": {"disabled": ["weekly-report", "other"]}}))
        (d / "profile.yaml").write_text(yaml.safe_dump({"ui_meta": {"hermes-bots": {"title": "Quill"}}}))
        (d / "SOUL.md").write_text("# Quill\n\nYou are **Quill**, a writer.\n")
        return d

    def test_teach_writes_skill_and_enables_it(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            pdir = self._bot(root)
            out = manage.manage({"op": "teach", "hermes_root": str(root), "name": "quill",
                                 "skill": "weekly-report", "description": "How we write the weekly report.",
                                 "steps": ["Collect the week's commits", "Draft three bullets"]})
            self.assertTrue(out["ok"], out)
            doc = (pdir / "skills" / "taught" / "weekly-report" / "SKILL.md").read_text()
            self.assertIn("name: weekly-report", doc)
            self.assertIn("1. Collect the week's commits", doc)
            self.assertNotIn("weekly-report", yaml.safe_load((pdir / "config.yaml").read_text())["skills"]["disabled"])

    def test_teach_needs_steps_or_body(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            self._bot(root)
            out = manage.manage({"op": "teach", "hermes_root": str(root), "name": "quill", "skill": "x"})
            self.assertFalse(out["ok"])
            self.assertIn("steps", out["error"])


class Team(unittest.TestCase):
    def test_team_needs_members(self):
        out = team.build_team({"team": "Content", "members": []})
        self.assertFalse(out["ok"])
        self.assertIn("at least one member", out["error"])

    def test_unknown_lead_is_refused_before_building(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            out = team.build_team({"hermes_root": str(root), "lead_name": "nobody",
                                   "members": [{"display_name": "Quill", "role": "Writer", "one_job": "writes",
                                                "soul_md": "# Quill\n", "toolsets": []}]})
            self.assertFalse(out["ok"])
            self.assertIn("nobody", out["error"])
            self.assertEqual(list((root / "profiles").iterdir()), [])

    def test_lead_learns_the_roster(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t), profiles=["ceo"])
            (root / "profiles" / "ceo" / "memories").mkdir(parents=True)
            team._tell_lead(root, "ceo", "Content", [{"name": "quill", "display_name": "Quill",
                                                      "description": "writes posts"}])
            mem = (root / "profiles" / "ceo" / "memories" / "MEMORY.md").read_text()
            self.assertIn("@quill", mem)
            self.assertIn("Content team", mem)


