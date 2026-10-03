"""Every third-party import must be declared in plugin.yaml, and bounded.

Hermes installs a plugin's ``python_dependencies`` into the shared environment the
plugin then runs in. An import that is never declared works only by accident — on a
machine where some unrelated package happens to drag it in. On a clean install it
fails at load time with ``ModuleNotFoundError``, which drops every tool and hook the
plugin provides, not just the one module.

That is exactly how v0.15.3 shipped: ``forge.py`` (and ``manage.py``, ``companion.py``,
``tools.py``) import ``yaml``, no manifest declared PyYAML, and the plugin failed to
load on any install whose environment did not already contain it. CI missed it because
the workflow ran a hardcoded ``pip install pyyaml`` instead of installing from the
manifest — so the declaration was never exercised.
"""
import ast
import re
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

# Imported from the Hermes host process, never pip-installable by the plugin:
# `hermes_cli` / `hermes_constants` ship with Hermes, and `tools` is Hermes' own
# package (the plugin's top-level `tools.py` is reached package-relative as
# `bot_forge.tools`, so a bare `tools` import is always the host's).
HOST_PROVIDED = {"hermes_cli", "hermes_constants", "tools"}

# Import name -> distribution name, for the imports where the two differ.
IMPORT_TO_DISTRIBUTION = {"yaml": "pyyaml"}

_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(spec: str) -> str:
    match = _REQUIREMENT_NAME.match(spec)
    if not match:
        raise AssertionError(f"unparseable requirement in plugin.yaml: {spec!r}")
    return _normalise(match.group(1))


def _third_party_imports(root: Path) -> dict[str, set[str]]:
    """Map each third-party top-level import to the files that make it.

    Only the shipped plugin is scanned. ``tests/`` is excluded deliberately: a test
    may import a dev-only helper (a mock server, a coverage tool) that must not be
    forced into the manifest Hermes installs for every user. Test-only packages go in
    requirements-dev.txt instead.
    """
    stdlib = set(sys.stdlib_module_names)
    local = {p.stem for p in root.rglob("*.py")}
    local |= {p.name for p in root.iterdir() if p.is_dir()}
    found: dict[str, set[str]] = {}
    for path in sorted(root.rglob("*.py")):
        parts = path.parts
        if ".git" in parts or "__pycache__" in parts or "tests" in parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except SyntaxError as exc:  # pragma: no cover - surfaced as a test failure
            raise AssertionError(f"{path} does not parse: {exc}") from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                # A relative import (level > 0) is in-package by definition.
                if node.level or not node.module:
                    continue
                names = [node.module.split(".")[0]]
            else:
                continue
            for name in names:
                if name in stdlib or name in local or name in HOST_PROVIDED:
                    continue
                found.setdefault(name, set()).add(str(path.relative_to(root)))
    return found


def _declared_requirements() -> list[str]:
    manifest = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8-sig"))
    declared = manifest.get("python_dependencies") or []
    if not isinstance(declared, list) or any(not isinstance(v, str) for v in declared):
        raise AssertionError("plugin.yaml python_dependencies must be a list of requirement strings")
    return declared


class DeclaredDependencies(unittest.TestCase):
    def test_every_third_party_import_is_declared(self):
        declared = {_requirement_name(spec) for spec in _declared_requirements()}
        undeclared = {
            name: sorted(files)
            for name, files in _third_party_imports(ROOT).items()
            if _normalise(IMPORT_TO_DISTRIBUTION.get(name, name)) not in declared
        }
        self.assertEqual(
            undeclared, {},
            "These modules are imported but never declared in plugin.yaml "
            "python_dependencies, so the plugin fails to load on an install that "
            "does not happen to have them: " + repr(undeclared))

    def test_declared_requirements_are_upper_bounded(self):
        for spec in _declared_requirements():
            self.assertIn("<", spec,
                          f"{spec!r} has no upper bound; Hermes' dependency policy requires one "
                          f"(e.g. 'PyYAML>=6.0,<7') so a future major cannot break the plugin "
                          f"silently")

    def test_the_manifest_itself_parses(self):
        manifest = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8-sig"))
        self.assertEqual(manifest.get("name"), "bot-forge")
        self.assertTrue(manifest.get("provides_tools"))


if __name__ == "__main__":
    unittest.main()
