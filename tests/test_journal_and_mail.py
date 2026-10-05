"""The work journal, the waiting queue, and the outbound mail they trigger.

Split out of tests/test_forge.py, which had grown past 2,300 lines; the shared helpers
and the sys.path setup Hermes-style imports need live in tests/support.py.
"""
import json
import tempfile
import unittest
from datetime import UTC
from pathlib import Path
from unittest import mock

from support import journal, make_root, yaml


class Journal(unittest.TestCase):
    def _bot(self, root, name="quill"):
        d = root / "profiles" / name
        d.mkdir(exist_ok=True)
        (d / "config.yaml").write_text(yaml.safe_dump({"model": {"default": "m"}}))
        (d / "profile.yaml").write_text(yaml.safe_dump({"ui_meta": {"hermes-bots": {"title": "Quill"}}}))
        (d / "SOUL.md").write_text("# Quill — Writer\n\nYou are **Quill**, a writer.\n")
        return d

    def test_enable_is_idempotent_and_preserves_persona(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            pdir = self._bot(root)
            first = journal.operate({"action": "enable", "name": "quill", "hermes_root": str(root)})
            second = journal.operate({"action": "enable", "name": "quill", "hermes_root": str(root)})
            self.assertTrue(first["ok"], first)
            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            soul = (pdir / "SOUL.md").read_text()
            self.assertEqual(soul.count(journal.JOURNAL_MARKER), 1)
            self.assertIn("You are **Quill**", soul)
            self.assertTrue((pdir / "journal" / "README.md").exists())

    def test_add_and_read_factual_entry(self):
        from datetime import datetime

        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            pdir = self._bot(root)
            journal.enable_journal(pdir)
            out = journal.add_entry(pdir, {"title": "Prepared launch draft", "summary": "Drafted three posts.",
                                                   "status": "completed", "evidence": ["drafts/x-launch.md"],
                                                   "next_steps": ["Owner reviews the hooks"], "tags": ["X", "launch"]},
                                    now=datetime(2026, 9, 20, 20, 30, tzinfo=UTC))
            self.assertTrue(out["written"])
            read = journal.read_entries(pdir, {"query": "three posts", "limit": 5})
            self.assertEqual(read["count"], 1)
            self.assertIn("completed", read["entries"][0]["entry"])
            self.assertIn("drafts/x-launch.md", read["entries"][0]["entry"])

    def test_secret_is_refused_without_echoing_value(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            pdir = self._bot(root)
            journal.enable_journal(pdir)
            fake = "sk-proj-" + "Z" * 30
            out = journal.operate({"action": "add", "name": "quill", "hermes_root": str(root),
                                   "title": "Configured API", "summary": f"Used {fake}"})
            self.assertFalse(out["ok"])
            self.assertNotIn(fake, str(out))
            self.assertEqual(list((pdir / "journal").glob("????-??-??.md")), [])

    def test_reading_disabled_journal_is_non_mutating(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            pdir = self._bot(root)
            out = journal.operate({"action": "read", "name": "quill", "hermes_root": str(root)})
            self.assertTrue(out["ok"], out)
            self.assertFalse(out["enabled"])
            self.assertEqual(out["entries"], [])
            self.assertFalse((pdir / "journal").exists())

    def test_root_profile_cannot_be_targeted(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            out = journal.operate({"action": "enable", "name": "default", "hermes_root": str(root)})
            self.assertFalse(out["ok"])
            self.assertIn("Bot name", out["error"])


class JournalPrivacy(unittest.TestCase):
    """A journal is the Bot's private record: it must never ride along in something shareable."""

    def _journaling_bot(self, root):
        import journal
        d = root / "profiles" / "quill"
        (d / "memories").mkdir(parents=True)
        (d / "config.yaml").write_text(yaml.safe_dump({"platform_toolsets": {"cli": ["web"]}}))
        (d / "profile.yaml").write_text(yaml.safe_dump({"ui_meta": {"hermes-bots": {"title": "Quill"}}}))
        (d / "SOUL.md").write_text("# Quill — Writer\n\nYou are **Quill**.\n")
        (d / "memories" / "MEMORY.md").write_text("Drafts go out Fridays.")
        journal.enable_journal(d)
        journal.add_entry(d, {"title": "Wrote the Q3 launch thread", "status": "completed",
                              "summary": "Drafted eight posts about the internal pricing change.",
                              "evidence": ["posts saved to drafts/q3.md"]})
        return d

    def test_shared_template_carries_no_journal_entries(self):
        import portable
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = self._journaling_bot(root)
            blob = json.dumps(portable.build_template(d, root))
            self.assertNotIn("Q3 launch thread", blob)
            self.assertNotIn("internal pricing", blob)
            self.assertNotIn("drafts/q3.md", blob)

    def test_journal_files_live_only_inside_the_profile(self):
        import journal
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = self._journaling_bot(root)
            written = list((d / "journal").glob("????-??-??.md"))
            self.assertTrue(written)
            for f in written:
                self.assertTrue(f.resolve().is_relative_to(d.resolve()))
                self.assertEqual(f.stat().st_mode & 0o777, 0o600)
            self.assertEqual((d / "journal").stat().st_mode & 0o777, 0o700)
            self.assertTrue(journal.journaling_enabled(d))

    def test_a_symlinked_journal_directory_is_refused(self):
        import journal
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            d = root / "profiles" / "quill"
            d.mkdir(parents=True)
            elsewhere = Path(t) / "outside"
            elsewhere.mkdir()
            (d / "journal").symlink_to(elsewhere)
            with self.assertRaises(ValueError):
                journal.ensure_journal(d)



class WaitingQueueTests(unittest.TestCase):
    """What is still waiting on the user, read out of the Bots' own journals."""

    def _bot(self, root, name, title, entries):
        import journal
        d = root / "profiles" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.yaml").write_text(yaml.safe_dump({"model": {"default": "m", "provider": "p"}}))
        (d / "profile.yaml").write_text(yaml.safe_dump({"ui_meta": {"hermes-bots": {"title": title}}}))
        journal.ensure_journal(d)
        for day, stamp, status, title_, body in entries:
            f = d / "journal" / f"{day}.md"
            f.write_text((f.read_text() if f.exists() else "")
                         + f"\n## {stamp} · {status} · {title_}\n{body}\n")
        return d

    def test_blocked_bots_surface_with_bot_name_age_and_detail(self):
        import waiting
        from datetime import datetime
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            self._bot(root, "marlow", "Marlow", [
                ("2026-09-20", "2026-09-20T09:00:00Z", "blocked", "Need the Stripe key",
                 "Invoice sync cannot run without it.")])
            now = datetime(2026, 9, 24, 9, 0, tzinfo=UTC)
            out = waiting.waiting_on_user(root, now)
            self.assertEqual(out["count"], 1)
            item = out["items"][0]
            self.assertEqual(item["display_name"], "Marlow")
            self.assertEqual(item["bot"], "marlow")
            self.assertEqual(item["age_days"], 4.0)
            self.assertEqual(item["icon"], "⚠️")
            self.assertIn("Invoice sync", item["detail"])
            self.assertIn("Marlow: Need the Stripe key", out["summary"])

    def test_a_later_completion_closes_the_item(self):
        import waiting
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            self._bot(root, "marlow", "Marlow", [
                ("2026-09-20", "2026-09-20T09:00:00Z", "blocked", "Need the Stripe key", "waiting"),
                ("2026-09-21", "2026-09-21T09:00:00Z", "completed", "Need the Stripe key", "got it")])
            self.assertEqual(waiting.waiting_on_user(root)["count"], 0)

    def test_finished_and_planned_work_never_counts_as_waiting(self):
        import waiting
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            self._bot(root, "nova", "Nova", [
                ("2026-09-20", "2026-09-20T09:00:00Z", "completed", "Wrote the post", "done"),
                ("2026-09-20", "2026-09-20T10:00:00Z", "planned", "Next week's posts", "later"),
                ("2026-09-20", "2026-09-20T11:00:00Z", "progress", "Drafting", "ongoing")])
            out = waiting.waiting_on_user(root)
            self.assertEqual(out["count"], 0)
            self.assertEqual(out["summary"], "nothing is waiting on you")

    def test_newest_first_and_capped(self):
        import waiting
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            self._bot(root, "marlow", "Marlow", [
                (f"2026-08-{d:02d}", f"2026-08-{d:02d}T09:00:00Z", "failed", f"item {d}", "x")
                for d in range(1, 29)])
            out = waiting.waiting_on_user(root)
            self.assertEqual(out["count"], waiting.MAX_ITEMS)
            self.assertEqual(out["items"][0]["title"], "item 28")
            self.assertIn("more)", out["summary"])

    def test_a_bot_without_a_journal_is_simply_quiet(self):
        import waiting
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t), profiles=("gary",))
            self.assertEqual(waiting.waiting_on_user(root)["count"], 0)

    def test_health_leads_with_what_is_waiting(self):
        import health
        with tempfile.TemporaryDirectory() as t:
            root = make_root(Path(t))
            self._bot(root, "nova", "Nova", [
                ("2026-09-20", "2026-09-20T09:00:00Z", "failed", "Could not publish", "needs approval")])
            out = health.check({"hermes_root": str(root)})
            self.assertEqual(out["waiting_count"], 1)
            self.assertTrue(out["summary"].startswith("1 waiting on you"))
            self.assertEqual(out["waiting_on_you"][0]["title"], "Could not publish")


class OutboundMail(unittest.TestCase):
    """A Bot tells you it is blocked. It cannot tell anyone else anything."""

    def _root(self, tmp, **env):
        root = make_root(Path(tmp))
        lines = {"EMAIL_SMTP_HOST": "smtp.example.com", "EMAIL_ADDRESS": "me@example.com",
                 "EMAIL_PASSWORD": "hunter2", **env}
        (root / ".env").write_text("\n".join(f"{k}={v}" for k, v in lines.items() if v) + "\n")
        return root

    def _bot(self, root, name="marlow", title="Marlow"):
        d = root / "profiles" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.yaml").write_text(yaml.safe_dump({"model": {"default": "m"}}))
        (d / "profile.yaml").write_text(yaml.safe_dump({"ui_meta": {"hermes-bots": {"title": title}}}))
        return d

    class Outbox:
        def __init__(self): self.sent = []
        def __call__(self, config, message): self.sent.append((config, message))

    def test_the_password_never_crosses_an_unverified_or_cleartext_link(self):
        import smtplib
        import ssl
        from email.message import EmailMessage
        import notify

        calls = []

        class FakeSMTP:
            starttls_error = None
            def __init__(self, *a, **kw): calls.append(("connect", a))
            def __enter__(self): return self
            def __exit__(self, *exc): return False
            def ehlo(self): pass
            def starttls(self, context=None):
                calls.append(("starttls", context))
                if self.starttls_error:
                    raise self.starttls_error
            def login(self, user, password): calls.append(("login", user))
            def send_message(self, message): calls.append(("send", None))

        config = {"host": "smtp.example.com", "port": 587, "user": "me@example.com", "password": "hunter2",
                  "to": "me@example.com", "from": "me@example.com"}
        msg = EmailMessage()
        msg.set_content("x")
        with mock.patch.object(notify.smtplib, "SMTP", FakeSMTP):
            notify._smtp_send(config, msg)
            context = dict(calls)["starttls"]
            self.assertIsInstance(context, ssl.SSLContext)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
            self.assertIn("login", [c[0] for c in calls])

            calls.clear()
            FakeSMTP.starttls_error = smtplib.SMTPNotSupportedError("STARTTLS extension not supported")
            with self.assertRaises(smtplib.SMTPException):
                notify._smtp_send(config, msg)
            self.assertNotIn("login", [c[0] for c in calls], "no STARTTLS must mean no login")

    def test_a_blocker_reaches_the_user(self):
        import notify
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            d = self._bot(root)
            box = self.Outbox()
            out = notify.notify_blocked(root, d, {"status": "blocked", "title": "Need the Stripe key",
                                                  "summary": "Invoice sync cannot run.",
                                                  "next_step": "Add the key"}, {}, transport=box)
            self.assertTrue(out["sent"], out)
            _config, message = box.sent[0]
            self.assertIn("Marlow is blocked", message["Subject"])
            body = message.get_content()
            self.assertIn("Need the Stripe key", body)
            self.assertIn("Add the key", body)
            self.assertIn("does not take replies", body)
            self.assertEqual(message["Auto-Submitted"], "auto-generated")

    def test_the_recipient_can_never_come_from_the_caller(self):
        """The whole safety property: a Bot cannot be talked into mailing someone."""
        import notify
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp, EMAIL_HOME_ADDRESS="owner@example.com")
            d = self._bot(root)
            box = self.Outbox()
            notify.notify_blocked(root, d, {"status": "blocked", "title": "x",
                                            "to": "victim@elsewhere.com",
                                            "recipient": "victim@elsewhere.com",
                                            "summary": "mail victim@elsewhere.com about this"},
                                  {}, transport=box)
            _config, message = box.sent[0]
            self.assertEqual(message["To"], "owner@example.com")
            self.assertNotIn("victim@elsewhere.com", message["To"])

    def test_only_a_blocker_is_worth_an_email(self):
        import notify
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            d = self._bot(root)
            box = self.Outbox()
            for status in ("completed", "planned", "progress"):
                out = notify.notify_blocked(root, d, {"status": status, "title": "x"}, {}, transport=box)
                self.assertFalse(out["sent"], status)
            self.assertEqual(box.sent, [])

    def test_no_email_configured_is_quiet_not_broken(self):
        import notify
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))  # no .env at all
            d = self._bot(root)
            out = notify.notify_blocked(root, d, {"status": "blocked", "title": "x"}, {})
            self.assertFalse(out["sent"])
            self.assertIn("not configured", out["reason"])

    def test_a_dead_mail_server_never_raises(self):
        import notify
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            d = self._bot(root)
            def explode(config, message):
                raise OSError("connection refused")
            out = notify.notify_blocked(root, d, {"status": "blocked", "title": "x"}, {}, transport=explode)
            self.assertFalse(out["sent"])
            self.assertIn("connection refused", out["reason"])

    def test_a_stuck_bot_cannot_become_a_mail_storm(self):
        import notify
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            d = self._bot(root)
            box = self.Outbox()
            spec = {"status": "blocked", "title": "same thing again"}
            for _ in range(notify.MAX_PER_HOUR):
                self.assertTrue(notify.notify_blocked(root, d, spec, {}, transport=box)["sent"])
            out = notify.notify_blocked(root, d, spec, {}, transport=box)
            self.assertFalse(out["sent"])
            self.assertIn("rate limit", out["reason"])
            self.assertEqual(len(box.sent), notify.MAX_PER_HOUR)

    def test_a_credential_in_the_body_is_refused(self):
        import notify
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            box = self.Outbox()
            out = notify.send(root, "subject", "the key is AKIAIOSFODNN7EXAMPLE",
                              {}, bot="marlow", transport=box)
            self.assertFalse(out["sent"])
            self.assertIn("credential", out["reason"])
            self.assertEqual(box.sent, [])

    def test_the_digest_carries_the_whole_queue(self):
        import notify
        with tempfile.TemporaryDirectory() as tmp:
            self._root(tmp)
            subject, body = notify.compose_digest({"count": 2, "items": [
                {"display_name": "Marlow", "title": "Need the Stripe key", "age_days": 4.0,
                 "detail": "invoice sync"},
                {"display_name": "Nova", "title": "Draft could not publish", "age_days": 0.5, "detail": ""}]})
            self.assertIn("2 waiting on you", subject)
            self.assertIn("Marlow: Need the Stripe key", body)
            self.assertIn("(4.0d)", body)
            self.assertIn("Nova", body)

    def test_an_empty_queue_sends_nothing(self):
        import notify
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            box = self.Outbox()
            out = notify.notify_waiting(root, {}, transport=box)
            self.assertFalse(out["sent"])
            self.assertEqual(box.sent, [])

    def test_it_can_be_switched_off(self):
        import notify
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            d = self._bot(root)
            box = self.Outbox()
            off = notify.notify_blocked(root, d, {"status": "blocked", "title": "x"},
                                        {"notify_blocked": False}, transport=box)
            self.assertFalse(off["sent"])
            self.assertEqual(notify.mail_config(root, {"notify_email": False}), {})

    def test_a_configured_address_wins_over_the_mailbox(self):
        import notify
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp, EMAIL_HOME_ADDRESS="home@example.com")
            self.assertEqual(notify.mail_config(root, {})["to"], "home@example.com")
            self.assertEqual(notify.mail_config(root, {"notify_email": "other@example.com"})["to"],
                             "other@example.com")


class ScheduledDigest(unittest.TestCase):
    """The waiting queue delivers itself, with no model turn and no mail setup."""

    def test_an_empty_queue_prints_nothing(self):
        """Silence is the feature: a daily "nothing is waiting" teaches you to ignore it."""
        import notify
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(notify.digest_text(make_root(Path(tmp))), "")

    def test_the_text_drops_the_email_wording(self):
        """Through Hermes' cron this may land in Telegram, where "this address" means nothing."""
        import notify
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            d = root / "profiles" / "nova"
            (d / "journal").mkdir(parents=True)
            (d / "config.yaml").write_text(yaml.safe_dump({"model": {"default": "m"}}))
            (d / "profile.yaml").write_text(yaml.safe_dump({"ui_meta": {"hermes-bots": {"title": "Nova"}}}))
            (d / "journal" / "2026-09-20.md").write_text(
                "\n## 2026-09-20T09:00:00Z \u00b7 blocked \u00b7 Draft could not publish\nneeds approval\n")
            text = notify.digest_text(root)
            self.assertIn("Nova: Draft could not publish", text)
            self.assertIn("Answer any of them in Hermes.", text)
            self.assertNotIn("this address", text)

    def test_the_script_goes_where_that_profile_will_look(self):
        """Hermes resolves --script against the running profile's scripts/, not the root's."""
        import notify
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            self.assertEqual(notify.scripts_dir(root, "ceo"), root / "profiles" / "ceo" / "scripts")
            self.assertEqual(notify.scripts_dir(root, ""), root / "scripts")
            path = notify.install_launcher(root, Path("/plug"), "ceo")
            self.assertEqual(path.parent, root / "profiles" / "ceo" / "scripts")
            self.assertIn("/plug/notify.py", path.read_text())
            self.assertIn("--stdout", path.read_text())

    def test_the_active_profile_is_read_from_the_diamond(self):
        import notify
        import subprocess
        listing = ("  Omarchy (default) gpt-5.6-sol    running\n"
                   " \u25c6Sanvith \u2014 Chief of Staff (ceo) gpt-6-astra  running\n"
                   "  Nova \u2014 CMO (nova) ornith-1.5-9b   running\n")
        out = subprocess.CompletedProcess([], 0, listing, "")
        self.assertEqual(notify.active_profile(Path("/x"), runner=lambda: out), "ceo")
        plain = subprocess.CompletedProcess([], 0, " \u25c6Omarchy (default) gpt-5.6-sol running\n", "")
        self.assertEqual(notify.active_profile(Path("/x"), runner=lambda: plain), "",
                         "the default profile takes no -p flag")

    def test_scheduling_uses_no_model_turn(self):
        import notify
        import subprocess
        seen = {}

        def fake_run(args):
            seen["args"] = args
            return subprocess.CompletedProcess(args, 0, "created", "")
        with tempfile.TemporaryDirectory() as tmp:
            out = notify.schedule(make_root(Path(tmp)), "0 8 * * *", profile="ceo",
                                  plugin_dir=Path("/plug"), runner=fake_run)
        self.assertTrue(out["ok"], out)
        self.assertIn("--no-agent", seen["args"], "the digest is deterministic; never call the model")
        self.assertIn("--script", seen["args"])
        self.assertIn(notify.SCRIPT_NAME, seen["args"])
        self.assertEqual(out["profile"], "ceo")
        self.assertIn("no email setup needed", out["delivery"])

    def test_a_refusal_keeps_the_reason(self):
        import notify
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            out = notify.schedule(make_root(Path(tmp)), "0 8 * * *", profile="ceo",
                                  plugin_dir=Path("/plug"),
                                  runner=lambda a: subprocess.CompletedProcess(a, 1, "", "no such profile"))
        self.assertFalse(out["ok"])
        self.assertIn("no such profile", out["error"])
