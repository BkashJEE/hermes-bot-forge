#!/usr/bin/env python3
"""Health check for every Bot: what's running, what's costing money, what's been forgotten.

usage: health.py spec.json   (or: health.py - < spec.json)

Spec: {"hermes_root": "...", "name": "optional single Bot"}

Read-only. Reports per Bot: model, gateway, routines with estimated runs/day, last activity, and flags —
too-frequent routines, paused or never-run routines, unused Bots, a SOUL.md that doesn't state the Bot's
name or approval checkpoints. Suggestions only; it never changes anything.
"""
import contextlib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

import forge

STALE_DAYS = 7
EXPENSIVE_RUNS_PER_DAY = 24


def _jobs(pdir: Path) -> list:
    try:
        data = json.loads((pdir / "cron" / "jobs.json").read_text())
    except (OSError, ValueError):
        return []
    jobs = data.get("jobs", []) if isinstance(data, dict) else data
    return [j for j in jobs if isinstance(j, dict)]


def _schedule_text(job: dict) -> str:
    sched = job.get("schedule")
    if isinstance(sched, dict):
        if sched.get("kind") == "interval" and sched.get("minutes"):
            return f"every {sched['minutes']}m"
        return str(sched.get("expr") or sched.get("display") or sched.get("run_at") or "")
    return str(sched or job.get("schedule_display") or "")


def _ts(value) -> float:
    if isinstance(value, (int, float)):
        return float(value) / (1000 if value > 1e12 else 1)
    if isinstance(value, str) and value:
        try:
            from datetime import datetime
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _last_active(pdir: Path) -> float:
    db = pdir / "state.db"
    if not db.exists():
        return 0.0
    try:
        with contextlib.closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)) as c:
            row = c.execute("select max(started_at) from sessions").fetchone()
            return float(row[0] or 0)
    except sqlite3.Error:
        return 0.0


def _gateways(root: Path) -> dict:
    """Profile -> running? from `hermes gateway list` (best effort)."""
    try:
        out = forge.run(root, "gateway", "list", check=False, timeout=60).stdout
    except Exception:
        return {}
    states = {}
    for line in out.splitlines():
        m = re.match(r"\s*([✓✗•\-])\s+([a-z0-9_-]+)", line)
        if m:
            states[m.group(2)] = m.group(1) == "✓"
    return states


def _journal_status(pdir: Path) -> dict:
    """Small, read-only journal summary; entry bodies stay out of health reports."""
    import journal

    folder = pdir / "journal"
    files = sorted(folder.glob("????-??-??.md")) if folder.is_dir() and not folder.is_symlink() else []
    entries = 0
    for path in files:
        try:
            entries += path.read_text(errors="ignore").count("\n## ")
        except OSError:
            continue
    return {"enabled": journal.journaling_enabled(pdir), "entries": entries,
            "latest": files[-1].stem if files else None}


def _acks_enabled(pdir: Path) -> bool:
    import acks
    return acks.acks_enabled(pdir)


def check_bot(pdir: Path, gateways: dict, now: float) -> dict:
    name = pdir.name
    meta = forge.load_yaml(pdir / "profile.yaml")
    bots = (meta.get("ui_meta") or {}).get("hermes-bots") or {}
    title = (bots.get("title") if isinstance(bots, dict) else None) or meta.get("display_name") or name
    cfg = forge.load_yaml(pdir / "config.yaml")
    soul = (pdir / "SOUL.md").read_text(errors="ignore") if (pdir / "SOUL.md").exists() else ""
    flags, routines, total_runs = [], [], 0.0

    for job in _jobs(pdir):
        sched = _schedule_text(job)
        rate = forge.runs_per_day(sched)
        total_runs += rate if job.get("enabled", True) else 0
        last = _ts(job.get("last_run_at"))
        entry = {"id": job.get("id"), "name": job.get("name") or sched, "schedule": sched,
                 "runs_per_day": round(rate, 1), "enabled": bool(job.get("enabled", True))}
        routines.append(entry)
        label = f"routine '{entry['name']}'"
        if entry["enabled"] and rate > EXPENSIVE_RUNS_PER_DAY:
            flags.append(f"{label} runs ~{int(rate)}×/day — every run is a model call; slow it down")
        if not entry["enabled"] or str(job.get("state", "")).lower() == "paused":
            flags.append(f"{label} is paused — resume it or remove it")
        elif not last and _ts(job.get("created_at")) and now - _ts(job.get("created_at")) > 2 * 86400:
            flags.append(f"{label} has never run")

    backend = ((cfg.get("terminal") or {}).get("backend") or "local").lower()
    shell_tools = {"terminal", "code_execution", "computer_use"} & set((cfg.get("platform_toolsets") or {}).get("cli") or [])
    if shell_tools and backend in ("", "local"):
        flags.append(f"runs {'/'.join(sorted(shell_tools))} directly on this machine — create it with a sandbox "
                     f"(docker) if you want it isolated")

    active = _last_active(pdir)
    idle_days = int((now - active) / 86400) if active else None
    if routines and idle_days is not None and idle_days >= STALE_DAYS:
        flags.append(f"no chats for {idle_days} days but routines keep running — still needed?")
    elif idle_days is not None and idle_days >= STALE_DAYS * 4:
        flags.append(f"unused for {idle_days} days — hide or delete it?")
    if soul and f"**{title}**" not in soul and title.lower() not in soul.lower()[:400]:
        flags.append("SOUL.md doesn't state the Bot's own name — it may introduce itself as another Bot")
    if soul and "## Ask first" not in soul and "approval" not in soul.lower():
        flags.append("no approval checkpoints in SOUL.md — add them with update_agent")
    if name in gateways and not gateways[name]:
        flags.append("gateway is not running — `hermes -p %s gateway start`" % name)

    return {"name": name, "display_name": title, "model": (cfg.get("model") or {}).get("default", ""),
            "gateway": {True: "running", False: "stopped"}.get(gateways.get(name), "unknown"),
            "routines": routines, "runs_per_day": round(total_runs, 1),
            "sandbox": backend, "acknowledges": _acks_enabled(pdir),
            "journal": _journal_status(pdir),
            "idle_days": idle_days, "hidden": bool(isinstance(bots, dict) and bots.get("hidden")),
            "flags": flags, "status": "attention" if flags else "ok"}


def check(s: dict) -> dict:
    root = Path(s.get("hermes_root") or forge.default_root())
    now = time.time()
    profiles = root / "profiles"
    bots = [d for d in sorted(profiles.iterdir()) if forge.is_live_profile(d)] if profiles.is_dir() else []
    if s.get("name"):
        wanted = forge.slug(str(s["name"]))

        def matches(d):
            meta = forge.load_yaml(d / "profile.yaml")
            title = ((meta.get("ui_meta") or {}).get("hermes-bots") or {}).get("title") or meta.get("display_name") or ""
            return wanted in {d.name, forge.slug(str(title))}

        bots = [d for d in bots if matches(d)]
        if not bots:
            return {"ok": False, "error": f"no Bot named '{s['name']}'"}
    import waiting
    gateways = _gateways(root)
    report = [check_bot(d, gateways, now) for d in bots]
    pending = waiting.waiting_on_user(root)
    attention = [b for b in report if b["flags"]]
    silent = [b["display_name"] for b in report if not b.get("acknowledges")]
    return {"ok": True, "bots": len(report), "needing_attention": len(attention),
            "not_acknowledging": silent,
            "waiting_on_you": pending["items"], "waiting_count": pending["count"],
            "total_routine_runs_per_day": round(sum(b["runs_per_day"] for b in report), 1),
            "report": report,
            "summary": (f"{pending['count']} waiting on you — {pending['summary']}" if pending["count"] else
                        "all Bots look healthy" if not attention else
                        "; ".join(f"{b['display_name']}: {b['flags'][0]}" for b in attention[:5]))}


def main():
    raw = sys.stdin.read() if len(sys.argv) < 2 or sys.argv[1] == "-" else Path(sys.argv[1]).read_text()
    print(json.dumps(check(json.loads(raw or "{}")), indent=2))


if __name__ == "__main__":
    main()
