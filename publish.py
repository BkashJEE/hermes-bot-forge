"""Share a Bot as a link, and take one back.

`share_agent` already writes a secret-scanned template and says it is safe to post as a gist. This
does the posting, and lets `import_agent` take the link instead of a file — so sharing a Bot is
"here, click this" rather than "here, download this attachment and tell me where you saved it".

Two decisions worth stating, because both could have gone the other way:

* **No credential of our own.** Publishing goes through the user's own `gh` CLI, which already holds
  their GitHub auth. Bot Forge stores no token, asks for none, and when `gh` is missing or signed
  out it says so instead of offering to hold one. That keeps the plugin's no-credentials rule
  intact for a feature that is, by nature, an account action.
* **A link is not a private file.** A secret gist is unlisted, not protected: anyone holding the URL
  can read it. The result says that in plain words every time, because "secret" reads as "private"
  and the difference matters when the thing being shared is a persona someone wrote for themselves.
"""

import json
import re
import shutil
import subprocess
import urllib.error
import urllib.request

MAX_FETCH_BYTES = 512_000
FETCH_TIMEOUT = 20
GIST_HOSTS = ("gist.github.com", "gist.githubusercontent.com")


def is_url(value: str) -> bool:
    return str(value or "").strip().lower().startswith(("http://", "https://"))


def gh_ready() -> tuple:
    """(ready, reason). Publishing needs the user's own GitHub CLI, signed in."""
    if not shutil.which("gh"):
        return False, ("publishing a link needs the GitHub CLI, which is not installed. Install `gh` "
                       "and run `gh auth login`, or share the template as a file instead.")
    try:
        out = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"could not run `gh auth status`: {exc}"
    if out.returncode != 0:
        return False, ("the GitHub CLI is installed but not signed in — run `gh auth login`, or share "
                       "the template as a file instead.")
    return True, ""


def publish(text: str, filename: str, description: str, runner=None) -> dict:
    """Post the template as a secret gist and return its link. Never raises."""
    ready, reason = gh_ready()
    if not ready:
        return {"ok": False, "error": reason}
    run = runner or (lambda cmd, payload: subprocess.run(
        cmd, input=payload, capture_output=True, text=True, timeout=120))
    try:
        out = run(["gh", "gist", "create", "--filename", filename, "--desc", description[:240], "-"], text)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": f"could not publish: {exc}"}
    if out.returncode != 0:
        return {"ok": False, "error": f"gh refused to publish: {(out.stderr or out.stdout).strip()[-300:]}"}
    url = next((line.strip() for line in reversed((out.stdout or "").splitlines())
                if line.strip().startswith("https://")), "")
    if not url:
        return {"ok": False, "error": "gh published nothing that looks like a link"}
    return {"ok": True, "url": url,
            "visibility": "unlisted — anyone with this link can read the Bot's design (not your "
                          "chats, memory of you, or keys). Delete it with `gh gist delete <url>`."}


def fetch(url: str, opener=None) -> dict:
    """Read a template someone shared. Only https, only small, never executed."""
    url = str(url or "").strip()
    if not url.lower().startswith("https://"):
        return {"ok": False, "error": "only https links are read, so the template cannot be fetched "
                                      "over a connection anyone on the path could rewrite"}
    raw = url
    m = re.match(r"https://gist\.github\.com/[^/]+/([0-9a-f]+)", url, re.I)
    if m and shutil.which("gh"):
        try:
            out = subprocess.run(["gh", "gist", "view", m.group(1), "--raw"],
                                 capture_output=True, text=True, timeout=FETCH_TIMEOUT)
            if out.returncode == 0 and out.stdout.strip():
                return {"ok": True, "text": out.stdout[:MAX_FETCH_BYTES], "source": url}
        except (OSError, subprocess.SubprocessError):
            pass  # fall through to a plain fetch
    if m:
        raw = f"https://gist.githubusercontent.com/{url.split('/')[3]}/{m.group(1)}/raw"
    try:
        request = urllib.request.Request(raw, headers={"User-Agent": "bot-forge"})
        with (opener or urllib.request.urlopen)(request, timeout=FETCH_TIMEOUT) as response:
            body = response.read(MAX_FETCH_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "error": f"could not read {raw}: {exc}"}
    if len(body) > MAX_FETCH_BYTES:
        return {"ok": False, "error": f"that link is larger than {MAX_FETCH_BYTES // 1000}KB — a Bot "
                                      f"template is a few KB, so this is not one"}
    try:
        return {"ok": True, "text": body.decode("utf-8", errors="strict"), "source": raw}
    except UnicodeDecodeError:
        return {"ok": False, "error": "that link is not text, so it is not a Bot template"}


def read_shared(url: str, opener=None) -> dict:
    """Fetch and validate a shared template: valid JSON, shaped like a Bot, free of credentials."""
    got = fetch(url, opener)
    if not got.get("ok"):
        return got
    text = got["text"]
    try:
        spec = json.loads(text)
    except ValueError:
        # `gh gist view --raw` prints the gist's description above the file, and a page someone
        # pasted may carry a heading. The template is still in there: parse from its first brace.
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return {"ok": False, "error": "that link is not a Bot template (it is not JSON)"}
        text = text[start:end + 1]
        try:
            spec = json.loads(text)
        except ValueError:
            return {"ok": False, "error": "that link is not a Bot template (it is not JSON)"}
    if not isinstance(spec, dict) or not spec.get("role"):
        return {"ok": False, "error": "that link is JSON but not a Bot template (no role)"}
    if __package__:
        from . import portable
    else:
        import portable

    scan = portable.scan_text(text)
    return {"ok": True, "spec": spec, "text": text, "scan": scan, "source": got["source"]}
