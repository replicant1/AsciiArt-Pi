#!/usr/bin/env python3
"""
Tests for src/asklog.py.

    python3 tests/asklog_test.py

No network and no key: the parser is never called here. What is under test is
the record keeping, and the thing worth being sure of is that a record can
still be read - and still means the same - months after it was written.

Section 9 is the one that matters most. It takes a logged ask, converts it with
as_case, and feeds the result to tests/parser_eval.py's own config_for and
score_delta. If the log's shape ever drifts from the case file's, that fails
here rather than being discovered by somebody hand-editing four hundred lines
of JSON.
"""

import json
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import asklog                                      # noqa: E402
from render_config import SPECS, RenderConfig      # noqa: E402

PASSED = FAILED = 0


def check(name, got, want):
    global PASSED, FAILED
    if got == want:
        PASSED += 1
        print(f"  ok    {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name}\n          got  {got!r}\n          want {want!r}")


def section(title):
    print(f"\n{title}")


def temp_log(**kw):
    path = Path(tempfile.mkdtemp()) / "sub" / "asks.jsonl"
    return asklog.AskLog(path, **kw), path


# --- 1. a record goes out and comes back ------------------------------------
section("1. round trip")
log, path = temp_log()
cfg = RenderConfig()
log.record("make it green", cfg, delta={"scheme": "green"}, seconds=4.12,
           usage={"input": 100, "output": 20})
back = asklog.load(path)
check("one record", len(back), 1)
check("utterance kept", back[0]["utterance"], "make it green")
check("delta kept", back[0]["delta"], {"scheme": "green"})
check("outcome", back[0]["outcome"], "answered")
check("seconds rounded", back[0]["seconds"], 4.12)
check("parent directory created", path.parent.is_dir(), True)
check("timestamp looks like a timestamp",
      len(back[0]["when"]) == 20 and back[0]["when"].endswith("Z"), True)

# --- 2. now and before are sparse, in eval_cases.json's shape ---------------
section("2. now/before are sparse deltas from the defaults")
log, path = temp_log()
now = RenderConfig().with_changes({"scheme": "amber", "contrast": 2.5})
before = RenderConfig().with_changes({"scheme": "grey"})
log.record("undo that", now, previous=before, delta={"scheme": "grey"})
rec = asklog.load(path)[0]
check("now holds only what differs", rec["now"],
      {"scheme": "amber", "contrast": 2.5})
check("before omitted when it equals the defaults",
      "before" in rec, False)

log, path = temp_log()
log.record("undo that", now, previous=RenderConfig().with_changes({"ramp": "fine"}))
rec = asklog.load(path)[0]
check("before recorded when it differs", rec["before"], {"ramp": "fine"})

log, path = temp_log()
log.record("hello", RenderConfig())
check("defaults give an empty now", asklog.load(path)[0]["now"], {})

# --- 3. outcomes use the eval's vocabulary ----------------------------------
section("3. outcome classification")
log, path = temp_log()
log.record("make it green", cfg, delta={"scheme": "green"})
log.record("make me a sandwich", cfg, declined="I only change settings.")
log.record("make it green", cfg, error="connection refused")
check("outcomes", [r["outcome"] for r in asklog.load(path)],
      ["answered", "declined", "error"])
check("error beats a delta if both somehow arrive",
      asklog.AskLog(temp_log()[1]).record(
          "x", cfg, delta={"scheme": "green"}, error="boom")["outcome"],
      "error")

# --- 4. empty keys are left out, so the file reads by eye -------------------
section("4. absent keys")
log, path = temp_log()
log.record("make it green", cfg, delta={"scheme": "green"})
rec = asklog.load(path)[0]
for key in ("unmet", "declined", "error", "before"):
    check(f"no {key} key", key in rec, False)
# `source` is here and the others are not, on purpose: an absent key means
# "nothing to say", but an absent source would mean "answered by something, we
# forgot to note what".
check("keys present", sorted(rec),
      ["delta", "now", "outcome", "source", "utterance", "when"])

# --- 5. a broken log must not break an ask ----------------------------------
section("5. failure is swallowed")
blocked = Path(tempfile.mkdtemp()) / "asks.jsonl"
blocked.mkdir()                       # a directory where the file should be
log = asklog.AskLog(blocked)
result = log.record("make it green", cfg, delta={"scheme": "green"})
check("returns None rather than raising", result, None)
check("counted as failed", log.failed, 1)
check("nothing counted as written", log.written, 0)

# --- 6. two clients can ask at once -----------------------------------------
section("6. concurrent writers")
log, path = temp_log()
threads = [threading.Thread(target=lambda i=i: log.record(
    f"utterance {i}", cfg, delta={"contrast": 1.0 + i / 100})) for i in range(24)]
for t in threads:
    t.start()
for t in threads:
    t.join()
lines = path.read_text().splitlines()
check("every write landed", len(lines), 24)
check("every line is valid JSON on its own",
      all(json.loads(line) for line in lines), True)
check("no interleaving", len({json.loads(l)["utterance"] for l in lines}), 24)

# --- 7. rotation ------------------------------------------------------------
section("7. rotation keeps one old file")
log, path = temp_log(max_bytes=400)
for i in range(20):
    log.record(f"utterance number {i}", cfg, delta={"scheme": "green"})
check("current file exists", path.exists(), True)
check("one old file kept", path.with_suffix(".jsonl.1").exists(), True)
check("current file is below the limit having just rotated",
      path.stat().st_size < 2000, True)
check("the oldest records are the ones dropped, not the newest",
      "utterance number 19" in path.read_text(), True)

# --- 8. a corrupt line does not lose the file -------------------------------
section("8. tolerant reading")
log, path = temp_log()
log.record("first", cfg, delta={"scheme": "green"})
with open(path, "a") as h:
    h.write('{"truncated": tru\n')          # power cut mid-write
log.record("third", cfg, delta={"scheme": "amber"})
back = asklog.load(path)
check("the good records survive", [r["utterance"] for r in back],
      ["first", "third"])
check("a missing file reads as empty", asklog.load(path.parent / "nope"), [])

# --- 9. a logged ask is a case the eval can actually run --------------------
section("9. log -> eval case, checked against the eval's own code")
import parser_eval                                     # noqa: E402

log, path = temp_log()
log.record("make it warmer", now, previous=before,
           delta={"scheme": "amber"}, seconds=3.0)
case = asklog.as_case(asklog.load(path)[0], case_id="logged-warmer")
check("id carried", case["id"], "logged-warmer")
check("expect is what the model said", case["expect"], {"scheme": "amber"})
check("now carried", case["now"], {"scheme": "amber", "contrast": 2.5})
check("flagged as needing a human", "CANDIDATE" in case["note"], True)

# the real check: the eval's own machinery accepts it
resolved_now, resolved_before = parser_eval.config_for(case)
check("parser_eval.config_for rebuilds the config", resolved_now.scheme, "amber")
check("...and its contrast", resolved_now.contrast, 2.5)
hits, misses, spurious, _ = parser_eval.score_delta(
    case, {"scheme": "amber"}, case["expect"])
check("a matching delta scores clean", (hits, misses, spurious), (1, 0, 0))
hits, misses, spurious, _ = parser_eval.score_delta(
    case, {"scheme": "cyan"}, case["expect"])
check("a wrong delta is caught", (hits, misses, spurious), (0, 1, 0))

log, path = temp_log()
log.record("make me a sandwich", cfg, declined="I only change settings.")
check("a declined ask becomes expect: decline",
      asklog.as_case(asklog.load(path)[0])["expect"], "decline")

# --- 10. a new setting reaches the log without anyone remembering -----------
section("10. the SPECS guard is real")
check("all SPECS fields are recorded",
      set(asklog._sparse(RenderConfig().with_changes(
          {s.name: asklog._other_value(s) for s in SPECS}))),
      {s.name for s in SPECS})

# and prove that guard can fail: drop a field and it must complain
real_sparse = asklog._sparse
try:
    asklog._sparse = lambda c: (None if c is None else
                                {k: v for k, v in real_sparse(c).items()
                                 if k != "scheme"})
    try:
        asklog._check_sparse_covers_specs()
        check("guard catches a dropped field", "no error", "RuntimeError")
    except RuntimeError as e:
        check("guard catches a dropped field", "scheme" in str(e), True)
finally:
    asklog._sparse = real_sparse

# --- 11. who answered ------------------------------------------------------
section("11. who answered")

log, path = temp_log()
log.record("make it green", cfg, delta={"scheme": "green"})
log.record("green", cfg, delta={"scheme": "green"}, source="table")
rows = asklog.load(path)
check("a parse is recorded as the model's answer", rows[0]["source"], "model")
check("a table hit says so", rows[1]["source"], "table")
# Always written, including on the default: a record with the key missing is
# ambiguous rather than obviously a model answer, and this file is read months
# later.
check("neither record leaves it out",
      [("source" in r) for r in rows], [True, True])
# The distinction has to survive the round trip, because it decides what a
# record is evidence of - a table hit says nothing about the prompt.
check("and it survives being read back",
      {r["utterance"]: r["source"] for r in rows},
      {"make it green": "model", "green": "table"})

print(f"\n{'-' * 60}\n{PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
