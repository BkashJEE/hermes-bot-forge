#!/usr/bin/env python3
"""Optional, unsupported: let a Bot use the root profile's login instead of signing in itself.

    python extras/share_login.py <bot-name> [...]

Hermes deliberately gives every profile its own credential store: a refresh token has one owner, and the
first profile to refresh an OAuth grant can log the others out. This script opts out of that on purpose,
by pointing a Bot's auth.json and auth.lock at the root profile's files, so OAuth models (ChatGPT/Codex,
Claude subscription) work in a new Bot with no browser sign-in.

Understand before running it:
  * a logout or re-login in ANY linked Bot affects every linked Bot
  * every linked Bot can use every provider login in your root profile
  * a Hermes update may undo or refuse the links
  * POSIX only

It never creates or modifies anything inside the root profile, and `hermes profile delete` on a linked Bot
removes only the link. Undo it with:  rm <profile>/auth.json <profile>/auth.lock
"""
import os
import sys
from pathlib import Path


def hermes_root() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "hermes"
    return Path(os.environ.get("HERMES_ROOT") or Path.home() / ".hermes")


def link(root: Path, bot: str) -> str:
    pdir = root / "profiles" / bot
    if not (pdir / "config.yaml").exists():
        return f"✗ {bot}: no such Bot"
    if not (root / "auth.json").is_file():
        return f"✗ {bot}: the root profile has no auth.json to share"
    if os.name == "nt":
        return f"✗ {bot}: not supported on Windows"
    linked = []
    for fname in ("auth.json", "auth.lock"):
        target, dest = root / fname, pdir / fname
        if not target.exists():
            continue
        tmp = dest.with_name(dest.name + ".linking")
        if tmp.is_symlink() or tmp.exists():
            tmp.unlink()
        tmp.symlink_to(target)
        os.replace(tmp, dest)
        linked.append(fname)
    return f"✓ {bot}: now shares the root profile's {', '.join(linked)}"


def main():
    bots = sys.argv[1:]
    if not bots:
        print(__doc__)
        sys.exit(2)
    root = hermes_root()
    print(f"Sharing {root}/auth.json with: {', '.join(bots)}")
    print("This trades away Hermes' one-login-per-profile isolation. Ctrl-C now if that is not what you want.\n")
    for bot in bots:
        print(link(root, bot))
    print("\nRestart the Bot's gateway to pick it up:  hermes -p <bot> gateway restart")


if __name__ == "__main__":
    main()
