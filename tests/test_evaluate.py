import json

from omi_ai import evaluate


def test_equivalent_routes_compare_equal():
    assert evaluate.norm("omarchy toggle input device touchpad off") == "omarchy toggle touchpad off"
    assert evaluate.norm('omarchy font set "JetBrainsMono Nerd Font"') == "omarchy font set JetBrainsMono Nerd Font"


def test_floors(tmp_path, monkeypatch):
    f = tmp_path / "floors.json"
    f.write_text(json.dumps({"test": {"deployed_fn_acc": 0.87, "false_command": 0.12}}))
    monkeypatch.setattr(evaluate, "FLOORS", f)
    assert evaluate.check_floors({"deployed_fn_acc": 0.865, "false_command": 0.125}, "test") == []
    warn = evaluate.check_floors({"deployed_fn_acc": 0.85, "false_command": 0.14}, "test")
    assert len(warn) == 2


def test_splits_partition_the_rows():
    v, t, a = evaluate.rows("valid"), evaluate.rows("test"), evaluate.rows("all")
    assert len(v) + len(t) == len(a) and not {r["q"] for r in v} & {r["q"] for r in t}
