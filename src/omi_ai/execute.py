"""Run a confirmed command. argv is passed as a list — never through a shell."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass


@dataclass
class Outcome:
    ok: bool
    output: str
    in_terminal: bool = False


def run(argv: list[str], terminal: bool) -> Outcome:
    if terminal:
        # Needs sudo or shows a TUI: Omarchy's floating terminal, detached. That
        # wrapper runs its argument through bash, so it gets a shell-quoted string.
        subprocess.Popen(["omarchy-launch-floating-terminal-with-presentation", shlex.join(argv)],
                         start_new_session=True, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)  # fmt: skip
        return Outcome(True, "", in_terminal=True)
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
    except subprocess.TimeoutExpired:
        return Outcome(False, "Timed out after 2 minutes.")
    except OSError as e:
        return Outcome(False, str(e))
    out = (r.stdout + r.stderr).strip()
    return Outcome(r.returncode == 0, out)


def launch_agent(prompt: str) -> None:
    subprocess.Popen(["omarchy", "agent", "prompt", prompt], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip
