#!/usr/bin/env python3
"""Build a whole team of Hermes Bots in one go: a lead plus specialists that report to it.

usage: team.py spec.json   (or: team.py - < spec.json)

Spec:
{
  "team": "Content",                       # optional label, used in the lead's brief
  "lead": {...create_agent fields...},     # optional: the chief of staff, built first
  "lead_name": "ceo",                      # or point at an existing Bot instead of building one
  "members": [ {...create_agent fields...}, ... ],
  "hermes_root": "...", "settings": {...}
}

Members are built one at a time. A member that fails is rolled back on its own; the rest of the team
stands. The lead learns who joined (roster in its memory) so it can delegate straight away.
"""
import json
import sys
from pathlib import Path

import forge

MAX_MEMBERS = 6


def _build(member: dict, base: dict, reports_to: str = "") -> dict:
    spec = {**member, "hermes_root": base["hermes_root"], "settings": base["settings"],
            "launch_profile": base.get("launch_profile") or "default"}
    if reports_to and not spec.get("reports_to"):
        spec["reports_to"] = reports_to
    return forge.forge(spec)


def _tell_lead(root: Path, lead_id: str, team: str, roster: list):
    """Append the roster to the lead's memory so it knows who to delegate to."""
    mem = (root if lead_id == "default" else root / "profiles" / lead_id) / "memories" / "MEMORY.md"
    if not mem.parent.is_dir():
        return
    lines = [f"- @{m['name']} ({m['display_name']}): {m['description']}" for m in roster]
    entry = (f"I lead the {team} team. My team and what each one does:\n" + "\n".join(lines)
             + "\nI delegate to them by name instead of doing their work myself.")
    existing = mem.read_text().rstrip() if mem.exists() else ""
    mem.write_text((existing + "\n§\n" if existing else "") + entry + "\n")


def build_team(s: dict) -> dict:
    root = Path(s.get("hermes_root") or forge.default_root())
    base = {"hermes_root": str(root), "settings": s.get("settings") or {},
            "launch_profile": s.get("launch_profile") or "default"}
    members = [m for m in (s.get("members") or []) if isinstance(m, dict)][:MAX_MEMBERS]
    if not members:
        return {"ok": False, "error": "a team needs at least one member (list them in `members`)"}

    team = (s.get("team") or "").strip() or "the"
    built, failed = [], []

    # 1. the lead — either a new Bot or one that already exists
    lead = None
    if s.get("lead"):
        result = _build(s["lead"], base)
        if not result.get("ok"):
            return {"ok": False, "error": f"the team lead could not be built: {result.get('error')}",
                    "rolled_back": result.get("rolled_back", False)}
        lead = result
        built.append(result)
    elif s.get("lead_name"):
        wanted = str(s["lead_name"]).strip().lstrip("@").lower()
        if wanted == "default" or (root / "profiles" / wanted / "config.yaml").exists():
            lead = {"name": wanted, "display_name": wanted}
        else:
            return {"ok": False, "error": f"no Bot named '{wanted}' to lead the team (see list_agents)"}

    # 2. the specialists
    for member in members:
        result = _build(member, base, reports_to=(lead or {}).get("name", ""))
        (built if result.get("ok") else failed).append(result)

    roster = [m for m in built if m.get("ok") and m["name"] != (lead or {}).get("name")]
    if lead and roster:
        try:
            _tell_lead(root, lead["name"], team, roster)
        except OSError:
            pass

    made = [{k: m.get(k) for k in ("name", "display_name", "model", "routines", "warning", "gateway", "connect_next")
             if m.get(k)} for m in built if m.get("ok")]
    out = {"ok": bool(made), "team": s.get("team") or None,
           "lead": (lead or {}).get("name"), "members": made,
           "failed": [{"name": f.get("name"), "error": f.get("error")} for f in failed],
           "note": "report created members, failures, and each member's warning and gateway readiness"}
    if not made:
        out["error"] = "no Bot in the team could be built"
    return out


def main():
    raw = sys.stdin.read() if len(sys.argv) < 2 or sys.argv[1] == "-" else Path(sys.argv[1]).read_text()
    result = build_team(json.loads(raw))
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
