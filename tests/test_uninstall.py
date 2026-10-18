import subprocess

from omi_ai import paths, uninstall


def test_uninstall_removes_install_and_keeps_data(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a[0]))
    units, bin_, share = tmp_path / "units", tmp_path / "bin", tmp_path / "share"
    for attr, val in (("UNIT_DIR", units), ("BIN_DIR", bin_), ("SHARE_DIR", share)):
        monkeypatch.setattr(paths, attr, val)
    for d in (units, bin_, share, paths.CACHE_DIR, paths.CONFIG_DIR, paths.STATE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    for f in (units / "omi-ai.socket", units / "omi-ai.service", share / "policy.json", paths.KEY_FILE):
        f.write_text("x")
    (bin_ / "omi-ask").symlink_to("/nonexistent")
    (units / "other.service").write_text("keep me")

    uninstall.main()
    assert not (units / "omi-ai.socket").exists() and not (bin_ / "omi-ask").is_symlink()
    assert not share.exists() and not paths.CACHE_DIR.exists()
    assert paths.KEY_FILE.exists() and (units / "other.service").exists()
    assert ["systemctl", "--user", "disable", "--now", "omi-ai.socket", "omi-ai.service"] in calls

    uninstall.main(purge=True)
    assert not paths.CONFIG_DIR.exists()
