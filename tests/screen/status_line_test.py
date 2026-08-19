#!/usr/bin/env python3
"""
Check the status line: what it says, and what it gives up when it cannot fit.

    python3 tests/screen/status_line_test.py

This had no test at all while it lived on the app, because reaching it meant
building a camera, a display and a config. As a function of its arguments the
interesting part is directly reachable, and the interesting part is the
trimming: a line that ends mid-word is a bug nobody notices until the window is
narrow, and by then it looks like a rendering fault rather than a formatting
one.

No curses, no display, no camera.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from control.render_config import RenderConfig                # noqa: E402
from screen.status_line import HINTS, readouts, status_line   # noqa: E402

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}" + (f"  ({detail})" if detail else ""))


CONFIG = RenderConfig()
WIDE = 200


def test_every_setting_reads_out():
    print("\n1. Every toggle's state is on the line")
    line = status_line(CONFIG, "15.0fps", "267x100", width=WIDE)
    for fragment in ("15.0fps", "267x100", "rot0", "con1.0", "sch:grey",
                     "chr:coarse", "auto:on", "fill:off", "inv:off",
                     "tgt:both"):
        check(f"{fragment!r} is shown", fragment in line, line)

    print("\n2. ...and follows the config rather than a copy of it")
    changed = CONFIG.with_changes(
        {"rotation": 180, "contrast": 2.4, "scheme": "amber", "ramp": "fine",
         "auto_levels": False, "fill": True, "invert": True,
         "target": "lcd"})
    line = status_line(changed, "15.0fps", "267x100", width=WIDE)
    for fragment in ("rot180", "con2.4", "sch:amber", "chr:fine", "auto:off",
                     "fill:on", "inv:on", "tgt:lcd"):
        check(f"{fragment!r} is shown", fragment in line, line)


def test_the_panel_appears_only_when_there_is_one():
    print("\n3. The panel's own grid shows when a panel is running")
    with_panel = status_line(CONFIG, "15.0fps", "267x100",
                             lcd_grid=(64, 24), width=WIDE)
    check("the panel grid and font size are shown",
          "lcd:64x24@8" in with_panel, with_panel)
    check("...and it is the panel's grid, not the terminal's",
          "267x100" in with_panel and "lcd:64x24" in with_panel)

    without = status_line(CONFIG, "15.0fps", "267x100", width=WIDE)
    check("no panel means no lcd section", "lcd:" not in without, without)


def test_it_gives_up_sections_not_characters():
    print("\n4. A narrowing window drops whole hint groups")
    stats = readouts(CONFIG, "15.0fps", "267x100")
    seen = []
    overflowed = []
    for width in range(200, 20, -1):
        line = status_line(CONFIG, "15.0fps", "267x100", width=width)
        if len(line) > width:
            overflowed.append(width)
        # Only the widths that can still hold the readouts have hints to choose
        # between; below that there is nothing left but the cut.
        if width >= len(stats) and (not seen or line != seen[-1]):
            seen.append(line)
    check("never overflows the width it was given, at any width",
          overflowed == [], f"overflowed at {overflowed[:5]}")

    tails = [line.split(" | ", 1)[1] if " | " in line else "" for line in seen]
    check("the hints step through the declared forms, in order",
          tails == [h.replace(" | ", "", 1) for h in HINTS[:len(tails)]],
          str(tails))
    check("more than one form is actually used", len(tails) > 2, str(len(tails)))

    print("\n5. The readouts are never sacrificed")
    stats = readouts(CONFIG, "15.0fps", "267x100")
    narrow = status_line(CONFIG, "15.0fps", "267x100", width=len(stats))
    check("at exactly their own width the readouts survive whole",
          narrow == stats, narrow)
    check("...and no hints are attached", " | " not in narrow, narrow)


def test_a_notice_takes_the_hints_place():
    print("\n6. Something to say beats the key list")
    line = status_line(CONFIG, "15.0fps", "267x100",
                       notice="rotation must be one of 0, 90, 180, 270",
                       width=WIDE)
    check("the notice is shown", "rotation must be one of" in line, line)
    check("...instead of the hints", "q:quit" not in line, line)

    print("\n7. A notice is cut to the width, since there is nothing to drop")
    # The one place truncation is right: a message is not made of sections, and
    # half a sentence still says more than none of it.
    narrow = status_line(CONFIG, "15.0fps", "267x100",
                         notice="a" * 200, width=90)
    check("it fits", len(narrow) <= 90, str(len(narrow)))


def test_frozen_and_headless_read_as_words():
    print("\n8. The two states that are not numbers")
    frozen = status_line(CONFIG.with_changes({"freeze": True}), "frozen",
                         "267x100", width=WIDE)
    check("a frozen picture says so where the rate goes",
          " frozen 267x100" in frozen, frozen)
    headless = status_line(CONFIG, "15.0fps", "headless", width=WIDE)
    check("no window says headless where the grid goes",
          "15.0fps headless" in headless, headless)


def main():
    print("=" * 68)
    print("The status line: what it says, and what it drops")
    print("=" * 68)
    test_every_setting_reads_out()
    test_the_panel_appears_only_when_there_is_one()
    test_it_gives_up_sections_not_characters()
    test_a_notice_takes_the_hints_place()
    test_frozen_and_headless_read_as_words()

    print("\n" + "=" * 68)
    if failures:
        print(f"{len(failures)} FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
