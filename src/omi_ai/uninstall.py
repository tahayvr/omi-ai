"""omi-ai uninstall: remove what the installer put in place.

Keeps the API key, config and usage log unless --purge, and says where they are.
"""

from __future__ import annotations

import shutil
import subprocess

from . import paths


def main(purge: bool = False) -> int:
    subprocess.run(["systemctl", "--user", "disable", "--now", "omi-ai.socket", "omi-ai.service"],
                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip
    removed = []
    for p in (paths.UNIT_DIR / "omi-ai.socket", paths.UNIT_DIR / "omi-ai.service",
              paths.BIN_DIR / "omi-ask", paths.BIN_DIR / "omi-ai"):  # fmt: skip
        if p.is_symlink() or p.exists():
            p.unlink()
            removed.append(str(p))
    for d in (paths.SHARE_DIR, paths.CACHE_DIR):
        if d.exists():
            shutil.rmtree(d)
            removed.append(str(d))
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    if purge:
        for d in (paths.CONFIG_DIR, paths.STATE_DIR):
            if d.exists():
                shutil.rmtree(d)
                removed.append(str(d))
    print("Removed:\n  " + "\n  ".join(removed) if removed else "Nothing to remove.")
    if not purge:
        kept = [str(d) for d in (paths.CONFIG_DIR, paths.STATE_DIR) if d.exists()]
        if kept:
            print(
                "Kept (API key, config, usage log) — `omi-ai uninstall --purge` removes them:\n  " + "\n  ".join(kept)
            )
    print("Your keybinding, if you added one, is still in your Hyprland config.")
    return 0
