from omi_ai import config


def test_defaults_without_file(tmp_path):
    cfg = config.load(tmp_path / "none.toml")
    assert cfg["model"]["name"] == "jev-1.13.0"
    assert cfg["thresholds"]["detail_max"] == 0.8 and not cfg.errors


def test_preset_then_explicit_override(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[thresholds]\npreset = "conservative"\nfits_min = 0.6\n')
    t = config.load(p)["thresholds"]
    assert t["detail_max"] == 0.5  # from the preset
    assert t["fits_min"] == 0.6  # explicit wins


def test_bad_values_fall_back_and_are_reported(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(
        '[thresholds]\nfits_min = 3\n[ui]\nsuggestions = "lots"\nbogus = 1\n[nope]\nx = 1\n'
        '[safety]\ndestructive = "maybe"\n'
    )
    cfg = config.load(p)
    assert cfg["thresholds"]["fits_min"] == 0.5
    assert cfg["ui"]["suggestions"] == 3
    assert cfg["safety"]["destructive"] == "confirm"
    joined = " ".join(cfg.errors)
    for bit in ("fits_min", "suggestions", "unknown key ui.bogus", "unknown section [nope]", "destructive"):
        assert bit in joined


def test_broken_toml_uses_defaults(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[model\nname=")
    cfg = config.load(p)
    assert cfg["model"]["name"] == "jev-1.13.0" and cfg.errors


def test_template_is_valid_and_matches_defaults(tmp_path):
    p = tmp_path / "c.toml"
    assert config.write_template(p) and not config.write_template(p)
    cfg = config.load(p)
    assert not cfg.errors
    assert cfg.data == config.load(tmp_path / "none.toml").data
