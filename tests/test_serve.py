from omi_ai import serve
from omi_ai.dispatch import MissingKey


class Fake:
    def __init__(self, exc):
        self.exc = exc

    def __call__(self, q):
        raise self.exc

    def offline_alternatives(self, q):
        return [{"command": "omarchy theme switcher"}]


def test_missing_key_becomes_no_key():
    r = serve.decision(Fake(MissingKey("x")), "q")
    assert r["escalate"] and r["kind"] == "no_key"


def test_network_error_becomes_offline_guesses():
    r = serve.decision(Fake(OSError("down")), "q")
    assert r["kind"] == "offline" and r["alternatives"][0]["command"] == "omarchy theme switcher"
