#!/usr/bin/env python3
"""
Offline tests for src/parser.py - no network, no key, no money.

    python3 tests/parser_test.py

What the eval cannot test lives here. tests/parser_eval.py scores the model's
answers, which needs the API; this covers the parts of the module that are
ordinary code and can be checked properly: the schema generated from SPECS, and
the gate that keeps the first request in a process from racing the others.

That gate is the reason this file exists. A race that shows up once in 123
parses cannot be tested by running the real thing and hoping - three clean runs
of a 1-in-123 event happen 37% of the time by luck, which is exactly how it was
declared fixed once already when it was not. So the concurrency here is driven
by events rather than timing, and every assertion is about *ordering*, which is
deterministic.
"""

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import parser as nl                                  # noqa: E402
from render_config import SPECS                      # noqa: E402

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


def arm():
    """Put the gate back to how a fresh process finds it."""
    nl._first_call_done = False


# --- 1. the first caller runs alone -----------------------------------------
section("1. the first request is serialised")
arm()
inside_first = threading.Event()
let_first_go = threading.Event()
second_got_in = threading.Event()


def first():
    with nl._first_call_alone():
        inside_first.set()
        let_first_go.wait(5)


def second():
    with nl._first_call_alone():
        second_got_in.set()


t1 = threading.Thread(target=first)
t1.start()
check("the first caller is inside", inside_first.wait(5), True)

t2 = threading.Thread(target=second)
t2.start()
# The assertion is ordering, not duration: while the first is demonstrably
# still inside, the second must not have got in.
blocked = not second_got_in.wait(0.5)
check("a second caller is held out while the first is inside", blocked, True)

let_first_go.set()
t1.join(5)
check("the second caller gets in once the first is done",
      second_got_in.wait(5), True)
t2.join(5)
check("the gate closed behind them", nl._first_call_done, True)

# --- 2. and then gets out of the way ----------------------------------------
section("2. after one success the gate is a no-op")
overlapped = []
in_a, in_b = threading.Event(), threading.Event()


def concurrent(mine, theirs):
    with nl._first_call_alone():
        mine.set()
        overlapped.append(theirs.wait(2))


ta = threading.Thread(target=concurrent, args=(in_a, in_b))
tb = threading.Thread(target=concurrent, args=(in_b, in_a))
ta.start(), tb.start()
ta.join(5), tb.join(5)
check("two callers were inside at the same time", overlapped, [True, True])

# --- 3. a failed first call must not disarm it ------------------------------
section("3. failure leaves the gate armed")
arm()
try:
    with nl._first_call_alone():
        raise RuntimeError("network down")
except RuntimeError:
    pass
check("still armed after a failure", nl._first_call_done, False)

# the lock must have been released, or everything after this deadlocks
done = threading.Event()


def after_failure():
    with nl._first_call_alone():
        pass
    done.set()


t = threading.Thread(target=after_failure, daemon=True)
t.start()
check("the lock was released, so the next caller is not stuck",
      done.wait(5), True)
check("and a later success does close it", nl._first_call_done, True)

# --- 4. repeated failures keep re-arming ------------------------------------
section("4. a camera that starts with no network keeps the protection")
arm()
for _ in range(3):
    try:
        with nl._first_call_alone():
            raise OSError("no route to host")
    except OSError:
        pass
check("three failures in a row, still armed", nl._first_call_done, False)

# --- 5. the schema, which is generated and so can silently drift ------------
section("5. schema generated from SPECS")
tools = nl.tools()
check("two tools", [t["name"] for t in tools], ["set_render", "decline"])
props = tools[0]["input_schema"]["properties"]
check("every SPEC is a property", {s.name for s in SPECS} - set(props), set())
check("unmet is there too and is not a setting",
      "unmet" in props and "unmet" not in {s.name for s in SPECS}, True)
check("nothing can be invented",
      tools[0]["input_schema"]["additionalProperties"], False)
check("a delta is sparse, so nothing is required",
      "required" in tools[0]["input_schema"], False)
check("but a refusal must give a reason",
      tools[1]["input_schema"]["required"], ["reason"])

# the bool/int trap: in Python bool subclasses int, so a naive isinstance test
# renders invert as an integer and rotation's enum as booleans.
check("booleans are booleans", props["invert"]["type"], "boolean")
check("integer enums stay integers", props["rotation"]["type"], "integer")
check("rotation's choices survive", props["rotation"]["enum"], [0, 90, 180, 270])
check("_json_type puts bool before int", nl._json_type(True), "boolean")
check("...and still calls 1 an integer", nl._json_type(1), "integer")

# ranges carry their bounds twice: in the schema, and in words for the model
check("ranges have a minimum", props["contrast"]["minimum"], 0.1)
check("...and say so in the description",
      "From 0.1 to 4.0." in props["contrast"]["description"], True)

print(f"\n{'-' * 60}\n{PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
