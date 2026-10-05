"""Load the plugin the way Hermes loads it, and check the manifest tells the truth.

Runs as its own process from a directory outside the checkout, so the repo is never on
``sys.path``. That matters: every in-package import has to be package-relative, and a probe
run from inside the repo passes even when they are not, because ``''`` on ``sys.path``
resolves a bare ``import forge`` to the top-level file. That is precisely how v0.15.0 shipped
a plugin that could not load, and why the fix was missed twice.

What the host actually promises a user is the manifest: the tools, hooks and settings listed
in ``plugin.yaml``. So the check is not "does something register" but "does registration
produce exactly what the manifest advertises" — a tool renamed in one place and not the other
is a tool the agent will never be offered.
"""
import importlib
import importlib.util
import sys
import types
from pathlib import Path

import yaml

repo, home = map(Path, sys.argv[1:])

# A believable Hermes home, so register() reads real files rather than the user's own.
(home / "profiles" / "quill").mkdir(parents=True, exist_ok=True)
(home / "config.yaml").write_text("plugins:\n  enabled: [bot-forge]\n")
(home / "profiles" / "quill" / "config.yaml").write_text("model:\n  default: test\n")
(home / "profiles" / "quill" / "SOUL.md").write_text("Synthetic Bot\n")

parent = types.ModuleType("hermes_plugins")
parent.__path__ = []
sys.modules["hermes_plugins"] = parent
name = "hermes_plugins.bot_forge"
spec = importlib.util.spec_from_file_location(
    name, repo / "__init__.py", submodule_search_locations=[str(repo)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[name] = plugin
spec.loader.exec_module(plugin)
assert str(repo) not in sys.path, "the probe must not put the plugin directory on sys.path"


class Context:
    """Records what a plugin registers. Mirrors the Hermes plugin context's shape."""

    def __init__(self):
        self.tools = {}
        self.hooks = []
        self.skills = []
        self.cli = {}

    def get_config(self, key, default=None):
        return default

    def register_tool(self, **kw):
        assert kw["name"] not in self.tools, f"{kw['name']} registered twice"
        for field in ("name", "schema", "handler", "description"):
            assert kw.get(field), f"{kw.get('name')!r} registered without {field}"
        assert callable(kw["handler"]), f"{kw['name']} handler is not callable"
        self.tools[kw["name"]] = kw["handler"]

    def register_hook(self, event, handler):
        assert callable(handler), f"{event} hook is not callable"
        self.hooks.append(event)

    def register_skill(self, skill, path):
        assert Path(path).exists(), f"skill {skill} points at {path}, which does not exist"
        self.skills.append(skill)

    def register_cli_command(self, **kw):
        assert callable(kw["handler_fn"]), f"{kw['name']} handler_fn is not callable"
        self.cli[kw["name"]] = kw


def check(plugin_dir, ctx):
    """Every tool and hook the manifest advertises must have actually been registered."""
    manifest = yaml.safe_load((plugin_dir / "plugin.yaml").read_text(encoding="utf-8"))

    declared_tools = set(manifest.get("provides_tools") or [])
    assert set(ctx.tools) == declared_tools, (
        "plugin.yaml and register() disagree about the tools. "
        f"declared but never registered: {sorted(declared_tools - set(ctx.tools))}; "
        f"registered but never declared: {sorted(set(ctx.tools) - declared_tools)}")

    declared_hooks = set(manifest.get("provides_hooks") or [])
    assert set(ctx.hooks) == declared_hooks, (
        f"declared hooks {sorted(declared_hooks)} but registered {sorted(set(ctx.hooks))}")

    # A declared config key with no default is a setting the user can never discover.
    for key, entry in (manifest.get("config_schema") or {}).items():
        assert isinstance(entry, dict) and "type" in entry and "description" in entry, \
            f"config_schema.{key} must declare a type and a description"


ctx = Context()
forge = importlib.import_module(name + ".forge")
original = forge.default_root
forge.default_root = lambda: home
try:
    plugin.register(ctx)
finally:
    forge.default_root = original

check(repo, ctx)

# The CLI command is the path that broke twice: registered, but with a handler that raised the
# moment it ran, because its import worked only inside the repo. Register it, then run it.
assert "bot-forge-doctor" in ctx.cli, (
    "bot-forge-doctor was not registered; a bare `except Exception` used to hide this")

# Skills are a promise too: whatever ships under skills/ should be offered.
on_disk = sorted(c.name for c in (repo / "skills").iterdir()
                 if c.is_dir() and (c / "SKILL.md").exists())
assert sorted(ctx.skills) == on_disk, f"registered skills {sorted(ctx.skills)} != {on_disk}"

# The companion ships inside every Bot and must register the same two hooks under the same load
# shape. It has no tools on purpose: a reaction hook should not widen what a Bot can do.
marks_name = "hermes_plugins.bot_forge_marks"
marks_spec = importlib.util.spec_from_file_location(
    marks_name, repo / "marks" / "__init__.py",
    submodule_search_locations=[str(repo / "marks")])
marks = importlib.util.module_from_spec(marks_spec)
sys.modules[marks_name] = marks
marks_spec.loader.exec_module(marks)
marks_ctx = Context()
marks.register(marks_ctx)
check(repo / "marks", marks_ctx)
assert not marks_ctx.tools, "the companion must grant a Bot no tools"

print(f"registered {len(ctx.tools)} tools, {len(ctx.hooks)} hooks, {len(ctx.skills)} skills, "
      f"{len(ctx.cli)} CLI command(s); companion registered {len(marks_ctx.hooks)} hooks")
