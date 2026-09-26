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

if __package__:  # Hermes imports this as a package; the CLI entry points run it as a script
    from . import policy as policy_mod
else:
    import policy as policy_mod

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
    return "\n".join(line for line in (text or "").splitlines()
                     if not any(n in line for n in NOISE)).strip()


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


def _creation_model_error(spec: dict) -> str:
    """Validate only an explicitly supplied creation-tool route, without echoing values."""
    if "model" not in spec:
        return ""
    model = spec["model"]
    if not isinstance(model, dict) or any(
        not isinstance(model.get(k), str) or not model[k].strip() for k in ("default", "provider")
    ):
        return "model must be an object with non-empty default and provider strings"
    if set(model) - {"default", "provider", "base_url", "api_mode"}:
        return "model accepts only default, provider, base_url and api_mode; never supply credentials"
    if any(not isinstance(v, str) for v in model.values()):
        return "model route fields must be strings"
    return ""


def create_agent(args: dict, settings: dict | None = None, **kwargs) -> str:
    problem = _creation_model_error(args)
    if problem:
        return json.dumps({"ok": False, "error": problem})
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
    # Check every explicit route before building the lead or any member.
    specs = [args.get("lead")] + list(args.get("members") or [])
    for spec in specs:
        if isinstance(spec, dict):
            problem = _creation_model_error(spec)
            if problem:
                return json.dumps({"ok": False, "error": problem})
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


def check_install(args: dict, settings: dict | None = None, **kwargs) -> str:
    try:
        p = subprocess.run([sys.executable, str(PLUGIN_DIR / "doctor.py"), "--json", "--settings-stdin"],
                           input=json.dumps(settings or {}), capture_output=True, text=True, timeout=300)
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


def _read_text_safe(path) -> str | None:
    """Read a text file, or None if it cannot be read as text.

    Separate from a plain `read_text()` because a UnicodeDecodeError is a ValueError, not an
    OSError, and escapes `except OSError` — which turned a hand-edited file with one latin-1
    apostrophe into a raised exception out of a read-only tool.
    """
    try:
        return path.read_text(errors="replace")
    except (OSError, ValueError):
        return None


def check_policies(args: dict, **kwargs) -> str:
    """Report which Bots' shared operating policy is current, and which have drifted."""
    root = hermes_root()
    relative = (args or {}).get("policy_path") or policy_mod.DEFAULT_RELATIVE
    try:
        canon = policy_mod.policy_path(root, relative)
    except policy_mod.PolicyPathError as exc:
        return json.dumps({"ok": False, "error": str(exc)})

    if not canon.exists():
        return json.dumps({"ok": False, "error": f"no shared policy at {canon}",
                          "hint": "create_agent writes one on first use; or create it yourself"})
    # errors="replace": a policy or SOUL.md saved by a non-UTF-8 editor (or containing one
    # latin-1 apostrophe) must degrade to "cannot read", not raise out of a read-only tool.
    # UnicodeDecodeError is a ValueError, so `except OSError` does not catch it.
    canon_text = _read_text_safe(canon)
    if canon_text is None:
        return json.dumps({"ok": False, "error": f"could not read {canon} as text"})
    if not policy_mod.policy_body(canon_text):
        return json.dumps({
            "ok": False,
            "error": f"shared policy at {canon} has no rules in it",
            "hint": "it contains only comments, so every Bot would be built with an empty policy",
        })
    expected = policy_mod.fingerprint(canon_text)

    bots, stale, without, unreadable = [], [], [], []
    candidates = sorted((root / "profiles").glob("*")) if (root / "profiles").is_dir() else []
    # The default profile's SOUL.md sits at the root, not under profiles/, so it is not in the
    # glob above. It is deliberately NOT audited: `_require_bot` refuses it, so `forge` never
    # writes a block there and no documented call can ever fix it. Reporting a permanent
    # `no_shared_policy` for a profile no operation can act on would make the drift report
    # untrustworthy -- the whole point of this tool is that every row it prints is actionable.
    for prof in candidates:
        name = prof.name
        soul = prof / "SOUL.md"
        try:
            text = soul.read_text(errors="replace")
        except OSError as exc:
            bots.append({"profile": name, "error": str(exc)[:120], "current": False,
                         "has_shared_policy": False, "reason": "unreadable",
                         "fingerprint": None, "canonical_fingerprint": expected})
            unreadable.append(name)
            continue
        report = policy_mod.audit_soul(text, expected)
        report["profile"] = name
        bots.append(report)
        if not report["current"]:
            (without if not report["has_shared_policy"] else stale).append(name)

    return json.dumps({
        "ok": True,
        "canonical_policy": str(canon),
        "canonical_fingerprint": expected,
        "bots_checked": len(bots),
        # counted from the rows themselves, not by subtraction: a row that errored belongs to
        # no list, and `checked - stale - without` silently counted it as current.
        "current": sum(1 for b in bots if b.get("current")),
        "stale": stale,
        "no_shared_policy": without,
        "unreadable": unreadable,
        "bots": bots,
        "fix": ("ask the Bot's owner to re-create it, or run update_agent with soul_md to "
                "rewrite its SOUL.md — create_agent refuses a name that is already taken, so "
                "re-running it is not a way to refresh an existing Bot"),
    })


def agent_journal(args: dict, settings: dict | None = None, **kwargs) -> str:
    """Enable, append to, or read a Bot's work journal."""
    root = hermes_root()
    spec = {**args, "launch_profile": launch_profile(kwargs.get("session_id"), root),
            "hermes_root": str(root), "settings": settings or {}}
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
    safe_keys = (
        # process essentials
        "PATH", "HOME", "LANG", "LC_ALL", "TZ", "TERM", "TMPDIR",
        "SYSTEMROOT", "WINDIR", "PATHEXT", "VIRTUAL_ENV",
        # who this machine's account is. The account *name* carries no authority — it is not a
        # credential and not a handle to one — but tools that already hold a login look it up to
        # find that login. Without USER the Claude CLI reported no login at all in this sanitized
        # environment, so ask_agent could not consult a Bot on a working Claude subscription.
        "USER", "LOGNAME", "USERNAME",
        # how this machine reaches the network and trusts certificates. Dropping these does not
        # fail loudly — the Bot simply cannot reach the model behind a corporate proxy, or rejects
        # a TLS-inspecting one. Read by utils.py, agent/proxy_bypass.py, agent/process_bootstrap.py
        # and the model-provider plugins.
        "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "no_proxy", "all_proxy",
        # where this machine keeps config and data. Hermes resolves 1Password and Bitwarden secret
        # sources through these (agent/secret_sources/, agent/vault_backends/), so without them a
        # Bot whose keys live in a vault cannot find them.
        "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
    )
    # Deliberately absent: SSH_AUTH_SOCK, GPG_AGENT_INFO and anything else that hands the child a
    # live handle to the caller's own credentials. This list is for reaching the network and
    # finding config, never for carrying authority.
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
