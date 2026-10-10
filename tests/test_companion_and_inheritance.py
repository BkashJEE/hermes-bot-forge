"""Shipping the companion into a Bot, and what a Bot inherits.

Split out of tests/test_forge.py, which had grown past 2,300 lines; the shared helpers
and the sys.path setup Hermes-style imports need live in tests/support.py.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import FakeCtx, ROOT, forge, make_root, manage, yaml


class CompanionInstall(unittest.TestCase):
    """The reaction hook has to live inside the Bot — a hook only runs in the profile running the turn."""

    def _bot(self, root, name="marlow", title="Marlow", meta=True):
        d = root / "profiles" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.yaml").write_text(yaml.safe_dump({"model": {"default": "m", "provider": "p"}}))
        if meta:
            (d / "profile.yaml").write_text(yaml.safe_dump({"ui_meta": {"hermes-bots": {"title": title}}}))
        return d

    def test_it_installs_the_hook_and_switches_it_on(self):
        import companion
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = self._bot(root)
            self.assertFalse(companion.marks_ready(d))
            out = companion.install_marks(d)
            self.assertTrue(out["ok"], out)
            self.assertTrue(out["copied"])
            self.assertTrue((d / "plugins" / companion.MARKS_NAME / "plugin.yaml").exists())
            self.assertTrue(companion.is_enabled(d))
            self.assertTrue(companion.marks_ready(d))

    def test_the_companion_grants_no_tools(self):
        """A Bot must not gain create_agent/delete_agent just to be able to react."""
        import companion
        manifest = yaml.safe_load((companion.SOURCE / "plugin.yaml").read_text())
        self.assertEqual(manifest.get("manifest_version", 1), 1)
        self.assertFalse(manifest.get("provides_tools"))
        self.assertEqual(sorted(manifest["provides_hooks"]), ["post_llm_call", "pre_llm_call"])

    def test_installing_twice_changes_nothing(self):
        import companion
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = self._bot(root)
            companion.install_marks(d)
            again = companion.install_marks(d)
            self.assertTrue(again["ok"])
            self.assertFalse(again["copied"])
            enabled = yaml.safe_load((d / "config.yaml").read_text())["plugins"]["enabled"]
            self.assertEqual(enabled.count(companion.MARKS_NAME), 1)

    def test_an_older_copy_is_replaced(self):
        import companion
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = self._bot(root)
            companion.install_marks(d)
            manifest = companion.installed_dir(d) / "plugin.yaml"
            manifest.write_text(manifest.read_text().replace(
                f"version: {companion.marks_version()}", "version: 0.0.1"))
            self.assertEqual(companion.installed_version(d), "0.0.1")
            self.assertFalse(companion.marks_ready(d))
            out = companion.install_marks(d)
            self.assertTrue(out["copied"])
            self.assertEqual(out["previous_version"], "0.0.1")
            self.assertTrue(companion.marks_ready(d))

    def test_it_keeps_the_profiles_other_plugins(self):
        import companion
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = self._bot(root)
            (d / "config.yaml").write_text(yaml.safe_dump(
                {"model": {"default": "m"}, "plugins": {"enabled": ["hermes-rss", "githermes"]}}))
            companion.install_marks(d)
            enabled = yaml.safe_load((d / "config.yaml").read_text())["plugins"]["enabled"]
            self.assertIn("hermes-rss", enabled)
            self.assertIn("githermes", enabled)
            self.assertIn(companion.MARKS_NAME, enabled)

    def test_the_installed_marks_package_executes_its_registered_hooks(self):
        """Exercise what ships into the Bot, including both reaction switches."""
        import companion
        import importlib.util

        class HookContext(FakeCtx):
            def __init__(self):
                super().__init__()
                self.hooks = {}
                self.enabled = True

            def get_config(self, key, default=None):
                return self.enabled if key == "ack_tapback" else default

            def register_hook(self, name, handler):
                self.hooks[name] = handler

        with tempfile.TemporaryDirectory() as tmp:
            bot = self._bot(make_root(Path(tmp)))
            self.assertTrue(companion.install_marks(bot)["copied"])
            installed = bot / "plugins" / companion.MARKS_NAME
            name = "_test_installed_bot_forge_marks"
            spec = importlib.util.spec_from_file_location(
                name, installed / "__init__.py", submodule_search_locations=[str(installed)])
            shipped = importlib.util.module_from_spec(spec)
            with mock.patch.dict(sys.modules, {name: shipped}):
                spec.loader.exec_module(shipped)
                ctx = HookContext()
                shipped.register(ctx)
                with mock.patch.object(shipped.tapback, "reactions_allowed", return_value=True), \
                     mock.patch.object(shipped.tapback, "_ensure_tool", return_value=True):
                    ctx.hooks["pre_llm_call"](platform="desktop")
                    ctx.hooks["post_llm_call"](platform="desktop", assistant_response="All done.")
                    self.assertEqual(ctx.calls, [
                        ("react_to_message", {"emoji": shipped.tapback.WORKING}),
                        ("react_to_message", {"emoji": shipped.tapback.DONE})])
                    ctx.calls.clear()
                    ctx.enabled = False
                    ctx.hooks["pre_llm_call"](platform="desktop")
                    ctx.hooks["post_llm_call"](platform="desktop", assistant_response="All done.")
                    self.assertEqual(ctx.calls, [], "explicit plugin disable must silence both hooks")
                    ctx.enabled = None
                    ctx.hooks["pre_llm_call"](platform="desktop")
                    self.assertEqual(ctx.calls, [
                        ("react_to_message", {"emoji": shipped.tapback.WORKING})])
                    ctx.calls.clear()
                    ctx.hooks["pre_llm_call"](platform="cli")
                    ctx.hooks["post_llm_call"](platform="cli", assistant_response="All done.")
                    self.assertEqual(ctx.calls, [], "CLI turns must not dispatch Desktop reactions")
                with mock.patch.object(shipped.tapback, "reactions_allowed", return_value=False), \
                     mock.patch.object(shipped.tapback, "_ensure_tool", return_value=True):
                    ctx.enabled = True
                    ctx.hooks["pre_llm_call"](platform="desktop")
                    ctx.hooks["post_llm_call"](platform="desktop", assistant_response="All done.")
                    self.assertEqual(ctx.calls, [], "the user's appearance setting must silence both hooks")

    def test_a_profile_made_any_other_way_is_adopted(self):
        """A Bot from Hermes' own New Agent dialog never heard of this plugin — it still reacts."""
        import companion
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            stranger = self._bot(root, "made-elsewhere", "Elsewhere", meta=False)
            self.assertFalse(companion.marks_ready(stranger))
            changed = companion.adopt_all(root, {"adopt_bots": True})
            self.assertIn("made-elsewhere", [c["bot"] for c in changed])
            self.assertTrue(companion.marks_ready(stranger))
            self.assertTrue(companion.reactions_setting(stranger))
            self.assertEqual(companion.adopt_all(root, {"adopt_bots": True}), [],
                             "a second pass must change nothing")

    def test_the_setting_is_switched_on_not_just_the_hook(self):
        """The half that is easy to miss: unset reads as off, and the Bot is silent."""
        import companion
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = self._bot(root, "quiet", "Quiet")
            self.assertFalse(companion.reactions_setting(d))
            out = companion.ensure_reactions(d)
            self.assertTrue(out["ok"])
            self.assertTrue(out["setting"])
            self.assertTrue(companion.reactions_setting(d))
            self.assertFalse(companion.ensure_reactions(d)["setting"], "idempotent")

    def test_adoption_can_be_switched_off(self):
        import companion
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            left = self._bot(root, "left-alone", "Left Alone")
            self.assertEqual(companion.adopt_all(root, {"adopt_bots": False}), [])
            # Opt-in: unset (Hermes' get_config returns None) must not touch other profiles either.
            self.assertEqual(companion.adopt_all(root, {"adopt_bots": None}), [])
            self.assertEqual(companion.adopt_all(root), [])
            self.assertFalse(companion.marks_ready(left))

    def test_bots_without_the_hook_are_listed_with_a_reason(self):
        import companion
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            ready = self._bot(root, "marlow", "Marlow")
            companion.install_marks(ready)
            self._bot(root, "nova", "Nova")
            self._bot(root, "plain", "Plain", meta=False)  # not a Bot Forge Bot
            missing = companion.bots_without_marks(root)
            self.assertEqual([m["bot"] for m in missing], ["nova"])
            self.assertEqual(missing[0]["reason"], "not installed")

    def test_installed_but_switched_off_is_reported_as_not_enabled(self):
        import companion
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = self._bot(root, "nova", "Nova")
            companion.install_marks(d)
            cfg = yaml.safe_load((d / "config.yaml").read_text())
            cfg["plugins"]["enabled"] = []
            (d / "config.yaml").write_text(yaml.safe_dump(cfg))
            self.assertEqual(companion.bots_without_marks(root)[0]["reason"], "not enabled")


class InheritedPlugins(unittest.TestCase):
    """Issue #25: a clone carries the root's plugins.enabled list but not the plugin directories, so a root
    plugin is enabled-but-inert in every Bot. Inheriting is opt-in and never carries Bot Forge or a secret."""

    def _root(self, tmp):
        root = make_root(Path(tmp))
        (root / "config.yaml").write_text(yaml.safe_dump({
            "model": {"default": "root-model", "provider": "p"},
            "plugins": {"enabled": ["style", "bot-forge", "bot-forge-marks", "bundled-thing"],
                        "disabled": ["orchestrator"]}}))
        for name, manifest in (("style", "style"), ("orchestrator", "orchestrator"),
                               ("forge-checkout", "bot-forge"), ("bot-forge-marks", "bot-forge-marks")):
            d = root / "plugins" / name
            d.mkdir(parents=True)
            (d / "plugin.yaml").write_text(f"name: {manifest}\nversion: 1.2.3\n")
            (d / "__init__.py").write_text("# code\n")
        style = root / "plugins" / "style"
        (style / ".env").write_text("STYLE_API_KEY=sk-live-do-not-copy\n")
        (style / "service.pem").write_text("-----BEGIN PRIVATE KEY-----\n")
        (style / "credentials.json").write_text("{}")
        (style / ".git").mkdir()
        (style / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        (style / "__pycache__").mkdir()
        (style / "__pycache__" / "x.pyc").write_bytes(b"\x00")
        (style / "skills" / "tone").mkdir(parents=True)
        (style / "skills" / "tone" / "SKILL.md").write_text("# tone\n")
        return root

    def _bot(self, root, name="marlow", enabled=None):
        d = root / "profiles" / name
        d.mkdir(parents=True, exist_ok=True)
        cfg = {"model": {"default": "m", "provider": "p"}}
        if enabled is not None:
            cfg["plugins"] = {"enabled": enabled, "disabled": ["style"]}
        (d / "config.yaml").write_text(yaml.safe_dump(cfg))
        (d / "profile.yaml").write_text(yaml.safe_dump({"ui_meta": {"hermes-bots": {"title": name.title()}}}))
        return d

    def test_true_means_every_enabled_root_plugin_but_never_bot_forge(self):
        import companion
        with tempfile.TemporaryDirectory() as t:
            root = self._root(t)
            chosen, skipped = companion.select_inherited(root, True)
            self.assertEqual(list(chosen), ["style"])  # not orchestrator (disabled), not bot-forge, not marks
            self.assertEqual({s["name"] for s in skipped}, {"bot-forge", "bot-forge-marks"})
            for spelling in (["all"], ["*"], "all"):
                self.assertEqual(list(companion.select_inherited(root, spelling)[0]), ["style"], spelling)

    def test_a_named_list_reports_what_it_cannot_carry(self):
        import companion
        with tempfile.TemporaryDirectory() as t:
            root = self._root(t)
            chosen, skipped = companion.select_inherited(root, ["style", "orchestrator", "nope", "bot-forge", "style"])
            self.assertEqual(list(chosen), ["style", "orchestrator"])  # a disabled root plugin can still be named
            reasons = {s["name"]: s["reason"] for s in skipped}
            self.assertIn("not installed", reasons["nope"])
            self.assertIn("never copied", reasons["bot-forge"])
            self.assertEqual(companion.select_inherited(root, None), ({}, []))
            self.assertEqual(companion.select_inherited(root, []), ({}, []))
            self.assertEqual(companion.select_inherited(root, False), ({}, []))

    def test_forge_is_recognised_by_manifest_and_by_path(self):
        import companion
        with tempfile.TemporaryDirectory() as t:
            root = self._root(t)
            self.assertTrue(companion.is_forge_itself(root / "plugins" / "forge-checkout"))
            self.assertTrue(companion.is_forge_itself(ROOT))  # this very checkout
            self.assertFalse(companion.is_forge_itself(root / "plugins" / "style"))

    def test_copy_enables_the_plugin_and_leaves_secrets_and_litter_behind(self):
        import companion
        with tempfile.TemporaryDirectory() as t:
            root = self._root(t)
            d = self._bot(root, enabled=["bot-forge"])
            out = companion.inherit_plugins(root, d, ["style"])
            self.assertTrue(out["ok"], out)
            self.assertEqual([i["name"] for i in out["installed"]], ["style"])
            self.assertEqual(out["installed"][0]["version"], "1.2.3")
            target = d / "plugins" / "style"
            self.assertTrue((target / "plugin.yaml").exists())
            self.assertTrue((target / "__init__.py").exists())
            self.assertTrue((target / "skills" / "tone" / "SKILL.md").exists())
            for gone in (".env", "service.pem", "credentials.json", ".git", "__pycache__"):
                self.assertFalse((target / gone).exists(), gone)
            plugins = yaml.safe_load((d / "config.yaml").read_text())["plugins"]
            self.assertEqual(plugins["enabled"], ["bot-forge", "style"])
            self.assertNotIn("style", plugins["disabled"])  # a cloned disabled entry would keep it off

    def test_inheriting_twice_replaces_the_copy_and_enables_once(self):
        import companion
        with tempfile.TemporaryDirectory() as t:
            root = self._root(t)
            d = self._bot(root)
            companion.inherit_plugins(root, d, ["style"])
            (d / "plugins" / "style" / "stale.py").write_text("old\n")
            companion.inherit_plugins(root, d, ["style"])
            self.assertFalse((d / "plugins" / "style" / "stale.py").exists())
            self.assertEqual(yaml.safe_load((d / "config.yaml").read_text())["plugins"]["enabled"].count("style"), 1)

    def test_the_companion_is_installed_once_at_its_own_version(self):
        import companion
        with tempfile.TemporaryDirectory() as t:
            root = self._root(t)
            d = self._bot(root)
            companion.install_marks(d)
            out = companion.inherit_plugins(root, d, True)
            self.assertTrue(out["ok"])
            self.assertEqual(companion.installed_version(d), companion.marks_version())  # not the root's 1.2.3
            self.assertTrue(companion.marks_ready(d))
            self.assertEqual(yaml.safe_load((d / "config.yaml").read_text())["plugins"]["enabled"].count(
                companion.MARKS_NAME), 1)

    def test_inert_plugins_never_name_a_bundled_or_unknown_one(self):
        import companion
        with tempfile.TemporaryDirectory() as t:
            root = self._root(t)
            d = self._bot(root, enabled=["style", "bot-forge", "bundled-thing", "mystery"])
            companion.install_marks(d)
            # bundled set known: everything without a directory that is not bundled
            self.assertEqual(sorted(companion.inert_plugins(d, root, {"bundled-thing"})), ["bot-forge", "mystery", "style"])
            # bundled set unknown: only names that exist as a directory under the root are certain
            self.assertEqual(sorted(companion.inert_plugins(d, root, None)), ["bot-forge", "style"])
            companion.inherit_plugins(root, d, ["style"])
            self.assertEqual(companion.inert_plugins(d, root, None), ["bot-forge"])

    def test_check_agents_flags_enabled_but_inert(self):
        import health
        from unittest import mock
        with tempfile.TemporaryDirectory() as t:
            root = self._root(t)
            d = self._bot(root, enabled=["style"])
            (d / "SOUL.md").write_text("# Marlow\n\nYou are **Marlow**.\n\n## Ask first\n- x\n")
            with mock.patch.object(health, "_gateways", return_value={}):
                out = health.check({"hermes_root": str(root)})
            bot = out["report"][0]
            self.assertEqual(bot["inert_plugins"], ["style"])
            self.assertTrue(any("enabled but not installed" in f and "style" in f for f in bot["flags"]), bot["flags"])
            import companion
            companion.inherit_plugins(root, d, ["style"])
            with mock.patch.object(health, "_gateways", return_value={}):
                bot = health.check({"hermes_root": str(root)})["report"][0]
            self.assertEqual(bot["inert_plugins"], [])
            self.assertFalse(any("enabled but not installed" in f for f in bot["flags"]))

    def test_update_agent_carries_plugins_into_an_existing_bot(self):
        with tempfile.TemporaryDirectory() as t:
            root = self._root(t)
            d = self._bot(root)
            (d / "SOUL.md").write_text("# Marlow\n\nYou are **Marlow**.\n")
            out = manage.manage({"op": "update", "hermes_root": str(root), "name": "marlow",
                                 "inherit_plugins": ["style", "nope"]})
            self.assertTrue(out["ok"], out)
            self.assertIn("plugins", out["changed"])
            self.assertEqual(out["plugins"]["inherited"], ["style"])
            self.assertEqual(out["plugins"]["skipped"][0]["name"], "nope")
            self.assertTrue((d / "plugins" / "style" / "plugin.yaml").exists())

    # ── create_agent end to end, with the hermes CLI faked ───────────────────
    def _fake_run(self, root, calls):
        def fake(r, *args, **kw):
            calls.append(args)
            if args[:2] == ("profile", "create"):
                d = root / "profiles" / args[2]
                d.mkdir(parents=True)
                (d / "config.yaml").write_text((root / "config.yaml").read_text())  # a clone carries the list
            if args[:2] == ("profile", "delete"):
                import shutil
                shutil.rmtree(root / "profiles" / args[3], ignore_errors=True)
            return type("P", (), {"returncode": 0, "stdout": "Hi, I am Marlow.", "stderr": ""})()
        return fake

    def _spec(self, root, **extra):
        return {"hermes_root": str(root), "role": "Editor", "display_name": "Marlow", "one_job": "edits",
                "soul_md": "# Marlow — Editor\n\nYou are **Marlow**.\n",
                "settings": {"install_gateway": False, "suggest_connectors": False, "workspace_survey": False},
                **extra}

    def test_create_agent_inherits_nothing_unless_asked(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as t:
            root = self._root(t)
            calls = []
            with mock.patch.object(forge, "run", side_effect=self._fake_run(root, calls)), \
                    mock.patch.object(forge, "has_bot_chat", return_value=True):
                out = forge.forge(self._spec(root))
            self.assertTrue(out["ok"], out)
            self.assertIsNone(out["plugins"])
            bot = root / "profiles" / "marlow"
            cfg = yaml.safe_load((bot / "config.yaml").read_text(encoding="utf-8"))
            self.assertNotIn("bot-forge-sentinel", cfg.get("plugins", {}).get("enabled", []))
            self.assertNotIn("bot-forge-sentinel", cfg)
            self.assertIn("## Ask first", (bot / "SOUL.md").read_text(encoding="utf-8"))
            self.assertEqual(sorted(p.name for p in (root / "profiles" / "marlow" / "plugins").iterdir()),
                             ["bot-forge-marks"])

    def test_create_agent_inherits_by_setting_or_by_argument(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as t:
            root = self._root(t)
            calls = []
            spec = self._spec(root)
            spec["settings"]["inherit_plugins"] = ["all"]
            with mock.patch.object(forge, "run", side_effect=self._fake_run(root, calls)), \
                    mock.patch.object(forge, "has_bot_chat", return_value=True):
                out = forge.forge(spec)
            self.assertTrue(out["ok"], out)
            self.assertEqual(out["plugins"]["inherited"], ["style"])
            pdir = root / "profiles" / "marlow"
            self.assertTrue((pdir / "plugins" / "style" / "plugin.yaml").exists())
            self.assertFalse((pdir / "plugins" / "style" / ".env").exists())
            self.assertFalse((pdir / "plugins" / "forge-checkout").exists())
            enabled = yaml.safe_load((pdir / "config.yaml").read_text())["plugins"]["enabled"]
            self.assertEqual(enabled.count("style"), 1)
            self.assertEqual(enabled.count("bot-forge-marks"), 1)
        with tempfile.TemporaryDirectory() as t:  # the call's own argument wins over the setting
            root = self._root(t)
            spec = self._spec(root, display_name="Vesper", inherit_plugins=["orchestrator"])
            spec["settings"]["inherit_plugins"] = ["style"]
            with mock.patch.object(forge, "run", side_effect=self._fake_run(root, [])), \
                    mock.patch.object(forge, "has_bot_chat", return_value=True):
                out = forge.forge(spec)
            self.assertTrue(out["ok"], out)
            self.assertEqual(out["plugins"]["inherited"], ["orchestrator"])
            self.assertFalse((root / "profiles" / "vesper" / "plugins" / "style").exists())

    def test_a_failed_inherit_rolls_the_whole_profile_back(self):
        import companion
        from unittest import mock
        with tempfile.TemporaryDirectory() as t:
            root = self._root(t)
            calls = []
            with mock.patch.object(forge, "run", side_effect=self._fake_run(root, calls)), \
                    mock.patch.object(forge, "has_bot_chat", return_value=True), \
                    mock.patch.object(companion, "install_plugin",
                                      return_value={"ok": False, "name": "style", "error": "disk full"}):
                out = forge.forge(self._spec(root, inherit_plugins=["style"]))
            self.assertFalse(out["ok"])
            self.assertIn("disk full", out["error"])
            self.assertTrue(out["rolled_back"])
            self.assertIn(("profile", "delete", "-y", "marlow"), calls)
            self.assertFalse((root / "profiles" / "marlow").exists())


class BlanketInheritanceStopsAtCredentials(unittest.TestCase):
    """"Give it everything" must not quietly hand a Bot reach into an account."""

    def _root(self, tmp, plugins):
        root = Path(tmp)
        (root / "profiles").mkdir()
        (root / "config.yaml").write_text(yaml.safe_dump(
            {"plugins": {"enabled": [n for n, _ in plugins]}}))
        for name, env in plugins:
            d = root / "plugins" / name
            d.mkdir(parents=True)
            (d / "plugin.yaml").write_text(yaml.safe_dump(
                {"name": name, "version": "1.0", "requires_env": env}))
        return root

    def test_all_skips_a_plugin_that_needs_credentials(self):
        import companion
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp, [("hermes-rss", []), ("mailroom", ["GMAIL_TOKEN"])])
            chosen, skipped = companion.select_inherited(root, ["all"])
            self.assertEqual(sorted(chosen), ["hermes-rss"])
            self.assertEqual([s["name"] for s in skipped], ["mailroom"])
            self.assertIn("GMAIL_TOKEN", skipped[0]["reason"])
            self.assertIn("name it explicitly", skipped[0]["reason"])

    def test_naming_it_is_how_you_say_yes(self):
        """The rule is about what arrives unasked, not about forbidding the plugin."""
        import companion
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp, [("mailroom", ["GMAIL_TOKEN"])])
            chosen, skipped = companion.select_inherited(root, ["mailroom"])
            self.assertEqual(sorted(chosen), ["mailroom"])
            self.assertEqual(skipped, [])

    def test_a_plugin_with_no_declared_env_rides_along(self):
        import companion
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp, [("hermes-rss", []), ("hermes-bookmarks", [])])
            chosen, _skipped = companion.select_inherited(root, True)
            self.assertEqual(sorted(chosen), ["hermes-bookmarks", "hermes-rss"])

    def test_a_manifest_that_cannot_be_read_is_not_treated_as_safe(self):
        import companion
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp, [("broken", [])])
            (root / "plugins" / "broken" / "plugin.yaml").write_text("{{ not yaml")
            self.assertEqual(companion.needs_credentials(root / "plugins" / "broken"), [])


