"""~/.config/omi-ai/config.toml — optional; every key has a default.

Unknown keys and bad values are reported (doctor shows them) and fall back to
the default, so a typo never stops the daemon from starting.
"""

from __future__ import annotations

import copy
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

# Threshold presets are the Pareto points from the sweep on the eval's valid split (NOTES.md).
PRESETS = {
    "conservative": {"actionable_min": 0.5, "fits_min": 0.5, "detail_max": 0.5,
                     "timing_max": 0.5, "destructive_min": 0.0},
    "balanced": {"actionable_min": 0.5, "fits_min": 0.5, "detail_max": 0.8,
                 "timing_max": 0.5, "destructive_min": 0.7},
    "permissive": {"actionable_min": 0.5, "fits_min": 0.5, "detail_max": 0.8,
                   "timing_max": 0.5, "destructive_min": 0.0},
}  # fmt: skip

DEFAULTS: dict[str, dict] = {
    "model": {"name": "jev-1.13.0", "timeout_s": 8.0},
    "thresholds": {
        "preset": "balanced",
        **PRESETS["balanced"],
        "other_max": 0.5,
        "suggest_min": 0.2,
    },
    "retrieval": {"candidates": 8},
    "ui": {"suggestions": 3, "show_confidence": True, "agent_handoff": True},
    "safety": {"destructive": "confirm"},
    "privacy": {"log_queries": True, "log_retention_days": 90},
    "daemon": {"port": 8127, "idle_exit_s": 180},
}

CHOICES = {
    ("thresholds", "preset"): set(PRESETS),
    ("safety", "destructive"): {"confirm", "block"},
}
UNIT_RANGE = {"actionable_min", "fits_min", "detail_max", "timing_max", "destructive_min",
              "other_max", "suggest_min"}  # fmt: skip

TEMPLATE = """\
# Omi AI configuration. Every key is optional; delete a line to use its default.
# After editing: omi-ai config reload

[model]
name = "jev-1.13.0"          # pinned Jev version; "jev-latest" follows the alias
timeout_s = 8

[thresholds]
preset = "balanced"          # conservative | balanced | permissive
# Individual values override the preset:
# actionable_min = 0.5       # below: treated as a question / problem report
# fits_min = 0.5             # below: "no single command does that"
# detail_max = 0.8           # above: names something the command can't take
# timing_max = 0.5           # above: asks for a delay or schedule
# destructive_min = 0.7      # destructive commands need actionable and fits above this
# other_max = 0.5            # above: asked for a value that isn't an option
# suggest_min = 0.2          # fit needed to show a command as a suggestion

[retrieval]
candidates = 8               # commands Jev chooses between

[ui]
suggestions = 3              # "did you mean" rows when no command fits
show_confidence = true
agent_handoff = true         # the "Ask the agent" row

[safety]
destructive = "confirm"      # confirm (ask twice) | block (never run them)

[privacy]
log_queries = true           # false: log outcomes only, never your text
log_retention_days = 90

[daemon]
port = 8127                  # re-run the installer after changing
idle_exit_s = 180
"""


@dataclass
class Config:
    data: dict
    errors: list[str] = field(default_factory=list)
    path: Path | None = None

    def __getitem__(self, section: str) -> dict:
        return self.data[section]

    def get(self, dotted: str):
        section, key = dotted.split(".", 1)
        return self.data[section][key]


def _check(section: str, key: str, value, default) -> str | None:
    if isinstance(default, bool):
        return None if isinstance(value, bool) else "must be true or false"
    if isinstance(default, (int, float)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "must be a number"
        if key in UNIT_RANGE and not 0 <= value <= 1.01:
            return "must be between 0 and 1"
        if value < 0:
            return "must not be negative"
        return None
    if isinstance(default, str):
        if not isinstance(value, str):
            return "must be a string"
        allowed = CHOICES.get((section, key))
        if allowed and value not in allowed:
            return f"must be one of: {', '.join(sorted(allowed))}"
    return None


def load(path: Path | None = None) -> Config:
    path = path or paths.CONFIG_FILE
    data = copy.deepcopy(DEFAULTS)
    errors: list[str] = []
    if not path.exists():
        return Config(data, errors, None)
    try:
        user = tomllib.loads(path.read_text())
    except (tomllib.TOMLDecodeError, OSError) as e:
        return Config(data, [f"{path}: {e} (using defaults)"], path)

    # The preset first, so explicit values in the file override it.
    preset = user.get("thresholds", {}).get("preset")
    if preset in PRESETS:
        data["thresholds"].update(PRESETS[preset])

    for section, values in user.items():
        if section not in DEFAULTS or not isinstance(values, dict):
            errors.append(f"unknown section [{section}]")
            continue
        for key, value in values.items():
            if key not in DEFAULTS[section]:
                errors.append(f"unknown key {section}.{key}")
                continue
            if problem := _check(section, key, value, DEFAULTS[section][key]):
                errors.append(f"{section}.{key} {problem} (using {data[section][key]!r})")
                continue
            data[section][key] = value
    return Config(data, errors, path)


def write_template(path: Path | None = None) -> bool:
    """Write the commented config if none exists. Returns True when written."""
    path = path or paths.CONFIG_FILE
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE)
    return True
