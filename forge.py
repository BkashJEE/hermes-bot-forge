#!/usr/bin/env python3
"""bot-forge: build a complete Hermes Bot (profile) from one JSON spec, no human input.

usage: forge.py spec.json   (or: forge.py - < spec.json)

Spec ("role" required; everything else gets a sane default):
{
  "display_name": "Quill",               # Proper Case, unique, not a generic role word
  "role": "X Posts & Threads Writer",
  "description": "...", "one_job": "...",
  "soul_md": "...full SOUL.md...",       # optional, rendered from fields if missing
  "memory": ["starter facts"],
  "toolsets": ["image_gen"],             # BASE_TOOLSETS are always added
  "skill_categories": ["social-media"],  # other categories get disabled (not deleted)
  "routines": [{"schedule": "0 9 * * 1", "prompt": "...", "name": "weekly-ideas"}],
  "avatar_kind": "cloud",
  "model": {...},                        # optional explicit model block
  "launch_profile": "ceo",               # set by the plugin: whose model to inherit
  "hermes_root": "/home/me/.hermes",     # set by the plugin
  "settings": {...}                      # plugin settings (see plugin.yaml config_schema)
}

Prints one JSON result. Name problems are reported before anything is created; any later failure
deletes the half-built profile.
"""
import json
import os
import random
import re
import shutil
import string
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import yaml

BASE_TOOLSETS = ["browser", "clarify", "file", "memory", "session_search", "skills", "todo", "web"]
ALL_TOOLSETS = set(BASE_TOOLSETS) | {"code_execution", "computer_use", "connections", "cronjob", "delegation",
                                     "image_gen", "terminal", "tts", "vision"}
ALWAYS_KEEP_CATEGORIES = {"autonomous-ai-agents", "research", "web"}
BOT_CHAT_TITLE = "Bot Chat"          # the canonical chat title Bot Mode looks for
KICKOFF = "Hey, tell me about yourself!"  # same first message Desktop's New Agent sends
CHAT_TIMEOUT = 300
AUTH_ERRORS = ("credential", "authenticate", "auth ", "api key", "401", "unauthorized", "not logged in", "login")
DEFAULT_LOCAL_ENDPOINTS = ("http://127.0.0.1:8080/v1", "http://127.0.0.1:11434/v1", "http://127.0.0.1:1234/v1")
BLOB_KINDS = ["round", "organic", "boxy", "capsule", "nub", "cloud", "droplet", "hexagon", "sun", "triangle"]
GENERIC_NAMES = {"default", "hermes", "bot", "agent", "assistant", "helper", "writer", "manager", "social",
                 "researcher", "coder", "coach", "editor", "designer", "analyst", "marketer", "planner", "test", "new"}
COOL_NAMES = ["Nova", "Quill", "Atlas", "Vega", "Orion", "Juno", "Onyx", "Sable", "Ember", "Lyra", "Kairo", "Zephyr",
              "Rune", "Nyx", "Cosmo", "Indigo", "Wren", "Axel", "Mira", "Nimbus", "Rook", "Sage", "Vesper", "Zara",
              "Pixel", "Echo", "Solstice", "Talon", "Aria", "Blaze", "Cipher", "Halo", "Jett", "Koda", "Luma", "Maven"]
NOISE = ("hermes update", "Gateways may", "hermes gateway restart", "tirith security scanner")
ASSISTANT_NAMING = re.compile(r"\b(call|calls|called|name|names|named)\b.{0,40}\bassistant\b|"
                              r"\bassistant\b.{0,40}\b(name|named|called)\b", re.I)
def default_root() -> Path:
    """Hermes root when the caller didn't pass one (Windows keeps it under LOCALAPPDATA)."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "hermes"
    return Path.home() / ".hermes"


DEFAULT_SETTINGS = {"inherit_model": True, "fallback_model": {},
                    "probe_local_models": False, "install_gateway": True, "suggest_connectors": True,
                    "journal_enabled": True, "ack_reactions": True, "ack_tapback": True,
                    "workspace_survey": True, "workspace_roots": []}


# ── hermes cli ───────────────────────────────────────────────────────────────
def cli_env(root: Path):
    """Clean env for `hermes`: drop the calling session's HERMES_* overrides; keep a custom root."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("HERMES_")}
    if root.resolve() != default_root().resolve():
        env["HERMES_HOME"] = str(root)
    return env


def run(root, *args, timeout=180, check=True):
    p = subprocess.run(["hermes", *args], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                       timeout=timeout, env=cli_env(root))
    if check and p.returncode != 0:
        raise RuntimeError(f"hermes {' '.join(args)} failed ({p.returncode}): {clean(p.stderr or p.stdout)[-800:]}")
    return p


def clean(text):
    return "\n".join(l for l in (text or "").splitlines() if not any(n in l for n in NOISE)).strip()


def load_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def dump_yaml(path: Path, data: dict):
    """Atomic write that keeps the original file mode — a cloned config.yaml is 0600 and may hold
    provider settings, so a default-umask rewrite would make it world-readable."""
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(tmp, mode)
    tmp.replace(path)


# ── names ────────────────────────────────────────────────────────────────────
def proper_case(name):
    words = re.sub(r"[^A-Za-z0-9 ]", " ", name).split()
    return " ".join(w[:1].upper() + w[1:] for w in words)[:32]


def slug(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())[:24]


def is_live_profile(d: Path) -> bool:
    """A real, not-deleted profile. `hermes profile delete` can leave an empty dir plus a tombstone in .deleted/."""
    return (d.is_dir() and not d.name.startswith(".") and (d / "config.yaml").exists()
            and not (d.parent / ".deleted" / d.name).exists())


def existing_bot_names(root: Path) -> set:
    """Lowercased profile ids, display names and Bot Mode titles already in use (root profile included)."""
    names = set()
    profiles = root / "profiles"
    homes = [root] + ([d for d in profiles.iterdir() if is_live_profile(d)] if profiles.is_dir() else [])
    for home in homes:
        if home != root:
            names.add(home.name.lower())
        meta = load_yaml(home / "profile.yaml")
        bots = (meta.get("ui_meta") or {}).get("hermes-bots")
        for value in (meta.get("display_name"), bots.get("title") if isinstance(bots, dict) else None):
            if value:
                names.update({str(value).lower(), slug(str(value))})
    return names


def pick_name(requested, taken):
    """Return (display_name, profile_id, error). Bad or taken names are refused with free suggestions."""
    taken = taken | GENERIC_NAMES
    free = [n for n in COOL_NAMES if n.lower() not in taken]
    random.shuffle(free)
    if requested:
        display = proper_case(requested)
        sid = slug(display)
        if not sid or not display[:1].isalpha():
            return None, None, f"'{requested}' is not a usable name"
        if display.lower() in taken or sid in taken:
            return None, None, (f"name '{display}' is taken or too generic. Pick a different unique Proper Case "
                                f"name, e.g. {', '.join(free[:4]) or 'something original'}")
        return display, sid, None
    if not free:
        return None, None, "no free default names left; pass a unique display_name"
    return free[0], slug(free[0]), None


# ── identity ─────────────────────────────────────────────────────────────────
def guardrails_block(approvals, reports_to) -> str:
    """Explicit approval checkpoints + escalation target, appended when the author's SOUL.md lacks them."""
    parts = []
    if approvals:
        parts.append("## Ask first\nNever do these without the user saying yes in this chat:\n"
                     + "\n".join(f"- {a}" for a in approvals))
    if reports_to:
        parts.append(f"## Escalate to\n- @{reports_to} for scope, priorities and final calls.")
    return ("\n\n" + "\n\n".join(parts) + "\n") if parts else ""


IDENTITY_LINE = re.compile(r"^You are \*\*[^*\n]+\*\*.*$\n?", re.M)


def soul_role(soul: str) -> str:
    """Role from a '# Name — Role' heading, if the persona has one."""
    first = (soul or "").lstrip().split("\n", 1)[0]
    m = re.match(r"#\s*[^—\-\n]+\s[—-]\s+(.+)$", first)
    return m.group(1).strip() if m else ""


def ensure_identity(soul: str, display: str, role: str, profile_id: str) -> str:
    """Give the persona exactly one identity: the heading and a single 'You are **Name**' line.
    Earlier identity lines (from a template, a copy or a rename) are replaced, never stacked — two names in
    one SOUL.md is how a Bot ends up introducing itself as someone else."""
    lines = IDENTITY_LINE.findall(soul or "")
    heading = (soul or "").lstrip().split("\n", 1)[0]
    heading_ok = not heading.startswith("#") or re.match(rf"#\s*{re.escape(display)}\b", heading)
    if len(lines) == 1 and lines[0].startswith(f"You are **{display}**") and heading_ok:
        return soul  # already exactly one, correct identity — keep the author's wording
    role = soul_role(soul) or role
    body = IDENTITY_LINE.sub("", soul or "")
    identity = (f"You are **{display}**, the {role} of this Hermes deployment (profile `{profile_id}`). "
                f"Always introduce yourself as {display}.\n")
    head, _, rest = body.lstrip().partition("\n")
    if head.startswith("#"):
        return f"# {display} — {role}\n\n{identity}\n{rest.lstrip()}"
    return f"{identity}\n{body.lstrip()}"


def filter_user_memory(text: str, other_names: set) -> str:
    """Keep facts about the user; drop entries that name the assistant (they'd make the Bot adopt that name)."""
    keep = []
    for entry in (e.strip() for e in text.split("§")):
        if not entry or ASSISTANT_NAMING.search(entry):
            continue
        if any(re.search(rf"\b{re.escape(n)}\b", entry, re.I) and re.search(r"\bname", entry, re.I) for n in other_names):
            continue
        keep.append(entry)
    return "\n§\n".join(keep) + ("\n" if keep else "")


def render_soul(s, profile_id):
    bullets = lambda xs: "\n".join(f"- {x}" for x in xs)
    habits = s.get("habits") or ["break the job into small steps and finish each one",
                                 "verify before claiming; say plainly when unsure"]
    never = (s.get("never") or []) + ["never fabricate numbers, quotes, or results",
                                      "never send, post, buy, or delete anything without the user's approval"]
    return f"""# {s['display_name']} — {s['role']}

You are **{s['display_name']}**, the {s['role']} of this Hermes deployment (profile `{profile_id}`). Always introduce yourself as {s['display_name']}.

## Your one job
{s['one_job']}.

## How you work
{bullets(habits)}

## Voice
{s.get('voice') or 'clear, direct, friendly'}

## Never
{bullets(never)}
"""


# ── sandboxes ────────────────────────────────────────────────────────────────
SANDBOXES = ("local", "docker", "singularity", "apptainer")


def sandbox_error(sandbox: str) -> str:
    """Refuse a sandbox this machine cannot actually run, before a half-usable Bot exists."""
    sandbox = (sandbox or "local").strip().lower()
    if sandbox in ("", "local"):
        return ""
    if sandbox not in SANDBOXES:
        return f"unknown sandbox '{sandbox}' — use one of: {', '.join(SANDBOXES)}"
    import doctor
    found = doctor.sandbox_backends().get(sandbox)
    if not found:
        return (f"{sandbox} is not installed on this machine, so the Bot would have no computer of its own. "
                f"Install it, or create the Bot with sandbox 'local' (it then shares this machine's shell).")
    if not found["usable"]:
        return found["hint"] or f"{sandbox} is installed but not reachable"
    return ""


# ── routines ─────────────────────────────────────────────────────────────────
MIN_ROUTINE_MINUTES = 30
DEFAULT_APPROVALS = ["send, post or publish anything", "spend money or buy anything", "delete files or data"]


def _field_count(field: str, lo: int, hi: int) -> int:
    """How many values a single cron field matches (handles *, */n, a-b, a-b/n, lists)."""
    total = 0
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = max(1, int(step_s)) if step_s.isdigit() else 1
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a_s, b_s = part.split("-", 1)
            a, b = (int(a_s), int(b_s)) if a_s.isdigit() and b_s.isdigit() else (lo, hi)
        elif part.isdigit():
            a = b = int(part)
        else:  # names like MON — count once
            a = b = lo
        total += len(range(a, b + 1, step))
    return max(total, 1)


def runs_per_day(schedule: str) -> float:
    """Rough runs/day for 'every 15m' / '2h' / a 5-field cron expression. 0 when unknown or one-off."""
    s = (schedule or "").strip().lower()
    m = re.fullmatch(r"(?:every\s+)?(\d+)\s*(m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)[0]
        minutes = n * {"m": 1, "h": 60, "d": 1440}[unit]
        return 1440 / minutes if minutes else 0
    parts = s.split()
    if len(parts) == 5:
        minute, hour, _dom, _mon, dow = parts
        per_day = _field_count(minute, 0, 59) * _field_count(hour, 0, 23)
        days = 7 if dow in ("*", "?") else min(_field_count(dow, 0, 6), 7)
        return per_day * days / 7
    return 0


def check_routine(r: dict) -> str:
    """Error message when a routine would fire more often than every MIN_ROUTINE_MINUTES."""
    rate = runs_per_day(r.get("schedule", ""))
    if rate > 1440 / MIN_ROUTINE_MINUTES and not r.get("allow_frequent"):
        return (f"routine '{r.get('name') or r.get('schedule')}' would run ~{int(rate)} times a day. Every run "
                f"costs a model call — use {MIN_ROUTINE_MINUTES} minutes or slower, or set allow_frequent: true "
                f"if the user explicitly asked for it")
    return ""


# ── bot mode ─────────────────────────────────────────────────────────────────
def write_bot_meta(pdir: Path, display, description, kind):
    """Mirror what Desktop's New Agent dialog saves (profiles.configure → ui_meta['hermes-bots'])."""
    path = pdir / "profile.yaml"
    data = load_yaml(path)
    seed = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    ui_meta = data.get("ui_meta") if isinstance(data.get("ui_meta"), dict) else {}
    ui_meta["hermes-bots"] = {
        "title": display, "description": description, "imageKind": "shape",
        "shape": f"blobatar:{seed}:{kind if kind in BLOB_KINDS else random.choice(BLOB_KINDS)}",
        "created": int(time.time() * 1000),
    }
    revisions = data.get("_ui_meta_revisions") if isinstance(data.get("_ui_meta_revisions"), dict) else {}
    revisions["hermes-bots"] = int(revisions.get("hermes-bots", 0)) + 1
    data.update({"display_name": display, "ui_meta": ui_meta, "_ui_meta_revisions": revisions})
    dump_yaml(path, data)


def bot_mode_install(root: Path) -> bool:
    """Is this install managed by Desktop Bot Mode? (any profile carrying the hermes-bots marker)"""
    homes = [root] + ([d for d in (root / "profiles").iterdir() if is_live_profile(d)]
                      if (root / "profiles").is_dir() else [])
    return any((load_yaml(h / "profile.yaml").get("ui_meta") or {}).get("hermes-bots") for h in homes)


def has_bot_chat(root, profile_id: str) -> bool:
    """Does this Bot already own its canonical chat? (then just continue it)"""
    import contextlib
    import sqlite3
    db = Path(root) / "profiles" / profile_id / "state.db"
    if not db.exists():
        return False
    try:
        with contextlib.closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)) as c:
            return bool(c.execute("select 1 from sessions where title=? limit 1", (BOT_CHAT_TITLE,)).fetchone())
    except sqlite3.Error:
        return False


def newest_session(root, profile_id: str) -> str:
    import contextlib
    import sqlite3
    db = Path(root) / "profiles" / profile_id / "state.db"
    try:
        with contextlib.closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)) as c:
            row = c.execute("select id from sessions order by started_at desc limit 1").fetchone()
            return row[0] if row else ""
    except sqlite3.Error:
        return ""


def bot_chat(root, profile_id, message, source: str = ""):
    """Send a message in the Bot's canonical Bot Chat (created on first use).

    The source stamped here is permanent, and Hermes decides a session's client surface from it
    (`tui_gateway/server.py::_gui_surface_toolsets`): a chat stamped `cli` never gets the desktop
    toolset, so a Bot whose canonical chat we created could not react to a message in Desktop. On a
    Bot-Mode install this chat belongs to the Desktop roster, so stamp it the way Desktop would."""
    source = source or ("desktop" if bot_mode_install(Path(root)) else "cli")
    existing = has_bot_chat(root, profile_id)
    if existing or source == "cli":
        p = run(root, "-p", profile_id, "chat", "-c", BOT_CHAT_TITLE, "--create-if-missing", "-Q",
                "--max-turns", "3", "-q", message, timeout=CHAT_TIMEOUT, check=False)
    else:
        # `chat -c <title> --create-if-missing` hardcodes source="cli" (hermes_cli/main.py), and a session's
        # stored source is what decides its client surface — a cli-stamped chat never gets the desktop
        # toolset, so the Bot cannot react to a message in Desktop. Start it with the right source, then
        # give it the canonical title.
        p = run(root, "-p", profile_id, "chat", "--source", source, "-Q", "--max-turns", "3", "-q", message,
                timeout=CHAT_TIMEOUT, check=False)
        session_id = newest_session(root, profile_id)  # -Q hides the session_id line, so read it back
        if session_id:
            run(root, "-p", profile_id, "sessions", "rename", session_id, BOT_CHAT_TITLE, check=False, timeout=60)
    out = clean(p.stdout)
    return p.returncode == 0 and bool(out), out or clean(p.stderr)[-800:]


# ── model & login ────────────────────────────────────────────────────────────
def local_model(endpoints=DEFAULT_LOCAL_ENDPOINTS):
    """First model served by a local OpenAI-compatible server (no login needed)."""
    for base in endpoints:
        try:
            data = json.load(urllib.request.urlopen(base.rstrip("/") + "/models", timeout=5))
        except Exception:
            continue
        ids = [m.get("id") for m in data.get("data") or []] + [m.get("model") or m.get("name") for m in data.get("models") or []]
        ids = [i for i in ids if i]
        if ids:
            return {"default": ids[0], "provider": "custom", "base_url": base.rstrip("/")}
    return None


STOPWORDS = {"the", "and", "for", "with", "that", "this", "your", "from", "into", "user", "users", "bot",
             "agent", "job", "one", "them", "they", "their", "posts", "post", "work", "help", "manage"}


def suggest_connectors(root: Path, text: str, limit: int = 3) -> list:
    """Match the Bot's job against Hermes' own MCP catalog so the user learns what to connect.
    Suggestions only — connecting an account always needs the user's own sign-in."""
    text = (text or "").lower()
    words = {w for w in re.findall(r"[a-z]{3,}", text) if w not in STOPWORDS}
    if not words:
        return []
    try:
        listing = run(root, "mcp", "catalog", timeout=60, check=False).stdout
    except Exception:
        return []
    scored = []
    for line in listing.splitlines():
        m = re.match(r"\s{2,}([a-z0-9][a-z0-9-]{1,40})\s{2,}(available|configured)\s{2,}(.+)", line)
        if not m:
            continue
        name, _status, desc = m.group(1), m.group(2), m.group(3).strip()
        haystack = {w for w in re.findall(r"[a-z]{3,}", f"{name} {desc}".lower())} - STOPWORDS
        score = len(words & haystack) + (3 if name.split("-")[0] in text else 0)
        if score:
            scored.append((score, name, desc))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [{"name": n, "what": d, "connect": f"hermes -p {{bot}} mcp install {n}"} for _s, n, d in scored[:limit]]


def disabled_skills(skills_dir: Path, keep_categories: set) -> set:
    names = set()
    if not skills_dir.is_dir():
        return names
    for skill_md in skills_dir.rglob("SKILL.md"):
        if skill_md.relative_to(skills_dir).parts[0] in keep_categories:
            continue
        m = re.search(r"^name:\s*['\"]?([^'\"\n]+)", skill_md.read_text(errors="ignore"), re.M)
        names.add(m.group(1).strip() if m else skill_md.parent.name)
    return names


# ── main ─────────────────────────────────────────────────────────────────────
def forge(s: dict) -> dict:
    root = Path(s.get("hermes_root") or default_root())
    settings = {**DEFAULT_SETTINGS, **{k: v for k, v in (s.get("settings") or {}).items() if v is not None}}
    if s.get("template"):
        import portable
        ref = str(s["template"]).strip()
        path = portable.bundled_templates().get(ref.lower()) or Path(ref).expanduser()
        try:
            tpl = portable.load_template(Path(path))
        except (OSError, ValueError) as exc:
            names = ", ".join(portable.bundled_templates())
            return {"ok": False, "error": f"template '{ref}': {exc}. Bundled templates: {names}", "rolled_back": False}
        scan = portable.scan_text(json.dumps(tpl))
        if scan["verdict"] == "BLOCK" and not settings.get("allow_secrets"):
            return {"ok": False, "error": "template contains what looks like a credential — refusing to import it",
                    "scan": scan, "rolled_back": False}
        s = {**{k: v for k, v in tpl.items() if k not in ("format", "version")},
             **{k: v for k, v in s.items() if v not in (None, "", [])}}
    if not s.get("role"):
        return {"ok": False, "error": "spec needs at least 'role'"}
    # Two Bots with the same job is what makes a roster useless. Check before building, not after.
    guard = None
    if settings.get("workspace_survey", True):
        try:
            import survey

            guard = survey.overlap_guard(survey.workspace_index(root, settings), survey.job_terms(s))
        except Exception:
            guard = None
    if guard and guard["verdict"] == "duplicate" and not s.get("allow_overlap"):
        return {"ok": False, "rolled_back": False, "covered_by": guard,
                "error": (f"@{guard['bot']} ({guard['display_name']}) already does this job"
                          + (f": {guard['one_job']}" if guard.get("one_job") else "")
                          + ". Give this Bot a narrower job, update that one instead, or pass "
                            "allow_overlap: true if two really are wanted.")}
    display, profile_id, err = pick_name(s.get("display_name") or s.get("name"), existing_bot_names(root))
    if err:
        return {"ok": False, "error": err, "rolled_back": False}
    s["display_name"] = display
    s.setdefault("one_job", f"acts as the user's {s['role']}")
    description = s.get("description") or f"{s['role']}: {s['one_job']}."
    soul = ensure_identity(s.get("soul_md") or render_soul(s, profile_id), display, s["role"], profile_id)
    sandbox = (s.get("sandbox") or "local").strip().lower()
    problem = sandbox_error(sandbox)
    if problem:
        return {"ok": False, "error": problem, "rolled_back": False}
    approvals = s.get("approvals")
    approvals = list(DEFAULT_APPROVALS) if approvals is None else [a for a in approvals if isinstance(a, str)]
    reports_to = (s.get("reports_to") or "").strip().lstrip("@")
    soul = soul.rstrip() + "\n" + guardrails_block(approvals if "## Ask first" not in soul else [],
                                                   reports_to if "## Escalate to" not in soul else "")
    if settings.get("ack_reactions", True) and s.get("ack_reactions", True):
        import acks
        soul = acks.apply_policy(soul)
    if settings.get("journal_enabled", True):
        import journal

        if journal.JOURNAL_MARKER not in soul:
            soul = soul.rstrip() + "\n\n" + journal.JOURNAL_POLICY.rstrip() + "\n"
    for r in s.get("routines") or []:
        problem = check_routine(r)
        if problem:
            return {"ok": False, "error": problem, "rolled_back": False}
    pdir = root / "profiles" / profile_id
    created = False
    try:
        # 1. profile (config, keys, skills from the root profile; messaging channels left behind)
        run(root, "profile", "create", profile_id, "--clone-from", "default", "--description", description,
            timeout=600)
        created = True
        if not (pdir / "config.yaml").exists():
            raise RuntimeError(f"profile dir {pdir} missing config.yaml after create")

        # 2. Bot Mode identity + SOUL.md
        write_bot_meta(pdir, display, description, s.get("avatar_kind"))
        (pdir / "SOUL.md").write_text(soul)
        journal_path = None
        if settings.get("journal_enabled", True):
            import journal

            journal_path = str(journal.ensure_journal(pdir))

        # The reaction hook ships inside the Bot: a hook only runs in the profile running the turn,
        # so one living here would never fire when the user talks to this Bot. Hooks only, no tools.
        marks = None
        if settings.get("ack_tapback", True):
            import companion

            installed = companion.install_marks(pdir)
            marks = installed.get("version") if installed.get("ok") else f"not installed: {installed.get('error')}"

        # 3. memories
        mem = pdir / "memories"
        mem.mkdir(exist_ok=True)
        user_md = root / "memories" / "USER.md"
        if user_md.exists():
            others = {n for n in existing_bot_names(root) if n not in GENERIC_NAMES and n != profile_id}
            (mem / "USER.md").write_text(filter_user_memory(user_md.read_text(), others))
        for skill, doc in (s.get("taught_skills") or {}).items():
            skill_id = re.sub(r"[^a-z0-9-]+", "-", str(skill).lower()).strip("-")[:48]
            if skill_id and isinstance(doc, str) and doc.strip():
                (pdir / "skills" / "taught" / skill_id).mkdir(parents=True, exist_ok=True)
                (pdir / "skills" / "taught" / skill_id / "SKILL.md").write_text(doc)
        facts = [f"My name is {display}. I am the {s['role']} (profile `{profile_id}`). I always introduce myself "
                 f"as {display}, never by another Bot's name. My one job: {s['one_job']}."] + list(s.get("memory") or [])
        if approvals:
            facts.append("I ask the user before: " + "; ".join(approvals) + ".")
        if reports_to:
            facts.append(f"I escalate scope and priority calls to @{reports_to}.")
        (mem / "MEMORY.md").write_text("\n§\n".join(facts) + "\n")

        # Where it landed: read once, written into its memory, so it never researches this again.
        workspace = None
        if settings.get("workspace_survey", True):
            try:
                import survey

                found = survey.survey(root, {**s, "soul_md": soul}, settings, exclude=profile_id)
                survey.attach(pdir, found)
                workspace = {k: found[k] for k in ("roots", "fits", "covered_by", "skills_here", "next_steps")}
            except Exception as exc:
                workspace = {"error": f"workspace survey skipped: {exc}"[:200]}

        # 4. config: tools, skills, model
        cfg_path = pdir / "config.yaml"
        cfg = load_yaml(cfg_path)
        tools = set(BASE_TOOLSETS) | {t for t in (s.get("toolsets") or []) if t in ALL_TOOLSETS}
        cfg.setdefault("platform_toolsets", {})["cli"] = sorted(tools)
        disabled = set()
        if s.get("skill_categories"):
            disabled = disabled_skills(pdir / "skills", set(s["skill_categories"]) | ALWAYS_KEEP_CATEGORIES)
        elif s.get("disabled_skills"):
            disabled = {str(x) for x in s["disabled_skills"]} - set((s.get("taught_skills") or {}).keys())
        if disabled:
            skills_cfg = cfg.get("skills") if isinstance(cfg.get("skills"), dict) else {}
            skills_cfg["disabled"] = sorted(set(skills_cfg.get("disabled") or []) | disabled)
            cfg["skills"] = skills_cfg
        launch = s.get("launch_profile") or "default"
        if s.get("model"):
            cfg["model"] = s["model"]
        elif settings["inherit_model"]:
            launch_model = load_yaml((root if launch == "default" else root / "profiles" / launch) / "config.yaml").get("model")
            if isinstance(launch_model, dict) and launch_model.get("default"):
                cfg["model"] = launch_model
        if sandbox not in ("", "local"):  # the Bot's shell runs in its own container, not on this machine
            terminal = cfg.get("terminal") if isinstance(cfg.get("terminal"), dict) else {}
            terminal["backend"] = sandbox
            cfg["terminal"] = terminal
        dump_yaml(cfg_path, cfg)

        # 5. routines
        routines = []
        for r in s.get("routines") or []:
            run(root, "-p", profile_id, "cron", "create", r["schedule"], r["prompt"], "--name",
                r.get("name") or "routine", "--deliver", r.get("deliver") or f"bot-chat:{profile_id}")
            routines.append(r.get("name") or r["schedule"])

        # 6. first words in its Bot Chat (doubles as the smoke test)
        model = (cfg.get("model") or {}).get("default", "?")
        warning = None
        ok, reply = bot_chat(root, profile_id, KICKOFF)
        if not ok and any(k in reply.lower() for k in AUTH_ERRORS):
            fallback = settings["fallback_model"] or (local_model() if settings["probe_local_models"] else None)
            if fallback:
                cfg["model"] = fallback
                dump_yaml(cfg_path, cfg)
                warning = f"{model} could not sign in for this Bot; switched to fallback {fallback.get('default')}"
                model = fallback.get("default")
                ok, reply = bot_chat(root, profile_id, KICKOFF)
            else:  # keep the Bot; it just needs its own sign-in
                ok, reply = True, ""
                warning = (f"{model} needs a sign-in for this Bot: run `hermes -p {profile_id} auth add "
                           f"{(cfg.get('model') or {}).get('provider', '<provider>')}` once")
        if not ok:
            raise RuntimeError(f"Bot did not answer: {reply}")

        # 7. gateway (best effort)
        gateway = "skipped"
        if settings["install_gateway"] and os.name != "nt":
            gw = run(root, "-p", profile_id, "gateway", "install", "--start-now", "--start-on-login", check=False, timeout=120)
            gateway = "started" if gw.returncode == 0 else f"not started: {clean(gw.stderr or gw.stdout)[-200:]}"

        connect_next = []
        if settings.get("suggest_connectors", True):
            connect_next = [{**c, "connect": c["connect"].format(bot=profile_id)}
                            for c in suggest_connectors(root, f"{s['role']} {s['one_job']} {description}")]

        return {"ok": True, "name": profile_id, "display_name": display, "description": description, "model": model,
                "connect_next": connect_next, "sandbox": sandbox,
                "approvals": approvals, "reports_to": reports_to or None,
                "warning": warning, "toolsets": sorted(tools),
                "skills_disabled": len(disabled), "routines": routines, "gateway": gateway, "intro": reply[-600:],
                "journal": journal_path, "reactions": marks, "workspace": workspace,
                "note": "done — it already introduced itself. Do not message, test or change this Bot; just report."}
    except Exception as e:
        rolled_back = False
        if created:
            deleted = run(root, "profile", "delete", "-y", profile_id, check=False, timeout=300)
            rolled_back = deleted.returncode == 0
            if sys.platform.startswith("linux"):
                subprocess.run(["systemctl", "--user", "reset-failed", f"hermes-gateway-{profile_id}.service"],
                               capture_output=True)
        result = {"ok": False, "name": profile_id, "error": str(e), "rolled_back": rolled_back}
        if created and not rolled_back:
            result["warning"] = (f"could not delete the half-built profile — remove it with "
                                 f"`hermes profile delete {profile_id}`")
        return result


def main():
    raw = sys.stdin.read() if len(sys.argv) < 2 or sys.argv[1] == "-" else Path(sys.argv[1]).read_text()
    result = forge(json.loads(raw))
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
