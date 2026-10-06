"""Shared setup for the test modules, and the one place sys.path is arranged.

Hermes imports a plugin as a package and never puts the plugin directory on sys.path. These
tests import the modules directly instead, which needs both the repo and its parent on the
path — so that happens here, once, rather than at the top of eight files. The test modules
take the plugin modules from here for the same reason: importing `forge` in a test file would
only work if some other test file had already imported this one.

Everything here is imported outright. Nothing is wrapped in `except ImportError`: a module
that has stopped importing is the most valuable thing this suite can report, and turning that
into a skip is what let two unloadable releases ship with CI green.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

import forge  # noqa: E402
import yaml  # noqa: E402

# Imported outright, never behind `except ImportError: ... = None`. These modules are always
# importable; the fallback existed only so a class could be skipped, which meant a plugin that
# had stopped importing at all — v0.15.0, v0.15.3 — silently skipped 22 tests and left CI green.
# A failure to import any of these is the thing the suite most needs to shout about.
import journal  # noqa: E402
import manage  # noqa: E402
import team  # noqa: E402
import tools  # noqa: E402


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


class FakeCtx:
    """A plugin context whose dispatch_tool behaves like the real one.

    Hermes hands a tool failure back as a value rather than raising, which is the detail the
    v0.9.0 tapback got wrong: it dispatched, got `{"error": ...}` in return, and reported
    success. Shared, because both the reaction hooks and the companion that ships them need it.
    """

    def __init__(self, result='{"success": true, "row_id": 31}', raises=False):
        self.calls, self.result, self.raises = [], result, raises

    def dispatch_tool(self, name, args, **kw):
        self.calls.append((name, args))
        if self.raises:
            raise RuntimeError("no session")
        return self.result


# Re-exported for the test modules. They must take these from here rather than importing them
# directly, because this module is what puts the plugin on sys.path.
__all__ = ["ROOT", "FakeCtx", "make_root", "forge", "journal", "manage", "team", "tools", "yaml"]
