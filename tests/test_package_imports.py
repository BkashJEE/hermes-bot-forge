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
            # Mirror forge.SAFE_ENV_KEYS: Path.home() on Windows resolves USERPROFILE, then
            # HOMEDRIVE + HOMEPATH, and never HOME — the same omission that broke every
            # ask_agent there (#82). Without them the child cannot start at all.
            passthrough = ("PATH", "HOME", "SYSTEMROOT", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
                           "TEMP", "TMP", "PATHEXT", "LOCALAPPDATA", "APPDATA")
            env = {k: os.environ[k] for k in passthrough if os.environ.get(k)}
            env["PYTHONPATH"] = str(ROOT.parent)
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
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT.parent),
                   "HOME": os.environ.get("HOME", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
            proc = subprocess.run([sys.executable, "-B", "-c", code], cwd=tmp, env=env,
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
