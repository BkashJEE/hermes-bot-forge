"""Sharing a Bot as a link, and taking one in from a link.

`support` is imported for its side effect: it is the one place sys.path is arranged, and the
tests below import `publish` inside each method. Without it those imports resolve only when
another test module happens to have been loaded first.
"""
import unittest

import support  # noqa: F401  (imported for the sys.path setup; see the docstring)


class ShareAsALink(unittest.TestCase):
    """A Bot you can send someone, and one you can take back."""

    class FakeRun:
        def __init__(self, rc=0, out="https://gist.github.com/u/abc123\n", err=""):
            self.rc, self.out, self.err, self.seen = rc, out, err, []

        def __call__(self, cmd, payload):
            import subprocess
            self.seen.append((cmd, payload))
            return subprocess.CompletedProcess(cmd, self.rc, self.out, self.err)

    def test_publishing_returns_a_link_and_says_who_can_read_it(self):
        """"Secret" gist reads as private; it is not. The result has to say so."""
        import publish
        self.addCleanup(setattr, publish, "gh_ready", publish.gh_ready)
        publish.gh_ready = lambda: (True, "")
        run = self.FakeRun()
        out = publish.publish('{"role": "writer"}', "quill.botforge.json", "a Bot", runner=run)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["url"], "https://gist.github.com/u/abc123")
        self.assertIn("anyone with this link can read", out["visibility"])
        self.assertIn("not your chats", out["visibility"])
        cmd, payload = run.seen[0]
        self.assertIn("gist", cmd)
        self.assertIn('"role": "writer"', payload)

    def test_no_github_cli_is_a_reason_not_a_crash(self):
        import publish
        self.addCleanup(setattr, publish, "gh_ready", publish.gh_ready)
        publish.gh_ready = lambda: (False, "the GitHub CLI is installed but not signed in — run `gh auth login`")
        out = publish.publish("{}", "x.json", "d")
        self.assertFalse(out["ok"])
        self.assertIn("gh auth login", out["error"])

    def test_only_https_links_are_read(self):
        import publish
        for url in ("http://example.com/bot.json", "file:///etc/passwd", "ftp://x/y"):
            self.assertFalse(publish.fetch(url)["ok"], url)
        self.assertIn("only https", publish.fetch("http://example.com/b.json")["error"])

    def test_a_description_header_does_not_stop_the_import(self):
        """`gh gist view --raw` prints the gist description above the file."""
        import publish
        body = 'Hermes Bot: Pane — import with Bot Forge\n\n{"role": "portal operator"}\n'
        self.addCleanup(setattr, publish, "fetch", publish.fetch)
        publish.fetch = lambda url, opener=None: {"ok": True, "text": body, "source": url}
        out = publish.read_shared("https://gist.github.com/u/abc123")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["spec"]["role"], "portal operator")

    def test_something_that_is_not_a_bot_is_refused(self):
        import publish
        self.addCleanup(setattr, publish, "fetch", publish.fetch)
        publish.fetch = lambda url, opener=None: {"ok": True, "text": "<html>hello</html>", "source": url}
        self.assertIn("not a Bot template", publish.read_shared("https://x/y")["error"])
        publish.fetch = lambda url, opener=None: {"ok": True, "text": '{"name": "no role here"}', "source": url}
        self.assertIn("no role", publish.read_shared("https://x/y")["error"])

    def test_a_shared_bot_carrying_a_credential_is_scanned(self):
        import publish
        self.addCleanup(setattr, publish, "fetch", publish.fetch)
        poisoned = '{"role": "writer", "memory": ["the key is AKIAIOSFODNN7EXAMPLE"]}'
        publish.fetch = lambda url, opener=None: {"ok": True, "text": poisoned, "source": url}
        out = publish.read_shared("https://x/y")
        self.assertTrue(out["ok"])
        self.assertEqual(out["scan"]["verdict"], "BLOCK",
                         "import must be able to refuse someone else's leaked key")

    def test_an_oversized_link_is_not_a_template(self):
        import io
        import publish

        class Big(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        out = publish.fetch("https://x/y", opener=lambda r, timeout=0: Big(b"x" * (publish.MAX_FETCH_BYTES + 10)))
        self.assertFalse(out["ok"])
        self.assertIn("larger than", out["error"])
