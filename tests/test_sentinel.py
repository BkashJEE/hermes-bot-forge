"""Sentinel decides what a Bot may do, and it has to decide the same way every time.

A policy layer earns nothing by being usually right. These tests are mostly about the cases
where being wrong is expensive: a rule that silently stops applying, a tool name that slips a
category, and anything that would make the layer fail open.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

import support  # noqa: F401  (arranges sys.path; see tests/support.py)

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "sentinel" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard = _load("guard")


class Precedence(unittest.TestCase):
    def test_refuse_beats_ask_and_allow(self):
        """A rule that says never has to survive a rule that says sometimes."""
        policy = {"refuse": ["send_email"], "ask": ["send_email"], "allow": ["send_email"]}
        self.assertEqual(guard.decide("send_email", policy)["action"], "block")

    def test_ask_beats_allow(self):
        self.assertEqual(
            guard.decide("send_email", {"ask": ["send_email"], "allow": ["send_email"]})["action"],
            "approve")

    def test_allow_clears_a_tool_that_looks_like_a_category(self):
        """A publishing Bot has to be able to publish; that is the whole point of allow."""
        self.assertIsNone(guard.decide("post_update", {"allow": ["post_update"]}))

    def test_a_tool_in_no_list_is_left_alone_by_default(self):
        self.assertIsNone(guard.decide("read_file", {}))


class FailsClosed(unittest.TestCase):
    """Adoption failing open is fine. Enforcement failing open is not."""

    def test_an_unreadable_policy_refuses(self):
        for policy in (None, "not a mapping", 42, []):
            with self.subTest(policy=policy):
                out = guard.decide("read_file", policy)
                self.assertEqual(out["action"], "block", policy)
                self.assertIn("could not be read", out["message"])

    def test_a_block_always_carries_a_message(self):
        """Hermes drops a block with no message, which would silently permit the call."""
        out = guard.decide("delete_profile", {"refuse": ["delete_profile"]})
        self.assertTrue(out["message"].strip())
        self.assertIn("Nothing happened", out["message"])

    def test_a_nameless_tool_is_abstained_on_not_guessed(self):
        for tool in ("", "   ", None, 7):
            with self.subTest(tool=tool):
                self.assertIsNone(guard.decide(tool, {}))


class TheThreeCategories(unittest.TestCase):
    """The categories are the ones a Bot's own SOUL.md already promises to ask about."""

    def test_each_category_reaches_the_human_gate(self):
        for tool in ("send_email", "post_tweet", "publish_page", "buy_item",
                     "transfer_funds", "delete_file", "purge_cache"):
            with self.subTest(tool=tool):
                out = guard.decide(tool, {})
                self.assertEqual(out["action"], "approve", tool)

    def test_a_word_inside_another_word_is_not_a_match(self):
        """Substring matching would catch undelete_draft and posture_report. Word parts do not."""
        for tool in ("undelete_draft", "posture_report", "spendable_budget_report",
                     "repost_count", "deleted_items_count"):
            with self.subTest(tool=tool):
                self.assertIsNone(guard.decide(tool, {}), tool)

    def test_separators_do_not_hide_a_category(self):
        for tool in ("send-email", "mail.send", "SEND_EMAIL", "Post_Tweet"):
            with self.subTest(tool=tool):
                self.assertEqual(guard.decide(tool, {})["action"], "approve", tool)

    def test_defaults_can_be_turned_off_but_explicit_rules_still_apply(self):
        self.assertIsNone(guard.decide("send_email", {"guard_defaults": False}))
        self.assertEqual(
            guard.decide("send_email", {"guard_defaults": False, "refuse": ["send_email"]})["action"],
            "block")


class LockedDownMode(unittest.TestCase):
    def test_ask_mode_gates_everything_not_cleared(self):
        self.assertEqual(guard.decide("read_file", {"mode": "ask"})["action"], "approve")
        self.assertIsNone(guard.decide("read_file", {"mode": "ask", "allow": ["read_file"]}))

    def test_mode_is_read_leniently(self):
        for mode in ("ask", "ASK", " ask "):
            with self.subTest(mode=mode):
                self.assertEqual(guard.decide("read_file", {"mode": mode})["action"], "approve")


class DirectiveShape(unittest.TestCase):
    """Hermes ignores a directive it cannot read, which would be a silent permit."""

    def test_approve_keys_its_always_rule_to_the_tool(self):
        out = guard.decide("send_email", {})
        self.assertEqual(out["rule_key"], "bot-forge-sentinel:send_email")

    def test_always_allowing_one_tool_does_not_clear_its_whole_category(self):
        self.assertNotEqual(guard.decide("send_email", {})["rule_key"],
                            guard.decide("post_tweet", {})["rule_key"])

    def test_every_directive_uses_an_action_hermes_acts_on(self):
        seen = set()
        for tool, policy in (("send_email", {}), ("x", {"refuse": ["x"]}),
                             ("y", {"ask": ["y"]}), ("z", None)):
            out = guard.decide(tool, policy)
            self.assertIn(out["action"], ("block", "approve"))
            seen.add(out["action"])
        self.assertEqual(seen, {"block", "approve"})


class TheHook(unittest.TestCase):
    def setUp(self):
        self.sentinel = self._load_package()

    def _load_package(self):
        """Loaded as a package, the way Hermes loads it — never by bare path."""
        spec = importlib.util.spec_from_file_location(
            "bot_forge_sentinel", ROOT / "sentinel" / "__init__.py",
            submodule_search_locations=[str(ROOT / "sentinel")])
        mod = importlib.util.module_from_spec(spec)
        sys.modules["bot_forge_sentinel"] = mod
        spec.loader.exec_module(mod)
        return mod

    class Ctx:
        def __init__(self, config=None, raises=False):
            self.config, self.raises, self.hooks = config or {}, raises, {}

        def get_config(self, key, default=None):
            if self.raises:
                raise RuntimeError("config unavailable")
            return self.config.get(key, default)

        def register_hook(self, event, handler):
            self.hooks[event] = handler

        def register_tool(self, **kw):  # pragma: no cover - must never be called
            raise AssertionError("the policy layer must not grant a Bot tools")

    def test_it_registers_one_hook_and_no_tools(self):
        ctx = self.Ctx()
        self.sentinel.register(ctx)
        self.assertEqual(list(ctx.hooks), ["pre_tool_call"])

    def test_the_hook_returns_a_directive_from_the_profile_policy(self):
        ctx = self.Ctx({"refuse": ["delete_profile"]})
        self.sentinel.register(ctx)
        out = ctx.hooks["pre_tool_call"](tool_name="delete_profile", args={})
        self.assertEqual(out["action"], "block")

    def test_a_config_that_raises_refuses_rather_than_permits(self):
        """If we cannot learn the policy, the answer is no — not silence."""
        ctx = self.Ctx(raises=True)
        self.sentinel.register(ctx)
        out = ctx.hooks["pre_tool_call"](tool_name="send_email", args={})
        self.assertEqual(out["action"], "block")
        self.assertIn("could not be read", out["message"])

    def test_the_hook_tolerates_the_kwargs_hermes_actually_sends(self):
        ctx = self.Ctx()
        self.sentinel.register(ctx)
        out = ctx.hooks["pre_tool_call"](
            tool_name="send_email", args={"to": "x"}, task_id="t", session_id="s",
            tool_call_id="c", turn_id=1, api_request_id="a", middleware_trace=[])
        self.assertEqual(out["action"], "approve")


class TheManifestIsTrue(unittest.TestCase):
    def test_it_declares_the_hook_it_registers_and_no_tools(self):
        import yaml
        manifest = yaml.safe_load((ROOT / "sentinel" / "plugin.yaml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["provides_hooks"], ["pre_tool_call"])
        self.assertFalse(manifest.get("provides_tools"))
        for key, entry in manifest["config_schema"].items():
            self.assertIn("type", entry, key)
            self.assertIn("description", entry, key)


if __name__ == "__main__":
    unittest.main()


class ShippedIntoEveryBot(unittest.TestCase):
    """The policy layer is only worth anything if Bots actually get it."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = support.make_root(Path(self.tmp.name), profiles=())
        self.bot = self.root / "profiles" / "marlow"
        self.bot.mkdir(parents=True)
        (self.bot / "config.yaml").write_text("{}")

    def test_a_bots_declared_approvals_become_its_policy(self):
        import companion
        out = companion.install_sentinel(self.bot, support.forge.DEFAULT_APPROVALS)
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["enforcing"])
        self.assertEqual((self.bot / "plugins" / "bot-forge-sentinel" / "plugin.yaml").exists(), True)

    def test_the_policy_is_switched_on_in_that_bots_config(self):
        import companion
        companion.install_sentinel(self.bot, support.forge.DEFAULT_APPROVALS)
        cfg = support.yaml.safe_load((self.bot / "config.yaml").read_text())
        self.assertIn("bot-forge-sentinel", cfg["plugins"]["enabled"])
        self.assertTrue(cfg["bot-forge-sentinel"]["guard_defaults"])

    def test_a_bot_that_promised_nothing_is_not_given_rules_it_never_claimed(self):
        """Enforcing categories a Bot never declared would be us inventing its policy."""
        import companion
        out = companion.install_sentinel(self.bot, [])
        self.assertTrue(out["ok"], out)
        self.assertFalse(out["enforcing"])

    def test_an_operator_edit_is_never_overwritten(self):
        """Re-creating or updating a Bot must not quietly undo a rule someone added by hand."""
        import companion
        companion.install_sentinel(self.bot, support.forge.DEFAULT_APPROVALS)
        cfg_path = self.bot / "config.yaml"
        cfg = support.yaml.safe_load(cfg_path.read_text())
        cfg["bot-forge-sentinel"]["refuse"] = ["delete_profile"]
        cfg["bot-forge-sentinel"]["mode"] = "ask"
        support.forge.dump_yaml(cfg_path, cfg)

        companion.install_sentinel(self.bot, support.forge.DEFAULT_APPROVALS)

        after = support.yaml.safe_load(cfg_path.read_text())["bot-forge-sentinel"]
        self.assertEqual(after["refuse"], ["delete_profile"])
        self.assertEqual(after["mode"], "ask")

    def test_the_policy_a_bot_gets_actually_governs_it(self):
        """End to end: what install writes is what guard reads."""
        import companion
        companion.install_sentinel(self.bot, support.forge.DEFAULT_APPROVALS)
        policy = support.yaml.safe_load((self.bot / "config.yaml").read_text())["bot-forge-sentinel"]
        self.assertEqual(guard.decide("send_email", policy)["action"], "approve")
        self.assertIsNone(guard.decide("read_file", policy))


class PolicyFollowsTheWording(unittest.TestCase):
    def test_each_declared_category_turns_the_guard_on(self):
        import companion
        for wording in ("send, post or publish anything", "spend money or buy anything",
                        "delete files or data"):
            with self.subTest(wording=wording):
                self.assertTrue(companion.policy_for([wording])["guard_defaults"], wording)

    def test_nothing_declared_means_nothing_enforced_by_default(self):
        import companion
        for approvals in ([], None, ["review the plan with me first"]):
            with self.subTest(approvals=approvals):
                self.assertFalse(companion.policy_for(approvals)["guard_defaults"])
