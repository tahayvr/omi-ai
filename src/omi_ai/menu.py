"""Thin wrappers over Omarchy's own menu (omarchy-menu-input / -select) and notify-send.

Every UI call in Omi goes through here, so tests can swap these three functions out.
"""

from __future__ import annotations

import subprocess

WIDTH = "760"


def ask_text(prompt: str) -> str | None:
    """Text input. None when dismissed or empty."""
    try:
        r = subprocess.run(["omarchy-menu-input", prompt, "--width", WIDTH],
                           capture_output=True, text=True, check=False)  # fmt: skip
    except OSError:
        return None
    text = r.stdout.strip()
    return text if r.returncode == 0 and text else None


def choose(prompt: str, options: list[str]) -> str | None:
    """Pick one row. None when dismissed."""
    if not options:
        return None
    prompt = prompt.rstrip(".…")  # the menu adds its own "…"
    try:
        r = subprocess.run(["omarchy-menu-select", prompt, *options, "--", "--width", WIDTH],
                           capture_output=True, text=True, check=False)  # fmt: skip
    except OSError:
        return None
    pick = r.stdout.rstrip("\n").split("\t")[0]
    return pick if r.returncode == 0 and pick in options else None


def notify(message: str) -> None:
    try:
        subprocess.run(["notify-send", "-a", "Omi AI", "Omi AI", message[:500]], check=False)
    except OSError:
        print(message)
