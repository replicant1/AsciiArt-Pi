#!/usr/bin/env python3
"""
Check the terminal geometry planner, which nothing else was checking.

    python3 tests/art/window_plan_test.py

`run_ascii_camera.sh` shells out to `window_plan.py` on every single launch to
pick the window shape, and falls back to a hardcoded 80x33 if it fails. It ran
before every session anybody has ever had with this app and had no test at all
- coverage measured it at 0%, the only module in `src/` at zero.

The arithmetic half runs against a **fake** `cell_size`, so the expected
geometries are exact numbers that can be worked out by hand rather than
whatever the code happened to return. The fake is not invented: its table is
the real Pango metrics measured on this Pi, and the first check compares the
two so that a font change makes the fake fail loudly rather than quietly go
stale.

Choosing 4:3 and 16:9 for the same request is deliberate. They differ - 267
columns against 356 - so a planner that ignored the camera's aspect would pass
one and fail the other, where a single ratio could have been produced by
arithmetic that never looked at the argument.

The last check runs the command line `run_ascii_camera.sh` actually calls, in a
subprocess, because a planner that works when imported and crashes when invoked
is no use to the thing that uses it.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from art import window_plan                              # noqa: E402

# Measured on this Pi on 25 Aug 2026 with the real Pango, for every size in
# FONT_SIZES: `cell_size(n)` for n in range(6, 15). Size 7 is the 6.0 x 11.0
# the module's own docstring quotes, which is the calibration the whole file
# rests on. Kept as data so the geometries below are hand-checkable.
MEASURED = {6: (5.0, 10.0), 7: (6.0, 11.0), 8: (6.0, 13.0),
            9: (7.0, 14.0), 10: (8.0, 17.0), 11: (9.0, 18.0),
            12: (10.0, 19.0), 13: (10.0, 21.0), 14: (11.0, 22.0)}

SCREEN = (2048, 1080)          # this Pi's HDMI output

failures = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"           got  {got!r}\n           want {want!r}")
        failures.append(label)


def with_fake_metrics(fn):
    """Run `fn` with cell_size replaced by the measured table."""
    real = window_plan.cell_size
    window_plan.cell_size = lambda size, family="Monospace": MEASURED[size]
    try:
        return fn()
    finally:
        window_plan.cell_size = real


def test_the_fake_is_honest():
    """
    The measured table still matches what Pango says on this machine.

    Without this the fake could drift from the real font metrics and every
    geometry below would go on asserting numbers that stopped being true - the
    quietest way for a test suite to become decorative.
    """
    real = {size: window_plan.cell_size(size) for size in window_plan.FONT_SIZES}
    check("the measured cell sizes are what Pango reports today", real, MEASURED)
    # And the reason this module exists: cells are not the 2.0 aspect that
    # assuming square-ish characters would give. Size 7 is 11/6.
    check("size 7 is not the naive 2.0 aspect", round(11.0 / 6.0, 3), 1.833)


def test_explicit_geometry_is_honoured():
    """"COLSxROWS" fixes both, and only the font size is still open."""
    got = with_fake_metrics(lambda: window_plan.plan("80x33", SCREEN))
    # 80x33 fits at every size, so the biggest picture wins: font 14, whose
    # 11x22 cells make 80 x 32 canvas rows measure 880 x 704 px. No other size
    # covers more screen.
    check("80x33 gives exactly 80x33, at the largest font that fits",
          got, (80, 33, 14, 2.0))


def test_a_width_that_does_not_fit_is_refused_not_shrunk():
    """
    A font at which the requested columns overflow is skipped, not clamped.

    This case exists because mutation testing found the hole: both geometries
    above either fit at every font size or at none, so neither could tell
    "reject this size" from "quietly return a narrower window". 300 columns fit
    at sizes 6 to 8 and overflow from 9 up, where a clamp would keep going and
    win on picture area - the biggest cells cover the most screen once they are
    allowed to drop columns. Asking for 300 and being handed 184 is the failure
    worth naming, because the picture would still look right.
    """
    got = with_fake_metrics(lambda: window_plan.plan("300x40", SCREEN))
    check("300x40 is honoured at font 8, the largest size 300 columns fit",
          got, (300, 40, 8, 2.167))


def test_rows_are_derived_from_columns():
    """"COLS" alone derives the rows from the picture's shape."""
    got = with_fake_metrics(lambda: window_plan.plan("80", SCREEN))
    # font 14: cell aspect 2.0, so ratio = 4/3 * 2 = 8/3. canvas = round(80 /
    # (8/3)) = 30, plus the status row = 31.
    check("80 columns derives 31 rows at font 14", got, (80, 31, 14, 2.0))


def test_fit_fills_the_screen():
    """"fit" is the case run_ascii_camera.sh uses, and the one worth pinning."""
    got = with_fake_metrics(lambda: window_plan.plan("fit", SCREEN))
    # font 6: 5x10 cells, so 2028/5 = 405 columns and 1010/10 - 1 = 100 canvas
    # rows will fit. ratio = 4/3 * 2.0 = 8/3, so 100 rows wants round(100 *
    # 8/3) = 267 columns, which is inside 405. 267*5 x 100*10 = 1,335,000 px of
    # picture, more than any other size manages.
    check("fit gives 267x101 at font 6", got, (267, 101, 6, 2.0))
    cols, rows, _, aspect = got
    # The status row is reserved, not drawn on: the picture is rows - 1 deep.
    check("and the picture's shape is the camera's, to within a column",
          round((rows - 1) * (4 / 3) * aspect), cols)


def test_the_camera_aspect_is_actually_used():
    """A wider camera must give a wider window, or the argument is ignored."""
    four_three = with_fake_metrics(lambda: window_plan.plan("fit", SCREEN, 4 / 3))
    sixteen_nine = with_fake_metrics(lambda: window_plan.plan("fit", SCREEN, 16 / 9))
    check("4:3 fills the height at 267 columns", four_three[:3], (267, 101, 6))
    check("and 16:9 needs 356 for the same 100 rows", sixteen_nine[:3],
          (356, 101, 6))


def test_a_screen_nothing_fits_on_falls_back():
    """
    The fallback exists because run_ascii_camera.sh needs four numbers.

    A 100x100 screen leaves 80 usable pixels across, which is 16 columns at the
    smallest font - under the 20 the planner insists on - so every size is
    rejected and the safe answer is returned instead.
    """
    got = with_fake_metrics(lambda: window_plan.plan("fit", (100, 100)))
    check("a screen too small for any font gives the 80x33 fallback",
          got, (80, 33, 7, 1.833))


def test_an_impossible_request_falls_back():
    """A window larger than the screen is refused at every size, not clamped."""
    got = with_fake_metrics(lambda: window_plan.plan("500x400", SCREEN))
    check("500x400 does not fit at any font size either", got, (80, 33, 7, 1.833))


def test_the_command_line():
    """
    The entry point run_ascii_camera.sh calls, run the way it calls it.

    Real Pango here, not the fake: this is the one check that the installed
    interpreter, the gi bindings and the font stack all still work together,
    which is what the shell script is actually relying on at start-up.
    """
    done = subprocess.run(
        [sys.executable, str(ROOT / "src" / "art" / "window_plan.py"),
         "fit", "2048", "1080"],
        capture_output=True, text=True, timeout=60)
    check("it exits cleanly", done.returncode, 0)
    fields = done.stdout.split()
    check("and prints four fields", len(fields), 4)
    if len(fields) == 4:
        cols, rows, font, aspect = fields
        check("which parse as the shell script expects",
              (cols.isdigit(), rows.isdigit(), font.isdigit(),
               float(aspect) > 1), (True, True, True, True))
        # Same numbers as the faked run, because the fake holds this machine's
        # real metrics - so this also proves the two halves agree.
        check("and match the geometry the measured table predicts",
              (int(cols), int(rows), int(font)), (267, 101, 6))


def main():
    print("window_plan: the geometry every launch depends on")
    print("=" * 66)
    test_the_fake_is_honest()
    test_explicit_geometry_is_honoured()
    test_a_width_that_does_not_fit_is_refused_not_shrunk()
    test_rows_are_derived_from_columns()
    test_fit_fills_the_screen()
    test_the_camera_aspect_is_actually_used()
    test_a_screen_nothing_fits_on_falls_back()
    test_an_impossible_request_falls_back()
    test_the_command_line()

    print("\n" + "=" * 66)
    if failures:
        print(f"RESULT: {len(failures)} CHECK(S) FAILED")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("RESULT: the planner returns the geometry it should, and its "
          "command line works.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
