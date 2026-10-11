"""A Bot that has hit a login asks for you, instead of failing at the wall.

usage: takeover.py spec.json   (or: takeover.py - < spec.json)

spec:
  {
    "hermes_root": "/home/u/.hermes",
    "from": "marlow",                  # the calling profile, resolved by the tool, never an argument
    "reason": "the site wants a 2FA code sent to your phone",
    "task": "booking the Lisbon flight",        # optional: what it was doing
    "resume": "retry the checkout once signed in",   # optional: what to do after
    "settings": {...}
  }

Hermes already owns the mechanics. `tools/bot_desktop/lease.py` holds a lease with an epoch: a
human acquires the desktop, the Bot's `assert_agent_may_act()` refuses while they hold it, and any
frame captured across the transition is discarded so the Bot never sees what was typed. What was
missing is the *asking*. Nothing let a Bot say "I cannot get past this; take the screen", and
nothing told the user it was stuck.

So this writes a blocked journal entry — which is already what mails the user and already what
`what's waiting on you` reads — carrying the reason and the command that opens that Bot's screen.

It deliberately does **not** claim the Bot will pick the work back up. Resuming on hand-back is a
separate piece of work; saying otherwise here would be the kind of promise this plugin has had to
retract before.
"""
import json
import re
import sys
from pathlib import Path

if __package__:
    from . import forge, journal
else:
    import forge
    import journal

MAX_REASON = 400
MAX_TASK = 200


def clean(text, limit: int) -> str:
    """One line, no control characters, bounded. The reason reaches an email subject and a journal."""
    if not isinstance(text, str):
        return ""
    flat = re.sub(r"\s+", " ", text.replace("\x00", "")).strip()
    return flat[:limit].strip()


def screen_state(root: Path, profile: str, runner=None) -> tuple[bool, str]:
    """Whether this Bot has a screen a human could be handed, and what to say if not.

    Asking for a take-over of a screen that does not exist would send the user to look at nothing,
    so this refuses rather than journalling a blocker nobody can act on.
    """
    run = runner or (lambda: forge.run(root, "-p", profile, "computer-use", "screen", "status",
                                       check=False, timeout=60))
    try:
        out = run()
    except Exception as exc:
        return False, f"could not read the screen status for {profile}: {str(exc)[:160]}"
    text = f"{getattr(out, 'stdout', '')}\n{getattr(out, 'stderr', '')}"
    if getattr(out, "returncode", 1) != 0 and not text.strip():
        return False, ("this Hermes build has no Bot Screen support, so there is no screen to hand "
                       "over")
    if re.search(r"not installed|no screen|not running|install on host", text, re.I):
        return False, (f"{profile} has no running screen to hand over — start one with "
                       f"`hermes -p {profile} computer-use screen start`")
    return True, ""


def compose(profile: str, display: str, reason: str, task: str, resume: str) -> dict:
    """The journal entry. `blocked` is what mails the user and what the waiting queue reads."""
    headline = f"Needs you on its screen: {reason}"
    summary = [reason]
    if task:
        summary.append(f"It was in the middle of: {task}.")
    summary.append(f"Take the screen with `hermes -p {profile} computer-use screen open`, "
                   f"do the sign-in, then hand control back.")
    if resume:
        summary.append(f"Afterwards it should: {resume}")
    summary.append("It will not pick this up by itself — tell it to carry on once you have "
                   "handed back.")
    return {"title": clean(headline, MAX_REASON), "status": "blocked",
            "summary": " ".join(summary),
            "evidence": [f"takeover requested by {display or profile}"],
            "next": resume or "wait for the user to hand the screen back"}


def request(spec: dict, runner=None) -> dict:
    root = Path(spec.get("hermes_root") or forge.default_root())
    profile = re.sub(r"[^a-z0-9_-]", "", str(spec.get("from") or "").lower())
    reason = clean(spec.get("reason"), MAX_REASON)
    task = clean(spec.get("task"), MAX_TASK)
    resume = clean(spec.get("resume"), MAX_TASK)

    if not profile or profile == "default":
        return {"ok": False, "error": "only a Bot can ask for its own screen to be taken over; "
                                      "the main profile already has the user's attention"}
    if not (root / "profiles" / profile / "config.yaml").exists():
        return {"ok": False, "error": f"no Bot named '{profile}'"}
    if not reason:
        return {"ok": False, "error": "say what you are stuck on — the reason is what the user "
                                      "reads before deciding to go and look"}

    ready, why = screen_state(root, profile, runner=runner)
    if not ready:
        return {"ok": False, "error": why}

    display = ""
    try:
        display = forge.load_yaml(root / "profiles" / profile / "profile.yaml").get("display_name") or ""
    except Exception:
        pass

    entry = compose(profile, display, reason, task, resume)
    written = {"written": False, "reason": "journal not enabled"}
    if journal.journaling_enabled(root / "profiles" / profile):
        try:
            out = journal.operate({**entry, "action": "add", "name": profile,
                                   "hermes_root": str(root), "settings": spec.get("settings") or {}})
            written = ({"written": True, "notified": out.get("notified")} if out.get("ok")
                       else {"written": False, "reason": str(out.get("error"))[:160]})
        except Exception as exc:
            written = {"written": False, "reason": str(exc)[:160]}

    return {"ok": True, "bot": profile, "reason": reason,
            "open_screen": f"hermes -p {profile} computer-use screen open",
            "journal": written,
            "note": "Stop here and tell the user you need them on this Bot's screen, and why. "
                    "End the turn with ✋. Do not retry the sign-in, and do not ask for their "
                    "password — they type it on the Bot's screen, where this plugin and the Bot "
                    "never see it."}


def main() -> None:
    raw = sys.stdin.read() if sys.argv[1:2] == ["-"] else Path(sys.argv[1]).read_text()
    print(json.dumps(request(json.loads(raw))))


if __name__ == "__main__":
    main()
