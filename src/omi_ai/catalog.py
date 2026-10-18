"""Live command catalog: parses `omarchy commands --all --json` into fillable forms.

A *form* is one way to call a command. Most commands have exactly one form; a
command whose args grammar has top-level alternatives led by a literal verb
(`omarchy bar position [...] | background [...] | ...`) gets one form per verb,
with the verb folded into the form's route (`omarchy bar position`).

Each argument is one of:
  choice  closed set of literal CLI tokens (Jev picks one)
  flag    boolean switch (Jev decides on/off)
  free    anything else (numbers, paths, names); never filled unless a dynamic
          resolver turns it into a choice at request time
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

DATA = Path(__file__).parent / "data"

# A literal CLI token: a word, or a --flag. Placeholders like N, +N, N%, SCALE are not.
LITERAL = re.compile(r"^(--?)?[a-z0-9][a-z0-9_.-]*$|^[A-Z][a-z][A-Za-z0-9]*$")


@dataclass
class Arg:
    name: str  # stable id within the form, e.g. "pos0", "--with-webcam"
    kind: str  # "choice" | "flag" | "free"
    required: bool = False
    values: list[str] = field(default_factory=list)  # choice values (literal tokens)
    open: bool = False  # choice also accepted non-literal values we dropped (e.g. +N)
    flag: str = ""  # for flags / valued flags: the spelling, e.g. "--webcam-size"
    style: str = ""  # valued flag: "eq" (--k=v) or "space" (--k v)
    placeholder: str = ""  # free arg placeholder, e.g. "theme-name"
    dynamic: str = ""  # resolver key from data/dynamic.json


@dataclass
class Form:
    route: str  # route including any folded verb
    base: str  # the real command route
    verb: list[str]  # literal tokens after base that select this form
    args: list[Arg]
    command: dict  # raw manifest entry

    @property
    def fn(self) -> str:
        return self.route.replace(" ", "_").replace("-", "_")

    def fillable(self) -> bool:
        """False when a required argument can never be filled."""
        return all(not a.required or a.kind != "free" or a.dynamic for a in self.args)

    def argv(self, values: dict[str, str | bool]) -> list[str]:
        """Assemble argv in grammar order. `values` maps arg name -> chosen value."""
        out = self.base.split() + self.verb
        for a in self.args:
            v = values.get(a.name)
            if v is None or v is False:
                continue
            if a.kind == "flag" and not a.style:
                out.append(a.flag)
            elif a.style == "eq":
                out.append(f"{a.flag}={v}")
            elif a.style == "space":
                out += [a.flag, str(v)]
            else:
                out.append(str(v))
        return out


def display(argv: list[str]) -> str:
    return shlex.join(argv)


def _split_top(s: str, sep: str = " ") -> list[str]:
    """Split on `sep` outside of [] and <> nesting."""
    parts, depth, cur = [], 0, ""
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in "[<(":
            depth += 1
        elif ch in "]>)":
            depth -= 1
        if depth == 0 and s.startswith(sep, i):
            parts.append(cur)
            cur = ""
            i += len(sep)
            continue
        cur += ch
        i += 1
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def _parse_group(tok: str, idx: int) -> Arg | None:
    required = tok.startswith("<")
    inner = tok[1:-1].strip()
    if inner.startswith("--") and "|" not in inner.split("=")[0].split(" ")[0]:
        # [--flag], [--flag=<v>], [--flag <v>]
        m = re.match(r"^(--[a-z0-9-]+)(?:([= ])<([^>]*)>)?$", inner)
        if not m:
            return None
        flag, sep, val = m.groups()
        if val is None:
            return Arg(name=flag, kind="flag", flag=flag, required=required)
        alts = val.split("|")
        lits = [a for a in alts if LITERAL.match(a)]
        if len(alts) > 1 and lits:
            return Arg(
                name=flag,
                kind="choice",
                values=lits,
                open=len(lits) < len(alts),
                flag=flag,
                style="eq" if sep == "=" else "space",
            )
        return Arg(
            name=flag,
            kind="free",
            flag=flag,
            placeholder=val,
            style="eq" if sep == "=" else "space",
        )
    if re.match(r"^-[a-z]\|--[a-z-]+$", inner):  # [-i|--interactive]
        long = inner.split("|")[1]
        return Arg(name=long, kind="flag", flag=long)
    if "|" in inner and not any(c in inner for c in "[]<> "):
        alts = [a.rstrip(".") for a in inner.split("|")]
        lits = [a for a in alts if LITERAL.match(a)]
        if lits:
            return Arg(
                name=f"pos{idx}",
                kind="choice",
                values=lits,
                required=required,
                open=len(lits) < len(alts),
            )
    return Arg(name=f"pos{idx}", kind="free", required=required, placeholder=inner)


def parse_args(spec: str) -> list[tuple[list[str], list[Arg]]]:
    """Return [(verb_tokens, args)] — one entry per form."""
    spec = spec.strip()
    if not spec:
        return [([], [])]
    alts = _split_top(spec, " | ")
    forms = []
    for alt in alts if len(alts) > 1 else [spec]:
        toks = _split_top(alt)
        verb, args = [], []
        for t in toks:
            if t[0] in "[<":
                a = _parse_group(t, len(args))
                if a:
                    args.append(a)
            elif not args and LITERAL.match(t) and len(alts) > 1:
                verb.append(t)
            else:  # bare word placeholder like `prompt`, `label`
                args.append(
                    Arg(
                        name=f"pos{len(args)}",
                        kind="free",
                        required=True,
                        placeholder=t,
                    )
                )
        forms.append((verb, args))
    return forms


@cache
def load_manifest() -> list[dict]:
    """The live manifest straight from the CLI, falling back to the snapshot."""
    try:
        out = subprocess.run(
            ["omarchy", "commands", "--all", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
        return json.loads(out)["commands"]
    except OSError, subprocess.SubprocessError, ValueError, KeyError:
        return json.loads((DATA / "manifest-live.json").read_text())["commands"]


@cache
def policy() -> dict:
    return json.loads((DATA / "policy.json").read_text())


@cache
def dynamic_map() -> dict:
    return json.loads((DATA / "dynamic.json").read_text())


def _route_match(route: str, prefixes) -> str | None:
    for p in prefixes:
        if route == p or route.startswith(p + " "):
            return p
    return None


def destructive_reason(route: str) -> str | None:
    p = _route_match(route, policy()["destructive"])
    return policy()["destructive"][p] if p else None


def offered(cmd: dict) -> bool:
    return not cmd["hidden"] or cmd["route"] in policy()["include_hidden"]


@cache
def forms() -> dict[str, Form]:
    """All offerable forms keyed by route."""
    dyn = dynamic_map()
    out: dict[str, Form] = {}
    for cmd in load_manifest():
        if not offered(cmd):
            continue
        for verb, args in parse_args(cmd["args"]):
            for a in args:
                key = f"{cmd['route']}::{a.placeholder}"
                if a.kind == "free" and key in dyn:
                    a.dynamic = key
            route = " ".join([cmd["route"], *verb])
            form = Form(
                route=route, base=cmd["route"], verb=verb, args=args, command=cmd
            )
            # Verbless alternatives share a route; keep the first one that can be filled.
            if route not in out or (not out[route].fillable() and form.fillable()):
                out[route] = form
    return out


def resolve_dynamic(key: str) -> dict[str, str]:
    """Run a dynamic resolver: {cli_value: description}."""
    d = dynamic_map()[key]
    out = subprocess.run(
        d["cmd"], capture_output=True, text=True, timeout=5, check=False
    ).stdout
    values = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        v = line.lower().replace(" ", "-") if d.get("slug") else line
        values[v] = line
    return values


def match_route(argv: list[str]) -> Form | None:
    """Longest form whose route is a word-prefix of argv — the execution gate."""
    best = None
    for f in forms().values():
        r = f.route.split()
        if argv[: len(r)] == r and (best is None or len(r) > len(best.route.split())):
            best = f
    return best
