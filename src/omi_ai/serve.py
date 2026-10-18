"""Socket-activated HTTP daemon: GET /ask?q=... -> JSON decision.

systemd owns 127.0.0.1:8127 (omi-ai.socket) and starts this on the first
request; it exits after IDLE_EXIT seconds without one. Everything heavy (live
manifest, spec, retriever, dynamic values) loads once at startup. The API key
is read from its 600 file here, never from the unit.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from typesafe_sdk import TypeSafeClient

from .dispatch import Dispatcher, read_api_key

IDLE_EXIT = float(os.environ.get("OMI_AI_IDLE_EXIT", "180"))
STATE = (
    Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    / "omi-ai"
)


def log(entry: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "log.jsonl").open("a") as f:
        f.write(json.dumps({"ts": time.time(), **entry}) + "\n")


class Handler(BaseHTTPRequestHandler):
    dispatcher: Dispatcher
    last = time.monotonic()

    def log_message(
        self, *args
    ) -> None:  # keep the journal quiet; queries go to log.jsonl
        pass

    def reply(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        Handler.last = time.monotonic()
        url = urlparse(self.path)
        if url.path == "/health":
            return self.reply(200, {"ok": True})
        if url.path != "/ask":
            return self.reply(404, {"error": "not found"})
        q = parse_qs(url.query).get("q", [""])[0].strip()[:500]
        if not q:
            return self.reply(400, {"error": "missing q"})
        try:
            r = self.dispatcher(q)
        except Exception as e:  # noqa: BLE001 — network down, API error: tell the user, don't crash the daemon
            log({"q": q, "error": type(e).__name__})
            return self.reply(
                200,
                {
                    "command": None,
                    "argv": None,
                    "confidence": 0,
                    "escalate": True,
                    "detail": f"Could not reach TypeSafe ({type(e).__name__}). Check your network connection.",
                },
            )
        body = {
            "command": r.command,
            "argv": r.argv,
            "confidence": round(r.confidence, 3),
            "escalate": r.escalate,
            "detail": r.detail,
            "destructive": r.destructive,
            "terminal": r.terminal,
            "kind": r.kind,
            "alternatives": r.alternatives,
            "debug": {
                "route": r.route,
                "scores": {k: v for k, v in r.scores.items() if k != "dist"},
                "tokens": r.input_tokens,
                "cached": r.cached,
                "jev_ms": round(r.latency * 1000),
            },
        }
        log(
            {
                "q": q,
                "route": r.route,
                "command": r.command,
                "confidence": r.confidence,
                "escalate": r.escalate,
                "kind": r.kind,
                "alternatives": [a["command"] for a in r.alternatives],
                "scores": r.scores,
                "tokens": r.input_tokens,
                "cached": r.cached,
            }
        )
        self.reply(200, body)


def systemd_socket() -> socket.socket | None:
    if (
        os.environ.get("LISTEN_PID") == str(os.getpid())
        and os.environ.get("LISTEN_FDS") == "1"
    ):
        return socket.socket(fileno=3)
    return None


def main() -> None:
    client = TypeSafeClient(api_key=read_api_key(), timeout=8)
    Handler.dispatcher = Dispatcher(client=client)
    sock = systemd_socket()
    if sock:
        server = ThreadingHTTPServer(
            sock.getsockname()[:2], Handler, bind_and_activate=False
        )
        server.socket = sock
    else:  # manual run for development
        server = ThreadingHTTPServer(
            ("127.0.0.1", int(os.environ.get("OMI_AI_PORT", "8127"))), Handler
        )

    def idle_watch() -> None:
        while time.monotonic() - Handler.last < IDLE_EXIT:
            time.sleep(5)
        server.shutdown()

    threading.Thread(target=idle_watch, daemon=True).start()
    print(
        f"omi-ai: ready ({len(Handler.dispatcher.forms)} commands)",
        file=sys.stderr,
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
