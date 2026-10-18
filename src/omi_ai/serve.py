"""Socket-activated HTTP daemon.

  GET /ask?q=...                     -> decision JSON (command, or escalate + suggestions)
  GET /build?route=...&values={...}  -> argv for a route with explicit values (menu edits)
  GET /health                        -> {"ok": true, "key": bool, "model": ...}

systemd owns the socket (omi-ai.socket) and starts this on the first request; it exits
after daemon.idle_exit_s without one. The manifest, spec, retriever and config load
once at startup. The API key is read from its 600 file, never from the unit.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from typesafe_sdk import TypeSafeError

from . import events
from .config import load
from .dispatch import Dispatcher, MissingKey, read_api_key


def decision(d: Dispatcher, q: str) -> dict:
    """Answer one request; never raises for missing keys or network trouble."""
    try:
        r = d(q)
    except MissingKey:
        return {
            "command": None,
            "argv": None,
            "confidence": 0,
            "escalate": True,
            "kind": "no_key",
            "detail": "Omi needs a TypeSafe API key. Run `omi-ai setup`.",
            "alternatives": [],
        }
    except (TypeSafeError, OSError, TimeoutError) as e:
        events.log({"src": "daemon", "q": q, "error": type(e).__name__})
        return {
            "command": None,
            "argv": None,
            "confidence": 0,
            "escalate": True,
            "kind": "offline",
            "detail": "Can't reach TypeSafe — offline best guesses:",
            "alternatives": d.offline_alternatives(q),
        }
    body = {
        "command": r.command,
        "argv": r.argv,
        "route": r.route,
        "confidence": round(r.confidence, 3),
        "escalate": r.escalate,
        "kind": r.kind,
        "detail": r.detail,
        "destructive": r.destructive,
        "terminal": r.terminal,
        "values": r.values,
        "args": r.args,
        "runner_up": r.runner_up,
        "alternatives": r.alternatives,
        "debug": {
            "route": r.route,
            "scores": {k: v for k, v in r.scores.items() if k != "dist"},
            "tokens": r.input_tokens,
            "cached": r.cached,
            "jev_ms": round(r.latency * 1000),
        },
    }
    events.log({"src": "daemon", "q": q, "route": r.route, "command": r.command,
                "confidence": r.confidence, "escalate": r.escalate, "kind": r.kind,
                "alternatives": [a["command"] for a in r.alternatives], "scores": r.scores,
                "tokens": r.input_tokens, "cached": r.cached})  # fmt: skip
    return body


class Handler(BaseHTTPRequestHandler):
    dispatcher: Dispatcher
    last = time.monotonic()

    def log_message(self, *args) -> None:  # queries go to log.jsonl, not the journal
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
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        d = self.dispatcher
        if url.path == "/health":
            try:
                read_api_key()
                key = True
            except MissingKey:
                key = False
            return self.reply(200, {"ok": True, "key": key, "model": d.model,
                                    "commands": len(d.forms), "pid": os.getpid()})  # fmt: skip
        if url.path == "/ask":
            q = params.get("q", "").strip()[:500]
            if not q:
                return self.reply(400, {"error": "missing q"})
            return self.reply(200, decision(d, q))
        if url.path == "/build":
            try:
                values = json.loads(params.get("values", "{}"))
                argv = d.build(params["route"], values)
            except (KeyError, ValueError) as e:
                return self.reply(400, {"error": str(e)})
            from .catalog import display

            return self.reply(200, {"argv": argv, "command": display(argv)})
        return self.reply(404, {"error": "not found"})


def systemd_socket() -> socket.socket | None:
    if os.environ.get("LISTEN_PID") == str(os.getpid()) and os.environ.get("LISTEN_FDS") == "1":
        return socket.socket(fileno=3)
    return None


def main() -> None:
    cfg = load()
    for problem in cfg.errors:
        print(f"omi-ai: config: {problem}", file=sys.stderr)
    Handler.dispatcher = Dispatcher(config=cfg)
    idle = float(os.environ.get("OMI_AI_IDLE_EXIT") or cfg["daemon"]["idle_exit_s"])
    sock = systemd_socket()
    if sock:
        server = ThreadingHTTPServer(sock.getsockname()[:2], Handler, bind_and_activate=False)
        server.socket = sock
    else:  # manual run for development
        port = int(os.environ.get("OMI_AI_PORT") or cfg["daemon"]["port"])
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)

    def idle_watch() -> None:
        while time.monotonic() - Handler.last < idle:
            time.sleep(min(5, idle))
        server.shutdown()

    threading.Thread(target=idle_watch, daemon=True).start()
    print(f"omi-ai: ready ({len(Handler.dispatcher.forms)} commands, {Handler.dispatcher.model})",
          file=sys.stderr, flush=True)  # fmt: skip
    server.serve_forever()


if __name__ == "__main__":
    main()
