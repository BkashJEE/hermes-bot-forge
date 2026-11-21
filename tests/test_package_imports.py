import unittest
import os
import sys
import tempfile
import subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

class PackageImports(unittest.TestCase):
    def test_package_import_does_not_fall_back_on_dependency_failure(self):
        """A broken package dependency must not resolve a bare sys.path namesake."""
        code = f"""
import importlib
import importlib.abc
import sys
import types
pkg = {ROOT.name!r}
sys.modules['forge'] = types.ModuleType('forge')
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == pkg + '.forge':
            raise ImportError('dependency unavailable')
sys.meta_path.insert(0, Block())
try:
    importlib.import_module(pkg + '.companion')
except ImportError as exc:
    assert 'dependency unavailable' in str(exc), str(exc)
else:
    raise AssertionError('package import silently used top-level decoy')
"""
        with tempfile.TemporaryDirectory() as tmp:
            # What this proves is that the imports do not need the repository on sys.path, so
            # the child gets the real environment with PYTHONPATH pointed at the parent
            # directory. An earlier version built a tiny allowlist instead, which is a POSIX
            # habit: on Windows it dropped USERPROFILE and LOCALAPPDATA, Path.home() raised,
            # and the child died before importing anything (#87).
            env = dict(os.environ)
            env["PYTHONPATH"] = str(ROOT.parent)
            env.pop("HERMES_HOME", None)
            proc = subprocess.run([sys.executable, "-B", "-c", code], cwd=tmp, env=env,
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_internal_imports_outside_repository(self):
        """Package imports must not rely on the repository being on sys.path."""
        code = (
            "import importlib; "
            f"f = importlib.import_module({ROOT.name!r} + '.forge'); "
            f"d = importlib.import_module({ROOT.name!r} + '.doctor'); "
            f"[importlib.import_module({ROOT.name!r} + '.' + n) for n in "
            "('forge', 'acks', 'health', 'journal', 'manage', 'survey', 'team', 'waiting', "
            "'companion', 'portable', 'tapback', 'schemas', 'tools', 'doctor', 'policy')]; "
            f"p = importlib.import_module({ROOT.name!r} + '.portable'); "
            "assert p.bundled_templates(); "
            f"a = importlib.import_module({ROOT.name!r} + '.acks'); "
            "assert isinstance(a.acks_enabled(__import__('pathlib').Path('/nonexistent')), bool); "
            "d.sandbox_backends = lambda: {'docker': {'usable': True}}; "
            "assert f.sandbox_error('docker') == ''; "
            "r = f.forge({'template': 'missing-template-for-import-test'}); "
            "assert r['ok'] is False and 'template' in r['error']"
        )
        with tempfile.TemporaryDirectory() as tmp:
            # The real environment with PYTHONPATH pointed at the parent directory. A tiny
            # allowlist here is a POSIX habit: on Windows it drops USERPROFILE, Path.home()
            # raises "Could not determine home directory" — the same message as #82 — and the
            # child dies before importing anything (#87). What this proves is that the imports
            # do not need the repository on sys.path, which only needs PYTHONPATH.
            env = dict(os.environ)
            env["PYTHONPATH"] = str(ROOT.parent)
            env.pop("HERMES_HOME", None)
            proc = subprocess.run([sys.executable, "-B", "-c", code], cwd=tmp, env=env,
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_no_unguarded_bare_in_package_imports(self):
        """Every deferred or module-level in-package import must guard with `if __package__:`."""
        import ast
        mods = {p.stem for p in ROOT.glob("*.py") if p.stem != "__init__"}
        offenders = []
        for path in sorted(ROOT.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            guarded = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "__package__":
                    for stmt in node.orelse:
                        for sub in ast.walk(stmt):
                            if isinstance(sub, ast.Import):
                                guarded.add(sub.lineno)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) and node.lineno not in guarded:
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        if top in mods and alias.name != "tools.react_to_message_tool":
                            offenders.append(f"{path.name}:{node.lineno}: import {alias.name}")
        self.assertEqual(offenders, [], "unguarded bare in-package imports: " + repr(offenders))

    def test_health_check_bot_runs_as_package_outside_repository(self):
        """Regression: health.check_bot used bare `import companion`, crashing under Hermes package loading."""
        code = (
            "import importlib, tempfile; from pathlib import Path; "
            f"h = importlib.import_module({ROOT.name!r} + '.health'); "
            "t = tempfile.TemporaryDirectory(); "
            "pdir = Path(t.name) / 'profiles' / 'alpha'; pdir.mkdir(parents=True); "
            "(pdir / 'config.yaml').write_text('model:\\n  default: test\\n', encoding='utf-8'); "
            "out = h.check_bot(pdir, {}, 1700000000.0, set()); "
            "assert out['name'] == 'alpha'; t.cleanup()"
        )
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            env["PYTHONPATH"] = str(ROOT.parent)
            env.pop("HERMES_HOME", None)
            proc = subprocess.run([sys.executable, "-B", "-c", code], cwd=tmp, env=env,
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
