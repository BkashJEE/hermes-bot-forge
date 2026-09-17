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


DEFAULT_SETTINGS = {"inherit_model": True, "share_login": False, "fallback_model": {},
                    "probe_local_models": False, "install_gateway": True}


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


def ensure_identity(soul: str, display: str, role: str, profile_id: str) -> str:
    """The Bot's own name must be explicit in SOUL.md or it borrows one from shared memory."""
    if f"You are **{display}**" in soul:
        return soul
    identity = (f"You are **{display}**, the {role} of this Hermes deployment (profile `{profile_id}`). "
                f"Always introduce yourself as {display}.\n")
    head, _, rest = soul.partition("\n")
    return f"{head}\n\n{identity}{rest}" if head.startswith("#") else f"{identity}\n{soul}"


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


def bot_chat(root, profile_id, message):
    """Send a message in the Bot's canonical Bot Chat (created on first use)."""
    p = run(root, "-p", profile_id, "chat", "-c", BOT_CHAT_TITLE, "--create-if-missing", "-Q", "--max-turns", "3",
            "-q", message, timeout=CHAT_TIMEOUT, check=False)
    out = clean(p.stdout)
    return p.returncode == 0 and bool(out), out or clean(p.stderr)[-800:]


# ── model & login ────────────────────────────────────────────────────────────
def share_root_login(root: Path, pdir: Path) -> bool:
    """Opt-in (settings.share_login): point the Bot's auth store at the root profile's, so OAuth models work
    without a per-Bot sign-in. Hermes treats a symlinked store as shared rather than a forked copy.

    Deliberately conservative: never creates or modifies anything inside the root profile, and the swap is
    atomic. Upstream's default is one login per profile — see the README before enabling this."""
    if os.name == "nt":
        return False
    src = root / "auth.json"
    if not src.is_file():
        return False
    for fname in ("auth.json", "auth.lock"):
        target, link = root / fname, pdir / fname
        if not target.exists():  # never create files in the root profile
            continue
        tmp = link.with_name(link.name + ".linking")
        if tmp.is_symlink() or tmp.exists():
            tmp.unlink()
        tmp.symlink_to(target)
        os.replace(tmp, link)
    return (pdir / "auth.json").is_symlink()


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
    if not s.get("role"):
        return {"ok": False, "error": "spec needs at least 'role'"}
    display, profile_id, err = pick_name(s.get("display_name") or s.get("name"), existing_bot_names(root))
    if err:
        return {"ok": False, "error": err, "rolled_back": False}
    s["display_name"] = display
    s.setdefault("one_job", f"acts as the user's {s['role']}")
    description = s.get("description") or f"{s['role']}: {s['one_job']}."
    soul = ensure_identity(s.get("soul_md") or render_soul(s, profile_id), display, s["role"], profile_id)
    approvals = [a for a in (s.get("approvals") or []) if isinstance(a, str)]
    reports_to = (s.get("reports_to") or "").strip().lstrip("@")
    if approvals and "## Ask first" not in soul:
        soul += guardrails_block(approvals, "")
    if reports_to and "## Escalate to" not in soul:
        soul += guardrails_block([], reports_to)
    pdir = root / "profiles" / profile_id
    created = False
    try:
        # 1. profile (config, keys, skills from the root profile; messaging channels left behind)
        run(root, "profile", "create", profile_id, "--clone-from", "default", "--description", description,
            timeout=600)
        created = True
        if not (pdir / "config.yaml").exists():
            raise RuntimeError(f"profile dir {pdir} missing config.yaml after create")
        shared_login = share_root_login(root, pdir) if settings["share_login"] else False

        # 2. Bot Mode identity + SOUL.md
        write_bot_meta(pdir, display, description, s.get("avatar_kind"))
        (pdir / "SOUL.md").write_text(soul)

        # 3. memories
        mem = pdir / "memories"
        mem.mkdir(exist_ok=True)
        user_md = root / "memories" / "USER.md"
        if user_md.exists():
            others = {n for n in existing_bot_names(root) if n not in GENERIC_NAMES and n != profile_id}
            (mem / "USER.md").write_text(filter_user_memory(user_md.read_text(), others))
        facts = [f"My name is {display}. I am the {s['role']} (profile `{profile_id}`). I always introduce myself "
                 f"as {display}, never by another Bot's name. My one job: {s['one_job']}."] + list(s.get("memory") or [])
        if approvals:
            facts.append("I ask the user before: " + "; ".join(approvals) + ".")
        if reports_to:
            facts.append(f"I escalate scope and priority calls to @{reports_to}.")
        (mem / "MEMORY.md").write_text("\n§\n".join(facts) + "\n")

        # 4. config: tools, skills, model
        cfg_path = pdir / "config.yaml"
        cfg = load_yaml(cfg_path)
        tools = set(BASE_TOOLSETS) | {t for t in (s.get("toolsets") or []) if t in ALL_TOOLSETS}
        cfg.setdefault("platform_toolsets", {})["cli"] = sorted(tools)
        disabled = set()
        if s.get("skill_categories"):
            disabled = disabled_skills(pdir / "skills", set(s["skill_categories"]) | ALWAYS_KEEP_CATEGORIES)
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

        return {"ok": True, "name": profile_id, "display_name": display, "description": description, "model": model,
                "approvals": approvals, "reports_to": reports_to or None,
                "shared_login": shared_login, "warning": warning, "toolsets": sorted(tools),
                "skills_disabled": len(disabled), "routines": routines, "gateway": gateway, "intro": reply[-600:],
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
