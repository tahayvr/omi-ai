"""menu.py against fake omarchy-menu-* binaries on PATH."""

import os

import pytest

from omi_ai import menu


@pytest.fixture
def fakebin(tmp_path, monkeypatch):
    d = tmp_path / "bin"
    d.mkdir()
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")

    def make(name, body):
        p = d / name
        p.write_text("#!/bin/bash\n" + body)
        p.chmod(0o755)

    return make


def test_choose_returns_label_without_subtext(fakebin):
    fakebin("omarchy-menu-select", 'printf "Run: x\\tsubtext\\n"')
    assert menu.choose("t", ["Run: x", "Cancel"]) == "Run: x"


def test_choose_dismissed(fakebin):
    fakebin("omarchy-menu-select", "exit 1")
    assert menu.choose("t", ["a"]) is None


def test_choose_rejects_rows_it_did_not_offer(fakebin):
    fakebin("omarchy-menu-select", "echo surprise")
    assert menu.choose("t", ["a"]) is None


def test_ask_text(fakebin):
    fakebin("omarchy-menu-input", 'echo "  hello  "')
    assert menu.ask_text("p") == "hello"
    fakebin("omarchy-menu-input", "exit 1")
    assert menu.ask_text("p") is None
