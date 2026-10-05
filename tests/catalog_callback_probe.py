"""Runs outside the checkout; do not add plugin files to sys.path."""
import contextlib
import importlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import types
from unittest import mock

repo, root = map(Path, sys.argv[1:])
root = root / 'synthetic-hermes'
root.mkdir()
bot = root / 'profiles' / 'quill'
bot.mkdir(parents=True)
(root / 'config.yaml').write_text('plugins:\n  enabled: [bot-forge]\n')
(bot / 'config.yaml').write_text('model:\n  default: test\n')
(bot / 'SOUL.md').write_text('Synthetic Bot\n')
(root / '.env').write_text('EMAIL_SMTP_HOST=smtp.example.test\nEMAIL_ADDRESS=sender@example.test\n'
                          'EMAIL_PASSWORD=synthetic-test-only\nEMAIL_HOME_ADDRESS=home@example.test\n')
parent = types.ModuleType('hermes_plugins')
parent.__path__ = []
sys.modules['hermes_plugins'] = parent
name = 'hermes_plugins.bot_forge'
spec = importlib.util.spec_from_file_location(name, repo / '__init__.py',
                                            submodule_search_locations=[str(repo)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[name] = plugin
spec.loader.exec_module(plugin)
assert str(repo) not in sys.path
doctor = importlib.import_module(name + '.doctor')
journal = importlib.import_module(name + '.journal')
notify = importlib.import_module(name + '.notify')
forge = importlib.import_module(name + '.forge')
config = {}

class Context:
    def __init__(self):
        self.tools = {}
        self.cli = {}
    def get_config(self, key, default=None): return config.get(key, default)
    def register_tool(self, **kw): self.tools[kw['name']] = kw['handler']
    def register_cli_command(self, **kw): self.cli[kw['name']] = kw['handler_fn']
    def register_hook(self, *args): pass
    def register_skill(self, *args): pass

ctx = Context()
outbox = []
def transport(cfg, msg): outbox.append((cfg, msg))

# Exercise the real subprocess payload and standalone doctor/journal entry
# points in process, keeping the final SMTP transport mocked. Also execute a
# real standalone journal subprocess below with notifications disabled.
def run(command, **kwargs):
    payload = json.loads(kwargs.get('input') or '{}')
    if Path(command[1]).name == 'journal.py':
        result = journal.operate(payload)
        return subprocess.CompletedProcess(command, 0, json.dumps(result), '')
    assert Path(command[1]).name == 'doctor.py', command
    assert '--settings-stdin' in command
    stream = io.StringIO()
    with mock.patch.object(sys, 'argv', command[1:]), mock.patch.object(sys, 'stdin', io.StringIO(kwargs['input'])):
        with contextlib.redirect_stdout(stream):
            try:
                doctor.main()
            except SystemExit:
                pass
    return subprocess.CompletedProcess(command, 0, stream.getvalue(), '')

with mock.patch.object(forge, 'default_root', return_value=root), \
     mock.patch.object(plugin.tools, 'hermes_root', return_value=root), \
     mock.patch.object(doctor, '_run', return_value=None), \
     mock.patch.object(doctor, 'sandbox_backends', return_value={}), \
     mock.patch.object(notify, '_smtp_send', side_effect=transport):
    plugin.register(ctx)
    assert json.loads(ctx.tools['list_agents']({}))['agents']
    with mock.patch.object(plugin.tools.subprocess, 'run', side_effect=run):
        assert json.loads(ctx.tools['agent_journal']({'action': 'enable', 'name': 'quill'}))['ok']
        cases = [({'notify_blocked': False}, False, None),
                 ({'notify_email': False}, False, None),
                 ({'notify_blocked': True, 'notify_email': 'custom@example.test'}, True, 'custom@example.test'),
                 ({'notify_blocked': True}, True, 'home@example.test'),
                 ({'notify_blocked': None, 'notify_email': None}, True, 'home@example.test')]
        for settings, expected, recipient in cases:
            config.clear()
            config.update(settings)
            before = len(outbox)
            args = {'action': 'add', 'name': 'quill', 'status': 'blocked', 'title': 'Synthetic blocker',
                    'summary': 'Synthetic work needs input',
                    'settings': {'notify_email': 'untrusted@example.test'}, 'to': 'untrusted@example.test'}
            result = json.loads(ctx.tools['agent_journal'](args))
            assert result['ok'] and result['written'], result
            assert result['notified']['sent'] is expected, result
            assert len(outbox) == before + int(expected)
            if expected:
                assert outbox[-1][1]['To'] == recipient
            read = json.loads(ctx.tools['agent_journal']({'action': 'read', 'name': 'quill'}))
            assert read['ok'] and read['count'] > 0, read
            # Both registered diagnostics must honor trusted operator settings.
            report = json.loads(ctx.tools['check_install']({'settings': {'notify_email': 'untrusted@example.test'}}))
            mail = next(c for c in report['checks'] if c['check'] == 'mail')
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                ctx.cli['bot-forge-doctor'](types.SimpleNamespace(json=True))
            cli_report = json.loads(stream.getvalue())
            assert next(c for c in cli_report['checks'] if c['check'] == 'mail') == mail
            if settings.get('notify_email') is False or settings.get('notify_blocked') is False:
                assert mail['status'] == 'warn' and 'disabled' in mail['detail'], mail
            else:
                assert (recipient or 'home@example.test') in mail['detail'], mail
        # Deferred package imports on the notify digest path.
        assert notify.notify_waiting(root, {'notify_email': False})['sent'] is False

payload = {'hermes_root': str(root), 'name': 'quill', 'action': 'add', 'status': 'blocked',
           'title': 'Standalone synthetic blocker', 'summary': 'Synthetic work needs input',
           'settings': {'notify_email': False}}
proc = subprocess.run([sys.executable, '-B', str(repo / 'journal.py'), '-'],
                      input=json.dumps(payload), capture_output=True, text=True, timeout=30)
assert proc.returncode == 0, proc.stderr
result = json.loads(proc.stdout)
assert result['ok'] and result['notified']['sent'] is False, result
print('registered CLI, diagnostic tool, journal callbacks and standalone journal passed')
