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


class ArgumentLimits(unittest.TestCase):
    """"May email me, not anyone else" — the rule a tool-name gate cannot express."""

    POLICY = {"limits": {"send_email": {"to": ["me@example.com"]}}}

    def test_a_call_within_its_limit_needs_no_asking(self):
        """The user already said this shape is fine; asking again would train them to click yes."""
        self.assertIsNone(guard.decide("send_email", self.POLICY, {"to": "me@example.com"}))

    def test_a_call_outside_its_limit_is_refused_and_says_which_argument(self):
        out = guard.decide("send_email", self.POLICY, {"to": "stranger@example.com"})
        self.assertEqual(out["action"], "block")
        self.assertIn("to", out["message"])
        self.assertIn("stranger@example.com", out["message"])

    def test_a_limit_beats_the_name_based_lists(self):
        """Naming the address must buy something, or the feature is decorative."""
        policy = {**self.POLICY, "ask": ["send_email"]}
        self.assertIsNone(guard.decide("send_email", policy, {"to": "me@example.com"}))

    def test_refuse_still_wins_over_a_satisfied_limit(self):
        policy = {**self.POLICY, "refuse": ["send_email"]}
        self.assertEqual(guard.decide("send_email", policy, {"to": "me@example.com"})["action"],
                         "block")

    def test_every_recipient_in_a_list_must_be_permitted(self):
        """One allowed address alongside one that is not is still sending to the stranger."""
        out = guard.decide("send_email", self.POLICY,
                           {"to": ["me@example.com", "stranger@example.com"]})
        self.assertEqual(out["action"], "block")
        self.assertIsNone(guard.decide("send_email", self.POLICY, {"to": ["me@example.com"]}))

    def test_case_and_padding_do_not_slip_past_a_limit(self):
        for value in ("  Me@Example.com ", "ME@EXAMPLE.COM"):
            with self.subTest(value=value):
                self.assertIsNone(guard.decide("send_email", self.POLICY, {"to": value}))

    def test_an_unreadable_argument_falls_through_rather_than_being_allowed(self):
        """A value we cannot read is a question, not a yes."""
        for value in ({"nested": "thing"}, 42, None, [], ["ok", 7]):
            with self.subTest(value=value):
                out = guard.decide("send_email", self.POLICY, {"to": value})
                self.assertEqual(out["action"], "approve", value)

    def test_an_absent_argument_does_not_satisfy_a_limit_on_its_own(self):
        """Omitting `to` must not be a way to skip the check on `to`."""
        out = guard.decide("send_email", self.POLICY, {"subject": "hello"})
        self.assertEqual(out["action"], "approve")

    def test_a_limit_on_one_tool_says_nothing_about_another(self):
        self.assertEqual(guard.decide("post_tweet", self.POLICY, {"to": "me@example.com"})["action"],
                         "approve")

    def test_a_malformed_limit_governs_nothing_and_permits_nothing(self):
        for limits in ({"send_email": {"to": []}}, {"send_email": {"to": "  "}},
                       {"send_email": {}}, {"send_email": "not a mapping"}, "not a mapping"):
            with self.subTest(limits=limits):
                out = guard.decide("send_email", {"limits": limits}, {"to": "anyone@example.com"})
                self.assertEqual(out["action"], "approve", limits)

    def test_limits_do_not_disturb_a_tool_with_no_rule(self):
        self.assertIsNone(guard.decide("read_file", self.POLICY, {"path": "/tmp/x"}))


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


class EverySettingIsActuallyRead(unittest.TestCase):
    """A setting the manifest advertises but the code never reads is a rule nobody applies.

    This is how `limits` shipped broken for an hour: declared in plugin.yaml, documented, unit
    tested through guard.decide directly — and absent from the key list the hook builds its
    policy from, so no real call ever saw it. The unit tests could not catch that, because they
    never went through the hook.
    """

    def test_the_hook_reads_every_setting_the_manifest_declares(self):
        import yaml as y
        declared = set(y.safe_load(
            (ROOT / "sentinel" / "plugin.yaml").read_text(encoding="utf-8"))["config_schema"])
        asked = set()

        class Ctx:
            def get_config(self, key, default=None):
                asked.add(key)
                return default

            def register_hook(self, event, handler):
                self.handler = handler

        ctx = Ctx()
        spec = importlib.util.spec_from_file_location(
            "bot_forge_sentinel_settings", ROOT / "sentinel" / "__init__.py",
            submodule_search_locations=[str(ROOT / "sentinel")])
        mod = importlib.util.module_from_spec(spec)
        sys.modules["bot_forge_sentinel_settings"] = mod
        spec.loader.exec_module(mod)
        mod.register(ctx)
        ctx.handler(tool_name="send_email", args={})

        self.assertEqual(declared - asked, set(),
                         "declared in plugin.yaml but never read by the hook")
        self.assertEqual(asked - declared, set(),
                         "read by the hook but never declared in plugin.yaml")


class LimitsThroughTheHook(unittest.TestCase):
    """The unit tests call guard.decide directly; a real call arrives through the hook."""

    def _hook(self, config):
        spec = importlib.util.spec_from_file_location(
            "bot_forge_sentinel_limits", ROOT / "sentinel" / "__init__.py",
            submodule_search_locations=[str(ROOT / "sentinel")])
        mod = importlib.util.module_from_spec(spec)
        sys.modules["bot_forge_sentinel_limits"] = mod
        spec.loader.exec_module(mod)
        captured = {}

        class Ctx:
            def get_config(self, key, default=None):
                return config.get(key, default)

            def register_hook(self, event, handler):
                captured["h"] = handler

        mod.register(Ctx())
        return captured["h"]

    def test_a_limit_reaches_a_real_call(self):
        hook = self._hook({"limits": {"send_email": {"to": ["me@example.com"]}}})
        self.assertIsNone(hook(tool_name="send_email", args={"to": "me@example.com"}))
        self.assertEqual(hook(tool_name="send_email", args={"to": "x@evil.com"})["action"], "block")


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
