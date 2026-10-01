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
import shutil
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
    copied = []
    # A copy, never a symlink. A live link means the Bot's profile *is* the root profile's
    # credential store: a token refreshed or revoked in one silently rewrites the other, and
    # anything with write access to the Bot can edit the credentials every profile depends on.
    # Catalog policy forbids it, and a copy is what the user actually meant — this Bot, these
    # credentials, until they are replaced.
    for fname in ("auth.json", "auth.lock"):
        target, dest = root / fname, pdir / fname
        if not target.is_file():
            continue
        tmp = dest.with_name(dest.name + ".copying")
        if tmp.is_symlink() or tmp.exists():
            tmp.unlink()
        shutil.copyfile(target, tmp)   # contents only: never the source's mode or ownership
        os.chmod(tmp, 0o600)
        if dest.is_symlink():
            dest.unlink()              # replace a link left by an older version of this script
        os.replace(tmp, dest)
        copied.append(fname)
    return (f"✓ {bot}: copied the root profile's {', '.join(copied)} (0600). This is a snapshot — "
            f"re-run it after you sign in again, and revoke it by deleting the file.")


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
