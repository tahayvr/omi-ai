"""omi-ai spec check: how the hand-written spec lines up with the live Omarchy catalog."""

from __future__ import annotations

import json
import subprocess

from . import catalog
from .dispatch import load_spec


def report() -> dict:
    spec = load_spec()
    forms = catalog.forms()
    fillable = {r for r, f in forms.items() if f.fillable()}
    described = {r for r in spec["commands"] if r in fillable}
    stale = sorted(r for r in spec["commands"] if r not in forms)
    stale_args = []
    overrides = []
    for route, args in spec["args"].items():
        f = forms.get(route)
        if f is None:
            stale_args.append(route)
            continue
        names = {a.name: a for a in f.args}
        for name, s in args.items():
            if name not in names:
                stale_args.append(f"{route} {name}")
                continue
            a = names[name]
            extra = set(s.get("options", {})) - set(a.values)
            if extra and a.values:
                overrides.append(f"{route} {name}: adds {', '.join(sorted(extra))}")

    snapshot = {c["route"] for c in json.loads((catalog.DATA / "manifest-live.json").read_text())["commands"]}
    live = {c["route"] for c in catalog.load_manifest()}
    return {
        "fillable": len(fillable),
        "described": len(described),
        "undescribed": sorted(fillable - described),
        "stale_spec": stale,
        "stale_args": sorted(stale_args),
        "overrides": overrides,
        "added_since_snapshot": sorted(live - snapshot),
        "removed_since_snapshot": sorted(snapshot - live),
    }


def update_snapshot() -> int:
    out = subprocess.run(["omarchy", "commands", "--all", "--json"],
                         capture_output=True, text=True, timeout=10, check=True).stdout  # fmt: skip
    data = json.loads(out)
    (catalog.DATA / "manifest-live.json").write_text(json.dumps(data, indent=2) + "\n")
    return len(data["commands"])


def main(show_all: bool = False, update: bool = False) -> int:
    r = report()
    print(f"Commands Omi can fill: {r['fillable']}  (hand-described: {r['described']}, "
          f"CLI summary only: {len(r['undescribed'])})")  # fmt: skip

    def section(title: str, items: list[str], limit: int | None = 25) -> None:
        if not items:
            return
        print(f"\n{title} ({len(items)}):")
        for it in items if show_all or limit is None else items[:limit]:
            print(f"  {it}")
        if not show_all and limit is not None and len(items) > limit:
            print(f"  … {len(items) - limit} more (--all)")

    section("New in Omarchy since the manifest snapshot", r["added_since_snapshot"], None)
    section("Gone from Omarchy since the snapshot", r["removed_since_snapshot"], None)
    section("Spec entries for commands that no longer exist", r["stale_spec"], None)
    section("Spec argument entries that no longer match", r["stale_args"], None)
    section("Spec options beyond the CLI's listed values (intentional overrides)", r["overrides"], None)
    section("Commands using only the CLI summary", r["undescribed"])
    if update:
        n = update_snapshot()
        print(f"\nSnapshot updated: {n} commands.")
    problems = r["stale_spec"] or r["stale_args"]
    return 1 if problems else 0
