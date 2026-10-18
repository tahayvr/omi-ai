"""HTTP client for the local daemon (127.0.0.1:<port>)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .config import load


def base_url() -> str:
    if url := os.environ.get("OMI_AI_URL"):
        return url.rstrip("/")
    return f"http://127.0.0.1:{load()['daemon']['port']}"


class DaemonDown(Exception):
    pass


def _get(path: str, params: dict | None = None, timeout: float = 15) -> dict:
    url = base_url() + path + ("?" + urllib.parse.urlencode(params) if params else "")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except ValueError:
            raise DaemonDown(f"HTTP {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise DaemonDown(str(e)) from e


def ask(q: str) -> dict:
    return _get("/ask", {"q": q})


def build(route: str, values: dict) -> dict:
    return _get("/build", {"route": route, "values": json.dumps(values)})


def health(timeout: float = 5) -> dict:
    return _get("/health", timeout=timeout)
