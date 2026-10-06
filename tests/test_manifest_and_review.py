"""The manifest agreeing with itself, and catalog-review follow-ups.

Split out of tests/test_forge.py, which had grown past 2,300 lines; the shared helpers
and the sys.path setup Hermes-style imports need live in tests/support.py.
"""
import os
import tempfile
import unittest
from pathlib import Path

from support import ROOT, yaml


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



class ReviewFollowUps(unittest.TestCase):
    """The findings from the catalog review that the first fix did not cover."""





    @unittest.skipUnless(os.name == "posix", "credential-copy helper is POSIX only")
    def test_sharing_a_login_copies_it_instead_of_linking(self):
        """A symlink makes the Bot's profile *be* the root's credential store; a copy is a copy."""
        import extras.share_login as share_login
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "auth.json").write_text('{"token": "abc"}')
            bot = root / "profiles" / "quill"
            bot.mkdir(parents=True)
            (bot / "config.yaml").write_text("model: {}\n")
            out = share_login.link(root, "quill")
            dest = bot / "auth.json"
            self.assertTrue(dest.is_file())
            self.assertFalse(dest.is_symlink(), "must never be a live link to another profile")
            self.assertEqual(dest.read_text(), '{"token": "abc"}')
            self.assertEqual(oct(dest.stat().st_mode)[-3:], "600")
            self.assertIn("copied", out)
            # the source is untouched by anything done to the copy
            dest.write_text('{"token": "replaced"}')
            self.assertEqual((root / "auth.json").read_text(), '{"token": "abc"}')

    @unittest.skipUnless(os.name == "posix", "credential-copy helper is POSIX only")
    def test_an_older_symlink_is_replaced_by_a_copy(self):
        import extras.share_login as share_login
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "auth.json").write_text('{"token": "abc"}')
            bot = root / "profiles" / "quill"
            bot.mkdir(parents=True)
            (bot / "config.yaml").write_text("model: {}\n")
            (bot / "auth.json").symlink_to(root / "auth.json")   # left by an older version
            share_login.link(root, "quill")
            self.assertFalse((bot / "auth.json").is_symlink())


if __name__ == "__main__":
    unittest.main()
