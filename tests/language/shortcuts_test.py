#!/usr/bin/env python3
"""
Tests for src/language/shortcuts.py.

    python3 tests/language/shortcuts_test.py

No network, no key, no money: the point of the table is that none of those are
involved, and the test is the same.

Sections 5 and 6 are the ones worth having. A lookup table competing with a
language model is only safe if two things hold, and neither is obvious by
inspection:

  * It must never claim a phrase that should be **declined**. Failing to match
    is not the same as declining, and a table that answered "asdfgh" would be
    confidently wrong with no round trip to blame it on. Section 5 puts every
    decline case from tests/language/eval_cases.json through the table and requires a
    miss.
  * Where the table and the model answer the same phrase, they must **agree**.
    Section 6 scores the table's own deltas with tests/language/parser_eval.py's scorer,
    against the same expectations the model is held to - bands and all. If the
    table drifts from the prompt, this fails here rather than as somebody
    noticing the camera behaves differently depending on which phrasing they
    used.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "language"))

from language import shortcuts                                    # noqa: E402
from control.render_config import BY_NAME, RenderConfig     # noqa: E402

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
    print(f"\n{title}\n{'-' * len(title)}")


BASE = RenderConfig()


def look(utterance, config=BASE, previous=None):
    return shortcuts.look_up(utterance, config, previous)


# --- 1. normalising, and how far it goes ------------------------------------
section("1. normalising, and how far it goes")

check("case does not matter", shortcuts.normalise("MAKE It Green"),
      "make it green")
check("nor does spacing", shortcuts.normalise("  make   it  green "),
      "make it green")
check("nor trailing punctuation", shortcuts.normalise("make it green!!"),
      "make it green")
check("manners are stripped", shortcuts.normalise("please make it green"),
      "make it green")
check("at either end", shortcuts.normalise("could you make it green please"),
      "make it green")
# The shallowness is deliberate: two different requests must never normalise to
# one string, because the table would then answer confidently and never ask.
check("but 'a bit' survives, since it is a different request",
      shortcuts.normalise("a bit more contrast"), "a bit more contrast")
check("and is a different entry from the plain form",
      look("a bit more contrast") == look("way more contrast"), False)

# --- 2. a setting's own value, said out loud --------------------------------
section("2. a setting's own value, said out loud")

for scheme in BY_NAME["scheme"].choices:
    check(f"the bare word {scheme!r}", look(scheme), {"scheme": scheme})
check("every scheme is reachable by name",
      [s for s in BY_NAME["scheme"].choices if look(f"make it {s}") is None], [])
check("every ramp too",
      [r for r in BY_NAME["ramp"].choices if look(f"{r} characters") is None], [])
check("'live colour', which is how it was really asked for",
      look("live colour"), {"scheme": "live"})
check("and the American spelling", look("live color"), {"scheme": "live"})

# A scheme added to palettes.py must become speakable with no edit here.
check("the table is generated, not typed out",
      len([p for p in shortcuts.TABLE if p in BY_NAME["scheme"].choices]),
      len(BY_NAME["scheme"].choices))

# The two settings get their own phrasings. One shared template produced a
# cross product where "fine colour" set the *ramp* - a phrase about colour,
# answered confidently with something else. Certain or nothing.
check("a colour phrasing does not reach the ramp",
      [look(f"{r} colour") for r in BY_NAME["ramp"].choices],
      [None] * len(BY_NAME["ramp"].choices))
check("nor the American spelling",
      [look(f"{r} color") for r in BY_NAME["ramp"].choices],
      [None] * len(BY_NAME["ramp"].choices))
check("and a scheme is not a ramp phrasing",
      [look(f"{s} ramp") for s in BY_NAME["scheme"].choices],
      [None] * len(BY_NAME["scheme"].choices))
# "X characters" is the one form both may claim, and it means the right thing
# either way: green characters are drawn in green, fine characters are finer.
check("both may claim 'characters', and each means its own setting",
      (look("green characters"), look("fine characters")),
      ({"scheme": "green"}, {"ramp": "fine"}))
check("every phrase resolves to exactly one setting",
      [p for p, r in shortcuts.TABLE.items()
       if (d := r(BASE, BASE.with_changes({"scheme": "amber"}))) and len(d) > 1
       and p not in ("undo that", "undo", "undo it", "put that back")], [])

# --- 3. booleans, said as verbs ---------------------------------------------
section("3. booleans, said as verbs")

check("freeze it", look("freeze it"), {"freeze": True})
check("unfreeze it", look("unfreeze it"), {"freeze": False})
check("invert it", look("invert it"), {"invert": True})
check("uninvert it", look("uninvert it"), {"invert": False})
check("flip it left to right", look("flip it left to right"), {"mirror": True})

# --- 4. steps along a range -------------------------------------------------
section("4. steps along a range")

check("more contrast goes up", look("more contrast"), {"contrast": 1.3})
check("less contrast goes down", look("less contrast"), {"contrast": 0.77})
check("a step is taken from where it is now, not from the default",
      look("more contrast", BASE.with_changes({"contrast": 2.0})),
      {"contrast": 2.6})
check("and stops at the top rather than being refused",
      look("more contrast", BASE.with_changes({"contrast": 4.0})),
      {"contrast": 4.0})
check("and at the bottom", look("less contrast",
                                BASE.with_changes({"contrast": 0.1})),
      {"contrast": 0.1})
check("bigger characters", look("bigger characters"), {"lcd_font_size": 9})
check("smaller characters", look("smaller characters"), {"lcd_font_size": 7})
check("font size stops at its ceiling",
      look("bigger characters", BASE.with_changes({"lcd_font_size": 16})),
      {"lcd_font_size": 16})

# --- 5. what it must not answer ---------------------------------------------
section("5. what it must not answer")

with open(ROOT / "tests" / "language" / "eval_cases.json") as handle:
    cases = json.load(handle)["cases"]
declines = [c for c in cases if c.get("expect") == "decline"]
check("there are decline cases to check against", len(declines) > 0, True)
claimed = [c["utterance"] for c in declines if look(c["utterance"]) is not None]
check("the table claims none of the eval's decline cases", claimed, [])

check("a mood is not a lookup", look("something calmer"), None)
check("nor is a compound request",
      look("green, high contrast, and the fine ramp"), None)
check("nor a phrase it has never seen", look("make it sepia"), None)
check("nor an empty string", look(""), None)

# undo is arithmetic, and refuses when the arithmetic is not available
check("undo with no history falls through to the model",
      look("undo that", BASE, None), None)
check("undo with nothing changed falls through too",
      look("undo that", BASE, BASE), None)
moved = BASE.with_changes({"scheme": "amber", "ramp": "fine"})
check("undo restores exactly what moved",
      look("undo that", moved, BASE), {"scheme": "grey", "ramp": "coarse"})
check("and only what moved",
      look("undo that", BASE.with_changes({"contrast": 1.4}), BASE),
      {"contrast": 1.0})

# --- 6. where the table and the model overlap, they must agree --------------
section("6. where the table and the model overlap, they must agree")

from parser_eval import config_for, score_delta          # noqa: E402

overlap = 0
for case in cases:
    if case.get("expect") == "decline":
        continue
    now, before = config_for(case)
    delta = shortcuts.look_up(case["utterance"], now, before)
    if delta is None:
        continue                       # the model's job, not the table's
    overlap += 1
    hits, misses, spurious, notes = score_delta(case, delta, case["expect"])
    check(f"{case['id']}: the table answers it the way the eval wants",
          (misses, spurious, notes), (0, 0, []))

check("the two do overlap, so section 6 checked something", overlap > 0, True)
print(f"        ({overlap} of {len(cases)} eval cases are answered by the table)")

# --- 7. the guards that fire at import --------------------------------------
section("7. the guards that fire at import")

check("every phrase in the table is normalised already",
      [p for p in shortcuts.TABLE if shortcuts.normalise(p) != p], [])

# A delta the validator would refuse must not be reachable from a phrase.
refused = []
for phrase, resolve in shortcuts.TABLE.items():
    produced = resolve(BASE, None)
    if produced is None:
        continue
    try:
        BASE.with_changes(produced)
    except Exception as e:
        refused.append((phrase, str(e)))
check("and every delta it can produce survives RenderConfig", refused, [])

# and prove that guard can fail
try:
    broken = dict(shortcuts.TABLE)
    broken["nonsense"] = shortcuts._fixed({"scheme": "sepia"})
    saved, shortcuts.TABLE = shortcuts.TABLE, broken
    try:
        shortcuts._check_table_is_answerable()
        check("the import guard catches an impossible delta", "no error",
              "RuntimeError")
    except RuntimeError as e:
        check("the import guard catches an impossible delta",
              "sepia" in str(e), True)
finally:
    shortcuts.TABLE = saved

print(f"\n{'-' * 60}\n{PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
