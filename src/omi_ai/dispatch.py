"""Jev dispatcher: utterance -> one omarchy command, or escalate.

One System One request per utterance. State is the utterance and nothing else.
Questions:
  __command__      Choice over the retrieved candidate forms (relative judgment)
  __actionable__   Noul: an action/info request, not a how-to, problem report or chat
  {route}|fits     Noul: this candidate would do what is asked (absolute, per candidate)
  {route}|{arg}    Choice: argument value, for every candidate (speculative fan-out)
  __timing__       Noul: asks for a delay, schedule, duration or repetition (we can't)
  {route}|detail   Noul: names something this candidate can't be told
  {route}|{arg}~   Noul: the request names a value outside the options
  {route}|{arg}?   Noul: was the optional argument stated at all
  {route}|{flag}!  Noul: should the flag be on

Escalation lives in the two Nouls, never as an option in the Choice: a Choice
always picks something, a Noul can be low for everything.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field

from typesafe_sdk import Choice, Noul, TypeSafeClient

from . import catalog, paths
from .catalog import Form
from .config import Config
from .retriever import Retriever

MODEL = os.environ.get("OMI_AI_MODEL", "jev-1.13.0")
CACHE = paths.JEV_CACHE
PRICE_PER_TOKEN = 0.042 / 1e6
TERMINAL_GROUPS = {
    "install",
    "remove",
    "update",
    "pkg",
    "setup",
    "reinstall",
    "upgrade",
    "migrate",
}


@dataclass
class Thresholds:
    """Defaults are the "balanced" point from the sweep on eval valid split (see NOTES.md)."""

    actionable_min: float = 0.5
    fits_min: float = 0.5  # the chosen candidate's |fits Noul
    route_min: float = 0.0
    other_max: float = 0.5
    timing_max: float = 0.5
    detail_max: float = 0.8
    # actionable and fits must both clear this for destructive routes
    destructive_min: float = 0.7
    # |fits a candidate needs to be offered as an escalate suggestion
    suggest_min: float = 0.2

    @classmethod
    def from_config(cls, cfg: Config) -> Thresholds:
        t = cfg["thresholds"]
        return cls(**{k: t[k] for k in cls.__dataclass_fields__ if k in t})


class MissingKey(Exception):
    """No TypeSafe API key configured."""


class StaleFixture(Exception):
    """Offline eval: this request isn't in the recorded fixtures (spec or prompts changed)."""


@dataclass
class Result:
    query: str
    argv: list[str] | None
    confidence: float
    escalate: bool
    detail: str = ""
    route: str | None = None
    destructive: str | None = None
    terminal: bool = False  # needs a terminal (sudo prompt or interactive output)
    kind: str = ""  # escalate reason: question | uncovered | timing | detail | value | destructive
    alternatives: list[dict] = field(default_factory=list)  # suggestions on escalate
    values: dict = field(default_factory=dict)  # chosen argument values, by arg name
    args: list[dict] = field(default_factory=list)  # per-argument detail for change/explain
    runner_up: dict | None = None
    candidates: list[str] = field(default_factory=list)
    scores: dict = field(default_factory=dict)  # raw judgments, for tuning and logs
    input_tokens: int = 0
    cached: bool = False
    latency: float = 0.0

    @property
    def command(self) -> str | None:
        return catalog.display(self.argv) if self.argv else None


def load_spec() -> dict:
    return json.loads((catalog.DATA / "spec.json").read_text())


def load_synonyms() -> dict:
    return json.loads((catalog.DATA / "synonyms.json").read_text())


class Dispatcher:
    def __init__(
        self,
        client: TypeSafeClient | None = None,
        k: int = 8,
        model: str | None = None,
        thresholds: Thresholds | None = None,
        config: Config | None = None,
        fixtures: dict | None = None,
        record: dict | None = None,
    ):
        """`fixtures`: replay recorded answers only (offline eval).
        `record`: dict that collects every answer used, keyed by request hash (snapshot)."""
        self.spec = load_spec()
        self.forms = {r: f for r, f in catalog.forms().items() if f.fillable()}
        self.retriever = Retriever(self.forms, self.spec, load_synonyms())
        self.client = client
        self.config = config
        if config is not None:
            k = config["retrieval"]["candidates"]
        self.th = thresholds or (Thresholds.from_config(config) if config else Thresholds())
        self.k = k
        # Explicit argument > OMI_AI_MODEL > config file > built-in default.
        self.model = model or os.environ.get("OMI_AI_MODEL") or (config["model"]["name"] if config else MODEL)
        self.fixtures = fixtures
        self.record = record
        self._dyn: dict[str, tuple[float, dict]] = {}

    # ---- spec lookups -------------------------------------------------------

    def describe(self, f: Form) -> str:
        s = self.spec["commands"].get(f.route, {})
        return s.get("description") or f.command["summary"]

    def arg_spec(self, f: Form, a: catalog.Arg) -> dict:
        return self.spec["args"].get(f.route, {}).get(a.name, {})

    def options(self, f: Form, a: catalog.Arg) -> dict[str, str]:
        """{cli_value: description} for a choice or dynamic argument."""
        s = self.arg_spec(f, a)
        if a.dynamic:
            now = time.monotonic()
            hit = self._dyn.get(a.dynamic)
            if not hit or now - hit[0] > 60:
                hit = (now, catalog.resolve_dynamic(a.dynamic))
                self._dyn[a.dynamic] = hit
            return dict(hit[1])
        if "options" in s:
            return dict(s["options"])
        return {v: v for v in a.values}

    def capabilities(self, f: Form) -> str:
        """Description plus what the action can be told, for the fits question."""
        parts = []
        for a in f.args:
            if a.kind == "flag":
                q = self.arg_spec(f, a).get("question")
                parts.append(f"optional: {q[:-1] if q else a.flag}")
            elif a.kind == "choice" or a.dynamic:
                opts = list(self.options(f, a).values())
                parts.append("one of: " + ", ".join(opts[:12]) + (" ..." if len(opts) > 12 else ""))
        return self.describe(f) + "." + (" It can be told: " + "; ".join(parts) + "." if parts else "")

    # ---- question building --------------------------------------------------

    def questions(self, cands: list[Form]) -> dict:
        qs: dict = {}
        menu = {f.route: self.describe(f) for f in cands}
        qs["__command__"] = Choice(
            instructions="Which one of these actions on the user's Linux desktop is the request asking for?",
            criteria=menu,
        )
        qs["__actionable__"] = Noul(
            instructions=(
                "Does the request say something the user wants the computer to do, change, open, install, "
                "or show them? Terse commands, a bare app or feature name, wishes like 'I want X' or "
                "'I like X', and questions about the computer's current state ('which theme am I using', "
                "'is bluetooth on') count. Asking how to do something or why something happens, describing "
                "a problem without saying what should be done about it, and small talk do not count."
            )
        )
        qs["__timing__"] = Noul(
            instructions=(
                "Does the request ask for something to happen later, after a delay, at a set time, for a "
                "set duration, or repeatedly, rather than right now?"
            )
        )
        for f in cands:
            qs[f"{f.route}|detail"] = Noul(
                instructions=(
                    "Does the request name a specific thing, such as a package, place, language, layout, "
                    "key, person or number, that this desktop action has no way to be told? "
                    f"The action: {self.capabilities(f)}"
                )
            )
            qs[f"{f.route}|fits"] = Noul(
                instructions=f"Would this desktop action do what the request asks for? The action: {self.capabilities(f)}"
            )
        for f in cands:
            for a in f.args:
                s = self.arg_spec(f, a)
                key = f"{f.route}|{a.name}"
                if a.kind == "flag":
                    qs[key + "!"] = Noul(
                        instructions=s.get("question")
                        or f"Does the request ask for the '{a.flag}' option of: {self.describe(f)}?"
                    )
                    continue
                opts = self.options(f, a)
                if not opts:
                    continue
                qs[key] = Choice(
                    instructions=s.get("question")
                    or f"For the action '{self.describe(f)}', which value does the request ask for?",
                    criteria=opts,
                )
                qs[key + "~"] = Noul(
                    instructions=f"Does the request name a specific choice that is not one of these: {', '.join(opts.values())}?"
                )
                if not a.required:
                    qs[key + "?"] = Noul(
                        instructions=s.get("stated")
                        or f"Does the request say which of these it wants: {', '.join(opts.values())}?"
                    )
        return qs

    # ---- calling Jev, with a disk cache -------------------------------------

    def _call(self, state: str, qs: dict) -> tuple[dict, bool]:
        payload = {k: v.model_dump(exclude_none=True) for k, v in sorted(qs.items())}
        h = hashlib.sha256(json.dumps([self.model, state, payload], sort_keys=True).encode()).hexdigest()
        if self.fixtures is not None:
            if h not in self.fixtures:
                raise StaleFixture(h)
            return self.fixtures[h], True
        path = CACHE / h[:2] / f"{h}.json"
        if path.exists():
            out = json.loads(path.read_text())
            if self.record is not None:
                self.record[h] = out
            return out, True
        if self.client is None:
            timeout = self.config["model"]["timeout_s"] if self.config else 8
            # Self-hosted System One servers (e.g. Kev) may not accept zstd request bodies.
            compression = False if os.environ.get("TYPESAFE_BASE_URL") else None
            self.client = TypeSafeClient(api_key=read_api_key(), timeout=timeout, compression=compression)
        r = self.client.system_one(state, qs, model=self.model)
        out = {
            "model": r.model,
            "input_tokens": r.usage.input_tokens,
            "choices": {k: {"choice": v.choice, "p": dict(v.probabilities)} for k, v in r.choices.items()},
            "nouls": {k: v.noul for k, v in r.nouls.items()},
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out))
        if self.record is not None:
            self.record[h] = out
        return out, False

    # ---- the decision -------------------------------------------------------

    def judge(self, q: str) -> tuple[list[Form], dict, bool, float]:
        t0 = time.monotonic()
        cands = [f for f, _ in self.retriever.search(q, self.k)]
        cands.sort(key=lambda f: f.route)  # Jev leans to the first option; don't hand it retrieval order
        ans, cached = self._call(q, self.questions(cands))
        return cands, ans, cached, time.monotonic() - t0

    def fill(self, f: Form, ans: dict, th: Thresholds) -> tuple[list[str] | None, float, dict]:
        """Build argv for one candidate from its argument judgments.

        Returns (None, 0, {}) when the request asked for a value outside the options.
        Confidence is the weakest argument judgment (the route pick is not included).
        """
        ch, no = ans["choices"], ans["nouls"]
        values: dict[str, str | bool] = {}
        confs = [1.0]
        for a in f.args:
            key = f"{f.route}|{a.name}"
            if a.kind == "flag":
                p = no.get(key + "!", 0.0)
                values[a.name] = p >= 0.5
                confs.append(max(p, 1 - p))
                continue
            if key not in ch:
                continue
            if not a.required:
                p_stated = no.get(key + "?", 0.0)
                confs.append(max(p_stated, 1 - p_stated))
                if p_stated < 0.5:
                    continue
            if no.get(key + "~", 0.0) >= th.other_max:
                return None, 0.0, {}
            c = ch[key]
            values[a.name] = c["choice"]
            confs.append(c["p"][c["choice"]])
        # An optional positional can't be skipped when a later one is given.
        pos = [a for a in f.args if not a.flag]
        for i, a in enumerate(pos):
            if a.name not in values and any(b.name in values for b in pos[i + 1 :]):
                fill = self.arg_spec(f, a).get("fill") or (a.values[0] if a.values else None)
                if fill:
                    values[a.name] = fill
        return f.argv(values), min(confs), values

    def alternatives(self, cands: list[Form], ans: dict, th: Thresholds, limit: int = 3) -> list[dict]:
        """Runnable "did you mean" suggestions for an escalate, best fit first."""
        p_route = ans["choices"]["__command__"]["p"]
        out = []
        for f in cands:
            fits = ans["nouls"].get(f"{f.route}|fits", 0.0)
            if fits < th.suggest_min:
                continue
            argv, conf, _ = self.fill(f, ans, th)
            if argv is None:
                continue
            out.append(
                {
                    "command": catalog.display(argv),
                    "argv": argv,
                    "fits": round(fits, 3),
                    "route_p": round(p_route.get(f.route, 0.0), 3),
                    "confidence": round(min(conf, fits), 3),
                    "destructive": catalog.destructive_reason(f.route),
                    "terminal": self.needs_terminal(f),
                }
            )
        out.sort(key=lambda x: (-x["fits"], -x["route_p"]))
        return out[:limit]

    def label(self, f: Form, a: catalog.Arg) -> str:
        s = self.arg_spec(f, a)
        if s.get("label"):
            return s["label"]
        if a.flag:
            return a.flag.lstrip("-").replace("-", " ")
        if a.placeholder:
            return a.placeholder.removesuffix("-name").replace("-", " ")
        return "option"

    def arg_info(self, f: Form, ans: dict | None, values: dict) -> list[dict]:
        """What the menu needs to show and change each argument of one form."""
        ch = ans["choices"] if ans else {}
        out = []
        for a in f.args:
            key = f"{f.route}|{a.name}"
            if a.kind == "flag":
                out.append(
                    {
                        "name": a.name,
                        "label": self.label(f, a),
                        "kind": "flag",
                        "value": bool(values.get(a.name)),
                        "required": False,
                    }
                )
                continue
            if a.kind != "choice" and not a.dynamic:
                continue
            opts = self.options(f, a)
            if not opts:
                continue
            value = values.get(a.name)
            p = ch.get(key, {}).get("p", {}).get(value) if value else None
            out.append(
                {
                    "name": a.name,
                    "label": self.label(f, a),
                    "kind": "choice",
                    "value": value,
                    "required": a.required,
                    "options": opts,
                    "p": round(p, 3) if p is not None else None,
                }
            )
        return out

    def build(self, route: str, values: dict) -> list[str]:
        """argv for a route with explicit argument values (menu edits). Validates values."""
        f = self.forms[route]
        clean: dict = {}
        for a in f.args:
            v = values.get(a.name)
            if v is None or v is False:
                continue
            if a.kind == "flag":
                clean[a.name] = bool(v)
            elif v in self.options(f, a):
                clean[a.name] = v
            else:
                raise ValueError(f"{v!r} is not a valid value for {a.name} of {route}")
        missing = [a.name for a in f.args if a.required and a.name not in clean]
        if missing:
            raise ValueError(f"{route} needs {', '.join(missing)}")
        return f.argv(clean)

    def offline_alternatives(self, q: str, limit: int = 5) -> list[dict]:
        """Retriever-only guesses for when Jev can't be reached."""
        out = []
        for f, score in self.retriever.search(q, limit * 2):
            if score <= 0:
                continue
            info = self.arg_info(f, None, {})
            needs = [a for a in info if a["required"]]
            out.append(
                {
                    "route": f.route,
                    "command": catalog.display(f.argv({})) if not needs else f.route + " …",
                    "argv": f.argv({}) if not needs else None,
                    "args": info,
                    "description": self.describe(f),
                    "destructive": catalog.destructive_reason(f.route),
                    "terminal": self.needs_terminal(f),
                }
            )
            if len(out) == limit:
                break
        return out

    @staticmethod
    def needs_terminal(f: Form) -> bool:
        return f.command["requires_sudo"] or f.command["group"] in TERMINAL_GROUPS

    def decide(self, q: str, cands: list[Form], ans: dict, th: Thresholds | None = None) -> Result:
        """Pure function of the judgments, so threshold sweeps need no API calls."""
        th = th or self.th
        ch, no = ans["choices"], ans["nouls"]
        cmd = ch["__command__"]
        route = cmd["choice"]
        p_route = cmd["p"][route]
        actionable, covered = no["__actionable__"], no[f"{route}|fits"]
        scores = {
            "route_p": p_route,
            "actionable": actionable,
            "covered": covered,
            "dist": dict(sorted(cmd["p"].items(), key=lambda kv: -kv[1])[:3]),
        }
        res = Result(
            query=q,
            argv=None,
            confidence=0.0,
            escalate=True,
            route=route,
            candidates=[f.route for f in cands],
            scores=scores,
            input_tokens=ans["input_tokens"],
        )

        def escalate(kind: str, detail: str) -> Result:
            res.kind, res.detail = kind, detail
            res.alternatives = self.alternatives(cands, ans, th)
            return res

        if actionable < th.actionable_min:
            return escalate(
                "question",
                "Sounds like a question, not an action.",
            )
        if covered < th.fits_min or p_route < th.route_min:
            return escalate("uncovered", "No single omarchy command does that.")
        scores["timing"], scores["detail"] = no["__timing__"], no[f"{route}|detail"]
        timed = self.spec["commands"].get(route, {}).get("timed", False)
        if scores["timing"] >= th.timing_max and not timed:
            return escalate(
                "timing",
                "Omi runs commands now; it can't schedule or delay them.",
            )
        if scores["detail"] >= th.detail_max:
            return escalate(
                "detail",
                "The command can't take the specific thing you named.",
            )
        if catalog.destructive_reason(route) and min(actionable, covered) < th.destructive_min:
            return escalate(
                "destructive",
                "Destructive, and the request wasn't clear enough.",
            )

        f = self.forms[route]
        others = sorted(((r, p) for r, p in cmd["p"].items() if r != route), key=lambda x: -x[1])
        if others:
            res.runner_up = {
                "route": others[0][0],
                "p": round(others[0][1], 3),
                "fits": round(no.get(f"{others[0][0]}|fits", 0.0), 3),
            }
        argv, conf, values = self.fill(f, ans, th)
        if argv is None:
            return escalate("value", "That value isn't one of the options.")
        res.argv = argv
        res.values = values
        res.args = self.arg_info(f, ans, values)
        res.confidence = min(p_route, conf)
        res.escalate = False
        res.destructive = catalog.destructive_reason(route)
        res.terminal = self.needs_terminal(f)
        return res

    def __call__(self, q: str) -> Result:
        cands, ans, cached, dt = self.judge(q)
        r = self.decide(q, cands, ans)
        r.cached, r.latency = cached, dt
        return r


def read_api_key() -> str:
    if k := os.environ.get("TYPESAFE_API_KEY"):
        return k
    if paths.KEY_FILE.exists() and (k := paths.KEY_FILE.read_text().strip()):
        return k
    raise MissingKey(str(paths.KEY_FILE))
