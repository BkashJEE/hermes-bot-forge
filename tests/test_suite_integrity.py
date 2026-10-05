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

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[0]


def _test_modules():
    return sorted(p for p in TESTS.glob("test_*.py") if p.name != Path(__file__).name)


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


def fn_is_test(fn):
    return fn.name.startswith("test")


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


if __name__ == "__main__":
    unittest.main()
