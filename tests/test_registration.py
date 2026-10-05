"""The manifest must describe the plugin that actually loads.

See tests/registration_probe.py for why this runs out-of-process from a temporary
directory rather than importing the package here.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tests" / "registration_probe.py"


def run_probe(repo: Path):
    """Run the probe against `repo` from a clean cwd, home and environment."""
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("HERMES_", "EMAIL_", "PYTHON"))}
        env.update(HOME=str(home), USERPROFILE=str(home), LOCALAPPDATA=str(home),
                   PYTHONUTF8="1")
        return subprocess.run([sys.executable, "-B", str(PROBE), str(repo), str(home)],
                              cwd=tmp, env=env, capture_output=True, text=True, timeout=60)


class Registration(unittest.TestCase):
    def test_manifest_matches_what_register_actually_registers(self):
        proc = run_probe(ROOT)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("CLI command", proc.stdout)

    def test_the_probe_notices_a_tool_that_stops_registering(self):
        """Guard the guard: a check that cannot fail is worse than no check.

        The copy is edited, never the checkout — dropping a tool from the real
        plugin.yaml would leave the repo broken if the assertion raised.
        """
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "bot_forge"
            _copy_tree(ROOT, copy)
            manifest = copy / "plugin.yaml"
            text = manifest.read_text(encoding="utf-8")
            self.assertIn("  - list_agents\n", text)
            manifest.write_text(text.replace("  - list_agents\n", "", 1), encoding="utf-8")
            proc = run_probe(copy)
        self.assertNotEqual(proc.returncode, 0,
                            "the probe passed a manifest that no longer declares list_agents")
        self.assertIn("list_agents", proc.stderr)


def _copy_tree(src: Path, dest: Path):
    """Copy the plugin, skipping everything that is not shipped."""
    import shutil
    shutil.copytree(
        src, dest,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "videos", "docs", "*.png"))


if __name__ == "__main__":
    unittest.main()
