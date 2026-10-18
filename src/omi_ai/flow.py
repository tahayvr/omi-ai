"""The menu flow behind `omi-ask`: ask -> confirm (or escalate menu) -> run.

Nothing runs without an explicit pick. Every run passes the gates in gates.py right
before execution. All UI goes through menu.py; all outcomes are logged via events.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading

from . import client, events, execute, gates, menu
from .config import Config, load

REPHRASE = "rephrase"


def _pct(x) -> str:
    return f"{int(float(x) * 100)}%" if x is not None else "edited"


def summary(resp: dict, total_ms: int | None = None) -> str:
    """The debug lines `omi-ai ask` prints (README: Reading the output)."""
    if resp.get("escalate"):
        first = f"ESCALATE ({resp.get('kind')}): {resp.get('detail')}"
    else:
        first = f"{resp.get('command')}  ({_pct(resp.get('confidence'))})"
        if resp.get("destructive"):
            first += f"  [DESTRUCTIVE: {resp['destructive']}]"
    d = resp.get("debug") or {}
    lines = [first]
    if d:
        lines.append(f"  route={d.get('route')} scores={json.dumps(d.get('scores'))} "
                     f"tokens={d.get('tokens')} cached={d.get('cached')} jev={d.get('jev_ms')}ms"
                     + (f" total={total_ms}ms" if total_ms is not None else ""))  # fmt: skip
    if resp.get("escalate") and resp.get("alternatives"):
        lines.append("  suggestions: " + ", ".join(
            f"{a['command']} (fits {a.get('fits', '-')})" for a in resp["alternatives"]))  # fmt: skip
    return "\n".join(lines)


def record(q: str, outcome: str, pick: dict | None = None, **extra) -> None:
    entry = {"src": "flow", "q": q, "outcome": outcome}
    if pick:
        entry.update({k: pick.get(k) for k in ("command", "argv", "route", "confidence", "terminal")})
    events.log({**entry, **extra})


# ---- running ---------------------------------------------------------------


def show_output(cmd: str, out: execute.Outcome) -> None:
    if out.in_terminal:
        return
    if not out.ok:
        menu.notify(f'"{cmd}" failed:\n' + "\n".join(out.output.splitlines()[:6]))
        return
    lines = [ln for ln in out.output.splitlines() if ln.strip()]
    if not lines:
        return
    if len(lines) <= 3:
        menu.notify("\n".join(lines))
        return
    # Long output: a scrollable menu; picking a line copies it.
    picked = menu.choose(cmd, lines[:300])
    if picked:
        _copy(picked)
        menu.notify(f"Copied: {picked}")


def _copy(text: str) -> None:
    try:
        subprocess.run(["wl-copy"], input=text, text=True, check=False)
    except OSError:
        pass


def run_confirmed(pick: dict, q: str, cfg: Config) -> None:
    argv, cmd = pick["argv"], pick["command"]
    if not gates.known_route(argv):
        menu.notify(f'Refusing: "{cmd}" is not a known omarchy command.')
        record(q, "refused-unknown", pick)
        return
    reason = gates.destructive_reason(argv) or pick.get("destructive")
    if reason:
        if cfg["safety"]["destructive"] == "block":
            menu.notify(
                f"Blocked: {reason}. Destructive commands are off in your config; run it yourself if you mean it."
            )
            record(q, "blocked-destructive", pick)
            return
        yes = f"Yes, run: {cmd}"
        if menu.choose(f"Destructive: {reason}", ["Cancel", yes]) != yes:
            record(q, "cancelled", pick, stage="destructive")
            return
    record(q, "ran", pick)
    show_output(cmd, execute.run(argv, bool(pick.get("terminal"))))


# ---- confirm menu ----------------------------------------------------------


def _option_rows(arg: dict) -> tuple[list[str], dict[str, str]]:
    rows, back = [], {}
    for value, desc in arg["options"].items():
        row = value if desc in ("", value) else f"{value} — {desc}"
        rows.append(row)
        back[row] = value
    return rows, back


def _rebuild(pick: dict, values: dict) -> dict | None:
    try:
        r = client.build(pick["route"], values)
    except client.DaemonDown:
        menu.notify("Omi's service stopped responding.")
        return None
    if r.get("error"):
        menu.notify(r["error"])
        return None
    new = dict(pick, argv=r["argv"], command=r["command"], values=values, confidence=None)
    new["args"] = [dict(a, value=values.get(a["name"]), p=None) for a in pick.get("args", [])]
    return new


def change_arg(pick: dict, arg: dict) -> dict | None:
    values = dict(pick.get("values") or {})
    if arg["kind"] == "flag":
        values[arg["name"]] = not arg["value"]
    else:
        rows, back = _option_rows(arg)
        if not arg["required"]:
            rows.insert(0, "(leave out — use the default)")
        picked = menu.choose(f"Choose {arg['label']}", rows)
        if picked is None:
            return pick
        if picked.startswith("(leave out"):
            values.pop(arg["name"], None)
        else:
            values[arg["name"]] = back[picked]
    return _rebuild(pick, values) or pick


def explain_rows(pick: dict) -> list[str]:
    d = (pick.get("debug") or {}).get("scores") or {}
    rows = [f"Command: {pick.get('route')} — {_pct(d.get('route_p'))} vs other candidates"]
    if "covered" in d:
        rows.append(f"Does what you asked: {_pct(d['covered'])}")
    if "actionable" in d:
        rows.append(f"Reads as an action: {_pct(d['actionable'])}")
    for a in pick.get("args", []):
        if a["kind"] == "flag":
            rows.append(f"{a['label']}: {'on' if a['value'] else 'off'}")
        else:
            val = a["value"] or "not said — default"
            rows.append(f"{a['label']}: {val}" + (f" ({_pct(a['p'])})" if a.get("p") is not None else ""))
    ru = pick.get("runner_up")
    if ru:
        rows.append(f"Runner-up: {ru['route']} ({_pct(ru['p'])})")
    rows.append(f"Confidence: {_pct(pick.get('confidence'))} (weakest of command and arguments)")
    return rows


def confirm(pick: dict, q: str, cfg: Config) -> str | None:
    while True:
        cmd = pick["command"]
        title = f"Run this? ({_pct(pick.get('confidence'))} sure)" if cfg["ui"]["show_confidence"] else "Run this?"
        run_row = f"Run: {cmd}"
        rows = [run_row]
        changes = {}
        for a in pick.get("args", []):
            if a["kind"] == "flag":
                row = f"Turn {a['label']} {'off' if a['value'] else 'on'}"
            else:
                row = f"Change {a['label']}: {a['value'] or 'default'}"
            changes[row] = a
            rows.append(row)
        rows += ["Explain", "Wrong command", "Copy", "Cancel"]
        picked = menu.choose(title, rows)
        if picked == run_row:
            run_confirmed(pick, q, cfg)
            return None
        if picked in changes:
            pick = change_arg(pick, changes[picked])
            continue
        if picked == "Explain":
            menu.choose("Why this command", [*explain_rows(pick), "Back"])  # any pick or Esc: back
            continue
        if picked == "Wrong command":
            record(q, "wrong", pick)
            return REPHRASE
        if picked == "Copy":
            _copy(cmd)
            record(q, "copied", pick)
            return None
        record(q, "cancelled", pick)
        return None


# ---- when no command fits ----------------------------------------------------


def _fill_required(alt: dict) -> dict | None:
    """Offline guesses can need an argument: ask for it, then build the command."""
    values = {}
    for a in alt.get("args", []):
        if a["kind"] == "choice" and a["required"]:
            rows, back = _option_rows(a)
            picked = menu.choose(f"Choose {a['label']}", rows)
            if picked is None:
                return None
            values[a["name"]] = back[picked]
    return _rebuild(dict(alt, args=[]), values)


def escalate(resp: dict, q: str, cfg: Config) -> str | None:
    kind = resp.get("kind")
    detail = resp.get("detail") or "No command fits that."
    alts = [] if kind == "timing" else resp.get("alternatives", [])[: cfg["ui"]["suggestions"]]
    if kind == "offline":
        alts = resp.get("alternatives", [])
    runs = {f"Run: {a['command']}": a for a in alts}
    agent_row = f"Ask the agent: {q[:60]}"
    agent = [agent_row] if cfg["ui"]["agent_handoff"] and kind != "offline" else []
    lead_with_agent = kind in ("question", "timing")
    rows = (agent + list(runs)) if lead_with_agent else (list(runs) + agent)
    picked = menu.choose(detail, [*rows, "Rephrase", "Cancel"])
    if picked == agent_row:
        record(q, "escalate-agent", kind=kind)
        execute.launch_agent(q)
        return None
    if picked in runs:
        alt = runs[picked]
        if alt.get("argv") is None:
            alt = _fill_required(alt)
            if alt is None:
                record(q, "escalate-cancelled", kind=kind)
                return None
        record(q, "escalate-picked-suggestion", alt, kind=kind)
        run_confirmed(alt, q, cfg)
        return None
    if picked == "Rephrase":
        record(q, "escalate-rephrased", kind=kind)
        return REPHRASE
    record(q, "escalate-cancelled", kind=kind)
    return None


# ---- entry points ------------------------------------------------------------


def _warm() -> None:
    try:
        client.health(timeout=10)
    except client.DaemonDown:
        pass


def run(query: str | None = None, cfg: Config | None = None, debug: bool = True) -> None:
    """omi-ask: the whole interactive flow. `query` skips the first input box."""
    import time

    cfg = cfg or load()
    threading.Thread(target=_warm, daemon=True).start()  # overlap cold start with typing
    q = query
    while True:
        if q is None:
            q = menu.ask_text("Ask Omi")
            if q is None:
                return
        t0 = time.monotonic()
        try:
            resp = client.ask(q)
        except client.DaemonDown:
            menu.notify("Omi's service isn't running. Run `omi-ai doctor` to see why.")
            return
        if debug:
            print(summary(resp, int((time.monotonic() - t0) * 1000)), file=sys.stderr)
        if resp.get("kind") == "no_key":
            if menu.choose("Omi needs a TypeSafe API key", ["Set up API key", "Cancel"]) == "Set up API key":
                from . import onboarding

                if onboarding.run_menu():
                    continue  # same question, now with a key
            return
        nxt = escalate(resp, q, cfg) if resp.get("escalate") else confirm(resp, q, cfg)
        if nxt != REPHRASE:
            return
        q = None


def history(cfg: Config | None = None, limit: int = 20) -> None:
    """Pick a recent command and run it again (no API call)."""
    cfg = cfg or load()
    seen: dict[str, dict] = {}
    for e in events.read():
        if e.get("src") == "flow" and e.get("outcome") == "ran" and e.get("argv"):
            seen.pop(e["command"], None)
            seen[e["command"]] = e
    recent = list(reversed(seen.values()))[:limit]
    if not recent:
        menu.notify("No history yet.")
        return
    rows = {f"{e['command']}" + (f"  — “{e['q']}”" if e.get("q") else ""): e for e in recent}
    picked = menu.choose("Run again", list(rows))
    if picked:
        e = rows[picked]
        run_confirmed(e, e.get("q", ""), cfg)
