"""Catalog-review regressions: real registered paths, isolated from user state."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RegisteredCallbacks(unittest.TestCase):
    def test_callbacks_outside_repo_with_trusted_settings(self):
        probe = ROOT / 'tests' / 'catalog_callback_probe.py'
        with tempfile.TemporaryDirectory() as tmp:
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(('HERMES_', 'EMAIL_', 'PYTHON'))}
            env.update(HOME=tmp, USERPROFILE=tmp, LOCALAPPDATA=tmp, PYTHONUTF8='1')
            proc = subprocess.run([sys.executable, '-B', str(probe), str(ROOT), tmp],
                                  cwd=tmp, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)


@unittest.skipUnless(os.name == 'posix', '0600 credential-copy helper is POSIX only')
# The IndependentCredentials tests covered extras/share_login.py, which is gone: a plugin
# that ships a credential-copying helper is asking to be trusted with something it should
# not hold. Removed with the script rather than left asserting a file that no longer exists.

class NotificationSubcommands(unittest.TestCase):
    def test_status_and_digest_use_isolated_home_without_shell_pipe(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(('HERMES_', 'EMAIL_', 'PYTHON'))}
            env.update(HOME=tmp, USERPROFILE=tmp, LOCALAPPDATA=tmp, PYTHONUTF8='1')
            for action in ('status', 'digest'):
                with self.subTest(action=action):
                    proc = subprocess.run([sys.executable, '-B', str(ROOT / 'notify.py'), action],
                                          cwd=tmp, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    result = json.loads(proc.stdout)
                    self.assertTrue(result['ok'])
                    self.assertEqual(result['action'], action)
                    if action == 'status':
                        self.assertFalse(result['configured'])
                    else:
                        self.assertFalse(result['sent'])
                        self.assertEqual(result['count'], 0)
