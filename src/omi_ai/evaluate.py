"""Evaluation: retriever recall, full Jev eval, threshold sweep, offline replay.

  omi-ai eval recall   [--split valid] [--k 8]
  omi-ai eval run      [--split valid] [--model jev-1.13.0] [--offline] [--fails]
  omi-ai eval sweep    [--split valid] [--offline]
  omi-ai eval snapshot                 record fixtures for --offline (uses the cache)

Splits: valid / test (hash split of eval/rows.jsonl), all, real (eval/real.jsonl from
`omi-ai review --export`). Fixtures live in eval/fixtures/ (not committed).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import statistics
from concurrent.futures import ThreadPoolExecutor
from itertools import product
from pathlib import Path

from .config import load
from .dispatch import PRICE_PER_TOKEN, Dispatcher, StaleFixture, Thresholds

EVAL = Path(__file__).resolve().parents[2] / "eval"
FIXTURES = EVAL / "fixtures"
FLOORS = EVAL / "floors.json"

# Different routes that run the same thing.
EQUIV = [
    ("omarchy toggle input device touchpad", "omarchy toggle touchpad"),
    ("omarchy toggle input device touchscreen", "omarchy toggle touchscreen"),
]


def norm(cmd: str | None) -> str | None:
    if cmd is None:
        return None
    s = " ".join(shlex.split(cmd))
    for a, b in EQUIV:
        if s == a or s.startswith(a + " "):
            s = b + s[len(a) :]
    return s


def rows(split: str) -> list[dict]:
    if split == "real":
        path = EVAL / "real.jsonl"
        return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()] if path.exists() else []
    out = []
    for line in (EVAL / "rows.jsonl").read_text().splitlines():
        r = json.loads(line)
        h = int(hashlib.sha1(r["q"].encode()).hexdigest(), 16) % 2
        if split == "all" or (split == "valid") == (h == 0):
            out.append(r)
    return out


def expected_route(d: Dispatcher, cmd: str) -> str | None:
    toks = shlex.split(norm(cmd))
    best = None
    for r in d.forms:
        rt = r.split()
        if toks[: len(rt)] == rt and (best is None or len(rt) > len(best.split())):
            best = r
    return best


def recall(d: Dispatcher, data: list[dict], k: int, show: bool) -> None:
    cmd_rows = [r for r in data if r["kind"] == "command"]
    for kk in sorted({1, 3, 5, k, 12, 16}):
        hit = sum(
            expected_route(d, r["expect"]) in [f.route for f, _ in d.retriever.search(r["q"], kk)] for r in cmd_rows
        )
        print(f"recall@{kk:<2} {hit / len(cmd_rows):6.1%}  ({hit}/{len(cmd_rows)})")
    if show:
        for r in cmd_rows:
            want = expected_route(d, r["expect"])
            got = [f.route for f, _ in d.retriever.search(r["q"], k)]
            if want not in got:
                print(f"  MISS {r['q']!r:55} want {want}  top3 {got[:3]}")


def run(d: Dispatcher, data: list[dict], workers: int = 8):
    """Judge every row. Offline, rows missing from the fixtures come back as None (stale)."""

    def one(r):
        try:
            return d.judge(r["q"])
        except StaleFixture:
            return None

    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(one, data))


def fixtures_path(model: str) -> Path:
    return FIXTURES / f"{model}.jsonl"


def load_fixtures(model: str) -> dict:
    path = fixtures_path(model)
    if not path.exists():
        raise SystemExit(f"No fixtures for {model}. Run `just snapshot` (omi-ai eval snapshot) first.")
    out = {}
    for line in path.read_text().splitlines():
        h, ans = json.loads(line)
        out[h] = ans
    return out


def snapshot(model: str | None = None) -> int:
    """Record the answer to every eval request (all splits + real) for offline replay."""
    record: dict = {}
    d = Dispatcher(config=load(), record=record, **({"model": model} if model else {}))
    data = rows("all") + rows("real")
    run(d, data)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    path = fixtures_path(d.model)
    path.write_text("".join(json.dumps([h, a]) + "\n" for h, a in sorted(record.items())))
    return len(record)


def check_floors(m: dict, split: str) -> list[str]:
    """Warnings when results fall more than 1 point below the recorded floor."""
    if not FLOORS.exists():
        return []
    floor = json.loads(FLOORS.read_text()).get(split, {})
    warn = []
    for key, value in floor.items():
        got = m.get(key)
        if got is None:
            continue
        worse = got > value + 0.01 if key in ("false_command", "over_escalate") else got < value - 0.01
        if worse:
            warn.append(f"{key} {got:.1%} vs floor {value:.1%}")
    return warn


def metrics(d: Dispatcher, data, judged, th: Thresholds) -> dict:
    n_cmd = n_esc = fn_ok = deployed_ok = arg_ok = esc_ok = false_cmd = over_esc = 0
    retr_miss = 0
    lat, toks, fails = [], 0, []
    stale = sum(j is None for j in judged)
    pairs = [(r, j) for r, j in zip(data, judged) if j is not None]
    for r, (cands, ans, cached, dt) in pairs:
        res = d.decide(r["q"], cands, ans, th)
        toks += ans["input_tokens"]
        if not cached:
            lat.append(dt)
        got = norm(res.command)
        if r["kind"] == "command":
            n_cmd += 1
            want_route = expected_route(d, r["expect"])
            in_cands = want_route in res.candidates
            retr_miss += not in_cands
            if res.escalate:
                over_esc += 1
                fails.append(("over-escalate", r, res))
                continue
            route_ok = res.route == want_route
            fn_ok += route_ok and in_cands
            deployed_ok += route_ok
            arg_ok += got == norm(r["expect"])
            if got != norm(r["expect"]):
                fails.append(("wrong-route" if not route_ok else "wrong-args", r, res))
        else:
            n_esc += 1
            if res.escalate:
                esc_ok += 1
            else:
                false_cmd += 1
                fails.append(("false-command", r, res))
    return {
        "n_cmd": n_cmd,
        "n_esc": n_esc,
        "fn_acc_given_retrieved": fn_ok / max(1, n_cmd - retr_miss),
        "deployed_fn_acc": deployed_ok / max(1, n_cmd),
        "arg_acc": arg_ok / max(1, n_cmd),
        "over_escalate": over_esc / max(1, n_cmd),
        "escalate_recall": esc_ok / max(1, n_esc),
        "false_command": false_cmd / max(1, n_esc),
        "retriever_miss": retr_miss / max(1, n_cmd),
        "median_latency_s": statistics.median(lat) if lat else None,
        "input_tokens": toks,
        "cost_usd": toks * PRICE_PER_TOKEN,
        "stale": stale,
        "fails": fails,
    }


def report(m: dict, show_fails: bool) -> None:
    for k, v in m.items():
        if k == "fails":
            continue
        print(
            f"  {k:24} {v:.1%}"
            if isinstance(v, float) and k not in ("median_latency_s", "cost_usd")
            else f"  {k:24} {v}"
        )
    if show_fails:
        for kind, r, res in m["fails"]:
            print(
                f"  [{kind}] {r['q']!r}\n      want {r['expect']}\n      got  {res.command or 'ESCALATE'}  "
                f"conf {res.confidence:.2f} {json.dumps({k: round(v, 2) for k, v in res.scores.items() if k != 'dist'})} "
                f"dist {json.dumps({k: round(v, 2) for k, v in res.scores['dist'].items()})}"
            )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="omi-ai eval")
    ap.add_argument("what", choices=["recall", "run", "sweep", "snapshot"])
    ap.add_argument("--split", default="valid", choices=["valid", "test", "all", "real"])
    ap.add_argument("--k", type=int, default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--offline", action="store_true", help="replay recorded fixtures, no API")
    ap.add_argument("--fails", action="store_true")
    a = ap.parse_args(argv)
    if a.what == "snapshot":
        n = snapshot(a.model)
        print(f"Recorded {n} answers to {fixtures_path(a.model or load()['model']['name'])}")
        return 0
    cfg = load()
    model = a.model or cfg["model"]["name"]
    fixtures = load_fixtures(model) if a.offline else None
    d = Dispatcher(config=cfg, fixtures=fixtures, **({"model": a.model} if a.model else {}))
    if a.k:
        d.k = a.k
    data = rows(a.split)
    mode = "offline" if a.offline else "live"
    print(f"{a.split}: {len(data)} rows, model {d.model}, k={d.k}, {mode}")
    if a.what == "recall":
        recall(d, data, d.k, a.fails)
        return 0
    judged = run(d, data)
    if a.what == "run":
        m = metrics(d, data, judged, d.th)
        report(m, a.fails)
        if m["stale"]:
            print(f"\n{m['stale']} rows aren't in the fixtures (spec or prompts changed): run `just snapshot`.")
            return 1
        warn = check_floors(m, a.split)
        for w in warn:
            print(f"WARNING: {w}")
        return 1 if warn else 0
    pts = []
    for am, cm, dm, tm, xm in product(
        [0.3, 0.5, 0.7],
        [0.3, 0.4, 0.5, 0.6, 0.7],
        [0.5, 0.6, 0.7, 0.8, 1.01],
        [0.5, 0.7, 1.01],
        [0.0, 0.7, 0.8, 0.9],
    ):
        th = Thresholds(actionable_min=am, fits_min=cm, detail_max=dm, timing_max=tm, destructive_min=xm)
        m = metrics(d, data, judged, th)
        pts.append((round(m["false_command"], 4), round(m["over_escalate"], 4), m["arg_acc"], am, cm, dm, tm, xm))
    # Pareto front on (false_command, over_escalate); keep the best arg_acc per front point
    best: dict = {}
    for p in pts:
        k = (p[0], p[1])
        if k not in best or p[2] > best[k][2]:
            best[k] = p
    front = [p for p in best.values()
             if not any(q[0] <= p[0] and q[1] <= p[1] and (q[0], q[1]) != (p[0], p[1]) for q in best.values())]  # fmt: skip
    print("false_cmd  over_esc  arg_acc   actionable fits detail timing destructive")
    for p in sorted(front):
        print(
            f"  {p[0]:6.1%}   {p[1]:6.1%}   {p[2]:6.1%}     {p[3]:.1f}      {p[4]:.1f}  {p[5]:.2f}   {p[6]:.2f}   {p[7]:.1f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
