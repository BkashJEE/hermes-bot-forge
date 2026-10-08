"""Rules about the tests themselves, because a test that cannot fail is worse than none.

A passing suite is the only evidence this plugin works, and twice it has been wrong: v0.15.0 and
v0.15.3 both shipped a plugin that could not load while CI was green. The reason was not a missing
test — it was tests that quietly declined to run. Five classes were decorated
``@unittest.skipIf(manage is None, ...)`` above a module-level ``except ImportError: manage =
None``, so the one failure mode that mattered most, the plugin no longer importing, turned 22 tests
into skips and the suite into a pass.

So the suite checks itself for the shapes that let that happen.
"""
import ast
import unittest
from pathlib import Path

import yaml

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[0]


def _test_modules():
    return sorted(p for p in TESTS.glob("test_*.py") if p.name != Path(__file__).name)


def fn_is_test(fn):
    return fn.name.startswith("test")


def _is_assertion(node):
    if isinstance(node, ast.Assert):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr.startswith(("assert", "fail"))
    return False


class EveryTestCanFail(unittest.TestCase):
    def test_every_test_method_asserts_something(self):
        """A test with no assertion passes by existing, and will pass forever."""
        empty = []
        for path in _test_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
                for fn in [n for n in cls.body
                           if isinstance(n, ast.FunctionDef) and fn_is_test(n)]:
                    if not any(_is_assertion(n) for n in ast.walk(fn)):
                        empty.append(f"{path.name}:{fn.lineno} {cls.name}.{fn.name}")
        self.assertEqual(empty, [], "these tests assert nothing: " + repr(empty))


class NoSilentSkips(unittest.TestCase):
    def test_no_test_module_swallows_an_import_error(self):
        """`except ImportError: mod = None` plus a skipIf turns broken into green.

        A plugin module that stopped importing is the single most important thing the suite can
        report. Importing it outright makes that a loud error instead of a skip.
        """
        offenders = []
        for path in _test_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Try):
                    continue
                for handler in node.handlers:
                    names = _exception_names(handler.type)
                    if not {"ImportError", "ModuleNotFoundError"} & names:
                        continue
                    for stmt in handler.body:
                        if isinstance(stmt, ast.Assign) and _assigns_none(stmt):
                            offenders.append(f"{path.name}:{stmt.lineno}")
        self.assertEqual(
            offenders, [],
            "an import failure here becomes None and then a skip, so a plugin that cannot be "
            "imported still passes CI; import it directly instead: " + repr(offenders))

    def test_a_skip_never_depends_on_whether_the_plugin_imported(self):
        """Skipping is for a platform or a missing backend, never for our own code."""
        offenders = []
        for path in _test_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                if not node.func.attr.startswith("skip"):
                    continue
                rendered = ast.unparse(node)
                if "is None" in rendered or "importable" in rendered:
                    offenders.append(f"{path.name}:{node.lineno} {rendered[:70]}")
        self.assertEqual(offenders, [], "skips conditioned on an import: " + repr(offenders))


def _exception_names(node):
    if node is None:
        return set()
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Tuple):
        return {e.id for e in node.elts if isinstance(e, ast.Name)}
    return set()


def _assigns_none(stmt):
    return isinstance(stmt.value, ast.Constant) and stmt.value.value is None



class PlatformClaimsMatchWhatIsTested(unittest.TestCase):
    """A platform may be claimed only if CI actually runs the suite on it.

    The first version of this test compared the skill's `platforms:` against a hardcoded
    `TESTED = ["linux", "macos"]` in this file. Both sides were things the maintainer typed, so
    it could only catch a typo — and it went green while every CI job ran `ubuntu-latest` and a
    test failed deterministically on macOS, which a contributor had to report (#37).

    So the evidence is the workflow. The OS list on the job that runs the suite *is* the set of
    platforms this project may claim; nothing in this file gets a vote.
    """

    WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"

    # GitHub runner label prefix -> the platform name a skill manifest uses.
    RUNNERS = {"ubuntu": "linux", "macos": "macos", "windows": "windows"}

    def platforms_ci_runs_the_suite_on(self):
        """Read the workflow and return the platforms the test suite is actually executed on."""
        import re
        workflow = yaml.safe_load(self.WORKFLOW.read_text(encoding="utf-8"))
        found = set()
        for name, job in (workflow.get("jobs") or {}).items():
            steps = job.get("steps") or []
            # Only a job that runs the whole suite counts. Linting on one OS is not coverage,
            # and neither is a job that loads the plugin without exercising its behaviour.
            if not any("unittest discover" in str(step.get("run", "")) for step in steps):
                continue
            labels = []
            runs_on = job.get("runs-on", "")
            if isinstance(runs_on, str) and "matrix." in runs_on:
                key = re.search(r"matrix\.([A-Za-z_][A-Za-z0-9_]*)", runs_on).group(1)
                labels = ((job.get("strategy") or {}).get("matrix") or {}).get(key) or []
            elif isinstance(runs_on, list):
                labels = runs_on
            elif runs_on:
                labels = [runs_on]
            self.assertTrue(labels, f"job {name!r} runs the suite but declares no runner")
            for label in labels:
                for prefix, platform in self.RUNNERS.items():
                    if str(label).startswith(prefix):
                        found.add(platform)
                        break
                else:
                    self.fail(f"unrecognised runner {label!r} in job {name!r}; "
                              f"add it to RUNNERS so the claim stays derived from CI")
        return found

    def test_ci_runs_the_suite_somewhere(self):
        """Guard the guard: if this returns nothing, every assertion below is vacuous."""
        self.assertTrue(self.platforms_ci_runs_the_suite_on(),
                        "no CI job runs `unittest discover`, so nothing below proves anything")

    def test_the_skill_claims_no_platform_ci_does_not_run(self):
        import re
        skill = (ROOT / "skills" / "bot-forge" / "SKILL.md").read_text(encoding="utf-8")
        match = re.search(r"^platforms:\s*\[([^\]]*)\]", skill, re.MULTILINE)
        self.assertIsNotNone(match, "skills/bot-forge/SKILL.md declares no platforms")
        claimed = {p.strip() for p in match.group(1).split(",") if p.strip()}
        unproven = claimed - self.platforms_ci_runs_the_suite_on()
        self.assertEqual(
            unproven, set(),
            "the skill claims these platforms but no CI job runs the suite on them — either add "
            "the runner to the unittest job's matrix or stop claiming the platform: "
            + repr(sorted(unproven)))

    def test_the_readme_does_not_call_windows_supported(self):
        """Windows stays disclaimed in prose until a Windows runner is in that matrix."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        if "windows" in self.platforms_ci_runs_the_suite_on():
            self.skipTest("CI runs on Windows now; the README disclaimer should be revisited")
        self.assertIn("Windows is not supported", readme)


if __name__ == "__main__":
    unittest.main()
