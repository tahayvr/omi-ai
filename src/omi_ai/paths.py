"""Where Omi keeps things. Nothing here lives in the repo."""

from __future__ import annotations

import os
from pathlib import Path


def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default)


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "omi-ai"
STATE_DIR = _xdg("XDG_STATE_HOME", ".local/state") / "omi-ai"
CACHE_DIR = _xdg("XDG_CACHE_HOME", ".cache") / "omi-ai"
SHARE_DIR = Path.home() / ".local" / "share" / "omi-ai"
BIN_DIR = Path.home() / ".local" / "bin"
UNIT_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "systemd" / "user"

KEY_FILE = CONFIG_DIR / "api-key"
CONFIG_FILE = CONFIG_DIR / "config.toml"
NOTICE_MARKER = CONFIG_DIR / ".privacy-notice-shown"
LOG_FILE = STATE_DIR / "log.jsonl"
JEV_CACHE = CACHE_DIR / "jev"

PRIVACY_NOTICE = (
    "Omi AI sends the text you type in the ask prompt to TypeSafe AI's servers for "
    "interpretation. It does not send your files, your configuration, or system "
    "information. It requires a network connection and your own TypeSafe API key. "
    "It will not work offline."
)
