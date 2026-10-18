from omi_ai import catalog
from omi_ai.catalog import parse_args


def test_every_live_args_string_parses():
    for cmd in catalog.load_manifest():
        parse_args(cmd["args"])  # must not raise


def test_verb_forms_split_into_routes():
    f = catalog.forms()
    assert "omarchy bar position" in f and "omarchy bar background" in f
    assert f["omarchy bar position"].args[0].values == ["top", "bottom", "left", "right"]


def test_short_long_flag_pair_is_one_flag():
    [(verb, args)] = parse_args("[-i|--interactive]")
    assert verb == [] and args[0].kind == "flag" and args[0].flag == "--interactive"


def test_placeholders_are_dropped_from_choices():
    [(_, args)] = parse_args("<raise|lower|mute-toggle|+N|-N>")
    assert args[0].values == ["raise", "lower", "mute-toggle"] and args[0].open


def test_valued_flag_choice_and_free():
    [(_, args)] = parse_args("[--webcam-size=<small|medium|large>] [--resolution=<size>]")
    size, res = args
    assert size.kind == "choice" and size.style == "eq" and size.values == ["small", "medium", "large"]
    assert res.kind == "free"


def test_hidden_commands_only_when_allowed():
    f = catalog.forms()
    assert "omarchy theme set vscode" in f  # hidden, allowed back in by policy
    assert "omarchy hw clamshell" not in f  # hidden helper


def test_argv_keeps_spaces_in_one_argument():
    f = catalog.forms()["omarchy font set"]
    assert f.argv({"pos0": "JetBrainsMono Nerd Font"}) == ["omarchy", "font", "set", "JetBrainsMono Nerd Font"]
    assert catalog.display(f.argv({"pos0": "JetBrainsMono Nerd Font"})) == "omarchy font set 'JetBrainsMono Nerd Font'"


def test_argv_flag_styles_in_grammar_order():
    f = catalog.forms()["omarchy capture screenrecording"]
    argv = f.argv({"--with-webcam": True, "--webcam-size": "large", "--fullscreen": True, "--status": False})
    assert argv == ["omarchy", "capture", "screenrecording", "--fullscreen", "--with-webcam", "--webcam-size=large"]


def test_dynamic_values_from_snapshot():
    themes = catalog.resolve_dynamic("omarchy theme set::theme-name")
    assert themes["tokyo-night"] == "Tokyo Night"


def test_match_route_picks_longest():
    assert catalog.match_route(["omarchy", "theme", "set", "vscode"]).route == "omarchy theme set vscode"
    assert catalog.match_route(["omarchy", "theme", "set", "nord"]).route == "omarchy theme set"
    assert catalog.match_route(["rm", "-rf"]) is None
