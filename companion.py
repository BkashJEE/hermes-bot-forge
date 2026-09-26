"""Install the acknowledgement hook into a Bot's own profile.

Hermes runs a plugin hook in whichever profile runs the turn. Bot Forge lives in the profile that
*creates* Bots, so its hooks never fire when the user talks to one of those Bots — which is why a
reaction placed from here could never appear on a Bot's chat. The `marks/` companion is the piece
that ships with the Bot: two hooks, no tools, so a Bot gains the reaction and nothing else.
"""

import shutil
from pathlib import Path

try:
    from . import forge
except ImportError:  # standalone CLI/repository import
    import forge

MARKS_NAME = "bot-forge-marks"
SOURCE = Path(__file__).resolve().parent / "marks"


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


def _enable(pdir: Path) -> bool:
    cfg_path = Path(pdir) / "config.yaml"
    cfg = forge.load_yaml(cfg_path)
    plugins = dict(cfg.get("plugins") or {})
    enabled = list(plugins.get("enabled") or [])
    if MARKS_NAME in enabled:
        return False
    plugins["enabled"] = sorted(enabled + [MARKS_NAME])
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
