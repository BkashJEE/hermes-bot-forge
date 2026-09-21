"""Portable Bot templates (.botforge.json): what gets shared, what never does, and the secret scan.

A template carries the Bot's design — persona, its own memory, tools, skill choices, taught skills, routines,
face. It never carries chat history, work journals, facts about the user (USER.md), credentials, logs or caches. Every
template is scanned for secrets on export and on import.
"""
import json
import re
from pathlib import Path

import forge

FORMAT = "bot-forge/template"
VERSION = 1
MAX_TEMPLATE_BYTES = 512_000

# High-confidence credential shapes → BLOCK. Generic "key: value" assignments → WARN.
SECRET_PATTERNS = {
    "OpenAI/Anthropic-style key": re.compile(r"\b(sk|rk)-(ant-|proj-)?[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "AWS access key": re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "Telegram bot token": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
}
GENERIC_SECRET = re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer)\b\s*[:=]\s*['\"]?[^\s'\"]{12,}")


def scan_text(text: str) -> dict:
    """Verdict for a blob of text. Reports the kind and location of a finding, never the value."""
    findings = []
    for kind, rx in SECRET_PATTERNS.items():
        for m in rx.finditer(text):
            findings.append({"kind": kind, "severity": "block", "line": text.count("\n", 0, m.start()) + 1})
    for m in GENERIC_SECRET.finditer(text):
        findings.append({"kind": f"'{m.group(1)}' assignment", "severity": "warn",
                         "line": text.count("\n", 0, m.start()) + 1})
    verdict = "BLOCK" if any(f["severity"] == "block" for f in findings) else ("WARN" if findings else "CLEAN")
    return {"verdict": verdict, "findings": findings[:20]}


def _memory_entries(pdir: Path) -> list:
    mem = pdir / "memories" / "MEMORY.md"
    if not mem.exists():
        return []
    return [e.strip() for e in mem.read_text(errors="ignore").split("§") if e.strip()]


def build_template(pdir: Path, root: Path) -> dict:
    """Snapshot a live Bot as a shareable template (design only — no history, user facts or credentials)."""
    meta = forge.load_yaml(pdir / "profile.yaml")
    bots = (meta.get("ui_meta") or {}).get("hermes-bots") or {}
    bots = bots if isinstance(bots, dict) else {}
    cfg = forge.load_yaml(pdir / "config.yaml")
    taught = {}
    taught_dir = pdir / "skills" / "taught"
    if taught_dir.is_dir():
        for skill_md in sorted(taught_dir.glob("*/SKILL.md")):
            taught[skill_md.parent.name] = skill_md.read_text(errors="ignore")
    routines = []
    try:
        data = json.loads((pdir / "cron" / "jobs.json").read_text())
        for job in (data.get("jobs", []) if isinstance(data, dict) else data):
            sched = job.get("schedule")
            if isinstance(sched, dict):
                sched = (f"every {sched['minutes']}m" if sched.get("kind") == "interval" and sched.get("minutes")
                         else sched.get("expr") or sched.get("display"))
            if sched and job.get("prompt"):
                routines.append({"name": job.get("name") or "routine", "schedule": str(sched), "prompt": job["prompt"]})
    except (OSError, ValueError, AttributeError):
        pass
    title = bots.get("title") or meta.get("display_name") or pdir.name
    shape = str(bots.get("shape") or "")
    return {
        "format": FORMAT, "version": VERSION,
        "display_name": title,
        "role": forge.soul_role((pdir / "SOUL.md").read_text(errors="ignore")) if (pdir / "SOUL.md").exists() else title,
        "description": meta.get("description") or bots.get("description") or "",
        "one_job": meta.get("description") or "",
        "soul_md": (pdir / "SOUL.md").read_text(errors="ignore") if (pdir / "SOUL.md").exists() else "",
        # the Bot's own starter facts; drop the auto-written identity line, the importer writes a fresh one
        "memory": [e for e in _memory_entries(pdir) if not e.startswith("My name is ")],
        "toolsets": [t for t in ((cfg.get("platform_toolsets") or {}).get("cli") or []) if t in forge.ALL_TOOLSETS],
        "disabled_skills": list((cfg.get("skills") or {}).get("disabled") or []),
        "taught_skills": taught,
        "routines": routines,
        "avatar_kind": shape.rsplit(":", 1)[-1] if shape.count(":") == 2 else "",
    }


def load_template(path: Path) -> dict:
    if path.stat().st_size > MAX_TEMPLATE_BYTES:
        raise ValueError(f"template is larger than {MAX_TEMPLATE_BYTES // 1000} KB")
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("not a bot-forge template (missing format: bot-forge/template)")
    if int(data.get("version", 0)) > VERSION:
        raise ValueError(f"template version {data['version']} is newer than this plugin understands")
    return data


def bundled_templates() -> dict:
    """name -> path for the starter templates shipped with the plugin."""
    folder = Path(__file__).resolve().parent / "templates"
    return {p.name.replace(".botforge.json", ""): p for p in sorted(folder.glob("*.botforge.json"))}
