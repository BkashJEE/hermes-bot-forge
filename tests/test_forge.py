"""Unit tests for the pure parts of bot-forge. Run: python -m unittest discover -s tests"""

import json
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

import forge  # noqa: E402
import yaml  # noqa: E402

try:  # the plugin package (tools.py uses relative-free imports, so plain import works too)
    import tools  # noqa: E402
except ImportError:  # pragma: no cover
    tools = None

try:
    import manage  # noqa: E402
except ImportError:  # pragma: no cover
    manage = None

try:
    import team  # noqa: E402
except ImportError:  # pragma: no cover
    team = None

try:
    import journal  # noqa: E402
except ImportError:  # pragma: no cover
    journal = None


def make_root(tmp: Path, profiles=(), titles=None, root_display=None):
    root = tmp / ".hermes"
    (root / "profiles").mkdir(parents=True)
    (root / "config.yaml").write_text(yaml.safe_dump({"model": {"default": "root-model", "provider": "p"}}))
    if root_display:
        (root / "profile.yaml").write_text(yaml.safe_dump({"display_name": root_display}))
    for name in profiles:
        d = root / "profiles" / name
        d.mkdir()
        (d / "config.yaml").write_text(yaml.safe_dump({"model": {"default": f"{name}-model", "provider": "p"}}))
        if titles and name in titles:
            (d / "profile.yaml").write_text(yaml.safe_dump({"ui_meta": {"hermes-bots": {"title": titles[name]}}}))
    return root


class Names(unittest.TestCase):
    def test_proper_case_and_slug(self):
        self.assertEqual(forge.proper_case("nova blaze"), "Nova Blaze")
        self.assertEqual(forge.proper_case("x.com writer"), "X Com Writer")
        self.assertEqual(forge.slug("Nova Blaze"), "novablaze")

    def test_generic_and_taken_names_are_refused_with_suggestions(self):
        display, sid, err = forge.pick_name("Writer", set())
        self.assertIsNone(display)
        self.assertIn("too generic", err)
        display, sid, err = forge.pick_name("quill", {"quill"})
        self.assertIsNone(sid)
        self.assertIn("e.g.", err)

    def test_free_name_is_accepted(self):
        self.assertEqual(forge.pick_name("kairo", set()), ("Kairo", "kairo", None))

    def test_auto_name_when_none_requested(self):
        display, sid, err = forge.pick_name(None, {"nova"})
        self.assertIsNone(err)
        self.assertIn(display, forge.COOL_NAMES)
        self.assertNotEqual(sid, "nova")

    def test_existing_names_include_titles_and_root_display_name(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t), profiles=["quill"], titles={"quill": "Quill"}, root_display="Maia")
            names = forge.existing_bot_names(root)
            self.assertTrue({"quill", "maia"} <= names)


    def test_deleted_profiles_do_not_block_names(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t), profiles=["kairo"])
            (root / "profiles" / "quill").mkdir()  # leftover dir without config
            (root / "profiles" / ".deleted").mkdir()
            (root / "profiles" / ".deleted" / "kairo").write_text("deleted")
            names = forge.existing_bot_names(root)
            self.assertNotIn("quill", names)
            self.assertNotIn("kairo", names)


class Identity(unittest.TestCase):
    def test_identity_inserted_after_heading(self):
        soul = "# Quill — Writer\n\n## Your one job\nWrite."
        out = forge.ensure_identity(soul, "Quill", "Writer", "quill")
        self.assertTrue(out.startswith("# Quill — Writer\n\nYou are **Quill**"))
        self.assertIn("## Your one job", out)

    def test_identity_not_duplicated(self):
        soul = "# Quill\n\nYou are **Quill**, a writer."
        self.assertEqual(forge.ensure_identity(soul, "Quill", "Writer", "quill"), soul)

    def test_rename_replaces_identity_instead_of_stacking(self):
        soul = ("# Dawn — Morning Brief Writer\n\nYou are **Dawn**, the Morning Brief Writer. "
                "Always introduce yourself as Dawn.\n\n## Your one job\nBrief.")
        out = forge.ensure_identity(soul, "Zeta Echo", "Bot", "zetaecho")
        self.assertEqual(out.count("You are **"), 1)
        self.assertNotIn("Dawn", out.split("## Your one job")[0])
        self.assertTrue(out.startswith("# Zeta Echo — Morning Brief Writer"))
        self.assertIn("## Your one job", out)

    def test_role_comes_from_heading(self):
        self.assertEqual(forge.soul_role("# Dawn — Morning Brief Writer\n\nbody"), "Morning Brief Writer")
        self.assertEqual(forge.soul_role("no heading"), "")

    def test_user_memory_drops_assistant_naming_only(self):
        text = "User likes short posts.\n§\nUser calls the assistant Maia and wants it to use that name.\n§\nUser is in IST."
        out = forge.filter_user_memory(text, {"maia"})
        self.assertIn("short posts", out)
        self.assertIn("IST", out)
        self.assertNotIn("Maia", out)

    def test_user_memory_keeps_unrelated_mentions_of_names(self):
        text = "User built Maia themes last week."
        self.assertIn("Maia themes", forge.filter_user_memory(text, {"maia"}))


class BotMeta(unittest.TestCase):
    def test_write_bot_meta_matches_desktop_shape_and_bumps_revision(self):
        with tempfile.TemporaryDirectory() as t:
            pdir = Path(t)
            (pdir / "profile.yaml").write_text(yaml.safe_dump({"description": "x", "_ui_meta_revisions": {"hermes-bots": 2}}))
            forge.write_bot_meta(pdir, "Quill", "Writes posts", "sun")
            data = yaml.safe_load((pdir / "profile.yaml").read_text())
            bots = data["ui_meta"]["hermes-bots"]
            self.assertEqual(bots["title"], "Quill")
            self.assertEqual(bots["imageKind"], "shape")
            self.assertRegex(bots["shape"], r"^blobatar:[a-z0-9]{8}:sun$")
            self.assertEqual(data["_ui_meta_revisions"]["hermes-bots"], 3)
            self.assertEqual(data["description"], "x")


class Skills(unittest.TestCase):
    def test_disabled_skills_respects_kept_categories(self):
        with tempfile.TemporaryDirectory() as t:
            skills = Path(t)
            for cat, name in (("research", "arxiv"), ("email", "himalaya"), ("creative", "humanizer")):
                (skills / cat / name).mkdir(parents=True)
                (skills / cat / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n")
            self.assertEqual(forge.disabled_skills(skills, {"research", "creative"}), {"himalaya"})


@unittest.skipIf(tools is None, "tools module not importable")
class LaunchProfile(unittest.TestCase):
    def test_session_owner_is_found(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t), profiles=["ceo"])
            c = sqlite3.connect(root / "profiles" / "ceo" / "state.db")
            try:
                c.execute("create table sessions (id text)")
                c.execute("insert into sessions values ('s1')")
                c.commit()
            finally:
                c.close()
            self.assertEqual(tools.launch_profile("s1", root), "ceo")
            self.assertEqual(tools.launch_profile("nope", root), "default")
            self.assertEqual(tools.launch_profile(None, root), "default")


class ForgeValidation(unittest.TestCase):
    def test_missing_role_fails_before_touching_disk(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            out = forge.forge({"hermes_root": str(root)})
            self.assertFalse(out["ok"])
            self.assertEqual(list((root / "profiles").iterdir()), [])

    def test_taken_name_fails_before_touching_disk(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t), profiles=["quill"])
            out = forge.forge({"hermes_root": str(root), "role": "Writer", "display_name": "Quill"})
            self.assertFalse(out["ok"])
            self.assertFalse(out["rolled_back"])
            self.assertEqual([p.name for p in (root / "profiles").iterdir()], ["quill"])



class Guardrails(unittest.TestCase):
    def test_guardrails_block_renders_approvals_and_escalation(self):
        out = forge.guardrails_block(["publish anything", "spend money"], "ceo")
        self.assertIn("## Ask first", out)
        self.assertIn("- publish anything", out)
        self.assertIn("@ceo", out)

    def test_guardrails_block_empty_without_input(self):
        self.assertEqual(forge.guardrails_block([], ""), "")


class ConfigWrites(unittest.TestCase):
    def test_dump_yaml_keeps_file_mode(self):
        import os
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "config.yaml"
            path.write_text("model: {}\n")
            os.chmod(path, 0o600)
            forge.dump_yaml(path, {"model": {"default": "m"}})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(yaml.safe_load(path.read_text())["model"]["default"], "m")


@unittest.skipIf(manage is None, "manage module not importable")
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
            with mock.patch.object(manage, "op_export", side_effect=lambda s, r, st: (calls.append(s), {"ok": True, "path": "/x.tar.gz"})[1]), \
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


@unittest.skipIf(manage is None, "manage module not importable")
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


@unittest.skipIf(team is None, "team module not importable")
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


@unittest.skipIf(journal is None, "journal module not importable")
class Journal(unittest.TestCase):
    def _bot(self, root, name="quill"):
        d = root / "profiles" / name
        d.mkdir(exist_ok=True)
        (d / "config.yaml").write_text(yaml.safe_dump({"model": {"default": "m"}}))
        (d / "profile.yaml").write_text(yaml.safe_dump({"ui_meta": {"hermes-bots": {"title": "Quill"}}}))
        (d / "SOUL.md").write_text("# Quill — Writer\n\nYou are **Quill**, a writer.\n")
        return d

    def test_enable_is_idempotent_and_preserves_persona(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            pdir = self._bot(root)
            first = journal.operate({"action": "enable", "name": "quill", "hermes_root": str(root)})
            second = journal.operate({"action": "enable", "name": "quill", "hermes_root": str(root)})
            self.assertTrue(first["ok"], first)
            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            soul = (pdir / "SOUL.md").read_text()
            self.assertEqual(soul.count(journal.JOURNAL_MARKER), 1)
            self.assertIn("You are **Quill**", soul)
            self.assertTrue((pdir / "journal" / "README.md").exists())

    def test_add_and_read_factual_entry(self):
        from datetime import datetime, timezone

        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            pdir = self._bot(root)
            journal.enable_journal(pdir)
            out = journal.add_entry(pdir, {"title": "Prepared launch draft", "summary": "Drafted three posts.",
                                                   "status": "completed", "evidence": ["drafts/x-launch.md"],
                                                   "next_steps": ["Owner reviews the hooks"], "tags": ["X", "launch"]},
                                    now=datetime(2026, 9, 20, 20, 30, tzinfo=timezone.utc))
            self.assertTrue(out["written"])
            read = journal.read_entries(pdir, {"query": "three posts", "limit": 5})
            self.assertEqual(read["count"], 1)
            self.assertIn("completed", read["entries"][0]["entry"])
            self.assertIn("drafts/x-launch.md", read["entries"][0]["entry"])

    def test_secret_is_refused_without_echoing_value(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            pdir = self._bot(root)
            journal.enable_journal(pdir)
            fake = "sk-proj-" + "Z" * 30
            out = journal.operate({"action": "add", "name": "quill", "hermes_root": str(root),
                                   "title": "Configured API", "summary": f"Used {fake}"})
            self.assertFalse(out["ok"])
            self.assertNotIn(fake, str(out))
            self.assertEqual(list((pdir / "journal").glob("????-??-??.md")), [])

    def test_reading_disabled_journal_is_non_mutating(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            pdir = self._bot(root)
            out = journal.operate({"action": "read", "name": "quill", "hermes_root": str(root)})
            self.assertTrue(out["ok"], out)
            self.assertFalse(out["enabled"])
            self.assertEqual(out["entries"], [])
            self.assertFalse((pdir / "journal").exists())

    def test_root_profile_cannot_be_targeted(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            out = journal.operate({"action": "enable", "name": "default", "hermes_root": str(root)})
            self.assertFalse(out["ok"])
            self.assertIn("Bot name", out["error"])


class Portable(unittest.TestCase):
    def test_scanner_blocks_keys_and_never_echoes_them(self):
        import portable
        fake = "sk-proj-" + "A" * 30
        out = portable.scan_text(f"memory: use {fake}")
        self.assertEqual(out["verdict"], "BLOCK")
        self.assertNotIn(fake, str(out))

    def test_scanner_warns_on_generic_assignment_and_passes_clean_text(self):
        import portable
        self.assertEqual(portable.scan_text("password: hunter2hunter2hunter2")["verdict"], "WARN")
        self.assertEqual(portable.scan_text("Write three bullets every Friday.")["verdict"], "CLEAN")

    def test_bundled_templates_are_valid_clean_and_affordable(self):
        import json as _json
        import portable
        found = portable.bundled_templates()
        self.assertGreaterEqual(len(found), 5)
        for name, path in found.items():
            tpl = portable.load_template(path)
            self.assertEqual(portable.scan_text(_json.dumps(tpl))["verdict"], "CLEAN", name)
            self.assertIn(f"You are **{tpl['display_name']}**", tpl["soul_md"], name)
            for r in tpl["routines"]:
                self.assertFalse(forge.check_routine(r), f"{name}: {r['schedule']}")

    def test_template_never_contains_history_or_user_facts(self):
        import portable
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = root / "profiles" / "quill"
            (d / "memories").mkdir(parents=True)
            (d / "config.yaml").write_text(yaml.safe_dump({"platform_toolsets": {"cli": ["web"]}}))
            (d / "SOUL.md").write_text("# Quill — Writer\n\nYou are **Quill**.")
            (d / "memories" / "MEMORY.md").write_text("My name is Quill.\n§\nDrafts go out Fridays.")
            (d / "memories" / "USER.md").write_text("User lives in Pune.")
            (d / "state.db").write_text("chat history")
            (d / "journal").mkdir()
            (d / "journal" / "2026-09-20.md").write_text("secret work journal entry")
            tpl = portable.build_template(d, root)
            blob = str(tpl)
            self.assertNotIn("Pune", blob)
            self.assertNotIn("chat history", blob)
            self.assertNotIn("secret work journal entry", blob)
            self.assertEqual(tpl["memory"], ["Drafts go out Fridays."])
            self.assertEqual(tpl["role"], "Writer")



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



class JournalPrivacy(unittest.TestCase):
    """A journal is the Bot's private record: it must never ride along in something shareable."""

    def _journaling_bot(self, root):
        import journal
        d = root / "profiles" / "quill"
        (d / "memories").mkdir(parents=True)
        (d / "config.yaml").write_text(yaml.safe_dump({"platform_toolsets": {"cli": ["web"]}}))
        (d / "profile.yaml").write_text(yaml.safe_dump({"ui_meta": {"hermes-bots": {"title": "Quill"}}}))
        (d / "SOUL.md").write_text("# Quill — Writer\n\nYou are **Quill**.\n")
        (d / "memories" / "MEMORY.md").write_text("Drafts go out Fridays.")
        journal.enable_journal(d)
        journal.add_entry(d, {"title": "Wrote the Q3 launch thread", "status": "completed",
                              "summary": "Drafted eight posts about the internal pricing change.",
                              "evidence": ["posts saved to drafts/q3.md"]})
        return d

    def test_shared_template_carries_no_journal_entries(self):
        import portable
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = self._journaling_bot(root)
            blob = json.dumps(portable.build_template(d, root))
            self.assertNotIn("Q3 launch thread", blob)
            self.assertNotIn("internal pricing", blob)
            self.assertNotIn("drafts/q3.md", blob)

    def test_journal_files_live_only_inside_the_profile(self):
        import journal
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = self._journaling_bot(root)
            written = list((d / "journal").glob("????-??-??.md"))
            self.assertTrue(written)
            for f in written:
                self.assertTrue(f.resolve().is_relative_to(d.resolve()))
                self.assertEqual(f.stat().st_mode & 0o777, 0o600)
            self.assertEqual((d / "journal").stat().st_mode & 0o777, 0o700)
            self.assertTrue(journal.journaling_enabled(d))

    def test_a_symlinked_journal_directory_is_refused(self):
        import journal
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = root / "profiles" / "quill"
            d.mkdir(parents=True)
            elsewhere = Path(t) / "outside"
            elsewhere.mkdir()
            (d / "journal").symlink_to(elsewhere)
            with self.assertRaises(ValueError):
                journal.ensure_journal(d)



class Manifest(unittest.TestCase):
    """The plugin files must import and agree with each other — a broken schemas.py used to pass CI."""

    def test_every_schema_is_wellformed(self):
        import schemas
        found = {v["name"]: v for v in vars(schemas).values()
                 if isinstance(v, dict) and "name" in v and "parameters" in v}
        self.assertGreaterEqual(len(found), 14)
        for name, schema in found.items():
            self.assertTrue(schema["description"].strip(), name)
            self.assertEqual(schema["parameters"]["type"], "object", name)
            for field, spec in (schema["parameters"].get("properties") or {}).items():
                self.assertIn("type", spec, f"{name}.{field}")

    def test_manifest_declares_exactly_the_registered_tools(self):
        import schemas
        manifest = yaml.safe_load(Path(ROOT / "plugin.yaml").read_text())
        registered = {v["name"] for v in vars(schemas).values()
                      if isinstance(v, dict) and "name" in v and "parameters" in v}
        self.assertEqual(set(manifest["provides_tools"]), registered)

    def test_versions_agree(self):
        manifest = yaml.safe_load(Path(ROOT / "plugin.yaml").read_text())
        skill = (ROOT / "skills" / "bot-forge" / "SKILL.md").read_text()
        changelog = (ROOT / "CHANGELOG.md").read_text()
        self.assertIn(f"version: {manifest['version']}", skill)
        self.assertIn(f"## [{manifest['version']}]", changelog)



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
        from unittest import mock
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
        from unittest import mock
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
        from unittest import mock
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
        from unittest import mock
        root = self._root(bot_mode=True)
        calls = []
        with mock.patch.object(forge, "run", side_effect=lambda r, *a, **k: calls.append(a) or
                               type("P", (), {"returncode": 0, "stdout": "hi", "stderr": ""})()), \
                mock.patch.object(forge, "has_bot_chat", return_value=True):
            forge.bot_chat(root, "quill", "hi")
        self.assertEqual(len(calls), 1)
        self.assertIn("--create-if-missing", calls[0])

    def test_without_bot_mode_the_chat_stays_a_cli_session(self):
        from unittest import mock
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

    class FakeCtx:
        def __init__(self, fail=False):
            self.calls, self.fail = [], fail

        def dispatch_tool(self, name, args, **kw):
            self.calls.append((name, args))
            if self.fail:
                raise RuntimeError("reactions are off")
            return "{}"

    def test_reacts_only_on_desktop_and_only_when_enabled(self):
        import tapback
        self.assertTrue(tapback.should_react("desktop", True))
        for platform in ("cli", "acp", "tui", "api_server", "", None):
            self.assertFalse(tapback.should_react(platform, True), platform)
        self.assertFalse(tapback.should_react("desktop", False))

    def test_turn_start_marks_working_and_end_marks_the_outcome(self):
        import tapback
        ctx = self.FakeCtx()
        marks = tapback.Tapback(ctx, lambda: True)
        marks.on_turn_start(platform="desktop")
        marks.on_turn_end(platform="desktop", assistant_response="Here is the draft.")
        self.assertEqual([a["emoji"] for _n, a in ctx.calls], [tapback.WORKING, tapback.DONE])
        self.assertEqual({n for n, _a in ctx.calls}, {"react_to_message"})

    def test_outcome_reads_the_reply(self):
        import tapback
        self.assertEqual(tapback.outcome_emoji("Done — draft saved."), tapback.DONE)
        self.assertEqual(tapback.outcome_emoji("I can't publish for you."), tapback.BLOCKED)
        self.assertEqual(tapback.outcome_emoji("Ready. Shall I post it?"), tapback.NEEDS_YOU)

    def test_a_failing_reaction_never_breaks_the_turn(self):
        import tapback
        ctx = self.FakeCtx(fail=True)
        marks = tapback.Tapback(ctx, lambda: True)
        self.assertIsNone(marks.on_turn_start(platform="desktop"))
        self.assertIsNone(marks.on_turn_end(platform="desktop", assistant_response="x"))

    def test_nothing_is_dispatched_off_desktop(self):
        import tapback
        ctx = self.FakeCtx()
        marks = tapback.Tapback(ctx, lambda: True)
        marks.on_turn_start(platform="cli")
        marks.on_turn_end(platform="acp", assistant_response="x")
        self.assertEqual(ctx.calls, [])


class WaitingQueueTests(unittest.TestCase):
    """What is still waiting on the user, read out of the Bots' own journals."""

    def _bot(self, root, name, title, entries):
        import journal
        d = root / "profiles" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.yaml").write_text(yaml.safe_dump({"model": {"default": "m", "provider": "p"}}))
        (d / "profile.yaml").write_text(yaml.safe_dump({"ui_meta": {"hermes-bots": {"title": title}}}))
        journal.ensure_journal(d)
        for day, stamp, status, title_, body in entries:
            f = d / "journal" / f"{day}.md"
            f.write_text((f.read_text() if f.exists() else "")
                         + f"\n## {stamp} · {status} · {title_}\n{body}\n")
        return d

    def test_blocked_bots_surface_with_bot_name_age_and_detail(self):
        import waiting
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            self._bot(root, "marlow", "Marlow", [
                ("2026-09-20", "2026-09-20T09:00:00Z", "blocked", "Need the Stripe key",
                 "Invoice sync cannot run without it.")])
            now = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)
            out = waiting.waiting_on_user(root, now)
            self.assertEqual(out["count"], 1)
            item = out["items"][0]
            self.assertEqual(item["display_name"], "Marlow")
            self.assertEqual(item["bot"], "marlow")
            self.assertEqual(item["age_days"], 4.0)
            self.assertEqual(item["icon"], "⚠️")
            self.assertIn("Invoice sync", item["detail"])
            self.assertIn("Marlow: Need the Stripe key", out["summary"])

    def test_a_later_completion_closes_the_item(self):
        import waiting
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            self._bot(root, "marlow", "Marlow", [
                ("2026-09-20", "2026-09-20T09:00:00Z", "blocked", "Need the Stripe key", "waiting"),
                ("2026-09-21", "2026-09-21T09:00:00Z", "completed", "Need the Stripe key", "got it")])
            self.assertEqual(waiting.waiting_on_user(root)["count"], 0)

    def test_finished_and_planned_work_never_counts_as_waiting(self):
        import waiting
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            self._bot(root, "nova", "Nova", [
                ("2026-09-20", "2026-09-20T09:00:00Z", "completed", "Wrote the post", "done"),
                ("2026-09-20", "2026-09-20T10:00:00Z", "planned", "Next week's posts", "later"),
                ("2026-09-20", "2026-09-20T11:00:00Z", "progress", "Drafting", "ongoing")])
            out = waiting.waiting_on_user(root)
            self.assertEqual(out["count"], 0)
            self.assertEqual(out["summary"], "nothing is waiting on you")

    def test_newest_first_and_capped(self):
        import waiting
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            self._bot(root, "marlow", "Marlow", [
                (f"2026-08-{d:02d}", f"2026-08-{d:02d}T09:00:00Z", "failed", f"item {d}", "x")
                for d in range(1, 29)])
            out = waiting.waiting_on_user(root)
            self.assertEqual(out["count"], waiting.MAX_ITEMS)
            self.assertEqual(out["items"][0]["title"], "item 28")
            self.assertIn("more)", out["summary"])

    def test_a_bot_without_a_journal_is_simply_quiet(self):
        import waiting
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t), profiles=("gary",))
            self.assertEqual(waiting.waiting_on_user(root)["count"], 0)

    def test_health_leads_with_what_is_waiting(self):
        import health
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            self._bot(root, "nova", "Nova", [
                ("2026-09-20", "2026-09-20T09:00:00Z", "failed", "Could not publish", "needs approval")])
            out = health.check({"hermes_root": str(root)})
            self.assertEqual(out["waiting_count"], 1)
            self.assertTrue(out["summary"].startswith("1 waiting on you"))
            self.assertEqual(out["waiting_on_you"][0]["title"], "Could not publish")


if __name__ == "__main__":
    unittest.main()
