"""Where a new Bot fits in the workspace it was born into.

A Bot arrives knowing its own job and nothing about the place it landed, so the first thing a user
has to do is explain their own machine to it — which repo holds the content, which Bot already
covers this, what is already scheduled. This reads that once, scores it against the Bot's own
directives, and writes the answer into the Bot's memory, so the Bot knows on turn one and never
runs the research again.

Three rules hold it in place:

* **Read-only and shallow.** Directory names, git remotes, the head of a README / AGENTS.md /
  CLAUDE.md, a package.json's name and description. Never source files, never deeper than
  `MAX_DEPTH`, never inside `SKIP_DIRS`, and never past `BUDGET_SECONDS`.
* **Indexed once, shared by every Bot.** The scan is cached under the Hermes root and reused until
  a root's mtime moves, so the tenth Bot costs nothing.
* **Deterministic.** Scoring is word overlap against the Bot's job — the same mechanic
  `forge.suggest_connectors` already uses for the MCP catalog. No model call, no tokens, no
  second opinion to wait for.

Nothing here writes outside the Bot's own profile, and everything that reaches memory is
secret-scanned first.
"""

import json
import os
import re
import subprocess
import time
from pathlib import Path

try:
    from . import forge
except ImportError:  # standalone CLI/repository import
    import forge

WORKSPACE_MARKER = "<!-- bot-forge-workspace:v1 -->"
INDEX_REL = Path(".bot-forge") / "workspace.json"

MAX_DEPTH = 3
MAX_PLACES = 120
BUDGET_SECONDS = 3.0
HEAD_LINES = 40
HEAD_BYTES = 4000
INDEX_TTL = 6 * 3600

SKIP_DIRS = {
    "node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build", "target", ".next",
    ".cache", ".cargo", ".rustup", ".npm", "vendor", "site-packages", ".mypy_cache", ".pytest_cache",
    "coverage", ".terraform", "Pods", ".gradle", ".tox", "snapshots", "renders",
}
# Read-only signals, cheapest first. A file only contributes its head.
HEAD_FILES = ("README.md", "readme.md", "AGENTS.md", "CLAUDE.md", "SKILL.md")
# An overlap this strong means an existing Bot already holds the job.
# Generic English only — never a word that names what a Bot does.
STOPWORDS = {"the", "and", "for", "with", "that", "this", "your", "from", "into", "you", "are", "its",
             "their", "them", "they", "all", "any", "not", "but", "has", "have", "can", "will", "our",
             "use", "using", "via", "per", "own", "end", "new", "one", "two", "each", "when", "what",
             "who", "how", "why", "here", "there", "then", "than", "also", "just", "only", "user",
             "users", "primary", "every", "before", "after", "about", "into", "over", "under"}

# In a Hermes workspace these match everything, so they identify nothing.
LOCAL_NOISE = {"hermes", "agent", "agents", "plugin", "plugins", "skill", "skills", "bots", "claude"}
OVERLAP_STRONG = 0.50
OVERLAP_NEAR = 0.30


# ── terms ────────────────────────────────────────────────────────────────────
def stem(word: str) -> str:
    """Crude, deliberate stemming so two personas written by different agents can match.

    One writes "write x.com posts", another "writing and repurposing posts" — without this they
    share almost nothing. Over-stemming collides a few unrelated words, which costs a little
    precision; missing the match entirely costs the whole feature.
    """
    w = word.strip(".-_,:;!?")
    for suffix in ("ing", "ed", "es", "s"):
        if len(w) - len(suffix) >= 4 and w.endswith(suffix):
            w = w[: -len(suffix)]
            break
    return w[:-1] if len(w) > 4 and w.endswith("e") else w


# Noise has to be matched in stemmed form too: `hermes` stems to `herm`, which would otherwise
# sail past a list that only knows the whole word.
_NOISE = STOPWORDS | LOCAL_NOISE
_NOISE |= {stem(w) for w in _NOISE}


def terms(text: str) -> set:
    """The words a job is actually about, stemmed and stripped of noise.

    This keeps its own stopword list rather than reusing `forge.STOPWORDS`: that list drops
    `posts`, `media`, `manage` and `work`, which is right for matching a connector catalogue and
    exactly wrong here — they are the words a social or ops Bot is *made of*. `hermes`, `agent`
    and `plugin` go the other way: inside a Hermes workspace they appear everywhere, so they
    identify nothing.
    """
    found = set()
    for raw in re.findall(r"[a-z][a-z0-9+.#-]{2,}", (text or "").lower()):
        w = stem(raw)
        if len(w) >= 3 and w not in _NOISE and raw not in _NOISE:
            found.add(w)
    return found


def weight(term: str) -> float:
    """A compound or a domain is specific; a bare word is not.

    `social-media` and `x.com` say what a Bot does; `write` and `media` could belong to anything,
    so two Bots sharing the specific terms should read as the same territory even when their prose
    has little else in common — which is exactly how two personas written by different agents look.
    """
    return 2.0 if ("-" in term or "." in term) else 1.0


def mass(words) -> float:
    return sum(weight(w) for w in words)


def job_terms(spec: dict) -> set:
    """What the Bot's job is ABOUT, from what it already declares — no new research needed.

    Deliberately excludes the toolset list and the Bot's own name: `file`, `web`, `browser` are
    capabilities every Bot has, and `Quill` matches nothing. Including them only dilutes the
    denominator and pushes a real domain match below the threshold.
    """
    parts = [spec.get("role"), spec.get("one_job"), spec.get("description")]
    parts += list(spec.get("skill_categories") or [])
    parts += list(spec.get("memory") or [])
    soul = spec.get("soul_md") or ""
    # The persona's job section carries the real vocabulary; the rest is style.
    m = re.search(r"##\s*Your one job\s*\n(.{0,600})", soul, re.S | re.I)
    if m:
        parts.append(m.group(1))
    return terms(" ".join(p for p in parts if isinstance(p, str)))


def overlap(a: set, b: set) -> float:
    """How much of the smaller vocabulary the two share (0–1).

    Dividing by the smaller set is what makes a short, specific job comparable to a long README:
    against `len(a)` a real match drowns in the larger document's vocabulary. An empty set on
    either side is 0, never a division by zero — a Bot with no persona yet has no territory.
    """
    if not a or not b:
        return 0.0
    return mass(a & b) / min(mass(a), mass(b))


def covered_share(wanted: set, other: set) -> float:
    """How much of THIS Bot's job an existing Bot already covers (0–1).

    Deliberately directional, and different from `overlap`. For a place, the question is mutual
    similarity. For a Bot it is not: a broad generalist whose vocabulary dwarfs this job still
    covers it completely, and dividing by its larger vocabulary would hide exactly the duplicate
    the guard exists to catch. What matters is the share of the new job already spoken for.
    """
    if not wanted or not other:
        return 0.0
    return mass(wanted & other) / mass(wanted)


# ── the workspace ────────────────────────────────────────────────────────────
def default_roots() -> list:
    """Where the Bot was created: the working directory Hermes is running in.

    Hermes exports the terminal's directory for its tools; fall back to the process cwd. The home
    directory itself is never a root — a Bot's birthplace is a project, not a whole machine.
    """
    for var in ("HERMES_TERMINAL_CWD", "TERMINAL_CWD", "PWD"):
        value = os.environ.get(var)
        if value and Path(value).is_dir():
            here = Path(value).resolve()
            break
    else:
        try:
            here = Path.cwd().resolve()
        except OSError:
            return []
    return [] if here == Path.home() else [here]


def configured_roots(settings: dict) -> list:
    out = []
    for raw in (settings or {}).get("workspace_roots") or []:
        try:
            p = Path(str(raw)).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if p.is_dir():
            out.append(p)
    return out


def _head(path: Path) -> str:
    try:
        with path.open(errors="ignore") as fh:
            return "".join(line for _i, line in zip(range(HEAD_LINES), fh))[:HEAD_BYTES]
    except OSError:
        return ""


def _git_remote(d: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(d), "config", "--get", "remote.origin.url"],
                             capture_output=True, text=True, timeout=3)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _headline(text: str) -> str:
    """The first line that actually says what this is.

    READMEs open with badge tables, centred HTML and YAML front matter; taking line one gives
    `<p align="center">`. Prefer the first markdown heading, then the first line of real prose.
    """
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":  # YAML front matter
        end = next((i for i, ln in enumerate(lines[1:], 1) if ln.strip() == "---"), 0)
        lines = lines[end + 1:]
    for line in lines:
        s = line.strip()
        if s.startswith("#"):
            s = s.lstrip("#").strip()
            if s:
                return s
    for line in lines:
        s = line.strip()
        if not s or s.startswith(("<", "![", "[!", "|", "-", "*", ">", "```", "<!--")):
            continue
        return re.sub(r"[*_`]", "", s)
    return ""


def _describe(d: Path) -> dict:
    """What a directory says about itself, from its own front matter only."""
    blurb, headline = "", ""
    for name in HEAD_FILES:
        f = d / name
        if f.is_file():
            text = _head(f)
            if text.strip():
                headline = _headline(text)
                blurb = text
                break
    pkg = d / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(errors="ignore")[:HEAD_BYTES * 4])
            blurb += f" {data.get('name', '')} {data.get('description', '')}"
            headline = headline or str(data.get("description") or "")
        except (OSError, ValueError):
            pass
    return {"headline": headline[:200], "blurb": blurb}


def scan_places(roots: list, now: float | None = None) -> list:
    """Every plausible place in the workspace, with the cheap signals that describe it."""
    now = now or time.time()
    deadline = now + BUDGET_SECONDS
    places = []
    for root in roots:
        stack = [(root, 0)]
        while stack and len(places) < MAX_PLACES and time.time() < deadline:
            d, depth = stack.pop()
            try:
                children = sorted(d.iterdir())
            except OSError:
                continue
            is_repo = (d / ".git").exists()
            described = _describe(d)
            if depth > 0 or is_repo:
                try:
                    mtime = d.stat().st_mtime
                except OSError:
                    mtime = 0
                places.append({
                    "path": str(d), "name": d.name, "repo": is_repo,
                    "remote": _git_remote(d) if is_repo else "",
                    "headline": described["headline"],
                    "terms": sorted(terms(f"{d.name} {described['blurb']} {described['headline']}"))[:80],
                    "days_idle": round(max(0.0, (now - mtime) / 86400), 1) if mtime else None,
                })
            if depth < MAX_DEPTH:
                for c in children:
                    if c.is_dir() and not c.is_symlink() and c.name not in SKIP_DIRS \
                            and not (c.name.startswith(".") and c.name != ".github"):
                        stack.append((c, depth + 1))
    return places


def scan_hermes(root: Path) -> dict:
    """What this Hermes install already runs — Bots, their jobs, routines, skills, plugins."""
    root = Path(root)
    bots, profiles = [], root / "profiles"
    for pdir in sorted(profiles.iterdir()) if profiles.is_dir() else []:
        if not forge.is_live_profile(pdir):
            continue
        meta = ((forge.load_yaml(pdir / "profile.yaml").get("ui_meta") or {}).get("hermes-bots") or {})
        if not meta:
            continue
        soul = (pdir / "SOUL.md").read_text(errors="ignore")[:2000] if (pdir / "SOUL.md").is_file() else ""
        jobs = re.search(r"##\s*Your one job\s*\n(.{0,400})", soul, re.S | re.I)
        one_job = " ".join((jobs.group(1) if jobs else "").split())[:240]
        routines = []
        jobs_file = pdir / "cron" / "jobs.json"
        if jobs_file.is_file():
            try:
                data = json.loads(jobs_file.read_text(errors="ignore"))
                routines = [str(j.get("name") or j.get("schedule") or "")[:60]
                            for j in (data if isinstance(data, list) else data.get("jobs") or [])][:6]
            except (OSError, ValueError):
                routines = []
        bots.append({"bot": pdir.name, "display_name": meta.get("title") or pdir.name,
                     "one_job": one_job, "routines": routines,
                     "terms": sorted(terms(f"{meta.get('title', '')} {meta.get('description', '')} {one_job}"))[:60]})
    skills = sorted({p.name for p in (root / "skills").iterdir()
                     if p.is_dir()} if (root / "skills").is_dir() else set())[:60]
    plugins = sorted({p.name for p in (root / "plugins").iterdir()
                      if p.is_dir()} if (root / "plugins").is_dir() else set())[:60]
    return {"bots": bots, "skills": skills, "plugins": plugins}


# ── the index ────────────────────────────────────────────────────────────────
def index_file(root: Path) -> Path:
    return Path(root) / INDEX_REL


def _roots_stamp(roots: list) -> list:
    out = []
    for r in roots:
        try:
            out.append([str(r), round(r.stat().st_mtime, 3)])
        except OSError:
            out.append([str(r), 0])
    return out


def load_index(root: Path, roots: list, now: float | None = None) -> dict | None:
    """The cached scan, when it is still true for these roots."""
    now = now or time.time()
    f = index_file(root)
    if not f.is_file():
        return None
    try:
        data = json.loads(f.read_text(errors="ignore"))
    except (OSError, ValueError):
        return None
    if now - float(data.get("built") or 0) > INDEX_TTL:
        return None
    if data.get("roots") != _roots_stamp(roots):
        return None
    return data


def build_index(root: Path, roots: list, now: float | None = None) -> dict:
    now = now or time.time()
    data = {"built": now, "roots": _roots_stamp(roots),
            "places": scan_places(roots, now), "hermes": scan_hermes(root)}
    f = index_file(root)
    try:
        f.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        f.write_text(json.dumps(data))
        os.chmod(f, 0o600)
    except OSError:
        pass  # an unwritable cache costs speed, never correctness
    return data


def workspace_index(root: Path, settings: dict | None = None, now: float | None = None,
                    refresh: bool = False) -> dict:
    roots = configured_roots(settings or {}) or default_roots()
    if not roots:
        return {"built": now or time.time(), "roots": [], "places": [], "hermes": scan_hermes(root)}
    if not refresh:
        cached = load_index(root, roots, now)
        if cached:
            return cached
    return build_index(root, roots, now)


# ── what it means for this Bot ───────────────────────────────────────────────
def where_it_fits(index: dict, wanted: set, limit: int = 4) -> list:
    """Places in the workspace whose own words match this Bot's job."""
    scored = []
    for place in index.get("places") or []:
        share = overlap(wanted, set(place.get("terms") or []))
        if share <= 0:
            continue
        # a repo is a stronger home than a loose folder, and recent work beats a dormant tree
        weight = share + (0.08 if place.get("repo") else 0)
        idle = place.get("days_idle")
        if isinstance(idle, (int, float)) and idle < 30:
            weight += 0.05
        scored.append((weight, share, place))
    scored.sort(key=lambda s: (-s[0], s[2]["name"]))
    return [{"path": p["path"], "name": p["name"], "repo": p["repo"], "remote": p.get("remote", ""),
             "headline": p.get("headline", ""), "days_idle": p.get("days_idle"),
             "match": round(share, 2)} for _w, share, p in scored[:limit]]


def existing_coverage(index: dict, wanted: set, exclude: str = "") -> list:
    """Bots already working in this territory, strongest first."""
    out = []
    for bot in (index.get("hermes") or {}).get("bots") or []:
        if bot.get("bot") == exclude:
            continue
        share = covered_share(wanted, set(bot.get("terms") or []))
        if share > 0:
            out.append({**{k: bot[k] for k in ("bot", "display_name", "one_job", "routines")},
                        "match": round(share, 2)})
    out.sort(key=lambda b: -b["match"])
    return out


def overlap_guard(index: dict, wanted: set, exclude: str = "") -> dict | None:
    """The Bot this one would duplicate, when there is one.

    A guard, not a veto: it hands the caller a refusal to relay and a narrower way through, and
    `allow_overlap` walks past it. Two Bots with the same job is the failure mode that makes a
    roster useless — better to say so at birth than to let the user discover it later.
    """
    for bot in existing_coverage(index, wanted, exclude):
        if bot["match"] >= OVERLAP_STRONG:
            return {**bot, "verdict": "duplicate"}
        if bot["match"] >= OVERLAP_NEAR:
            return {**bot, "verdict": "adjacent"}
        break
    return None


def matching_skills(index: dict, wanted: set, limit: int = 5) -> list:
    """Skills already installed here that this Bot's job names."""
    hermes = index.get("hermes") or {}
    hits = []
    for name in (hermes.get("skills") or []) + (hermes.get("plugins") or []):
        own = terms(name.replace("-", " "))
        if own and len(own & wanted) / len(own) >= 0.5:
            hits.append(name)
    return sorted(set(hits))[:limit]


def next_steps(fits: list, covered: list, skills: list) -> list:
    """Concrete things the user can do with what is already here."""
    steps = []
    if fits:
        top = fits[0]
        steps.append(f"Point it at {top['name']} first — {top['path']}"
                     + (f" ({top['headline']})" if top["headline"] else ""))
    for place in fits[1:3]:
        steps.append(f"Also relevant: {place['name']} — {place['path']}")
    if skills:
        steps.append("Already installed here and worth giving it: " + ", ".join(skills))
    for bot in covered[:1]:
        if bot["match"] >= OVERLAP_NEAR:
            steps.append(f"{bot['display_name']} works nearby — split the job or set reports_to")
    return steps[:5]


def survey(root: Path, spec: dict, settings: dict | None = None, now: float | None = None,
           exclude: str = "") -> dict:
    """Everything the new Bot should already know about where it landed."""
    index = workspace_index(root, settings, now)
    wanted = job_terms(spec)
    fits = where_it_fits(index, wanted)
    covered = existing_coverage(index, wanted, exclude)
    skills = matching_skills(index, wanted)
    return {"roots": [r[0] for r in index.get("roots") or []],
            "scanned": len(index.get("places") or []),
            "fits": fits, "covered_by": covered[:3], "skills_here": skills,
            "next_steps": next_steps(fits, covered, skills)}


def memory_block(result: dict) -> str:
    """What the Bot carries into turn one, so it never has to look again."""
    lines = [WORKSPACE_MARKER, "Where I work, surveyed when I was created:"]
    for place in result.get("fits") or []:
        head = f" — {place['headline']}" if place.get("headline") else ""
        lines.append(f"- {place['name']} at {place['path']}{head}")
    for bot in result.get("covered_by") or []:
        if bot["match"] >= OVERLAP_NEAR:
            lines.append(f"- @{bot['bot']} ({bot['display_name']}) already works in this territory: "
                         f"{bot['one_job'] or 'related job'}. Ask before taking its work.")
    if result.get("skills_here"):
        lines.append("- Already available here: " + ", ".join(result["skills_here"]))
    if len(lines) == 2:
        return ""
    lines.append("This was read from the workspace once. Trust it as a starting point, verify before "
                 "acting on a path, and do not re-survey unless the user asks.")
    return "\n".join(lines)


def attach(pdir: Path, result: dict) -> bool:
    """Append the survey to the Bot's memory, secret-scanned, never replacing what is there."""
    block = memory_block(result)
    if not block:
        return False
    try:
        from . import portable
    except ImportError:  # standalone CLI/repository import
        import portable

    if portable.scan_text(block)["verdict"] == "BLOCK":
        return False  # a path that looks like a credential never reaches memory
    mem = Path(pdir) / "memories" / "MEMORY.md"
    try:
        mem.parent.mkdir(exist_ok=True)
        current = mem.read_text(errors="ignore") if mem.is_file() else ""
        if WORKSPACE_MARKER in current:
            return False
        mem.write_text((current.rstrip() + "\n§\n" if current.strip() else "") + block + "\n")
    except OSError:
        return False
    return True
