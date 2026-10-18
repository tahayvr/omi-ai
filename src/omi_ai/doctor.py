"""omi-ai doctor: health checks, each with the one command that fixes it."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass

from . import client, paths
from .config import load


@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail
    detail: str = ""
    fix: str = ""


def _systemd_env() -> dict[str, str]:
    try:
        out = subprocess.run(["systemctl", "--user", "show-environment"],
                             capture_output=True, text=True, timeout=5, check=False).stdout  # fmt: skip
    except OSError, subprocess.SubprocessError:
        return {}
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def _active(unit: str) -> str:
    try:
        return subprocess.run(["systemctl", "--user", "is-active", unit],
                              capture_output=True, text=True, timeout=5, check=False).stdout.strip()  # fmt: skip
    except OSError, subprocess.SubprocessError:
        return "unknown"


def run_checks(network: bool = True) -> list[Check]:
    from .onboarding import check_key

    cfg = load()
    checks: list[Check] = []
    add = checks.append

    # Config
    if cfg.errors:
        add(Check("Config file", "fail", "; ".join(cfg.errors), f"edit {paths.CONFIG_FILE}"))
    else:
        add(Check("Config file", "ok", str(cfg.path or "defaults (no config.toml)")))

    # Key
    key = None
    if os.environ.get("TYPESAFE_API_KEY"):
        key = os.environ["TYPESAFE_API_KEY"]
        add(Check("API key", "ok", "from TYPESAFE_API_KEY"))
    elif not paths.KEY_FILE.exists():
        add(Check("API key", "fail", "no key saved", "omi-ai setup"))
    else:
        mode = stat.S_IMODE(paths.KEY_FILE.stat().st_mode)
        key = paths.KEY_FILE.read_text().strip()
        if mode & 0o077:
            add(Check("API key", "fail", f"readable by others (mode {mode:o})", f"chmod 600 {paths.KEY_FILE}"))
        elif not key:
            add(Check("API key", "fail", "key file is empty", "omi-ai setup"))
        else:
            add(Check("API key", "ok", f"{paths.KEY_FILE} (mode 600)"))

    # TypeSafe reachable + key accepted
    if network and key:
        t0 = time.monotonic()
        problem = check_key(key)
        ms = int((time.monotonic() - t0) * 1000)
        if problem is None:
            add(Check("TypeSafe", "warn" if ms > 1000 else "ok", f"key accepted, {ms} ms",
                      "slow network; Omi will still work" if ms > 1000 else ""))  # fmt: skip
        elif "Couldn't reach" in problem:
            add(Check("TypeSafe", "fail", problem, "check your network (Omi falls back to offline guesses)"))
        else:
            add(Check("TypeSafe", "fail", problem, "omi-ai setup"))

    # Service
    sock = _active("omi-ai.socket")
    if sock != "active":
        add(Check("Service", "fail", f"omi-ai.socket is {sock}", "just install  (or bin/omi-ai-install)"))
    else:
        try:
            h = client.health(timeout=15)
            detail = f"answering ({h.get('commands')} commands, model {h.get('model')})"
            if h.get("model") != (os.environ.get("OMI_AI_MODEL") or cfg["model"]["name"]):
                add(Check("Service", "warn", detail + " — config changed since it started", "omi-ai config reload"))
            else:
                add(Check("Service", "ok", detail))
        except client.DaemonDown as e:
            add(Check("Service", "fail", f"socket active but no answer ({e})", "journalctl --user -u omi-ai -n 50"))

    # Omarchy
    if not shutil.which("omarchy"):
        add(Check("Omarchy CLI", "fail", "`omarchy` not on PATH", "install Omarchy"))
    else:
        add(Check("Omarchy CLI", "ok", shutil.which("omarchy") or ""))
    env = _systemd_env()
    if not env.get("OMARCHY_PATH"):
        add(Check("OMARCHY_PATH", "warn", "not set in the systemd user environment; theme names may be missing",
                  "systemctl --user import-environment OMARCHY_PATH"))  # fmt: skip
    else:
        add(Check("OMARCHY_PATH", "ok", env["OMARCHY_PATH"]))
    missing = [
        b for b in ("omarchy-menu-input", "omarchy-menu-select", "notify-send", "wl-copy") if not shutil.which(b)
    ]
    add(Check("Menu tools", "fail" if missing else "ok", ", ".join(missing) + " missing" if missing else "all present",
              "update Omarchy" if missing else ""))  # fmt: skip

    # Spec drift
    try:
        from .speccheck import report

        r = report()
        n_new, n_stale = len(r["undescribed"]), len(r["stale_spec"])
        if n_stale:
            add(Check("Spec", "warn", f"{n_stale} spec entries for commands that no longer exist", "omi-ai spec check"))
        else:
            add(
                Check(
                    "Spec",
                    "ok",
                    f"{r['described']}/{r['fillable']} commands hand-described, {n_new} use the CLI summary",
                )
            )
    except Exception as e:  # noqa: BLE001 — a broken spec check shouldn't hide the other checks
        add(Check("Spec", "warn", f"couldn't check ({e})", "omi-ai spec check"))

    # Disk use
    size = sum(f.stat().st_size for f in paths.CACHE_DIR.rglob("*") if f.is_file()) if paths.CACHE_DIR.exists() else 0
    log = paths.LOG_FILE.stat().st_size if paths.LOG_FILE.exists() else 0
    mb = (size + log) / 1e6
    add(Check("Cache and log", "warn" if mb > 50 else "ok", f"{mb:.1f} MB",
              "omi-ai review --prune" if mb > 50 else ""))  # fmt: skip
    return checks


ICON = {"ok": "✓", "warn": "!", "fail": "✗"}


def render(checks: list[Check]) -> str:
    w = max(len(c.name) for c in checks)
    lines = []
    for c in checks:
        lines.append(f"{ICON[c.status]} {c.name:<{w}}  {c.detail}")
        if c.fix and c.status != "ok":
            lines.append(f"  {'':<{w}}  → {c.fix}")
    return "\n".join(lines)


def main(as_menu: bool = False) -> int:
    checks = run_checks()
    failed = any(c.status == "fail" for c in checks)
    if as_menu:
        from . import menu

        rows = [f"{ICON[c.status]} {c.name}: {c.detail}" + (f" → {c.fix}" if c.fix and c.status != "ok" else "")
                for c in checks]  # fmt: skip
        menu.choose("Omi doctor — " + ("problems found" if failed else "all good"), rows)
    else:
        print(render(checks))
    return 1 if failed else 0
