"""omi-ai review: what real use says to fix next. No API calls."""

from __future__ import annotations

import json
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from . import events, paths
from .config import load
from .dispatch import PRICE_PER_TOKEN

EVAL_REAL = Path(__file__).resolve().parents[2] / "eval" / "real.jsonl"


def summarize(days: int = 7) -> dict:
    since = time.time() - days * 86400
    flow = [e for e in events.read(since=since) if e.get("src") == "flow"]
    daemon = [e for e in events.read(since=since) if e.get("src") == "daemon"]
    outcomes = Counter(e["outcome"] for e in flow)
    tokens = sum(e.get("tokens", 0) for e in daemon if not e.get("cached"))
    confs = [e["confidence"] for e in flow if e.get("outcome") == "ran" and e.get("confidence") is not None]

    by_route: dict[str, Counter] = defaultdict(Counter)
    for e in flow:
        if e.get("route"):
            by_route[e["route"]][e["outcome"]] += 1
    weak = sorted(
        ((r, c) for r, c in by_route.items() if c["cancelled"] + c["wrong"] > 0),
        key=lambda rc: -(rc[1]["cancelled"] + rc[1]["wrong"] * 2),
    )
    return {
        "days": days,
        "requests": len(daemon),
        "outcomes": dict(outcomes),
        "tokens": tokens,
        "cost": tokens * PRICE_PER_TOKEN,
        "median_confidence_ran": statistics.median(confs) if confs else None,
        "overrode_refusal": [e for e in flow if e["outcome"] == "escalate-picked-suggestion"],
        "wrong": [e for e in flow if e["outcome"] == "wrong"],
        "cancelled": [e for e in flow if e["outcome"] == "cancelled"],
        "never_matched": [
            e
            for e in flow
            if e["outcome"] in ("escalate-cancelled", "escalate-rephrased") and e.get("kind") == "uncovered"
        ],
        "weak_routes": [(r, dict(c)) for r, c in weak[:10]],
    }


def _q(e: dict) -> str:
    return f"“{e['q']}”" if e.get("q") else "(text not logged)"


def render(s: dict) -> str:
    o = s["outcomes"]
    lines = [
        f"Last {s['days']} days: {s['requests']} requests, ${s['cost']:.4f} ({s['tokens']} tokens)",
        "  " + ", ".join(f"{k} {v}" for k, v in sorted(o.items(), key=lambda kv: -kv[1])) if o else "  no outcomes yet",
    ]
    if s["median_confidence_ran"] is not None:
        lines.append(f"  median confidence of commands you ran: {s['median_confidence_ran']:.0%}")

    def block(title: str, rows: list[str]) -> None:
        if rows:
            lines.append(f"\n{title} ({len(rows)}):")
            lines.extend(f"  {r}" for r in rows[:15])
            if len(rows) > 15:
                lines.append(f"  … {len(rows) - 15} more")

    block("Marked wrong — the clearest misses", [f"{_q(e)} → {e.get('command')}" for e in s["wrong"]])
    block("Refusals you overrode by picking a suggestion — likely threshold or spec misses",
          [f"{_q(e)} ({e.get('kind')}) → you ran {e.get('command')}" for e in s["overrode_refusal"]])  # fmt: skip
    block("Commands you saw and cancelled", [f"{_q(e)} → {e.get('command')}" for e in s["cancelled"]])
    block("No command fit and no suggestion helped — spec or Omarchy gaps", [_q(e) for e in s["never_matched"]])
    block("Commands with the most misses", [f"{r}: {c}" for r, c in s["weak_routes"]])
    if len(lines) == 2 + (s["median_confidence_ran"] is not None):
        lines.append("\nNothing to fix yet.")
    return "\n".join(lines)


def export(days: int = 30, path: Path = EVAL_REAL) -> int:
    """Append labelled rows from real misses to eval/real.jsonl, asking for each expected command."""
    from . import menu

    s = summarize(days)
    have = set()
    if path.exists():
        have = {json.loads(ln)["q"] for ln in path.read_text().splitlines() if ln.strip()}
    rows = []
    for e in s["wrong"] + s["overrode_refusal"] + s["cancelled"] + s["never_matched"]:
        q = e.get("q")
        if not q or q in have:
            continue
        have.add(q)
        label_cmd = e.get("command") if e["outcome"] == "escalate-picked-suggestion" else None
        choice = menu.choose(
            f"Label: “{q}”",
            ([f"Should be: {label_cmd}"] if label_cmd else [])
            + ["No command should run (escalate)", "Type the right command…", "Skip"],
        )
        if choice is None or choice == "Skip":
            continue
        if choice.startswith("Should be: "):
            rows.append({"q": q, "expect": label_cmd, "kind": "command", "note": "real use"})
        elif choice.startswith("No command"):
            rows.append({"q": q, "expect": None, "kind": "escalate", "note": "real use"})
        else:
            typed = menu.ask_text(f"Right command for “{q}” (starts with omarchy)")
            if typed and typed.startswith("omarchy "):
                rows.append({"q": q, "expect": typed.strip(), "kind": "command", "note": "real use"})
    if rows:
        with path.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    return len(rows)


def main(days: int = 7, do_export: bool = False, do_prune: bool = False) -> int:
    if do_prune:
        keep_days = load()["privacy"]["log_retention_days"]
        kept, removed = events.prune(keep_days)
        print(f"Pruned {removed} log entries older than {keep_days} days ({kept} kept).")
        cache = paths.JEV_CACHE
        if cache.exists():
            cutoff = time.time() - keep_days * 86400
            old = [f for f in cache.rglob("*.json") if f.stat().st_mtime < cutoff]
            for f in old:
                f.unlink()
            print(f"Removed {len(old)} cached Jev answers older than {keep_days} days.")
        return 0
    if do_export:
        n = export(days)
        print(f"Added {n} labelled rows to {EVAL_REAL}.")
        return 0
    print(render(summarize(days)))
    return 0
