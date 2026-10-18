"""omi-ai command line."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from . import paths


def cmd_ask(a) -> int:
    from . import flow

    if a.menu:
        flow.run(" ".join(a.query) or None, debug=not a.quiet)
        return 0
    if not a.query:
        print('usage: omi-ai ask "<request>"   (or --menu for the interactive flow)', file=sys.stderr)
        return 2
    # Resolve locally and print; never runs anything.
    from .config import load
    from .dispatch import Dispatcher, MissingKey

    try:
        r = Dispatcher(config=load())(" ".join(a.query))
    except MissingKey:
        print("No API key. Run `omi-ai setup`.", file=sys.stderr)
        return 1
    if r.escalate:
        print(f"ESCALATE ({r.kind}): {r.detail}")
        for s in r.alternatives:
            print(f"  suggestion: {s['command']} (fits {s['fits']})")
    else:
        warn = f"  [DESTRUCTIVE: {r.destructive}]" if r.destructive else ""
        print(f"{r.command}  ({r.confidence:.0%}){warn}")
    scores = {k: v for k, v in r.scores.items() if k != "dist"}
    print(f"  route={r.route} scores={scores} tokens={r.input_tokens} cached={r.cached} "
          f"jev={round(r.latency * 1000)}ms")  # fmt: skip
    return 0


def cmd_setup(a) -> int:
    from . import onboarding

    ok = onboarding.run_terminal() if a.terminal else onboarding.run_menu()
    return 0 if ok else 1


def cmd_doctor(a) -> int:
    from . import doctor

    return doctor.main(as_menu=a.menu)


def cmd_review(a) -> int:
    from . import review

    return review.main(days=a.days, do_export=a.export, do_prune=a.prune)


def cmd_history(a) -> int:
    from . import flow

    flow.history()
    return 0


def cmd_config(a) -> int:
    from .config import load, write_template

    if a.action == "path":
        print(paths.CONFIG_FILE)
    elif a.action == "show":
        cfg = load()
        print(f"# {cfg.path or 'no config file — defaults'}")
        for section, values in cfg.data.items():
            print(f"[{section}]")
            for k, v in values.items():
                print(f"{k} = {v!r}".replace("True", "true").replace("False", "false").replace("'", '"'))
        for e in cfg.errors:
            print(f"# problem: {e}")
    elif a.action == "get":
        print(load().get(a.key))
    elif a.action == "edit":
        write_template()
        editor = os.environ.get("EDITOR", "nano").split()
        return subprocess.call([*editor, str(paths.CONFIG_FILE)])
    elif a.action == "reload":
        subprocess.run(["systemctl", "--user", "try-restart", "omi-ai.service"], check=False)
        print("Reloaded. Problems, if any:", *load().errors or ["none"], sep="\n  ")
    return 0


def cmd_spec(a) -> int:
    from . import speccheck

    return speccheck.main(show_all=a.all, update=a.update_snapshot)


def cmd_eval(a) -> int:
    from . import evaluate

    return evaluate.main(a.rest)


def cmd_serve(a) -> int:
    from . import serve

    serve.main()
    return 0


def cmd_uninstall(a) -> int:
    from . import uninstall

    return uninstall.main(purge=a.purge)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="omi-ai", description="Plain-English requests to omarchy commands.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ask", help="resolve a request (prints; --menu runs the interactive flow)")
    s.add_argument("query", nargs="*")
    s.add_argument("--menu", action="store_true", help="the omi-ask flow: confirm, then run")
    s.add_argument("--quiet", action="store_true", help="no debug summary on stderr")
    s.set_defaults(fn=cmd_ask)

    s = sub.add_parser("setup", help="add or replace your TypeSafe API key")
    s.add_argument("--terminal", action="store_true", help="hidden input in the terminal instead of the menu")
    s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("doctor", help="check that everything works")
    s.add_argument("--menu", action="store_true", help="show results in an Omarchy menu")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("review", help="what your usage says to fix next")
    s.add_argument("--days", type=int, default=7)
    s.add_argument("--export", action="store_true", help="label misses into eval/real.jsonl")
    s.add_argument("--prune", action="store_true", help="drop log and cache older than log_retention_days")
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("history", help="pick a recent command and run it again")
    s.set_defaults(fn=cmd_history)

    s = sub.add_parser("config", help="show, edit or reload the config file")
    s.add_argument("action", choices=["show", "edit", "reload", "path", "get"], nargs="?", default="show")
    s.add_argument("key", nargs="?", help="for get: section.key")
    s.set_defaults(fn=cmd_config)

    s = sub.add_parser("spec", help="spec vs live catalog")
    s.add_argument("action", choices=["check"])
    s.add_argument("--all", action="store_true")
    s.add_argument("--update-snapshot", action="store_true", help="refresh the bundled manifest snapshot")
    s.set_defaults(fn=cmd_spec)

    s = sub.add_parser("eval", help="evaluation (dev)", add_help=False)
    s.add_argument("rest", nargs=argparse.REMAINDER)
    s.set_defaults(fn=cmd_eval)

    s = sub.add_parser("serve", help="run the daemon (normally socket-activated)")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("uninstall", help="remove the service and symlinks")
    s.add_argument("--purge", action="store_true", help="also remove API key, config and usage log")
    s.set_defaults(fn=cmd_uninstall)
    return p


def main(argv: list[str] | None = None) -> None:
    a = parser().parse_args(argv)
    if a.cmd == "config" and a.action == "get" and not a.key:
        parser().error("config get needs section.key")
    sys.exit(a.fn(a) or 0)
