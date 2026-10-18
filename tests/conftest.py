"""Shared test setup: no network, no live Omarchy, no files outside tmp."""

from __future__ import annotations

import os

import pytest

os.environ["OMI_AI_SNAPSHOT"] = "1"  # bundled manifest + dynamic values, before any import caches them
os.environ.pop("TYPESAFE_API_KEY", None)

from omi_ai import config, dispatch, paths


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Point every Omi path at a fresh temp dir."""
    cfg, state, cache = tmp_path / "config", tmp_path / "state", tmp_path / "cache"
    monkeypatch.setattr(paths, "CONFIG_DIR", cfg)
    monkeypatch.setattr(paths, "KEY_FILE", cfg / "api-key")
    monkeypatch.setattr(paths, "CONFIG_FILE", cfg / "config.toml")
    monkeypatch.setattr(paths, "NOTICE_MARKER", cfg / ".privacy-notice-shown")
    monkeypatch.setattr(paths, "STATE_DIR", state)
    monkeypatch.setattr(paths, "LOG_FILE", state / "log.jsonl")
    monkeypatch.setattr(paths, "CACHE_DIR", cache)
    monkeypatch.setattr(paths, "JEV_CACHE", cache / "jev")
    monkeypatch.setattr(dispatch, "CACHE", cache / "jev")
    return tmp_path


@pytest.fixture(scope="session")
def disp():
    return dispatch.Dispatcher(config=config.load(paths.CONFIG_DIR / "missing.toml"))


def answers(route_p: dict, nouls: dict | None = None, choices: dict | None = None, default_noul: float = 0.0) -> dict:
    """A fake Jev answer: command distribution, Nouls (unset -> default_noul) and arg Choices."""
    top = max(route_p, key=route_p.get)
    return {
        "input_tokens": 1000,
        "choices": {"__command__": {"choice": top, "p": route_p}, **(choices or {})},
        "nouls": _Nouls(nouls or {}, default_noul),
    }


class _Nouls(dict):
    def __init__(self, data, default):
        super().__init__(data)
        self.default = default

    def __getitem__(self, k):
        return super().get(k, self.default)

    def get(self, k, default=None):
        return super().get(k, self.default)
