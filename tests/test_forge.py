"""Unit tests for the pure parts of bot-forge. Run: python -m unittest discover -s tests"""

import sqlite3
import sys
import tempfile
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
            with sqlite3.connect(root / "profiles" / "ceo" / "state.db") as c:
                c.execute("create table sessions (id text)")
                c.execute("insert into sessions values ('s1')")
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
            tpl = portable.build_template(d, root)
            blob = str(tpl)
            self.assertNotIn("Pune", blob)
            self.assertNotIn("chat history", blob)
            self.assertEqual(tpl["memory"], ["Drafts go out Fridays."])
            self.assertEqual(tpl["role"], "Writer")


if __name__ == "__main__":
    unittest.main()
