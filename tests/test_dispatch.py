import pytest
from conftest import answers

from omi_ai.dispatch import Thresholds

TH = Thresholds()


def cands(disp, *routes):
    return [disp.forms[r] for r in routes]


def theme_ans(**nouls):
    base = {"__actionable__": 0.9, "omarchy theme set|fits": 0.9, "omarchy theme switcher|fits": 0.3}
    return answers(
        {"omarchy theme set": 0.95, "omarchy theme switcher": 0.05},
        {**base, **nouls},
        {"omarchy theme set|pos0": {"choice": "nord", "p": {"nord": 0.9, "white": 0.1}}},
    )


def test_confident_command_with_argument(disp):
    c = cands(disp, "omarchy theme set", "omarchy theme switcher")
    r = disp.decide("make it nord", c, theme_ans(), TH)
    assert not r.escalate
    assert r.argv == ["omarchy", "theme", "set", "nord"]
    assert r.confidence == pytest.approx(0.9)
    assert r.values == {"pos0": "nord"}
    assert r.args[0]["label"] == "theme" and r.args[0]["p"] == 0.9 and "tokyo-night" in r.args[0]["options"]
    assert r.runner_up["route"] == "omarchy theme switcher"


@pytest.mark.parametrize(
    ("nouls", "kind"),
    [
        ({"__actionable__": 0.1}, "question"),
        ({"omarchy theme set|fits": 0.3}, "uncovered"),
        ({"__timing__": 0.9}, "timing"),
        ({"omarchy theme set|detail": 0.9}, "detail"),
        ({"omarchy theme set|pos0~": 0.9}, "value"),
    ],
)
def test_each_refusal_kind(disp, nouls, kind):
    c = cands(disp, "omarchy theme set", "omarchy theme switcher")
    r = disp.decide("q", c, theme_ans(**nouls), TH)
    assert r.escalate and r.kind == kind and r.argv is None


def test_timed_routes_are_exempt_from_timing(disp):
    c = cands(disp, "omarchy reminder", "omarchy reminder show")
    ans = answers(
        {"omarchy reminder": 0.9, "omarchy reminder show": 0.1},
        {"__actionable__": 0.9, "omarchy reminder|fits": 0.9, "__timing__": 0.95},
    )
    assert not disp.decide("set a reminder", c, ans, TH).escalate


def test_destructive_needs_clearer_judgments(disp):
    c = cands(disp, "omarchy remove ai claude", "omarchy install ai claude")
    p = {"omarchy remove ai claude": 0.95, "omarchy install ai claude": 0.05}
    unsure = disp.decide("q", c, answers(p, {"__actionable__": 0.6, "omarchy remove ai claude|fits": 0.9}), TH)
    assert unsure.escalate and unsure.kind == "destructive"
    sure = disp.decide("q", c, answers(p, {"__actionable__": 0.95, "omarchy remove ai claude|fits": 0.9}), TH)
    assert not sure.escalate and sure.destructive


def test_skipped_optional_positional_is_filled(disp):
    c = cands(disp, "omarchy powerprofiles set")
    ans = answers(
        {"omarchy powerprofiles set": 1.0},
        {"__actionable__": 0.9, "omarchy powerprofiles set|fits": 0.9, "omarchy powerprofiles set|pos1?": 0.9},
        {
            "omarchy powerprofiles set|pos0": {"choice": "ac", "p": {"ac": 0.5}},
            "omarchy powerprofiles set|pos1": {"choice": "performance", "p": {"performance": 0.95}},
        },
    )
    r = disp.decide("performance mode", c, ans, TH)
    assert r.argv == ["omarchy", "powerprofiles", "set", "autodetect", "performance"]


def test_suggestions_ranked_by_fit_and_filtered(disp):
    routes = ["omarchy restart wifi", "omarchy network speedtest", "omarchy network band", "omarchy dns"]
    c = cands(disp, *routes)
    ans = answers(
        {r: 0.25 for r in routes},
        {
            "__actionable__": 0.1,
            "omarchy restart wifi|fits": 0.5,
            "omarchy network speedtest|fits": 0.7,
            "omarchy dns|fits": 0.1,
        },
    )
    r = disp.decide("why is my wifi slow", c, ans, TH)
    assert [a["command"] for a in r.alternatives] == ["omarchy network speedtest", "omarchy restart wifi"]


def test_build_validates_values(disp):
    assert disp.build("omarchy theme set", {"pos0": "nord"}) == ["omarchy", "theme", "set", "nord"]
    with pytest.raises(ValueError):
        disp.build("omarchy theme set", {"pos0": "solarized"})
    with pytest.raises(ValueError):
        disp.build("omarchy system", {})


def test_offline_alternatives_ask_for_required_args(disp):
    alts = disp.offline_alternatives("switch to nord theme")
    ts = next(a for a in alts if a["route"] == "omarchy theme set")
    assert ts["argv"] is None and ts["args"][0]["required"]
