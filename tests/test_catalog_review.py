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
                                  cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)


@unittest.skipUnless(os.name == 'posix', '0600 credential-copy helper is POSIX only')
class IndependentCredentials(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('share_login', ROOT / 'extras/share_login.py')
        self.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.helper)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Resolved, because copy_login() resolves its root (extras/share_login.py:27).
        # On macOS tempfile hands back /var/folders/..., which resolves to
        # /private/var/folders/..., so an unresolved path here never matches the one the
        # helper actually operates on and the assertions silently compare nothing (#37).
        self.root = Path(self.tmp.name).resolve()
        self.bot = self.root / 'profiles' / 'quill'
        self.bot.mkdir(parents=True)
        (self.bot / 'config.yaml').write_text('{}')
        (self.root / 'auth.json').write_text('{"synthetic":"test-only"}')
        (self.root / 'auth.lock').write_text('synthetic lock')

    def test_copy_is_private_independent_and_never_shares_lock(self):
        self.helper.copy_login(self.root, 'quill')
        dest = self.bot / 'auth.json'
        self.assertFalse(dest.is_symlink())
        self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
        self.assertEqual(dest.read_bytes(), (self.root / 'auth.json').read_bytes())
        self.assertFalse((self.bot / 'auth.lock').exists())
        dest.write_text('changed in Bot')
        self.assertEqual((self.root / 'auth.json').read_text(), '{"synthetic":"test-only"}')

    def test_old_links_are_detached_without_changing_root(self):
        for name in ('auth.json', 'auth.lock'):
            (self.bot / name).symlink_to(self.root / name)
        before = {name: ((self.root / name).read_bytes(), (self.root / name).stat().st_mode)
                  for name in ('auth.json', 'auth.lock')}
        self.helper.link(self.root, 'quill')
        self.assertFalse((self.bot / 'auth.lock').is_symlink())
        self.assertFalse((self.bot / 'auth.json').is_symlink())
        (self.bot / 'auth.json').write_text('independent')
        for name, expected in before.items():
            self.assertEqual(((self.root / name).read_bytes(), (self.root / name).stat().st_mode), expected)

    def test_hardlink_and_preexisting_temp_link_cannot_write_root(self):
        os.link(self.root / 'auth.json', self.bot / 'auth.json')
        (self.bot / 'auth.json.linking').symlink_to(self.root / 'auth.json')
        self.helper.copy_login(self.root, 'quill')
        (self.bot / 'auth.json').write_text('independent')
        self.assertEqual((self.root / 'auth.json').read_text(), '{"synthetic":"test-only"}')

    def test_rejects_traversal_and_profile_directory_links(self):
        for name in ('..', '../quill', 'default', '/tmp', 'quill/../../'):
            self.assertIn('invalid', self.helper.copy_login(self.root, name))
        (self.root / 'profiles' / 'linked').symlink_to(self.root, target_is_directory=True)
        self.assertIn('symlink', self.helper.copy_login(self.root, 'linked'))

    def test_failure_keeps_old_destination_and_cleans_temp(self):
        from unittest import mock
        dest = self.bot / 'auth.json'
        dest.write_text('old synthetic credentials')
        with mock.patch.object(self.helper.os, 'replace', side_effect=OSError('test failure')):
            with self.assertRaises(OSError):
                self.helper.copy_login(self.root, 'quill')
        self.assertEqual(dest.read_text(), 'old synthetic credentials')
        self.assertEqual(list(self.bot.glob('.auth-copy-*')), [])

    def test_a_root_reached_through_a_symlink_is_handled(self):
        """macOS reaches its temp dir through a symlink; Linux CI never did, so #37 hid there.

        Recreating that shape here means this platform difference is exercised on every CI run
        rather than only on a contributor's laptop.
        """
        real = Path(self.tmp.name) / 'real-home'
        (real / 'profiles' / 'quill').mkdir(parents=True)
        (real / 'profiles' / 'quill' / 'config.yaml').write_text('{}')
        (real / 'auth.json').write_text('{"synthetic":"test-only"}')
        link = Path(self.tmp.name) / 'linked-home'
        link.symlink_to(real, target_is_directory=True)

        self.helper.copy_login(link, 'quill')

        dest = real / 'profiles' / 'quill' / 'auth.json'
        self.assertTrue(dest.exists(), 'the copy must land in the real directory')
        self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
        self.assertFalse(dest.is_symlink())

    def test_credentials_are_private_before_copying_any_bytes(self):
        from unittest import mock
        original_read = Path.read_bytes
        observed = []
        def read_bytes(path):
            if path == self.root / 'auth.json':
                temps = list(self.bot.glob('.auth-copy-*'))
                self.assertEqual(len(temps), 1)
                observed.append(temps[0].stat().st_mode & 0o777)
            return original_read(path)
        old_umask = os.umask(0o022)
        try:
            with mock.patch.object(Path, 'read_bytes', autospec=True, side_effect=read_bytes):
                self.helper.copy_login(self.root, 'quill')
        finally:
            os.umask(old_umask)
        self.assertEqual(observed, [0o600])


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
                                          cwd=tmp, env=env, capture_output=True, text=True, timeout=30)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    result = json.loads(proc.stdout)
                    self.assertTrue(result['ok'])
                    self.assertEqual(result['action'], action)
                    if action == 'status':
                        self.assertFalse(result['configured'])
                    else:
                        self.assertFalse(result['sent'])
                        self.assertEqual(result['count'], 0)
