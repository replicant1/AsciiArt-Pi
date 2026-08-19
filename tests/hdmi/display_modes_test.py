#!/usr/bin/env python3
"""
Check the four ways the app can be started, with no camera and no panel.

    python3 tests/hdmi/display_modes_test.py

The app can run with the terminal, with the SPI panel, with both, or - the one
combination that is refused - with neither. The refusal matters as much as the
others: without it the app would open the camera, render frames and show them
to nobody, which looks exactly like a hang.

The conformance check is the one with a long shelf life. HeadlessDisplay stands
in for NcursesDisplay, so anything the render loop calls on one must exist on
the other; comparing their public surfaces catches the drift the day it is
introduced rather than the next time somebody runs headless.
"""

import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from art import palettes                              # noqa: E402
import ascii_camera                          # noqa: E402
from hdmi.display import NcursesDisplay           # noqa: E402
from hdmi.headless import HeadlessDisplay         # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def public_surface(cls):
    """Attribute names a caller could reasonably use."""
    return {name for name in dir(cls) if not name.startswith("_")}


def test_conformance():
    print("\n1. HeadlessDisplay can stand in for NcursesDisplay")
    missing = public_surface(NcursesDisplay) - public_surface(HeadlessDisplay)
    check("headless implements everything the terminal display offers",
          not missing, f"missing {sorted(missing)}" if missing else "")

    check("the terminal display draws", NcursesDisplay.draws is True)
    check("the headless one does not", HeadlessDisplay.draws is False)

    # Everything the render loop actually reaches for, gathered by reading
    # ascii_camera.py rather than from memory, so a new call site shows up
    # here rather than as an AttributeError mid-run. Checked against an
    # instance, not the class: several of these are set in __init__.
    source = (ROOT / "ascii_camera.py").read_text()
    used = sorted(set(re.findall(r"self\.display\.([A-Za-z_][A-Za-z_0-9]*)",
                                 source)))
    probe = HeadlessDisplay(stream=io.StringIO())
    try:
        check("at least a few call sites were found", len(used) >= 8,
              f"found {used}")
        for name in used:
            check(f"headless provides {name!r}", hasattr(probe, name))
    finally:
        probe.close()


def test_argument_combinations():
    print("\n2. The four start-up combinations")

    both = ascii_camera.parse_args(["--lcd"])
    check("terminal + panel is accepted",
          both.lcd and not both.no_terminal)

    terminal_only = ascii_camera.parse_args([])
    check("terminal alone is the default",
          not terminal_only.lcd and not terminal_only.no_terminal)

    panel_only = ascii_camera.parse_args(["--lcd", "--no-terminal"])
    check("panel alone is accepted",
          panel_only.lcd and panel_only.no_terminal)

    # Neither: must be refused, and must say so on stdout rather than in a log
    # file the user has no reason to look at yet.
    captured, sys.stdout = sys.stdout, io.StringIO()
    try:
        code = ascii_camera.main(["--no-terminal"])
        printed = sys.stdout.getvalue()
    finally:
        sys.stdout = captured

    check("neither output is refused", code == 2, f"exit code {code}")
    check("the refusal names both flags",
          "--no-terminal" in printed and "--lcd" in printed,
          repr(printed.strip()[:70]))
    check("the refusal happens before the camera is opened",
          "Traceback" not in printed)


def test_headless_behaviour():
    print("\n3. HeadlessDisplay behaviour")
    stream = io.StringIO()
    display = HeadlessDisplay(status_interval=0, stream=stream)

    display.set_scheme(palettes.by_name("amber"))
    check("it carries the scheme", display.scheme.name == "amber")
    check("it reports colour as usable, so schemes are not skipped",
          display.colour_ok is True)
    check("nothing can resize it", display.refresh_size() is False)
    check("it offers no cell metrics", display.cell_metrics() is None)

    display.render((), "15.0fps headless sch:amber", None)
    check("the status line reaches the stream",
          "sch:amber" in stream.getvalue(), repr(stream.getvalue().strip()))

    display.message("Starting camera, please wait...")
    display.message("Starting camera, please wait...")
    check("a repeated message is only printed once",
          stream.getvalue().count("Starting camera") == 1)

    # stdin here is not a terminal, so keys must be off rather than blocking.
    check("no keyboard when stdin is not a terminal",
          display.get_key() is None)

    display.close()
    check("closing twice is safe", display.close() is None)


def test_no_output_is_refused_at_runtime():
    print("\n4. Headless with a panel that fails to start")

    args = ascii_camera.parse_args(["--lcd", "--no-terminal"])

    # Forced rather than assumed absent. This Pi really does have a panel, and
    # letting the test build a live one leaves an LCD worker thread and the
    # GPIO pins open behind a half-constructed app - which segfaults the
    # interpreter on the way out. Patching the one method keeps the check
    # about the refusal and nothing else, and makes it run anywhere.
    original = ascii_camera.MainRenderLooper._start_lcd
    ascii_camera.MainRenderLooper._start_lcd = lambda self: None

    display = HeadlessDisplay(status_interval=0, stream=io.StringIO())
    try:
        ascii_camera.MainRenderLooper(display, args)
        check("a headless run with no panel is refused", False,
              "it started anyway")
    except RuntimeError as e:
        check("a headless run with no panel is refused", True)
        check("the error says where to look", ".log" in str(e), str(e)[:70])
    except Exception as e:
        check("a headless run with no panel is refused", False,
              f"raised {type(e).__name__}: {e}")
    finally:
        ascii_camera.MainRenderLooper._start_lcd = original
        display.close()


def main():
    print("=" * 64)
    print("Display combinations")
    print("=" * 64)

    test_conformance()
    test_argument_combinations()
    test_headless_behaviour()
    test_no_output_is_refused_at_runtime()

    print("\n" + "=" * 64)
    if failures:
        print(f"RESULT: {len(failures)} CHECK(S) FAILED")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("RESULT: all four start-up combinations behave as intended.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
