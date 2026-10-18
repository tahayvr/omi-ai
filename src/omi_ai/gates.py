"""Execution gates, checked right before anything runs — independent of the daemon's verdict.

Gate A: the argv must start with a real route in the live Omarchy manifest.
Gate B: destructive routes (policy.json) need a second confirmation, or are blocked.
Routes are matched word by word, never as raw string prefixes.
"""

from __future__ import annotations

import json
import os
import subprocess
from functools import cache

from .catalog import DATA


def _prefix(argv: list[str], route: str) -> bool:
    r = route.split()
    return argv[: len(r)] == r


@cache
def _live_routes() -> tuple[str, ...]:
    if os.environ.get("OMI_AI_SNAPSHOT"):
        raw = (DATA / "manifest-live.json").read_text()
    else:
        raw = subprocess.run(["omarchy", "commands", "--all", "--json"],
                             capture_output=True, text=True, timeout=10, check=True).stdout  # fmt: skip
    return tuple(c["route"] for c in json.loads(raw)["commands"])


def known_route(argv: list[str]) -> bool:
    try:
        routes = _live_routes()
    except OSError, subprocess.SubprocessError, ValueError, KeyError:
        return False  # can't verify -> refuse
    return bool(argv) and argv[0] == "omarchy" and any(_prefix(argv, r) for r in routes)


def destructive_reason(argv: list[str]) -> str | None:
    policy = json.loads((DATA / "policy.json").read_text())
    for route, reason in policy["destructive"].items():
        if _prefix(argv, route):
            return reason
    return None
