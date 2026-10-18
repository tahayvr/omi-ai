"""The omi-ask menu flow, with menus, daemon, execution and gates replaced by fakes."""

from __future__ import annotations

import json

import pytest

from omi_ai import client, config, events, execute, flow, gates, menu, paths


class Script:
    """Answers menu calls in order; records what each menu showed."""

    def __init__(self, picks):
        self.picks = list(picks)
        self.shown = []

    def choose(self, prompt, options):
        self.shown.append((prompt, list(options)))
        want = self.picks.pop(0)
        if want is None:
            return None
        matches = [o for o in options if o.startswith(want)]
        assert matches, f"{want!r} not in menu {prompt!r}: {options}"
        return matches[0]

    def ask_text(self, prompt):
        self.shown.append((prompt, None))
        return self.picks.pop(0)


@pytest.fixture
def ui(monkeypatch):
    state = {"ran": [], "notes": [], "agent": [], "copied": [], "built": [], "resp": None}

    def install(picks, resp, output=None):
        output = output or execute.Outcome(True, "")
        s = Script(picks)
        monkeypatch.setattr(menu, "choose", s.choose)
        monkeypatch.setattr(menu, "ask_text", s.ask_text)
        monkeypatch.setattr(menu, "notify", state["notes"].append)
        responses = resp if isinstance(resp, list) else [resp]
        monkeypatch.setattr(client, "ask", lambda q: responses.pop(0) if len(responses) > 1 else responses[0])
        monkeypatch.setattr(client, "health", lambda timeout=5: {"ok": True})

        def build(route, values):
            state["built"].append((route, values))
            argv = ["omarchy", *route.split()[1:], *[v for v in values.values() if isinstance(v, str)]]
            return {"argv": argv, "command": " ".join(argv)}

        monkeypatch.setattr(client, "build", build)
        monkeypatch.setattr(execute, "run", lambda argv, terminal: state["ran"].append(argv) or output)
        monkeypatch.setattr(execute, "launch_agent", state["agent"].append)
        monkeypatch.setattr(flow, "_copy", state["copied"].append)
        state["script"] = s
        return state

    return install


def cmd_resp(argv, **extra):
    return {
        "escalate": False,
        "command": " ".join(argv),
        "argv": argv,
        "route": " ".join(argv[:3]),
        "confidence": 0.9,
        "terminal": False,
        "destructive": None,
        "values": {},
        "args": [],
        **extra,
    }


def esc_resp(kind, alts=(), detail="No single omarchy command does that."):
    return {"escalate": True, "kind": kind, "detail": detail, "alternatives": list(alts)}


def outcomes():
    return [e["outcome"] for e in events.read() if e.get("src") == "flow"]


THEME = cmd_resp(
    ["omarchy", "theme", "set", "nord"],
    route="omarchy theme set",
    values={"pos0": "nord"},
    args=[
        {
            "name": "pos0",
            "label": "theme",
            "kind": "choice",
            "value": "nord",
            "required": True,
            "p": 0.9,
            "options": {"nord": "Nord", "white": "White"},
        }
    ],
)


def test_run(ui):
    s = ui(["Run:"], THEME)
    flow.run("make it nord", debug=False)
    assert s["ran"] == [["omarchy", "theme", "set", "nord"]]
    assert outcomes() == ["ran"]
    title, rows = s["script"].shown[0]
    assert title == "Run this? (90% sure)"
    assert rows == ["Run: omarchy theme set nord", "Change theme: nord", "Explain", "Wrong command", "Copy", "Cancel"]


def test_cancel_and_dismiss_run_nothing(ui):
    s = ui(["Cancel"], THEME)
    flow.run("x", debug=False)
    s2 = ui([None], THEME)
    flow.run("x", debug=False)
    assert s["ran"] == [] and s2["ran"] == [] and outcomes() == ["cancelled", "cancelled"]


def test_copy(ui):
    s = ui(["Copy"], THEME)
    flow.run("x", debug=False)
    assert s["copied"] == ["omarchy theme set nord"] and s["ran"] == []


def test_wrong_command_logs_and_reopens_input(ui):
    s = ui(["Wrong command", None], THEME)  # then dismiss the new input box
    flow.run("make it nord", debug=False)
    assert outcomes() == ["wrong"] and s["ran"] == []
    assert s["script"].shown[-1] == ("Ask Omi", None)


def test_change_argument_then_run(ui):
    s = ui(["Change theme", "white", "Run:"], THEME)
    flow.run("x", debug=False)
    assert s["built"] == [("omarchy theme set", {"pos0": "white"})]
    assert s["ran"] == [["omarchy", "theme", "set", "white"]]


def test_explain_then_back_then_run(ui):
    s = ui(["Explain", "Back", "Run:"], THEME)
    flow.run("x", debug=False)
    explain = s["script"].shown[1][1]
    assert any(r.startswith("Command: omarchy theme set") for r in explain) and explain[-1] == "Back"
    assert s["ran"]


def test_destructive_asks_twice(ui):
    argv = ["omarchy", "remove", "ai", "claude"]
    s = ui(["Run:", "Cancel"], cmd_resp(argv, route="omarchy remove ai claude"))
    flow.run("x", debug=False)
    assert s["ran"] == [] and s["script"].shown[1][0].startswith("Destructive:")
    s = ui(["Run:", "Yes, run"], cmd_resp(argv, route="omarchy remove ai claude"))
    flow.run("x", debug=False)
    assert s["ran"] == [argv]


def test_destructive_blocked_by_config(ui, monkeypatch):
    paths.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    paths.CONFIG_FILE.write_text('[safety]\ndestructive = "block"\n')
    s = ui(["Run:"], cmd_resp(["omarchy", "remove", "ai", "claude"]))
    flow.run("x", debug=False)
    assert s["ran"] == [] and outcomes() == ["blocked-destructive"]


def test_unknown_command_refused_even_if_daemon_says_so(ui):
    s = ui(["Run:"], cmd_resp(["omarchy", "rm", "-rf", "/"]))
    flow.run("x", debug=False)
    assert s["ran"] == [] and "Refusing" in s["notes"][0] and outcomes() == ["refused-unknown"]


def test_long_output_opens_a_menu_and_copies_the_pick(ui):
    out = execute.Outcome(True, "\n".join(f"Theme {i}" for i in range(6)))
    s = ui(["Run:", "Theme 3"], THEME, output=out)
    flow.run("x", debug=False)
    assert s["copied"] == ["Theme 3"]


def test_escalate_question_offers_agent_first(ui):
    alts = [{"command": "omarchy restart wifi", "argv": ["omarchy", "restart", "wifi"], "fits": 0.6}]
    s = ui(["Ask the agent"], esc_resp("question", alts))
    flow.run("why is my wifi slow", debug=False)
    rows = s["script"].shown[0][1]
    assert rows[0].startswith("Ask the agent") and rows[1] == "Run: omarchy restart wifi"
    assert s["agent"] == ["why is my wifi slow"] and outcomes() == ["escalate-agent"]


def test_escalate_suggestion_runs_after_gates(ui):
    alts = [{"command": "omarchy launch nautilus", "argv": ["omarchy", "launch", "nautilus"], "fits": 0.4}]
    s = ui(["Run: omarchy launch nautilus"], esc_resp("uncovered", alts))
    flow.run("open files", debug=False)
    assert s["script"].shown[0][1][0] == "Run: omarchy launch nautilus"  # suggestions lead here
    assert s["ran"] == [["omarchy", "launch", "nautilus"]]


def test_timing_shows_no_suggestions(ui):
    alts = [{"command": "omarchy system shutdown", "argv": ["omarchy", "system", "shutdown"], "fits": 0.5}]
    s = ui(["Cancel"], esc_resp("timing", alts))
    flow.run("shut down in 30 minutes", debug=False)
    assert not any(r.startswith("Run:") for r in s["script"].shown[0][1])


def test_rephrase_asks_again(ui):
    ui(["Rephrase", "make it louder", "Cancel"], [esc_resp("uncovered"), THEME])
    flow.run("blah", debug=False)
    assert outcomes() == ["escalate-rephrased", "cancelled"]


def test_offline_guess_asks_for_required_value(ui):
    alt = {
        "route": "omarchy theme set",
        "command": "omarchy theme set …",
        "argv": None,
        "args": [
            {
                "name": "pos0",
                "label": "theme",
                "kind": "choice",
                "required": True,
                "options": {"nord": "Nord", "white": "White"},
            }
        ],
    }
    s = ui(["Run: omarchy theme set", "nord"], esc_resp("offline", [alt], "Can't reach TypeSafe"))
    flow.run("theme nord", debug=False)
    assert s["ran"] == [["omarchy", "theme", "set", "nord"]]


def test_no_key_offers_setup(ui, monkeypatch):
    from omi_ai import onboarding

    called = []
    monkeypatch.setattr(onboarding, "run_menu", lambda: called.append(1) or False)
    ui(["Set up API key"], {"escalate": True, "kind": "no_key", "detail": "", "alternatives": []})
    flow.run("x", debug=False)
    assert called == [1]


def test_query_text_not_logged_when_privacy_off(ui):
    paths.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    paths.CONFIG_FILE.write_text("[privacy]\nlog_queries = false\n")
    ui(["Run:"], THEME)
    flow.run("secret words", debug=False)
    raw = paths.LOG_FILE.read_text()
    assert "secret words" not in raw and json.loads(raw.splitlines()[0])["outcome"] == "ran"


def test_history_reruns_through_gates(ui, monkeypatch):
    events.log(
        {
            "src": "flow",
            "q": "nord please",
            "outcome": "ran",
            "command": "omarchy theme set nord",
            "argv": ["omarchy", "theme", "set", "nord"],
            "terminal": False,
        }
    )
    s = ui(["omarchy theme set nord"], THEME)
    calls = []
    monkeypatch.setattr(gates, "known_route", lambda argv: calls.append(argv) or True)
    flow.history(config.load())
    assert s["ran"] == [["omarchy", "theme", "set", "nord"]] and calls


def test_summary_line():
    line = flow.summary(
        {
            **THEME,
            "debug": {
                "route": "omarchy theme set",
                "scores": {"route_p": 1.0},
                "tokens": 10,
                "cached": True,
                "jev_ms": 3,
            },
        },
        7,
    )
    assert line.startswith("omarchy theme set nord  (90%)") and "total=7ms" in line
