# Omi AI dev commands. `just` lists them.

export OMARCHY_PATH := env("OMARCHY_PATH", env("HOME") / "omarchy")

default:
    @just --list

# Resolve a request and print the scores (never runs anything)
ask +query:
    uv run omi-ai ask "{{query}}"

# The full menu flow, from the repo
menu:
    uv run omi-ai ask --menu

# Unit tests
test *args:
    uv run pytest {{args}}

# Offline eval on a split (replays recorded answers: no API, no cost)
eval split="test":
    uv run omi-ai eval run --split {{split}} --offline

# Live eval against Jev (uses the disk cache; new requests cost tokens)
eval-live split="valid":
    uv run omi-ai eval run --split {{split}} --fails

# Threshold sweep on the valid split, offline
sweep:
    uv run omi-ai eval sweep --split valid --offline

# Retriever recall on a split
recall split="valid":
    uv run omi-ai eval recall --split {{split}} --fails

# Record answers for the offline eval (run after changing the spec or prompts)
snapshot:
    uv run omi-ai eval snapshot

# Lint
lint:
    uv run ruff check src tests
    uv run ruff format --check src tests

# Format
fmt:
    uv run ruff format src tests
    uv run ruff check --fix src tests

# Everything before a push: lint, tests, offline eval on both splits
check: lint test
    uv run omi-ai eval run --split valid --offline
    uv run omi-ai eval run --split test --offline

# Install the service and symlinks for this user
install:
    bin/omi-ai-install

# Restart the daemon (picks up code, spec and config changes)
restart:
    systemctl --user restart omi-ai.service

# Follow the daemon's journal
logs:
    journalctl --user -u omi-ai -f

doctor:
    uv run omi-ai doctor

review days="7":
    uv run omi-ai review --days {{days}}

# Spec vs the live Omarchy catalog
spec-check:
    uv run omi-ai spec check
