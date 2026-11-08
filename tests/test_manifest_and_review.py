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
        manifest = yaml.safe_load(Path(ROOT / "plugin.yaml").read_text(encoding="utf-8"))
        registered = {v["name"] for v in vars(schemas).values()
                      if isinstance(v, dict) and "name" in v and "parameters" in v}
        self.assertEqual(set(manifest["provides_tools"]), registered)

    def test_versions_agree(self):
        manifest = yaml.safe_load(Path(ROOT / "plugin.yaml").read_text(encoding="utf-8"))
        skill = (ROOT / "skills" / "bot-forge" / "SKILL.md").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"version: {manifest['version']}", skill)
        self.assertIn(f"## [{manifest['version']}]", changelog)



# ReviewFollowUps held the two extras/share_login.py tests. The script is gone — a plugin
# that ships a credential-copying helper is asking to be trusted with something it should
# not hold — so its tests went with it rather than being left to assert a missing file.
