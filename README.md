# Omi AI

Type a request in plain English, get an `omarchy` command, confirm, run.

## Test

```bash
# Resolve only (prints the command, never runs it)
uv run omi-ai ask "make it louder"

# Through the daemon (what the launcher uses)
curl -s --get 127.0.0.1:8127/ask --data-urlencode "q=switch to tokyo night"

# Full flow: input menu -> confirm -> run
omi-ask
```

If theme names aren't recognised in a plain shell, set `export OMARCHY_PATH=$HOME/omarchy` first (systemd already has it).

Things to try: `hide the bar`, `screenshot of a window and copy it`, `night light on`, `keep the screen awake`, `bar on the left`, `performance mode`, `why is my wifi slow` (should refuse), `shut down in 30 minutes` (should refuse), `factory reset` (asks twice).

## When it can't find a command

`omi-ask` shows a menu titled with the reason, instead of just refusing:

- **Ask the agent: …** opens your default coding agent with your text (`omarchy agent prompt`). This row comes first for questions, problem reports and timed requests.
- **Run: …** shows up to 3 "did you mean" commands Jev already scored (`fits` ≥ 0.2), at no extra API cost. Picking one runs it, and destructive ones still ask twice. None are shown for timed requests ("shut down in 30 minutes").
- **Rephrase** reopens the input box.
- **Cancel** closes the menu.

Picks are logged as `escalate-agent`, `escalate-picked-suggestion`, `escalate-rephrased` or `escalate-cancelled`. To see which escalations users overrode:

```bash
jq -c 'select(.outcome | startswith("escalate")) | {q, outcome, command}' ~/.local/state/omi-ai/log.jsonl
```

## Reading the output

```
omarchy toggle bar on  (92%)
  route=omarchy toggle bar scores={"route_p":0.99,"actionable":0.96,"covered":0.95,"timing":0.07,"detail":0.17} tokens=2665 cached=false jev=80ms total=95ms
```

- `(92%)`: overall confidence, the weakest judgment behind the command (command pick, each argument, each "was it stated").
- `route`: the command Jev picked (also shown on escalate, so you can see what it considered).
- `route_p`: probability Jev gave that command against the other 7 candidates.
- `actionable`: is this an action or a status question? Below 0.3 → refused as a how-to, problem report or chat.
- `covered`: would the picked command actually do what you asked? Below 0.5 → "no single command does that".
- `timing`: did you ask for a delay, schedule or duration? 0.5 or above → refused (except reminders).
- `detail`: did you name something the command can't take (a package, place, number…)? 0.8 or above → refused.
- Destructive commands also need `actionable` and `covered` ≥ 0.7.
- `tokens`: input tokens for this request (output is free). ~2.5k tokens ≈ $0.0001.
- `cached`: answer came from the disk cache (`~/.cache/omi-ai/jev`), no API call or cost.
- `jev`: daemon time for retrieval + the Jev call. `total`: full round trip from `omi-ask`.

Thresholds live in `Thresholds` in `src/omi_ai/dispatch.py`.

## After changing code or spec

```bash
systemctl --user restart omi-ai.service   # daemon reloads spec/policy
OMARCHY_PATH=$HOME/omarchy uv run python -m omi_ai.evaluate run --split valid --fails
```

## Logs and API usage

- Every query: `~/.local/state/omi-ai/log.jsonl`
- Daemon errors: `journalctl --user -u omi-ai`
- Tokens and cost spent through the daemon:
  ```bash
  jq -s '[.[] | select(.cached == false) | .tokens] | add as $t | {tokens: $t, usd: ($t * 0.042 / 1e6)}' ~/.local/state/omi-ai/log.jsonl
  ```
- Account-wide usage and limits: https://console.typesafe.ai

See [NOTES.md](NOTES.md) for design and results.

By [Taha Nejad](https://taha.gg).
