# Omi AI — notes and results

Built against the **live** CLI (`omarchy commands --all --json`), not the old Mac data files.

## Layout

| Path | What |
|---|---|
| `src/omi_ai/cli.py` | `omi-ai` subcommands |
| `src/omi_ai/catalog.py` | Parses the live manifest's `args` into fillable forms (choice / flag / free), applies policy; `OMI_AI_SNAPSHOT=1` uses the bundled snapshot |
| `src/omi_ai/retriever.py` | rapidfuzz keyword retriever, top-k candidates |
| `src/omi_ai/dispatch.py` | Jev questions, disk cache, fixtures replay, decision logic, thresholds, `build()` for argument edits, offline guesses |
| `src/omi_ai/serve.py` | Socket-activated daemon: `/ask`, `/build`, `/health` |
| `src/omi_ai/flow.py` | The `omi-ask` menu flow: confirm, change argument, explain, wrong, escalate menu, history |
| `src/omi_ai/gates.py` | Run-time gates: live route check, destructive policy (word-prefix match) |
| `src/omi_ai/execute.py` | Runs argv (never a shell); sudo/TUI commands in Omarchy's floating terminal |
| `src/omi_ai/menu.py` | `omarchy-menu-input` / `-select` / `notify-send` wrappers |
| `src/omi_ai/config.py` | `config.toml` loading, presets, validation, template |
| `src/omi_ai/onboarding.py` | `omi-ai setup` (key validated via `models.list()`, saved atomically, 600) |
| `src/omi_ai/doctor.py`, `review.py`, `speccheck.py`, `uninstall.py` | The matching subcommands |
| `src/omi_ai/events.py` | Usage log (`log.jsonl`), privacy filter, pruning |
| `src/omi_ai/evaluate.py` | recall / run / sweep / snapshot, `--offline` replay, floors |
| `src/omi_ai/data/` | `spec.json`, `policy.json`, `dynamic.json` (+ snapshot), `synonyms.json`, `manifest-live.json` snapshot |
| `bin/omi-ask`, `bin/omi-ai-install` | Entry point to bind a key to; idempotent installer |
| `eval/rows.jsonl`, `eval/floors.json` | 425 labelled rows (valid/test by hash); held-out floors `just eval` warns on |
| `tests/` | pytest, no network: catalog, gates, config, dispatch, flow (fake menus), onboarding, menu (fake binaries), serve, review, uninstall |

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

## Spec round 2 (2026-10-18)

Hand-described commands 157 → 349 of 392 (the 43 left are `hw` probes and `dev` tools); status-bar/script helpers are
described as internal so Jev stops picking them; 33 new argument specs with labels. Re-swept on valid: with the
richer spec `actionable_min` 0.5 dominates 0.3, so all presets now use 0.5.

Held-out test, balanced preset:

| | command | args | over-escalate | escalate recall | false-command |
|---|---|---|---|---|---|
| before (157 described, actionable 0.3) | 87.0% | 83.2% | 10.3% | 87.2% | 12.8% |
| **after (349 described, actionable 0.5)** | **89.1%** | **86.4%** | **9.2%** | **89.7%** | **10.3%** |

| test split | command | args | over-escalate | false-command |
|---|---|---|---|---|
| conservative | 85.3% | 82.6% | 13.0% | 10.3% |
| balanced | 89.1% | 86.4% | 9.2% | 10.3% |
| permissive | 89.7% | 87.0% | 8.7% | 12.8% |

Remaining false commands are mostly "picker" commands given a specific value (timezone, language, keyboard
layout, AUR package): they open the right picker, but the eval labels them as escalations.

## Jev vs Kev-0.8B (2026-10-18)

[Kev](https://github.com/jaredpalmer/kev) is an open, local System One–compatible model family (Qwen3.5 + LoRA +
pointer head). The TypeSafe SDK talks to it unchanged via `TYPESAFE_BASE_URL`; Omi turns off zstd request
compression for custom base URLs because Kev's server doesn't accept it.

This machine (i7-7700K, 16 GB, AMD RX 580 — no usable GPU) can only run Kev-0.8B, on CPU in fp32. Kev-4B needs
8–16 GB just for weights and would take minutes per request here. Same 100-row sample of the held-out test split
(83 commands, 17 escalations), same spec and retriever:

| | command | args | over-escalate | false-command | time per request |
|---|---|---|---|---|---|
| Jev 1.13, balanced | 86.7% | 86.7% | 10.8% | 5.9% | ~80 ms (API) |
| Jev 1.13, best thresholds at ≤6% false-command | 89.2% | 89.2% | 8.4% | 5.9% | |
| Kev-0.8B, Jev's thresholds | 14.5% | 12.0% | 85.5% | 17.6% | ~30 s (CPU, alone) |
| Kev-0.8B, best thresholds at ≤6% false-command | 10.8% | 10.8% | 89.2% | 5.9% | |
| Kev-0.8B, best at ≤35% false-command | 49.4% | 49.4% | 38.6% | 35.3% | |
| Jev, gates off (command pick only) | 96.4% | 95.2% | 0% | 100% | |
| Kev-0.8B, gates off (command pick only) | 89.2% | 79.5% | 0% | 100% | |

- Kev-0.8B is a usable *picker* (89% right command among 8 candidates) but its Noul judgments carry almost no
  signal on Omi's questions: its "is this an action?" median is 0.41 on command rows and 0.40 on escalation rows,
  so no threshold separates them. The escalate gates are what make Omi safe, so Kev-0.8B can't replace Jev here.
- At ~30 s per request on this CPU it also fails the latency bar by two orders of magnitude.
- Not tested: Kev-4B / 9B / 27B, which Kev's README puts within 1–4 points of Jev on its own suites. That needs a
  GPU (an L40S or H100 on Modal, per Kev's docs). To reproduce: start
  `kev.serve --run jaredpalmer/kev-4b@v1.0 --port 8009`, then
  `TYPESAFE_BASE_URL=http://127.0.0.1:8009 TYPESAFE_API_KEY=local omi-ai eval run --split test --sample 100 --model kev-latest`
  with a separate `XDG_CACHE_HOME` and a long `model.timeout_s`.

## Gates

- Installer: `bin/omi-ai-install` (venv, key file 600, units, symlinks, privacy notice once).
- Gate 7 ✅ socket inactive→active on request, idle exit (tested at 6 s; default 180 s), key absent from `systemctl --user cat` and the unit environment.
- Gate 8 partial ✅ unknown command refused (`omarchy rm -rf /`). Destructive command gets a second confirmation from `policy.json` even when the daemon doesn't flag it. Run path logs to `~/.local/state/omi-ai/log.jsonl`. Tested with a fake daemon and stubbed menus. **Not yet tested with a real keypress** — keybinding awaits approval.
- Launcher: no walker/fuzzel/wofi/rofi on this system. Uses Omarchy's own `omarchy-menu-input` / `omarchy-menu-select`.
- Proposed keybinding (`SUPER + SLASH` is taken by monitor scaling), in `~/.config/hypr/bindings.lua`:
  `o.bind("SUPER + SHIFT + SPACE", "Ask Omi AI", "omi-ask")`
