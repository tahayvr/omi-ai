import sys


def main() -> None:
    """omi-ai ask "<request>"  — resolve locally and print, never runs anything.
    omi-ai serve               — run the HTTP daemon (normally socket-activated)."""
    args = sys.argv[1:]
    if args[:1] == ["serve"]:
        from .serve import main as serve

        return serve()
    if args[:1] == ["ask"] and len(args) > 1:
        from .dispatch import Dispatcher

        r = Dispatcher()(" ".join(args[1:]))
        if r.escalate:
            print(f"ESCALATE: {r.detail}")
        else:
            warn = f"  [DESTRUCTIVE: {r.destructive}]" if r.destructive else ""
            print(f"{r.command}  ({r.confidence:.0%}){warn}")
        print(
            f"  route={r.route} scores={ {k: v for k, v in r.scores.items() if k != 'dist'} } tokens={r.input_tokens}"
        )
        return
    print(main.__doc__)
    sys.exit(2)
