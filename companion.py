"""Install the acknowledgement hook into a Bot's own profile.

Hermes runs a plugin hook in whichever profile runs the turn. Bot Forge lives in the profile that
*creates* Bots, so its hooks never fire when the user talks to one of those Bots — which is why a
reaction placed from here could never appear on a Bot's chat. The `marks/` companion is the piece
that ships with the Bot: two hooks, no tools, so a Bot gains the reaction and nothing else.
"""

import fnmatch
import shutil
from pathlib import Path

if __package__:
    from . import forge
else:
    import forge

MARKS_NAME = "bot-forge-marks"
SOURCE = Path(__file__).resolve().parent / "marks"
SENTINEL_NAME = "bot-forge-sentinel"
SENTINEL_SOURCE = Path(__file__).resolve().parent / "sentinel"
FORGE_DIR = Path(__file__).resolve().parent
# Never carried into a Bot with an inherited plugin: VCS and build litter, and anything that could
# hold a credential. A plugin's secrets live in its own .env; a Bot has to be given them by the user.
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache", ".mypy_cache", ".tox"}
ALL = {"all", "*"}  # list spellings of inherit_plugins: true
SKIP_FILES = (".env", ".env.*", "*.env", ".netrc", "auth.json", "auth.lock", "*.pem", "*.key", "*.p12",
              "*.pfx", "credentials*", "secret*", "*.secret", "*.secrets", "*.pyc")


def marks_version(folder: Path | None = None) -> str:
    return str(forge.load_yaml((folder or SOURCE) / "plugin.yaml").get("version") or "")


def installed_dir(pdir: Path) -> Path:
    return Path(pdir) / "plugins" / MARKS_NAME


def installed_version(pdir: Path) -> str:
    folder = installed_dir(pdir)
    return marks_version(folder) if (folder / "plugin.yaml").exists() else ""


def is_enabled(pdir: Path) -> bool:
    enabled = (forge.load_yaml(Path(pdir) / "config.yaml").get("plugins") or {}).get("enabled") or []
    return MARKS_NAME in enabled


def marks_ready(pdir: Path) -> bool:
    """Installed, at this version, and switched on."""
    return bool(installed_version(pdir)) and installed_version(pdir) == marks_version() and is_enabled(pdir)


def _enable(pdir: Path, name: str = MARKS_NAME) -> bool:
    """Switch a plugin on in the profile's config.yaml. Returns True when the config changed."""
    cfg_path = Path(pdir) / "config.yaml"
    cfg = forge.load_yaml(cfg_path)
    plugins = dict(cfg.get("plugins") or {})
    enabled = list(plugins.get("enabled") or [])
    disabled = [d for d in (plugins.get("disabled") or []) if d != name]
    if name in enabled and len(disabled) == len(plugins.get("disabled") or []):
        return False
    if name not in enabled:
        plugins["enabled"] = sorted(enabled + [name])
    if "disabled" in plugins:
        plugins["disabled"] = disabled
    cfg["plugins"] = plugins
    forge.dump_yaml(cfg_path, cfg)
    return True


def install_marks(pdir: Path) -> dict:
    """Copy the companion into the Bot and switch it on. Idempotent; re-copies on a version change."""
    pdir = Path(pdir)
    if not SOURCE.is_dir():
        return {"ok": False, "error": "companion source is missing from this install"}
    if not (pdir / "config.yaml").exists():
        return {"ok": False, "error": f"{pdir.name} has no config.yaml"}
    target = installed_dir(pdir)
    have, want = installed_version(pdir), marks_version()
    copied = have != want
    if copied:
        try:
            if target.exists():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(SOURCE, target)
        except OSError as exc:
            return {"ok": False, "error": f"could not install the reaction hook: {exc}"}
    switched = _enable(pdir)
    return {"ok": True, "name": MARKS_NAME, "version": want, "copied": copied,
            "enabled": switched or is_enabled(pdir), "previous_version": have or None}


# ── enforced approvals ───────────────────────────────────────────────────────
# A Bot's `approvals` are written into its SOUL.md as prose, which nothing checks. Sentinel
# turns the same list into pre_tool_call directives Hermes enforces, so what a Bot promises and
# what it may actually do stop being two different things.

# The approval wording create_agent writes -> the category Sentinel knows it by.
_APPROVAL_CATEGORIES = (("send", "send"), ("post", "send"), ("publish", "send"),
                        ("spend", "spend"), ("buy", "spend"), ("money", "spend"),
                        ("delete", "delete"), ("remove", "delete"))


def policy_for(approvals) -> dict:
    """The Sentinel policy a Bot's own declared approvals imply.

    A Bot that promised nothing gets no built-in categories: enforcing rules it never claimed
    would be us inventing its policy rather than holding it to its word. The explicit lists stay
    empty and editable, so an operator can always add rules by hand afterwards.
    """
    wording = " ".join(a.lower() for a in (approvals or []) if isinstance(a, str))
    covered = {category for word, category in _APPROVAL_CATEGORIES if word in wording}
    return {"guard_defaults": bool(covered), "mode": "allow",
            "refuse": [], "ask": [], "allow": []}


def install_sentinel(pdir: Path, approvals=None) -> dict:
    """Ship the policy layer into a Bot and write the policy its own approvals imply."""
    pdir = Path(pdir)
    if not SENTINEL_SOURCE.is_dir():
        return {"ok": False, "error": "the policy layer is missing from this install"}
    result = install_plugin(pdir, SENTINEL_NAME, SENTINEL_SOURCE, folder=SENTINEL_NAME)
    if not result.get("ok"):
        return result
    policy = policy_for(approvals)
    cfg_path = pdir / "config.yaml"
    cfg = forge.load_yaml(cfg_path)
    existing = cfg.get(SENTINEL_NAME)
    if isinstance(existing, dict):
        # Never undo a rule an operator added by hand; only fill in what is missing.
        policy = {**policy, **existing}
    cfg[SENTINEL_NAME] = policy
    forge.dump_yaml(cfg_path, cfg)
    return {**result, "policy": policy, "enforcing": bool(policy.get("guard_defaults"))}


# ── inherited plugins (issue #25) ────────────────────────────────────────────
def _manifest_name(folder: Path) -> str:
    return str(forge.load_yaml(folder / "plugin.yaml").get("name") or "").strip()


def plugin_dirs(home: Path) -> dict:
    """Plugins installed under a profile: directory name -> path (a manifest name that differs from
    the directory is added as an alias, since ``plugins.enabled`` may use either)."""
    folder = Path(home) / "plugins"
    found = {}
    if not folder.is_dir():
        return found
    for child in sorted(folder.iterdir()):
        if child.is_dir() and not child.name.startswith(".") and (child / "plugin.yaml").exists():
            found[child.name] = child
            alias = _manifest_name(child)
            if alias and alias != child.name:
                found.setdefault(alias, child)
    return found


def enabled_plugins(home: Path) -> list:
    plugins = forge.load_yaml(Path(home) / "config.yaml").get("plugins") or {}
    enabled = plugins.get("enabled") if isinstance(plugins, dict) else None
    return [str(n) for n in enabled if isinstance(n, str)] if isinstance(enabled, list) else []


def is_forge_itself(folder: Path) -> bool:
    """Bot Forge must never be copied into a Bot: a Bot would gain create/delete powers over Bots."""
    try:
        return Path(folder).resolve() == FORGE_DIR or _manifest_name(folder) == "bot-forge"
    except OSError:
        return False


def _ignore(folder, names):
    out = set()
    for name in names:
        if name in SKIP_DIRS or any(fnmatch.fnmatch(name, pat) for pat in SKIP_FILES):
            out.add(name)
    return out


def needs_credentials(source: Path) -> list:
    """Environment variables a plugin's manifest says it needs, if any.

    `requires_env` is how a plugin declares that it reaches into an account — a mail plugin, a
    tracker, anything holding a token. Those are exactly the plugins a Bot should not acquire as a
    side effect of "give it everything", because the reach arrives without the user ever naming it.
    """
    try:
        manifest = forge.load_yaml(Path(source) / "plugin.yaml")
    except Exception:
        return []
    declared = manifest.get("requires_env") or []
    return [str(e) for e in declared if str(e).strip()] if isinstance(declared, (list, tuple)) else []


def select_inherited(root: Path, wanted) -> tuple:
    """Resolve an ``inherit_plugins`` value into (name -> source dir, skipped reasons).

    ``True`` means every plugin enabled on the root profile that has a directory there; a list names
    them one by one. Bot Forge itself and its companion are never inherited (the companion is installed
    on its own path, at the current version). A name that cannot be carried is returned in the
    skipped list with its reason, never dropped silently."""
    root = Path(root)
    available = plugin_dirs(root)
    if isinstance(wanted, str):
        wanted = [wanted]
    if isinstance(wanted, (list, tuple)):
        names = [str(n).strip() for n in wanted if str(n).strip()]
        if any(n.lower() in ALL for n in names):
            wanted, names = True, []
    blanket = wanted is True
    if wanted is True:
        names = [n for n in enabled_plugins(root) if n in available]
    elif not isinstance(wanted, (list, tuple)):
        return {}, []
    chosen, skipped, seen = {}, [], set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        source = available.get(name)
        if name == MARKS_NAME or (source and _manifest_name(source) == MARKS_NAME):
            skipped.append({"name": name, "reason": "the reaction companion is installed by Bot Forge itself"})
        elif source is None:
            skipped.append({"name": name, "reason": "not installed under the root profile's plugins/"})
        elif is_forge_itself(source):
            skipped.append({"name": name, "reason": "Bot Forge is never copied into a Bot"})
        elif source.resolve() in {p.resolve() for p in chosen.values()}:
            continue  # alias of one already chosen
        elif blanket and needs_credentials(source):
            skipped.append({"name": name, "reason": "needs credentials (" +
                            ", ".join(needs_credentials(source)[:3]) +
                            ") — name it explicitly if this Bot should have that reach"})
        else:
            chosen[name] = source
    return chosen, skipped


def install_plugin(pdir: Path, name: str, source: Path, folder: str | None = None) -> dict:
    """Copy one plugin directory into the Bot and switch it on. Same path as install_marks: a fresh copy
    replaces an older one, credentials and build litter stay behind."""
    pdir, source = Path(pdir), Path(source)
    if not (source / "plugin.yaml").exists():
        return {"ok": False, "name": name, "error": f"{source} has no plugin.yaml"}
    target = pdir / "plugins" / (folder or source.name)
    try:
        if target.exists() or target.is_symlink():
            shutil.rmtree(target) if target.is_dir() and not target.is_symlink() else target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, ignore=_ignore)
    except OSError as exc:
        return {"ok": False, "name": name, "error": f"could not copy plugin {name}: {exc}"}
    _enable(pdir, name)
    return {"ok": True, "name": name, "version": str(forge.load_yaml(target / "plugin.yaml").get("version") or ""),
            "path": str(target)}


def inherit_plugins(root: Path, pdir: Path, wanted) -> dict:
    """Carry the root profile's user plugins into a new Bot (opt-in, see ``inherit_plugins``)."""
    chosen, skipped = select_inherited(root, wanted)
    installed, failed = [], []
    for name, source in chosen.items():
        out = install_plugin(pdir, name, source)
        (installed if out["ok"] else failed).append(out)
    return {"ok": not failed, "installed": installed, "skipped": skipped, "failed": failed}


def inert_plugins(home: Path, root: Path, bundled: set | None = None) -> list:
    """Names in ``plugins.enabled`` with no directory under this profile's plugins/ — enabled but inert.

    A cloned config.yaml carries the root profile's list, so this is the common state of a Bot. Hermes'
    own bundled plugins load from the install, not the profile, so they are never inert; when the
    bundled set cannot be read, only names that exist as a directory under the root profile are named,
    so a name we cannot classify is never reported."""
    home = Path(home)
    have = set(plugin_dirs(home))
    known = plugin_dirs(root) if bundled is None else None
    out = []
    for name in enabled_plugins(home):
        if name in have or name in (bundled or set()):
            continue
        if known is not None and name not in known:
            continue
        out.append(name)
    return out


def bundled_plugin_names() -> set | None:
    """Plugins that ship inside Hermes itself, or None when Hermes is not importable here."""
    try:
        from hermes_cli.plugins import get_bundled_plugins_dir  # type: ignore
        folder = Path(get_bundled_plugins_dir())
    except Exception:
        return None
    names = set()
    try:
        for child in folder.iterdir():
            if child.is_dir():
                names.add(child.name)
                alias = _manifest_name(child)
                if alias:
                    names.add(alias)
    except OSError:
        return None
    return names


def bots_without_marks(root: Path) -> list:
    """Live Bots that will not react, and why — for check_install."""
    root = Path(root)
    profiles = root / "profiles"
    out = []
    for pdir in sorted(profiles.iterdir()) if profiles.is_dir() else []:
        if not forge.is_live_profile(pdir):
            continue
        meta = ((forge.load_yaml(pdir / "profile.yaml").get("ui_meta") or {}).get("hermes-bots") or {})
        if not meta:
            continue  # not a Bot Forge Bot
        have = installed_version(pdir)
        if marks_ready(pdir):
            continue
        out.append({"bot": pdir.name, "display_name": meta.get("title") or pdir.name,
                    "reason": ("not installed" if not have else
                               "not enabled" if not is_enabled(pdir) else
                               f"version {have}, expected {marks_version()}")})
    return out


def companion_running(plugin_dir: Path) -> bool:
    """True when `bot-forge-marks` is installed and enabled beside this plugin.

    Both register the same pair of turn hooks, and Hermes treats setting the same emoji twice on a
    message as a tapback toggle — so with both loaded every reaction is placed and immediately
    cleared, and the user sees nothing at all. The companion wins that tie: it ships inside every
    Bot, including the profile that creates them, so it is the copy that is always present.
    """
    sibling = Path(plugin_dir).parent / MARKS_NAME
    if not (sibling / "plugin.yaml").exists():
        return False
    try:
        import yaml

        data = yaml.safe_load((Path(plugin_dir).parent.parent / "config.yaml").read_text()) or {}
    except Exception:
        return True  # installed but the config cannot be read: never risk double-placing
    return MARKS_NAME in ((data.get("plugins") or {}).get("enabled") or [])


# ── adoption ─────────────────────────────────────────────────────────────────
def reactions_setting(pdir: Path) -> bool:
    """Hermes' own Settings → Appearance → Message Reactions, for this profile."""
    display = forge.load_yaml(Path(pdir) / "config.yaml").get("display") or {}
    return display.get("message_reactions") is True


def enable_reactions_setting(pdir: Path) -> bool:
    """Switch the setting on. Unset means off in Hermes, and a Bot born without it is silent.

    This is the half that is easy to miss: the hook can be installed, enabled and running, and the
    Bot still never reacts, because Hermes reads `message_reactions` as False when it is absent.
    """
    path = Path(pdir) / "config.yaml"
    cfg = forge.load_yaml(path)
    if not cfg or (cfg.get("display") or {}).get("message_reactions") is True:
        return False
    display = dict(cfg.get("display") or {})
    display["message_reactions"] = True
    cfg["display"] = display
    forge.dump_yaml(path, cfg)
    return True


def ensure_reactions(pdir: Path) -> dict:
    """Everything a profile needs to acknowledge a message, in one idempotent call."""
    pdir = Path(pdir)
    installed = install_marks(pdir)
    if not installed.get("ok"):
        return {"ok": False, "bot": pdir.name, "error": installed.get("error")}
    return {"ok": True, "bot": pdir.name,
            "hook": bool(installed.get("copied")), "switched_on": bool(installed.get("enabled")),
            "setting": enable_reactions_setting(pdir)}


def adopt_all(root: Path, settings: dict | None = None) -> list:
    """Give every profile the reaction, including ones this plugin did not create.

    A Bot made through Hermes' own New Agent dialog, or a profile created on the command line, has
    no idea this plugin exists — and the user does not care which door a Bot came through; they
    expect all of them to behave the same. This runs on plugin load, does nothing when everything
    is already in place, and reports only what it changed.
    """
    if (settings or {}).get("adopt_bots") is not True:  # opt-in: never touch other profiles unasked
        return []
    root = Path(root)
    profiles = root / "profiles"
    changed = []
    for pdir in sorted(profiles.iterdir()) if profiles.is_dir() else []:
        if not forge.is_live_profile(pdir):
            continue
        if marks_ready(pdir) and reactions_setting(pdir):
            continue
        try:
            result = ensure_reactions(pdir)
        except Exception as exc:  # one broken profile must never stop the others
            result = {"ok": False, "bot": pdir.name, "error": f"{type(exc).__name__}: {exc}"[:120]}
        if result.get("ok") is False or any(result.get(k) for k in ("hook", "switched_on", "setting")):
            changed.append(result)
    return changed
