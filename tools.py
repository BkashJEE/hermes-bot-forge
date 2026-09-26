"""Tool handlers. Bot creation runs forge.py in a subprocess with a clean environment, so the calling
agent's per-session overrides (HOME / HERMES_HOME) never leak into the Bot being built or asked."""

import contextlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
NOISE = ("hermes update", "Gateways may", "hermes gateway restart", "tirith security scanner")


def hermes_root() -> Path:
    """Root Hermes dir (``<root>/profiles/<name>`` layout), honoring custom HERMES_HOME roots."""
    try:
        from hermes_constants import get_default_hermes_root
        return Path(get_default_hermes_root())
    except Exception:
        if os.name == "nt":
            return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "hermes"
        return Path.home() / ".hermes"


def _clean(text):
    return "\n".join(l for l in (text or "").splitlines() if not any(n in l for n in NOISE)).strip()


def launch_profile(session_id=None, root=None) -> str:
    """Profile of the agent calling the tool. Desktop serves every Bot from one backend process, so
    prefer the context-local home override, then the profile whose state.db owns the calling session."""
    root = Path(root or hermes_root())
    try:
        from hermes_constants import get_hermes_home_override
        override = get_hermes_home_override()
        if override and Path(override).resolve().parent == (root / "profiles").resolve():
            return Path(override).resolve().name
    except Exception:
        pass
    if session_id:
        profiles = root / "profiles"
        homes = [("default", root)] + (sorted((d.name, d) for d in profiles.iterdir() if d.is_dir()) if profiles.is_dir() else [])
        for name, home in homes:
            db = home / "state.db"
            if not db.exists():
                continue
            try:
                with contextlib.closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)) as c:
                    if c.execute("select 1 from sessions where id=? limit 1", (session_id,)).fetchone():
                        return name
            except sqlite3.Error:
                continue
    return "default"


def create_agent(args: dict, settings: dict | None = None, **kwargs) -> str:
    root = hermes_root()
    spec = {**args, "launch_profile": launch_profile(kwargs.get("session_id"), root),
            "hermes_root": str(root), "settings": settings or {}}
    try:
        p = subprocess.run([sys.executable, str(PLUGIN_DIR / "forge.py"), "-"], input=json.dumps(spec),
                           capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "error": "create_agent timed out after 15 min"})
    out = p.stdout.strip()
    try:
        return json.dumps(json.loads(out[out.index("{"):]))
    except ValueError:
        return json.dumps({"ok": False, "error": _clean(p.stderr or out)[-1500:]})


def _manage(op: str, args: dict, settings: dict | None = None) -> str:
    root = hermes_root()
    spec = {**args, "op": op, "hermes_root": str(root), "settings": settings or {}}
    try:
        p = subprocess.run([sys.executable, str(PLUGIN_DIR / "manage.py"), "-"], input=json.dumps(spec),
                           capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "error": f"{op} timed out after 15 min"})
    out = p.stdout.strip()
    try:
        return json.dumps(json.loads(out[out.index("{"):]))
    except ValueError:
        return json.dumps({"ok": False, "error": _clean(p.stderr or out)[-1500:]})


def create_team(args: dict, settings: dict | None = None, **kwargs) -> str:
    root = hermes_root()
    spec = {**args, "launch_profile": launch_profile(kwargs.get("session_id"), root),
            "hermes_root": str(root), "settings": settings or {}}
    try:
        p = subprocess.run([sys.executable, str(PLUGIN_DIR / "team.py"), "-"], input=json.dumps(spec),
                           capture_output=True, text=True, timeout=3600)
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "error": "create_team timed out after 60 min"})
    out = p.stdout.strip()
    try:
        return json.dumps(json.loads(out[out.index("{"):]))
    except ValueError:
        return json.dumps({"ok": False, "error": _clean(p.stderr or out)[-1500:]})


def check_install(args: dict, **kwargs) -> str:
    try:
        p = subprocess.run([sys.executable, str(PLUGIN_DIR / "doctor.py"), "--json"],
                           capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "error": "check_install timed out"})
    out = p.stdout.strip()
    try:
        return json.dumps(json.loads(out[out.index("{"):]))
    except ValueError:
        return json.dumps({"ok": False, "error": _clean(p.stderr or out)[-1500:]})


def check_agents(args: dict, **kwargs) -> str:
    root = hermes_root()
    try:
        p = subprocess.run([sys.executable, str(PLUGIN_DIR / "health.py"), "-"],
                           input=json.dumps({**args, "hermes_root": str(root)}),
                           capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "error": "check_agents timed out"})
    out = p.stdout.strip()
    try:
        return json.dumps(json.loads(out[out.index("{"):]))
    except ValueError:
        return json.dumps({"ok": False, "error": _clean(p.stderr or out)[-1500:]})


def agent_journal(args: dict, **kwargs) -> str:
    """Enable, append to, or read a Bot's work journal."""
    root = hermes_root()
    spec = {**args, "launch_profile": launch_profile(kwargs.get("session_id"), root),
            "hermes_root": str(root)}
    try:
        p = subprocess.run([sys.executable, str(PLUGIN_DIR / "journal.py"), "-"], input=json.dumps(spec),
                           capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "error": "agent_journal timed out"})
    out = p.stdout.strip()
    try:
        return json.dumps(json.loads(out[out.index("{"):]))
    except ValueError:
        return json.dumps({"ok": False, "error": _clean(p.stderr or out)[-1500:]})


def teach_agent(args: dict, settings: dict | None = None, **kwargs) -> str:
    return _manage("teach", args, settings)


def update_agent(args: dict, settings: dict | None = None, **kwargs) -> str:
    return _manage("update", args, settings)


def copy_agent(args: dict, settings: dict | None = None, **kwargs) -> str:
    return _manage("copy", args, settings)


def share_agent(args: dict, settings: dict | None = None, **kwargs) -> str:
    # allow_secrets is an operator setting, never a tool argument
    return _manage("export", {k: v for k, v in args.items() if k != "allow_secrets"}, settings)


def import_agent(args: dict, settings: dict | None = None, **kwargs) -> str:
    return _manage("import", {**{k: v for k, v in args.items() if k != "allow_secrets"},
                              "launch_profile": launch_profile(kwargs.get("session_id"))}, settings)


def hide_agent(args: dict, settings: dict | None = None, **kwargs) -> str:
    return _manage("hide" if args.get("hidden", True) else "show", args, settings)


def delete_agent(args: dict, settings: dict | None = None, **kwargs) -> str:
    return _manage("delete", args, settings)


def _profile_info(name, home):
    import yaml
    cfg, meta = {}, {}
    for fname, target in (("config.yaml", cfg), ("profile.yaml", meta)):
        try:
            target.update(yaml.safe_load((home / fname).read_text()) or {})
        except Exception:
            pass
    bots = (meta.get("ui_meta") or {}).get("hermes-bots") or {}
    bots = bots if isinstance(bots, dict) else {}
    info = {"name": name, "display_name": bots.get("title") or meta.get("display_name") or name,
            "description": (meta.get("description") or "").strip(),
            "model": (cfg.get("model") or {}).get("default") or ""}
    if bots.get("hidden"):
        info["hidden"] = True
    try:
        jobs = json.loads((home / "cron" / "jobs.json").read_text())
        count = len(jobs.get("jobs", jobs) if isinstance(jobs, dict) else jobs)
        if count:
            info["routines"] = count
    except Exception:
        pass
    return info


def list_agents(args: dict, **kwargs) -> str:
    root = hermes_root()
    agents = [_profile_info("default", root)]
    profiles = root / "profiles"
    if profiles.is_dir():
        agents += [_profile_info(d.name, d) for d in sorted(profiles.iterdir()) if (d / "config.yaml").exists()]
    return json.dumps({"agents": agents})


def ask_agent(args: dict, **kwargs) -> str:
    root = hermes_root()
    name = (args.get("name") or "").strip().lower()
    message = (args.get("message") or "").strip()
    if not NAME_RE.match(name) or not message:
        return json.dumps({"ok": False, "error": "need a valid profile name and a message"})
    if name != "default" and not (root / "profiles" / name / "config.yaml").exists():
        return json.dumps({"ok": False, "error": f"no Bot named '{name}' (see list_agents)"})
    # The caller may have loaded its entire .env (or a routed profile's secrets).
    # Never forward that process environment to another Bot. The CLI loads the
    # target profile's own .env and auth.json after -p resolves its home.
    safe_keys = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "TERM", "TMPDIR",
                 "SYSTEMROOT", "WINDIR", "PATHEXT", "VIRTUAL_ENV", "SSL_CERT_FILE",
                 "REQUESTS_CA_BUNDLE")
    env = {k: os.environ[k] for k in safe_keys if k in os.environ}
    env["HERMES_HOME"] = str(root)  # -p resolves under this root, independent of caller HOME
    try:
        p = subprocess.run(["hermes", "-p", name, "chat", "-Q", "--max-turns", "30", "-q", message],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=900, env=env)
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "error": f"{name} did not answer within 15 min"})
    except FileNotFoundError:
        return json.dumps({"ok": False, "error": "hermes CLI not found on PATH"})
    reply = _clean(p.stdout)
    if p.returncode != 0 or not reply:
        return json.dumps({"ok": False, "error": _clean(p.stderr or p.stdout)[-1500:]})
    return json.dumps({"ok": True, "name": name, "reply": reply[-6000:]})
