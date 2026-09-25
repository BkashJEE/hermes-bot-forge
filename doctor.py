#!/usr/bin/env python3
"""`hermes bot-forge doctor` — is this install actually going to work?

Bot Forge is opt-in per profile and its tools only appear after the gateway restarts. Get either
step wrong and nothing errors: the agent simply never mentions the tools. This checks both, plus the
things that decide whether a new Bot can answer at all (model sign-in, sandbox backends), and prints
the exact next command. Read-only: it never changes a profile.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import forge

PLUGIN_DIR = Path(__file__).resolve().parent
OAUTH_PROVIDERS = {"openai-codex", "anthropic", "anthropic-oauth", "xai", "nous"}
SANDBOX_BACKENDS = {
    "docker": (["docker", "info"], "Docker is installed but not reachable — start the docker service "
                                   "(as root) and add yourself to the `docker` group"),
    "podman": (["podman", "info"], "Podman is installed but not reachable"),
    "singularity": (["singularity", "--version"], "Singularity is installed but not reachable"),
    "apptainer": (["apptainer", "--version"], "Apptainer is installed but not reachable"),
}
OK, WARN, FAIL = "ok", "warn", "fail"


def _run(*args, timeout=30):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HERMES_")}
    try:
        return subprocess.run(args, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError):
        return None


def sandbox_backends() -> dict:
    """Which per-Bot sandbox backends this machine can actually run right now."""
    found = {}
    for name, (probe, hint) in SANDBOX_BACKENDS.items():
        if not shutil.which(probe[0]):
            continue
        p = _run(*probe)
        found[name] = {"usable": bool(p and p.returncode == 0), "hint": "" if p and p.returncode == 0 else hint}
    return found


def _profiles(root: Path) -> list:
    out = [("default", root)]
    folder = root / "profiles"
    if folder.is_dir():
        out += [(d.name, d) for d in sorted(folder.iterdir()) if forge.is_live_profile(d)]
    return out


def _gateway_pids(root: Path) -> dict:
    p = _run("hermes", "gateway", "list", timeout=60)
    pids = {}
    if not p:
        return pids
    for line in p.stdout.splitlines():
        parts = line.split()
        if "PID" in line:
            name = next((w for w in parts if w not in {"✓", "✗", "—", "-", "PID"} and not w.isdigit()), "")
            pid = next((w for w in parts if w.isdigit()), "")
            if name:
                pids[name.strip("()")] = int(pid) if pid else 0
    return pids


def installed_dir(root: Path, profile: str, pdir: Path) -> Path:
    """Where this profile loads Bot Forge from — the installed copy, not this source checkout."""
    for candidate in (pdir / "plugins" / "bot-forge", root / "plugins" / "bot-forge"):
        if (candidate / "plugin.yaml").exists():
            return candidate.resolve()
    return PLUGIN_DIR


def _code_mtime(folder: Path) -> float:
    return max((f.stat().st_mtime for f in folder.glob("*.py")), default=0.0)


def _proc_start(pid: int) -> float:
    try:
        return Path(f"/proc/{pid}").stat().st_mtime
    except OSError:
        return 0.0


def check(root: Path | None = None) -> dict:
    root = Path(root or forge.default_root())
    checks, steps = [], []

    enabled, missing = [], []
    for name, pdir in _profiles(root):
        cfg = forge.load_yaml(pdir / "config.yaml")
        (enabled if "bot-forge" in ((cfg.get("plugins") or {}).get("enabled") or []) else missing).append((name, pdir))

    if enabled:
        checks.append({"check": "enabled", "status": OK,
                       "detail": "enabled on: " + ", ".join(n for n, _ in enabled)})
    else:
        checks.append({"check": "enabled", "status": FAIL,
                       "detail": "not enabled on any profile — an agent cannot see the tools"})
        steps.append("hermes plugins enable bot-forge   # and `hermes -p <bot> plugins enable bot-forge` per Bot")
    if missing and enabled:
        checks.append({"check": "other profiles", "status": OK,
                       "detail": "no Bot Forge on " + ", ".join(n for n, _ in missing)
                                 + " (fine — enable it only where you chat)"})

    # a gateway started before the plugin files changed is still serving the old code
    pids = _gateway_pids(root)
    stale = [n for n, pdir in enabled
             if pids.get(n) and _proc_start(pids[n]) < _code_mtime(installed_dir(root, n, pdir))]
    down = [n for n, _ in enabled if n in pids and not pids.get(n)]
    if stale:
        checks.append({"check": "gateway", "status": FAIL,
                       "detail": "started before the current plugin files — the tools will not appear: "
                                 + ", ".join(stale)})
        steps += [f"hermes{'' if n == 'default' else f' -p {n}'} gateway restart" for n in stale]
        steps.append("then quit and reopen Hermes Desktop")
    elif down:
        checks.append({"check": "gateway", "status": WARN, "detail": "not running: " + ", ".join(down)})
    else:
        checks.append({"check": "gateway", "status": OK, "detail": "up to date with the plugin files"})

    marked = any(((forge.load_yaml(p / "profile.yaml").get("ui_meta") or {}).get("hermes-bots"))
                 for _n, p in _profiles(root))
    checks.append({"check": "bot mode", "status": OK if marked else WARN,
                   "detail": "Desktop Bot Mode detected — new Bots appear in the roster" if marked else
                             "no Bot Mode marker found; Bots still work from the CLI, but the Desktop roster and "
                             "Bot Chat need Hermes Desktop"})

    # can a new Bot actually answer? it inherits this profile's model
    for name, pdir in enabled or _profiles(root)[:1]:
        model = (forge.load_yaml(pdir / "config.yaml").get("model") or {})
        provider, model_id = model.get("provider", ""), model.get("default", "")
        settings = (((forge.load_yaml(pdir / "config.yaml").get("plugins") or {}).get("entries") or {})
                    .get("bot-forge") or {}).get("settings") or {}
        has_fallback = bool(settings.get("fallback_model") or settings.get("probe_local_models"))
        if provider in OAUTH_PROVIDERS and not has_fallback:
            checks.append({"check": f"model ({name})", "status": WARN,
                           "detail": f"{model_id} signs in per profile, so a new Bot needs `hermes -p <bot> auth add "
                                     f"{provider}` once — or set a fallback_model / probe_local_models"})
        else:
            checks.append({"check": f"model ({name})", "status": OK,
                           "detail": f"{model_id or 'unset'} ({provider or 'unset'})"
                                     + (" with a fallback" if has_fallback else "")})

    if os.name == "nt":
        checks.append({"check": "platform", "status": WARN,
                       "detail": "Windows is untested: gateway install, sandboxes and login sharing are skipped; "
                                 "Bots are still created and usable from the CLI"})

    boxes = sandbox_backends()
    usable = [n for n, b in boxes.items() if b["usable"]]
    if usable:
        checks.append({"check": "sandboxes", "status": OK, "detail": "available: " + ", ".join(usable)})
    else:
        detail = "; ".join(b["hint"] for b in boxes.values() if b["hint"]) or \
                 "none installed — Bots share this machine's shell (install Docker for per-Bot isolation)"
        checks.append({"check": "sandboxes", "status": WARN, "detail": detail})

    import acks
    bots = [p for _n, p in _profiles(root)[1:]]
    acking = [p.name for p in bots if acks.acks_enabled(p)]
    if bots:
        silent = [p.name for p in bots if p.name not in acking]
        checks.append({"check": "acknowledgements", "status": OK if not silent else WARN,
                       "detail": f"{len(acking)}/{len(bots)} Bots acknowledge with a reaction"
                                 + (f" — {', '.join(silent)} predate the feature: ask an agent to "
                                    f"\"turn on acknowledgements for <name>\"" if silent else "")})

    import companion
    missing = companion.bots_without_marks(root)
    forged = [p for p in bots if (forge.load_yaml(p / "profile.yaml").get("ui_meta") or {}).get("hermes-bots")]
    if forged:
        reacting = len(forged) - len(missing)
        detail = f"{reacting}/{len(forged)} Bots can react to your message in the desktop app"
        if missing:
            detail += " — " + ", ".join(f"{m['display_name']} ({m['reason']})" for m in missing[:4]) + \
                      "; ask an agent to \"turn on reactions for <name>\""
        try:
            import tapback
            if not tapback.reactions_allowed():
                detail += ". Message Reactions is off in Settings → Appearance, so none of them will show"
        except Exception:
            pass
        checks.append({"check": "reactions", "status": OK if not missing else WARN, "detail": detail})

    import portable
    checks.append({"check": "templates", "status": OK,
                   "detail": ", ".join(sorted(portable.bundled_templates()))})

    versions = {n: forge.load_yaml(installed_dir(root, n, pdir) / "plugin.yaml").get("version", "?")
                for n, pdir in enabled}
    if len(set(versions.values())) > 1:
        checks.append({"check": "version", "status": WARN,
                       "detail": "profiles run different versions: "
                                 + ", ".join(f"{n} {v}" for n, v in versions.items())
                                 + " — `hermes -p <name> plugins update bot-forge`"})
    elif versions:
        checks.append({"check": "version", "status": OK, "detail": next(iter(versions.values()))})

    worst = FAIL if any(c["status"] == FAIL for c in checks) else (
        WARN if any(c["status"] == WARN for c in checks) else OK)
    return {"ok": worst != FAIL, "status": worst, "root": str(root), "checks": checks,
            "next_steps": steps,
            "summary": {OK: "Bot Forge is ready — ask a Bot to make you a Bot",
                        WARN: "Bot Forge works, but read the warnings",
                        FAIL: "Bot Forge will not be visible to your agents yet"}[worst]}


ICON = {OK: "✓", WARN: "!", FAIL: "✗"}


def render(result: dict) -> str:
    lines = [f"Bot Forge doctor — {result['root']}", ""]
    for c in result["checks"]:
        lines.append(f"  {ICON[c['status']]} {c['check']:22} {c['detail']}")
    lines += ["", f"  {result['summary']}"]
    if result["next_steps"]:
        lines += ["", "  Next:"] + [f"    {s}" for s in result["next_steps"]]
    return "\n".join(lines) + "\n"


def cli(args=None) -> int:
    result = check()
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
    else:
        print(render(result))
    return 0 if result["ok"] else 1


def main():
    as_json = "--json" in sys.argv
    result = check()
    print(json.dumps(result, indent=2) if as_json else render(result))
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
