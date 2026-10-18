"""omi-ai setup: get a TypeSafe API key in, check it, store it safely.

The key is validated with one models.list() call before it's saved, written
atomically with mode 600, and never printed or logged.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import tempfile

from typesafe_sdk import TypeSafeAuthenticationError, TypeSafeClient, TypeSafeError

from . import config, menu, paths

CONSOLE = "https://console.typesafe.ai"


def check_key(key: str) -> str | None:
    """None if TypeSafe accepts the key, else a short reason."""
    try:
        with TypeSafeClient(api_key=key, timeout=10) as c:
            c.models.list()
    except TypeSafeAuthenticationError:
        return "TypeSafe rejected that key."
    except TypeSafeError as e:
        msg = str(e).lower()
        if "api key" in msg or "whitespace" in msg or "empty" in msg:
            return "That doesn't look like an API key."
        return f"Couldn't reach TypeSafe ({type(e).__name__}); key not saved."
    except OSError as e:
        return f"Couldn't reach TypeSafe ({e}); key not saved."
    return None


def save_key(key: str) -> None:
    paths.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=paths.CONFIG_DIR, prefix=".api-key.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(key)
        os.replace(tmp, paths.KEY_FILE)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    os.chmod(paths.KEY_FILE, 0o600)


def has_key() -> bool:
    return paths.KEY_FILE.exists() and bool(paths.KEY_FILE.read_text().strip())


def _after_save() -> None:
    config.write_template()
    paths.NOTICE_MARKER.touch()
    # The daemon reads the key per request; restart anyway so config changes land too.
    subprocess.run(["systemctl", "--user", "try-restart", "omi-ai.service"], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip


def run_menu() -> bool:
    """Interactive setup with Omarchy menus. Returns True when a working key is saved."""
    if has_key():
        keep, replace = "Keep current key", "Replace key"
        picked = menu.choose("Omi already has a TypeSafe API key", [keep, replace, "Cancel"])
        if picked != replace:
            return picked == keep
    if not paths.NOTICE_MARKER.exists():
        ok = "I understand"
        if menu.choose(paths.PRIVACY_NOTICE, [ok, "Cancel"]) != ok:
            return False
    prompt = f"TypeSafe API key (from {CONSOLE})"
    while True:
        key = menu.ask_text(prompt)
        if key is None:
            return False
        key = key.strip()
        problem = check_key(key)
        if problem is None:
            save_key(key)
            _after_save()
            menu.notify("Omi is ready. Bind a key to omi-ask, or run it from a terminal.")
            return True
        if "Couldn't reach" in problem:
            menu.notify(problem)
            return False
        prompt = f"{problem} Try again — TypeSafe API key"


def run_terminal() -> bool:
    """Same as run_menu but in the terminal, with hidden input."""
    if has_key() and input("A key is already saved. Replace it? [y/N] ").strip().lower() != "y":
        return True
    if not paths.NOTICE_MARKER.exists():
        print("\n" + paths.PRIVACY_NOTICE + "\n")
    while True:
        key = getpass.getpass(f"TypeSafe API key (from {CONSOLE}, hidden): ").strip()
        if not key:
            return False
        problem = check_key(key)
        if problem is None:
            save_key(key)
            _after_save()
            print(f"Saved to {paths.KEY_FILE} (mode 600). Omi is ready.")
            return True
        print(problem)
        if "Couldn't reach" in problem:
            return False
