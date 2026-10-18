"""The usage log: ~/.local/state/omi-ai/log.jsonl, one JSON object per line.

Two sources write here: the daemon ("src": "daemon", one line per Jev decision, with
scores and tokens) and the menu flow ("src": "flow", one line per user outcome).
With privacy.log_queries = false the request text is dropped from every line.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path

from . import paths
from .config import load


def log(entry: dict, path: Path | None = None) -> None:
    path = path or paths.LOG_FILE
    if not load()["privacy"]["log_queries"]:
        entry = {k: v for k, v in entry.items() if k != "q"}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps({"ts": time.time(), **entry}) + "\n")


def read(path: Path | None = None, since: float = 0) -> Iterator[dict]:
    path = path or paths.LOG_FILE
    if not path.exists():
        return
    with path.open() as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("ts", 0) >= since:
                yield e


def prune(days: int, path: Path | None = None) -> tuple[int, int]:
    """Drop entries older than `days`. Returns (kept, removed)."""
    path = path or paths.LOG_FILE
    if not path.exists():
        return 0, 0
    cutoff = time.time() - days * 86400
    lines = path.read_text().splitlines()
    kept = [ln for ln in lines if _ts(ln) >= cutoff]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(ln + "\n" for ln in kept))
    tmp.replace(path)
    return len(kept), len(lines) - len(kept)


def _ts(line: str) -> float:
    try:
        return float(json.loads(line).get("ts", 0))
    except ValueError, TypeError:
        return 0.0
