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


if __name__ == "__main__":
    unittest.main()


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
