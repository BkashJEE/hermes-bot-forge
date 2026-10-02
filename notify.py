"""Outbound-only mail: a Bot tells you when it is blocked, so you find out before you ask.

`check_agents` already gathers what is waiting on the user, but only when the user thinks to ask.
This is the other half — the push. A Bot that records a blocker can send one plain-text email, and
a scheduled digest can send the whole queue.

The shape of this is chosen to be boring on purpose:

* **The recipient is never an argument.** It comes from this plugin's `notify_email`, or Hermes'
  own `EMAIL_HOME_ADDRESS`, or the mailbox the account sends from — never from a tool call, a
  persona, or anything a model wrote. A Bot cannot mail a stranger, so the usual agent-email
  failure modes (a model talked into contacting someone, two agents replying to each other
  forever) have nowhere to go.
* **It reuses Hermes' own credentials.** `EMAIL_SMTP_HOST`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD` are
  already how Hermes does email. Nothing new to configure, and nothing new to leak.
* **Outbound only.** Nothing here reads a mailbox or accepts a reply. You answer the Bot in Hermes,
  where the work is.
* **Rate limited, secret-scanned, and silent on failure.** A Bot that cannot send simply doesn't;
  no turn, journal write or routine ever breaks because a mail server was unreachable.
"""

import json
import os
import re
import smtplib
import ssl
import time
from email.message import EmailMessage
from pathlib import Path

if __package__:  # Hermes imports this as a package; the CLI entry points run it as a script
    from . import forge
else:
    import forge

STATE_REL = Path(".bot-forge") / "notify.json"
DEFAULT_PORT = 587
MAX_PER_HOUR = 4          # a stuck routine must not become a mail storm
MAX_BODY = 4000
SUBJECT_PREFIX = "[Bot Forge]"
ENV_KEYS = ("EMAIL_ADDRESS", "EMAIL_PASSWORD", "EMAIL_SMTP_HOST", "EMAIL_SMTP_PORT",
            "EMAIL_HOME_ADDRESS")


def _env(root: Path, key: str) -> str:
    """Hermes' own email settings: the live environment first, then its `.env` on disk.

    A plugin running inside the gateway inherits the environment; one shelled out from a tool or a
    cron job may not, and the answer is sitting in the same file Hermes reads.
    """
    value = os.environ.get(key)
    if value:
        return value.strip()
    try:
        text = (Path(root) / ".env").read_text(errors="ignore")
    except OSError:
        return ""
    m = re.search(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=\s*(.+?)\s*$", text, re.M)
    return m.group(1).strip().strip("'\"") if m else ""


def mail_config(root: Path, settings: dict | None = None) -> dict:
    """Everything needed to send, or `{}` when email is not set up.

    `to` is resolved here and only here. Nothing downstream may override it.
    """
    settings = settings or {}
    if settings.get("notify_email") is False:
        return {}
    root = Path(root)
    host = _env(root, "EMAIL_SMTP_HOST")
    user = _env(root, "EMAIL_ADDRESS")
    password = _env(root, "EMAIL_PASSWORD")
    configured = settings.get("notify_email")
    to = (configured if isinstance(configured, str) and "@" in configured else "") \
        or _env(root, "EMAIL_HOME_ADDRESS") or user
    if not (host and user and password and to):
        return {}
    try:
        port = int(_env(root, "EMAIL_SMTP_PORT") or DEFAULT_PORT)
    except ValueError:
        port = DEFAULT_PORT
    return {"host": host, "port": port, "user": user, "password": password, "to": to, "from": user}


# ── rate limit ───────────────────────────────────────────────────────────────
def _state_file(root: Path) -> Path:
    return Path(root) / STATE_REL


def _load_state(root: Path) -> dict:
    try:
        return json.loads(_state_file(root).read_text(errors="ignore"))
    except (OSError, ValueError):
        return {}


def _rate_ok(root: Path, bot: str, now: float, limit: int = MAX_PER_HOUR) -> bool:
    sent = [t for t in (_load_state(root).get(bot) or []) if now - t < 3600]
    return len(sent) < limit


def _record(root: Path, bot: str, now: float) -> None:
    state = _load_state(root)
    state[bot] = [t for t in (state.get(bot) or []) if now - t < 3600] + [now]
    f = _state_file(root)
    try:
        f.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        f.write_text(json.dumps(state))
        os.chmod(f, 0o600)
    except OSError:
        pass


# ── composing ────────────────────────────────────────────────────────────────
def _clean(value: object, limit: int = 300) -> str:
    return " ".join(str(value or "").split())[:limit]


def compose_blocked(display_name: str, bot: str, spec: dict) -> tuple:
    """One blocker, in the fewest words that let the user act."""
    title = _clean(spec.get("title")) or "something is blocked"
    status = _clean(spec.get("status"), 20).lower() or "blocked"
    lines = [f"{display_name} stopped and needs you.", "", f"  {title}", ""]
    if spec.get("summary"):
        lines += [_clean(spec.get("summary"), 800), ""]
    if spec.get("next_step"):
        lines += [f"Next step: {_clean(spec.get('next_step'), 300)}", ""]
    lines += [f"Reply to {display_name} in Hermes — this address does not take replies.",
              f"Open it with:  hermes -p {bot} chat -c 'Bot Chat'"]
    return f"{SUBJECT_PREFIX} {display_name} is {status} — {title}"[:180], "\n".join(lines)


def compose_digest(waiting: dict) -> tuple:
    """The whole queue, oldest pain first."""
    items = waiting.get("items") or []
    if not items:
        return "", ""
    head = f"{len(items)} waiting on you"
    lines = [head, ""]
    for item in items:
        age = item.get("age_days")
        age_text = f"{age}d" if isinstance(age, (int, float)) else "—"
        lines.append(f"  {item.get('display_name', item.get('bot'))}: {_clean(item.get('title'))}  ({age_text})")
        if item.get("detail"):
            lines.append(f"      {_clean(item.get('detail'), 200)}")
    lines += ["", "Answer any of them in Hermes; this address does not take replies."]
    return f"{SUBJECT_PREFIX} {head}", "\n".join(lines)


# ── sending ──────────────────────────────────────────────────────────────────
def _smtp_send(config: dict, message: EmailMessage) -> None:
    # Verify the server's certificate and hostname, and never send the password in cleartext:
    # implicit TLS on 465, otherwise STARTTLS is required (a server or MITM that refuses the
    # upgrade raises here, before login).
    context = ssl.create_default_context()
    if int(config["port"]) == 465:
        with smtplib.SMTP_SSL(config["host"], config["port"], timeout=20, context=context) as smtp:
            smtp.login(config["user"], config["password"])
            smtp.send_message(message)
        return
    with smtplib.SMTP(config["host"], config["port"], timeout=20) as smtp:
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.ehlo()
        smtp.login(config["user"], config["password"])
        smtp.send_message(message)


def send(root: Path, subject: str, body: str, settings: dict | None = None, bot: str = "bot",
         transport=None, now: float | None = None) -> dict:
    """Send one message to the user's own address. Never raises."""
    now = now or time.time()
    if not subject or not body:
        return {"sent": False, "reason": "nothing to say"}
    config = mail_config(root, settings)
    if not config:
        return {"sent": False, "reason": "email is not configured for this Hermes install"}
    if not _rate_ok(root, bot, now):
        return {"sent": False, "reason": f"rate limit: {MAX_PER_HOUR} messages an hour for {bot}"}

    if __package__:
        from . import portable
    else:
        import portable

    body = body[:MAX_BODY]
    scan = portable.scan_text(f"{subject}\n{body}")
    if scan["verdict"] == "BLOCK":
        return {"sent": False, "reason": "refused: the message looks like it contains a credential"}

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config["from"]
    message["To"] = config["to"]          # resolved from config only — never from a caller
    message["Auto-Submitted"] = "auto-generated"   # keeps vacation responders quiet
    message["X-Auto-Response-Suppress"] = "All"
    message.set_content(body)
    try:
        (transport or _smtp_send)(config, message)
    except Exception as exc:
        return {"sent": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}
    _record(root, bot, now)
    return {"sent": True, "to": config["to"], "subject": subject}


# ── the two things worth sending ─────────────────────────────────────────────
def notify_blocked(root: Path, pdir: Path, spec: dict, settings: dict | None = None,
                   transport=None, now: float | None = None) -> dict:
    """Called when a Bot records a blocker. Quiet unless the entry really is one."""
    settings = settings or {}
    if settings.get("notify_blocked") is False:
        return {"sent": False, "reason": "disabled"}
    if _clean(spec.get("status"), 20).lower() not in ("blocked", "failed"):
        return {"sent": False, "reason": "not a blocker"}
    pdir = Path(pdir)
    meta = ((forge.load_yaml(pdir / "profile.yaml").get("ui_meta") or {}).get("hermes-bots") or {})
    display = meta.get("title") or pdir.name
    subject, body = compose_blocked(display, pdir.name, spec)
    return send(root, subject, body, settings, bot=pdir.name, transport=transport, now=now)


def notify_waiting(root: Path, settings: dict | None = None, transport=None,
                   now: float | None = None) -> dict:
    """The digest: everything still waiting, in one message. Nothing waiting, nothing sent."""
    if __package__:
        from . import waiting
    else:
        import waiting

    queue = waiting.waiting_on_user(Path(root))
    subject, body = compose_digest(queue)
    if not subject:
        return {"sent": False, "reason": "nothing is waiting on you", "count": 0}
    result = send(root, subject, body, settings, bot="digest", transport=transport, now=now)
    return {**result, "count": queue["count"]}


def operate(spec: dict) -> dict:
    root = Path(spec.get("hermes_root") or forge.default_root())
    settings = spec.get("settings") or {}
    action = _clean(spec.get("action"), 20).lower() or "digest"
    try:
        if action == "digest":
            return {"ok": True, "action": action, **notify_waiting(root, settings)}
        if action == "status":
            config = mail_config(root, settings)
            return {"ok": True, "action": action, "configured": bool(config),
                    "to": config.get("to", ""), "via": config.get("host", "")}
        return {"ok": False, "error": "action must be digest or status"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main() -> None:
    import sys

    arg = sys.argv[1] if len(sys.argv) > 1 else "-"
    if arg in ("digest", "status"):      # the documented form: no shell pipe to get one action
        spec = {"action": arg}
    elif arg == "-":
        spec = json.loads(sys.stdin.read() or "{}")
    else:
        spec = json.loads(Path(arg).read_text())
    result = operate(spec)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
