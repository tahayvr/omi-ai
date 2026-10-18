from omi_ai import gates


def test_known_route():
    assert gates.known_route(["omarchy", "theme", "set", "nord"])
    assert not gates.known_route(["omarchy", "rm", "-rf", "/"])
    assert not gates.known_route(["rm", "-rf", "/"])
    assert not gates.known_route([])


def test_destructive_matches_whole_words_only():
    assert gates.destructive_reason(["omarchy", "remove", "ai", "claude"])
    assert gates.destructive_reason(["omarchy", "setup", "factory", "reset"])
    assert gates.destructive_reason(["omarchy", "removex"]) is None
    assert gates.destructive_reason(["omarchy", "refresh", "applications"]) is None
    assert gates.destructive_reason(["omarchy", "theme", "set", "nord"]) is None
