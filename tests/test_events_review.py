import time

from omi_ai import events, paths, review


def test_log_and_read_roundtrip():
    events.log({"src": "flow", "q": "hi", "outcome": "ran"})
    [e] = list(events.read())
    assert e["q"] == "hi" and e["ts"] <= time.time()


def test_prune_drops_old_entries():
    paths.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    old, new = time.time() - 100 * 86400, time.time()
    paths.LOG_FILE.write_text(f'{{"ts": {old}, "x": 1}}\n{{"ts": {new}, "x": 2}}\nnot json\n')
    kept, removed = events.prune(90)
    assert (kept, removed) == (1, 2)
    assert [e["x"] for e in events.read()] == [2]


def test_review_buckets():
    for outcome, extra in [
        ("ran", {"confidence": 0.9, "route": "omarchy theme set"}),
        ("cancelled", {"route": "omarchy theme set", "command": "omarchy theme set nord"}),
        ("wrong", {"route": "omarchy toggle bar", "command": "omarchy toggle bar"}),
        ("escalate-picked-suggestion", {"kind": "uncovered", "command": "omarchy launch nautilus"}),
        ("escalate-cancelled", {"kind": "uncovered"}),
    ]:
        events.log({"src": "flow", "q": outcome, "outcome": outcome, **extra})
    events.log({"src": "daemon", "q": "x", "tokens": 2000, "cached": False})
    s = review.summarize(7)
    assert s["requests"] == 1 and s["tokens"] == 2000
    assert len(s["wrong"]) == len(s["cancelled"]) == len(s["overrode_refusal"]) == len(s["never_matched"]) == 1
    assert s["weak_routes"][0][0] == "omarchy toggle bar"  # wrong counts double
    text = review.render(s)
    assert "Marked wrong" in text and "“wrong” → omarchy toggle bar" in text


def test_review_empty():
    assert "Nothing to fix yet" in review.render(review.summarize(7))
