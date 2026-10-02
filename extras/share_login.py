#!/usr/bin/env python3
"""Optional, unsupported: copy the root login into independent Bot credential stores.

    python extras/share_login.py <bot-name> [...]

Each Bot receives its own auth.json (0600); auth.lock is never copied or linked.
Existing credential links are replaced without writing through them. OAuth refresh
tokens may still compete at the provider, so independent sign-in is recommended.
Every selected Bot receives every provider login in the root file. POSIX only.
"""
import os
import re
import sys
import tempfile
from pathlib import Path


def hermes_root() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "hermes"
    return Path(os.environ.get("HERMES_ROOT") or Path.home() / ".hermes")


def copy_login(root: Path, bot: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", bot) or bot == "default":
        return f"? {bot}: invalid Bot name"
    root = Path(root).resolve()
    profiles = root / "profiles"
    pdir = profiles / bot
    if profiles.is_symlink() or pdir.is_symlink() or not pdir.resolve().is_relative_to(profiles.resolve()):
        return f"? {bot}: profile directory cannot be a symlink"
    if not (pdir / "config.yaml").is_file():
        return f"? {bot}: no such Bot"
    source = root / "auth.json"
    if not source.is_file():
        return f"? {bot}: the root profile has no auth.json to copy"
    if os.name == "nt":
        return f"? {bot}: not supported on Windows"

    # Exclusive creation with 0600, then replace the directory entry. Never
    # open the destination itself: that could follow an old symlink/hardlink.
    fd, name = tempfile.mkstemp(prefix=".auth-copy-", dir=pdir)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            os.fchmod(out.fileno(), 0o600)
            out.write(source.read_bytes())
        os.replace(tmp, pdir / "auth.json")
        lock = pdir / "auth.lock"
        if lock.is_symlink():
            lock.unlink()  # detach legacy shared locks, never touch their target
    finally:
        if tmp.exists():
            tmp.unlink()
    return f"{bot}: copied login into independent auth.json (0600)"


def link(root: Path, bot: str) -> str:
    """Compatibility entry point; now copies instead of creating links."""
    return copy_login(root, bot)


def main():
    bots = sys.argv[1:]
    if not bots:
        print(__doc__)
        sys.exit(2)
    root = hermes_root()
    print(f"Copying login into independent stores for: {', '.join(bots)}")
    for bot in bots:
        print(copy_login(root, bot))
    print("\nRestart the Bot's gateway to pick it up:  hermes -p <bot> gateway restart")


if __name__ == "__main__":
    main()
