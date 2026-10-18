# Omi AI

Type a request in plain English, get an `omarchy` command, confirm, run. Built on
[TypeSafe Jev](https://docs.typesafe.ai) and Omarchy's own menus.

## Install

```bash
git clone https://github.com/tahayvr/omi-ai && cd omi-ai
bin/omi-ai-install     # service, omi-ai and omi-ask on your PATH
omi-ai setup           # paste your TypeSafe API key (checked before it's saved)
omi-ai doctor          # everything green?
```

Then run `omi-ask`, or bind a key to it yourself in `~/.config/hypr/bindings.lua`, e.g.
`o.bind("SUPER + SHIFT + SPACE", "Ask Omi", "omi-ask")`. Omi doesn't set keybindings for you.

Omi AI sends the text you type in the ask prompt to TypeSafe AI's servers for interpretation. It does not send your
files, your configuration, or system information. It needs a network connection and your own TypeSafe API key;
without a connection it falls back to offline best guesses.

## Using it

- **Confirm menu:** Run / Change any argument / Explain / Wrong command / Copy / Cancel. Nothing runs without Run.
- **Destructive commands** (uninstall, reset, overwrite…) ask a second time, or never run with `destructive = "block"`.
- **When nothing fits:** ask the agent with your text, pick a "did you mean" command, rephrase, or cancel. Questions
  and timed requests ("shut down in 30 minutes") lead with the agent; timed requests get no suggestions.
- **Long output** opens in a menu; picking a line copies it.

Things to try: `hide the bar`, `screenshot of a window and copy it`, `night light on`, `keep the screen awake`,
`bar on the left`, `performance mode`, `why is my wifi slow` (question → agent), `shut down in 30 minutes` (refused),
`factory reset` (asks twice).

| Command | What it does |
| --- | --- |
| `omi-ask` | The whole flow (what you bind a key to) |
| `omi-ai ask "…"` | Resolve and print with scores; never runs anything |
| `omi-ai setup [--terminal]` | Add or replace the API key (`--terminal`: hidden input) |
| `omi-ai doctor [--menu]` | Health checks, each with its fix |
| `omi-ai history` | Pick a recent command and run it again (no API call) |
| `omi-ai review [--days N] [--export] [--prune]` | What your usage says to fix; export misses as eval rows |
| `omi-ai config [show\|edit\|reload\|path\|get KEY]` | The config file |
| `omi-ai spec check [--all] [--update-snapshot]` | Spec vs the live Omarchy catalog |
| `omi-ai uninstall [--purge]` | Remove the service and symlinks (`--purge`: key, config and log too) |

## Config

`~/.config/omi-ai/config.toml`, optional. `omi-ai config edit` opens a commented copy; `omi-ai config reload`
applies it. Main knobs: `thresholds.preset` (`conservative` / `balanced` / `permissive`), `ui.suggestions`,
`safety.destructive`, `privacy.log_queries`, `model.name`.

## Development

```bash
just            # list recipes
just ask "make it louder"
just test       # unit tests (no network, < 1 s)
just snapshot   # record Jev answers for the offline eval (once, and after spec or prompt changes)
just eval       # offline eval on the test split: no API, no cost
just check      # lint + tests + offline eval, before you push
just restart    # daemon picks up code, spec and config changes
```

Evals stay local; CI runs lint and tests only. Fixtures in `eval/fixtures/` are not committed.
If theme names are missing in a plain shell, `export OMARCHY_PATH=$HOME/omarchy` (the justfile sets it).

### Reading `omi-ai ask` output

```
omarchy toggle bar on  (92%)
  route=omarchy toggle bar scores={"route_p":0.99,"actionable":0.96,"covered":0.95,"timing":0.07,"detail":0.17} tokens=2665 cached=false jev=80ms
```

- `(92%)`: confidence, the weakest of the command pick and its arguments.
- `route_p`: probability for the picked command against the other 7 candidates.
- `actionable`: an action or status question? Below 0.5 → treated as a question.
- `covered`: would the command do what you asked? Below 0.5 → "no single command does that".
- `timing`: a delay or schedule? 0.5+ → refused (reminders exempt).
- `detail`: names something the command can't take? 0.8+ → refused.
- Destructive commands also need `actionable` and `covered` ≥ 0.7.
- `tokens`: input tokens (~2.5k ≈ $0.0001; output is free). `cached`: answered from `~/.cache/omi-ai/jev`, free.
- `jev`: daemon time for retrieval + the Jev call. `omi-ask` also prints `total` (full round trip).

### Logs and usage

- Every request and outcome: `~/.local/state/omi-ai/log.jsonl` (`omi-ai review` reads it)
- Daemon: `just logs`
- Account usage and limits: https://console.typesafe.ai

See [NOTES.md](NOTES.md) for design and eval results.

By [Taha Nejad](https://taha.gg).
