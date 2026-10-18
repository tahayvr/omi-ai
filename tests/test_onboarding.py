import stat

import pytest

from omi_ai import menu, onboarding, paths


@pytest.fixture
def quiet(monkeypatch):
    notes = []
    monkeypatch.setattr(menu, "notify", notes.append)
    monkeypatch.setattr(onboarding, "_after_save", lambda: None)
    return notes


def test_save_key_is_private_and_atomic():
    onboarding.save_key("ts-secret")
    assert paths.KEY_FILE.read_text() == "ts-secret"
    assert stat.S_IMODE(paths.KEY_FILE.stat().st_mode) == 0o600
    assert not list(paths.CONFIG_DIR.glob(".api-key.*"))  # no temp file left behind


def test_menu_setup_retries_a_rejected_key(monkeypatch, quiet):
    inputs = iter(["  bad  ", "good"])
    monkeypatch.setattr(menu, "choose", lambda p, o: "I understand")
    prompts = []
    monkeypatch.setattr(menu, "ask_text", lambda p: prompts.append(p) or next(inputs))
    monkeypatch.setattr(onboarding, "check_key", lambda k: None if k == "good" else "TypeSafe rejected that key.")
    assert onboarding.run_menu()
    assert paths.KEY_FILE.read_text() == "good"
    assert prompts[1].startswith("TypeSafe rejected that key.")


def test_menu_setup_does_not_save_when_offline(monkeypatch, quiet):
    monkeypatch.setattr(menu, "choose", lambda p, o: "I understand")
    monkeypatch.setattr(menu, "ask_text", lambda p: "k")
    monkeypatch.setattr(onboarding, "check_key", lambda k: "Couldn't reach TypeSafe (x); key not saved.")
    assert not onboarding.run_menu()
    assert not paths.KEY_FILE.exists() and "Couldn't reach" in quiet[0]


def test_existing_key_kept_by_default(monkeypatch, quiet):
    onboarding.save_key("old")
    monkeypatch.setattr(menu, "choose", lambda p, o: "Keep current key")
    assert onboarding.run_menu() and paths.KEY_FILE.read_text() == "old"


def test_privacy_notice_must_be_accepted(monkeypatch, quiet):
    monkeypatch.setattr(menu, "choose", lambda p, o: "Cancel")
    assert not onboarding.run_menu() and not paths.KEY_FILE.exists()
