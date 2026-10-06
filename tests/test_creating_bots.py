"""Designing and spawning a Bot: names, identity, defaults, guardrails.

Split out of tests/test_forge.py, which had grown past 2,300 lines; the shared helpers
and the sys.path setup Hermes-style imports need live in tests/support.py.
"""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from support import forge, make_root, tools, yaml


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
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "config.yaml"
            path.write_text("model: {}\n")
            os.chmod(path, 0o600)
            forge.dump_yaml(path, {"model": {"default": "m"}})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(yaml.safe_load(path.read_text())["model"]["default"], "m")


