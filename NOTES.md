# Omi AI — notes and results

Built against the **live** CLI (`omarchy commands --all --json`), not the old Mac data files.

## Layout

| Path | What |
|---|---|
| `src/omi_ai/catalog.py` | Parses the live manifest's `args` strings into fillable forms (choice / flag / free), applies policy |
| `src/omi_ai/retriever.py` | rapidfuzz keyword retriever, top-k candidates |
| `src/omi_ai/dispatch.py` | Jev questions, disk cache, decision logic, thresholds |
| `src/omi_ai/serve.py` | Socket-activated HTTP daemon, `GET /ask?q=` |
| `src/omi_ai/evaluate.py` | recall / run / sweep |
| `src/omi_ai/data/spec.json` | Hand-written descriptions, argument questions, option meanings |
| `src/omi_ai/data/policy.json` | Hidden routes allowed back in, destructive routes |
| `src/omi_ai/data/dynamic.json` | Args resolved live (theme names, fonts) |
| `src/omi_ai/data/synonyms.json` | Retriever-only query expansion |
| `bin/omi-ask` | Launcher: Omarchy menu input → confirm → run |
| `bin/omi-ai-install` | Idempotent installer |
| `eval/rows.jsonl` | 425 labelled rows (written by a separate agent from the catalog, never shown the spec). Split valid/test by hash of the query |

Try it: `uv run omi-ai ask "make it louder"` (prints, never runs).

## SDK / models (checked 2026-10-17)

- `typesafe-sdk` 0.7.5. `Choice(instructions=, criteria={value: description})`, `Noul(instructions=)`, `Score(criteria=[...])`.
- Models: `jev-1.13.0` (= `jev-latest`) and `jev-1.14.0` (= `jev-preview`, from 2026-10-14). $0.042/Mtok input, output free. `models.list()` shows aliases only (documented).
- Pinned to **`jev-1.13.0`** (`OMI_AI_MODEL` overrides). 1.14 was not better on test (see below).

## Catalog

- Live manifest: 528 commands, 420 visible + 108 hidden.
- **Hidden ≠ forbidden.** 24 hidden commands are allowed back in (`policy.json` → `include_hidden`): all the `theme set <app>` sync commands, `bar text color`, `input method`, `toggle input device`, `launch docker tui`, `theme bg boot intro`, `capture webcam list`. The other 84 hidden commands are internal helpers or probes.
- **Destructive commands are offered, with a second explicit confirmation** (67 routes in `policy.json`). I picked them by scanning the live manifest for reset/remove/wipe/factory/reinstall/overwrite and reading the summaries. This is a judgement call to review, not an upstream list. Destructive routes also need stricter Jev thresholds (`destructive_min`).
- Multi-form grammars (`omarchy bar position … | background …`, `dock`, `reminder`) are split into separate forms.
- 458 forms; **392 fillable**. The other 66 need free text (URLs, package names, minutes, plugin ids…) and are excluded. Free-string arguments are never filled.
- Dynamic args: theme name (theme set / remove / plymouth set by theme) and font name, resolved from `omarchy theme list` / `omarchy font list` at request time.
- Spec options can override parsed values: `dns` gains `DHCP` (the parser dropped it as a placeholder). `brightness display` gains `+10% / 10%- / 25–100%`, which the CLI accepts but the grammar only shows as `+N%`.
- `omarchy theme list` needs `OMARCHY_PATH` (set in the systemd user env, not in every shell). Without it, only user themes are listed and test recall@8 drops from 97.3% to 95.1%. Run evals with `OMARCHY_PATH=$HOME/omarchy` (or wherever omarchy lives).
- Commands are executed as an argv array, never by word-splitting (font names have spaces). Commands needing sudo or a TUI (install/remove/update/pkg/setup/…) open in Omarchy's floating terminal.

## Dispatcher design

One Jev request per utterance. State is the utterance only. Candidates are sorted alphabetically before the command Choice, because Jev leans toward the first option and retrieval order would bias it.

| Question | Type | Used for |
|---|---|---|
| `__command__` | Choice over top-8 | which form |
| `__actionable__` | Noul | action / state question vs how-to, problem report, chat |
| `__timing__` | Noul | delay / schedule / duration → escalate (`timed` spec routes exempt) |
| `{route}\|fits` | Noul per candidate | would this action do it (description + what it can be told) |
| `{route}\|detail` | Noul per candidate | names something the action can't be told |
| `{route}\|{arg}` | Choice | argument value |
| `{route}\|{arg}?` | Noul | optional arg stated at all |
| `{route}\|{arg}~` | Noul | asked for a value outside the options ("solarized", "vivaldi") |
| `{route}\|{flag}!` | Noul | flag on/off |

Confidence = min of the judgments used. Omitted optional positionals are filled when a later positional is set (`powerprofiles set autodetect performance`).

Single-escalate-Noul history on valid: 75.9% → 92.5% fn acc after per-candidate `fits` + spec fixes. The global "covered" Noul listing all 8 descriptions was badly under-confident (0.15–0.4 on clear requests).

## Results

Retriever recall (fn rows): valid@8 100% (tuned on it), **test@8 97.3%**, test@5 96.7%, test@1 75.0%.

Threshold sweep on **valid** (Pareto front on false-command vs over-escalate):

| point | actionable | fits | detail | timing | destructive | false-cmd | over-esc | arg acc |
|---|---|---|---|---|---|---|---|---|
| conservative | 0.3 | 0.5 | 0.5 | 0.5 | 0.0 | 7.0% | 11.3% | 82.4% |
| **balanced (default)** | 0.3 | 0.5 | 0.8 | 0.5 | 0.7 | 9.3% | 7.5% | 86.2% |
| permissive | 0.3 | 0.5 | 0.8 | 0.5 | 0.0 | 11.6% | 5.7% | 88.1% |

Held-out **test** (223 rows: 184 command, 39 escalate):

| System | deployed fn acc | arg acc | escalate recall | false-command | over-escalate |
|---|---|---|---|---|---|
| retrieval-top1 | 75.0% | — | 0% | 100% | 0% |
| jev-1.13.0 conservative | 84.8% | 81.5% | 92.3% | 7.7% | 13.0% |
| **jev-1.13.0 balanced** | **87.0%** | **83.2%** | **87.2%** | **12.8%** | **10.3%** |
| jev-1.13.0 permissive | 88.6% | 84.8% | 84.6% | 15.4% | 8.7% |
| jev-1.14.0 balanced | 86.4% | 84.2% | 84.6% | 15.4% | 10.9% |

(The old plan's Granite/retrieval rows used a different command set and eval, so they aren't comparable.)

- Test false commands at balanced (5/39), none destructive: "remind me in 10 minutes to stretch" → `reminder` (interactive), "bind super+b to open firefox" → `launch browser`, "make the bar font bigger" → `display text size`, "connect to my bluetooth speaker" → `audio output switch`, "set the theme to dracula" → `theme set templates`.
- Cost: test run ~497k input tokens = **$0.021** (~2.2k tokens/request). Valid is about the same.
- Latency: median Jev round trip **~78 ms**. Daemon cold start 1.3 s (manifest + theme/font lists), warm request ~100 ms end to end.

Remaining weak spots: near-duplicate routes (`screensaver` vs `launch screensaver`, `bar reset` vs `bar defaults`), "back on/off" direction on toggles, flags that Jev adds unasked (`--fullscreen`, `--meta`), and no-arg picker commands given a specific value ("set timezone to Berlin" → opens the timezone picker; labelled escalate).

## Gates

- Installer: `bin/omi-ai-install` (venv, key file 600, units, symlinks, privacy notice once).
- Gate 7 ✅ socket inactive→active on request, idle exit (tested at 6 s; default 180 s), key absent from `systemctl --user cat` and the unit environment.
- Gate 8 partial ✅ unknown command refused (`omarchy rm -rf /`). Destructive command gets a second confirmation from `policy.json` even when the daemon doesn't flag it. Run path logs to `~/.local/state/omi-ai/log.jsonl`. Tested with a fake daemon and stubbed menus. **Not yet tested with a real keypress** — keybinding awaits approval.
- Launcher: no walker/fuzzel/wofi/rofi on this system. Uses Omarchy's own `omarchy-menu-input` / `omarchy-menu-select`.
- Proposed keybinding (`SUPER + SLASH` is taken by monitor scaling), in `~/.config/hypr/bindings.lua`:
  `o.bind("SUPER + SHIFT + SPACE", "Ask Omi AI", "omi-ask")`
