"""Reading the workspace a Bot is born into, and bundled templates.

Split out of tests/test_forge.py, which had grown past 2,300 lines; the shared helpers
and the sys.path setup Hermes-style imports need live in tests/support.py.
"""
import tempfile
import unittest
from pathlib import Path

from support import forge, make_root, yaml


class Portable(unittest.TestCase):
    def test_scanner_blocks_keys_and_never_echoes_them(self):
        import portable
        fake = "sk-proj-" + "A" * 30
        out = portable.scan_text(f"memory: use {fake}")
        self.assertEqual(out["verdict"], "BLOCK")
        self.assertNotIn(fake, str(out))

    def test_scanner_warns_on_generic_assignment_and_passes_clean_text(self):
        import portable
        self.assertEqual(portable.scan_text("password: hunter2hunter2hunter2")["verdict"], "WARN")
        self.assertEqual(portable.scan_text("Write three bullets every Friday.")["verdict"], "CLEAN")

    def test_bundled_templates_are_valid_clean_and_affordable(self):
        import json as _json
        import portable
        found = portable.bundled_templates()
        self.assertGreaterEqual(len(found), 5)
        for name, path in found.items():
            tpl = portable.load_template(path)
            self.assertEqual(portable.scan_text(_json.dumps(tpl))["verdict"], "CLEAN", name)
            self.assertIn(f"You are **{tpl['display_name']}**", tpl["soul_md"], name)
            for r in tpl["routines"]:
                self.assertFalse(forge.check_routine(r), f"{name}: {r['schedule']}")

    def test_template_never_contains_history_or_user_facts(self):
        import portable
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = root / "profiles" / "quill"
            (d / "memories").mkdir(parents=True)
            (d / "config.yaml").write_text(yaml.safe_dump({"platform_toolsets": {"cli": ["web"]}}))
            (d / "SOUL.md").write_text("# Quill — Writer\n\nYou are **Quill**.")
            (d / "memories" / "MEMORY.md").write_text("My name is Quill.\n§\nDrafts go out Fridays.")
            (d / "memories" / "USER.md").write_text("User lives in Pune.")
            (d / "state.db").write_text("chat history")
            (d / "journal").mkdir()
            (d / "journal" / "2026-09-20.md").write_text("secret work journal entry")
            tpl = portable.build_template(d, root)
            blob = str(tpl)
            self.assertNotIn("Pune", blob)
            self.assertNotIn("chat history", blob)
            self.assertNotIn("secret work journal entry", blob)
            self.assertEqual(tpl["memory"], ["Drafts go out Fridays."])
            self.assertEqual(tpl["role"], "Writer")



class WorkspaceSurvey(unittest.TestCase):
    """Where a Bot fits, read once at birth so it never researches its own machine again."""

    def _workspace(self, tmp):
        ws = tmp / "work"
        (ws / "x-content" / ".git").mkdir(parents=True)
        (ws / "x-content" / "README.md").write_text(
            "<p align=\"center\"><img src=\"b.png\"></p>\n\n# X Content Studio\n\n"
            "Drafts, threads and the posting calendar for x.com.\n")
        (ws / "billing-api").mkdir(parents=True)
        (ws / "billing-api" / "README.md").write_text("# Billing API\n\nStripe invoices and refunds.\n")
        (ws / "billing-api" / "node_modules" / "junk").mkdir(parents=True)
        (ws / "billing-api" / "node_modules" / "junk" / "README.md").write_text("# threads x.com social\n")
        return ws

    def _bot(self, root, name, title, one_job):
        d = root / "profiles" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.yaml").write_text(yaml.safe_dump({"model": {"default": "m"}}))
        (d / "profile.yaml").write_text(yaml.safe_dump({"ui_meta": {"hermes-bots": {"title": title}}}))
        (d / "SOUL.md").write_text(f"# {title}\n\n## Your one job\n{one_job}\n")
        return d

    def test_it_finds_the_place_that_matches_the_job(self):
        import survey
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root, ws = make_root(tmp), self._workspace(tmp)
            out = survey.survey(root, {"role": "social media manager",
                                       "one_job": "write x.com posts and threads"},
                                {"workspace_roots": [str(ws)]})
            names = [f["name"] for f in out["fits"]]
            self.assertIn("x-content", names)
            self.assertLess(names.index("x-content"), names.index("billing-api") if "billing-api" in names else 99)
            top = out["fits"][0]
            self.assertEqual(top["headline"], "X Content Studio", "headline should skip the badge markup")
            self.assertTrue(top["repo"])

    def test_it_never_walks_into_dependency_trees(self):
        import survey
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root, ws = make_root(tmp), self._workspace(tmp)
            index = survey.workspace_index(root, {"workspace_roots": [str(ws)]}, refresh=True)
            self.assertFalse([p for p in index["places"] if "node_modules" in p["path"]])

    def test_a_bot_already_doing_the_job_is_refused(self):
        import survey
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = make_root(tmp)
            self._bot(root, "nova", "Nova", "write and schedule x.com posts, threads and replies")
            index = survey.workspace_index(root, {"workspace_roots": [str(tmp / "empty")]}, refresh=True)
            wanted = survey.job_terms({"role": "x.com writer", "one_job": "write x.com posts and threads"})
            guard = survey.overlap_guard(index, wanted)
            self.assertIsNotNone(guard)
            self.assertEqual(guard["bot"], "nova")
            self.assertIn(guard["verdict"], ("duplicate", "adjacent"))

    def test_an_unrelated_job_is_not_blocked(self):
        import survey
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = make_root(tmp)
            self._bot(root, "nova", "Nova", "write and schedule x.com posts, threads and replies")
            index = survey.workspace_index(root, {"workspace_roots": [str(tmp / "empty")]}, refresh=True)
            wanted = survey.job_terms({"role": "recipe keeper", "one_job": "store and scale family recipes"})
            self.assertIsNone(survey.overlap_guard(index, wanted))

    def test_stemming_matches_two_personas_that_use_different_words(self):
        import survey
        a = survey.terms("write and schedule posts")
        b = survey.terms("writing, scheduling and repurposing a post")
        self.assertTrue({"writ", "schedul", "post"} <= (a & b), sorted(a & b))

    def test_words_that_describe_everything_here_are_dropped(self):
        import survey
        self.assertEqual(survey.terms("hermes agent plugin skill"), set())
        # but the words a Bot is made of survive, unlike forge's connector stopwords
        self.assertTrue({"post", "media", "manag"} <= survey.terms("posts media manage"))

    def test_the_survey_is_written_into_memory_once(self):
        import survey
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root, ws = make_root(tmp), self._workspace(tmp)
            d = root / "profiles" / "quill"
            (d / "memories").mkdir(parents=True)
            (d / "memories" / "MEMORY.md").write_text("My name is Quill.\n")
            found = survey.survey(root, {"role": "social media manager",
                                         "one_job": "write x.com posts and threads"},
                                  {"workspace_roots": [str(ws)]})
            self.assertTrue(survey.attach(d, found))
            once = (d / "memories" / "MEMORY.md").read_text()
            self.assertIn("My name is Quill.", once)
            self.assertIn(survey.WORKSPACE_MARKER, once)
            self.assertIn("x-content", once)
            self.assertFalse(survey.attach(d, found))
            self.assertEqual((d / "memories" / "MEMORY.md").read_text(), once)

    def test_a_path_that_looks_like_a_credential_never_reaches_memory(self):
        import survey
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "quill"
            (d / "memories").mkdir(parents=True)
            poisoned = {"fits": [{"name": "keys", "path": "/w/keys",
                                  "headline": "AKIAIOSFODNN7EXAMPLE aws key", "repo": False}],
                        "covered_by": [], "skills_here": [], "next_steps": []}
            self.assertFalse(survey.attach(d, poisoned))
            self.assertFalse((d / "memories" / "MEMORY.md").exists())

    def test_the_index_is_reused_instead_of_rescanned(self):
        import survey
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root, ws = make_root(tmp), self._workspace(tmp)
            settings = {"workspace_roots": [str(ws)]}
            first = survey.workspace_index(root, settings, refresh=True)
            self.assertTrue(survey.index_file(root).exists())
            calls = []
            real = survey.scan_places
            survey.scan_places = lambda *a, **k: calls.append(1) or real(*a, **k)
            self.addCleanup(setattr, survey, "scan_places", real)
            second = survey.workspace_index(root, settings)
            self.assertEqual(calls, [], "a cached index must not rescan the disk")
            self.assertEqual(second["places"], first["places"])

    def test_the_home_directory_is_never_a_root_by_itself(self):
        import survey
        self.assertNotIn(Path.home(), survey.default_roots())

    def test_an_empty_vocabulary_scores_zero_rather_than_dividing_by_it(self):
        import survey
        self.assertEqual(survey.overlap(set(), {"a"}), 0.0)
        self.assertEqual(survey.overlap({"a"}, set()), 0.0)
        self.assertEqual(survey.covered_share(set(), {"a"}), 0.0)

    def test_a_specific_term_outweighs_a_generic_one(self):
        import survey
        self.assertGreater(survey.weight("social-media"), survey.weight("media"))
        self.assertGreater(survey.weight("x.com"), survey.weight("post"))


