#!/usr/bin/env python3
"""
Check that the LCD worker adopts config changes, without a panel attached.

    python3 tests/lcd_worker_test.py

This is the wiring between the app's RenderConfig and the panel, and until now
nothing in software tested it. tests/lcd_font_size_test.py drives
LcdDisplay.set_font_size directly and needs the real ILI9341; what it does not
cover is the worker's *decision* to call it. So a config change that stopped
reaching the panel would have been caught only by running the hardware test, or
by someone looking at the glass.

That is the same gap that let the blank()/splash bug through: the app-side test
asserted a method was called on a stub, and nothing asserted the consequence.
Here the display is a fake, but it records what it was asked to do, and the
worker is the real one.
"""

import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lcd_worker import LcdWorker              # noqa: E402
from render_config import RenderConfig        # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


class RecordingDisplay:
    """A panel that draws nothing but remembers everything it was told."""

    panel_size = (320, 240)

    def __init__(self):
        # Font 8 on this panel, matching the real default.
        self.font_size = 8
        self.cols, self.rows = 64, 24
        self.cell_aspect = 2.0
        self.font_sizes = []        # every set_font_size argument, in order
        self.ramps = []             # every set_ramp argument, in order
        self.frames = 0
        self.clears = 0

    @property
    def grid_size(self):
        return self.cols, self.rows

    def set_font_size(self, font_size):
        # The real one re-rasterises the atlas and re-fits the grid. These
        # numbers are the measured ones from the hardware test, so a caller
        # reading grid_size or cell_aspect back gets something truthful.
        self.font_sizes.append(font_size)
        self.font_size = font_size
        self.cols, self.rows = {6: (80, 30), 8: (64, 24), 9: (64, 20)}.get(
            font_size, (64, 24))
        self.cell_aspect = 240 / self.rows / (320 / self.cols)

    def set_ramp(self, ramp):
        self.ramps.append(ramp)

    def render(self, indices, colours=None, screen=(0, 0, 0)):
        self.frames += 1
        self.last = (indices, colours, screen)

    def show_image(self, image):
        pass

    def clear(self):
        self.clears += 1

    def close(self):
        pass


class Frame:
    """Enough of a YuvFrame for the worker's greyscale path."""

    luma = np.zeros((48, 64), dtype=np.uint8)


def drive(worker, display, config, frames=4, gap=0.05):
    """Push frames until the worker has drawn at least one for this config."""
    before = display.frames
    for _ in range(frames):
        worker.submit(Frame(), config)
        time.sleep(gap)
    return display.frames - before


def test_font_size_reaches_the_panel():
    print("\n1. A font size change in the config reaches the panel")
    display = RecordingDisplay()
    worker = LcdWorker(display, splash_hold=0.0)
    worker.start()
    try:
        drive(worker, display, RenderConfig(lcd_font_size=8))
        check("starting at font 8 asks for no rebuild",
              display.font_sizes in ([], [8]), str(display.font_sizes))

        drive(worker, display, RenderConfig(lcd_font_size=9))
        check("changing to 9 tells the panel", 9 in display.font_sizes,
              str(display.font_sizes))
        check("...and the grid follows it", display.grid_size == (64, 20),
              str(display.grid_size))

        print("\n2. The processor is re-told the cell shape")
        # The worker's ImageProcessor is given a cell aspect once, at
        # construction. A font change moves the panel's cell shape, and a stale
        # aspect squashes the picture on the panel while leaving the terminal's
        # correct - which reads as a panel fault rather than a missed
        # assignment, and is not something a screenshot can catch.
        #
        # Checked at font 9 specifically, and not at 6 or 8. All three tile the
        # panel 4:3, but 8 and 6 both work out at exactly 2.0 - so an assertion
        # made after either of those would read 2.0 whether the worker had
        # updated the aspect or never touched it, and would pass on a broken
        # build. 9 gives 12/5 = 2.4, which only a real update produces.
        check("the cell aspect is the panel's, not the one it started with",
              abs(worker.processor.cell_aspect - 2.4) < 1e-6,
              f"{worker.processor.cell_aspect}, wanted 2.4")

        drive(worker, display, RenderConfig(lcd_font_size=6))
        check("changing to 6 tells the panel too", 6 in display.font_sizes,
              str(display.font_sizes))
        check("...and the grid follows again", display.grid_size == (80, 30),
              str(display.grid_size))
        check("...and the cell aspect comes back to 2.0",
              abs(worker.processor.cell_aspect - 2.0) < 1e-6,
              str(worker.processor.cell_aspect))

        print("\n3. An unchanged font size does not rebuild")
        seen = list(display.font_sizes)
        drive(worker, display, RenderConfig(lcd_font_size=6))
        check("re-sending the same size asks for nothing",
              display.font_sizes == seen, str(display.font_sizes))
    finally:
        worker.stop()


def test_ramp_reaches_the_panel():
    print("\n4. Ramp and invert reach the panel; contrast does not")
    display = RecordingDisplay()
    worker = LcdWorker(display, splash_hold=0.0)
    worker.start()
    try:
        drive(worker, display, RenderConfig())
        check("the ramp is set up front", len(display.ramps) >= 1,
              str(display.ramps))

        seen = len(display.ramps)
        drive(worker, display, RenderConfig(invert=True))
        check("inverting re-sends the ramp", len(display.ramps) > seen,
              str(display.ramps))
        check("...reversed", display.ramps[-1] == display.ramps[0][::-1],
              f"{display.ramps[0]!r} -> {display.ramps[-1]!r}")

        seen = len(display.ramps)
        drive(worker, display, RenderConfig(invert=True, contrast=2.5))
        check("a contrast change does not touch the ramp",
              len(display.ramps) == seen, str(display.ramps))
        check("...but does reach the processor",
              worker.processor.contrast == 2.5,
              str(worker.processor.contrast))
    finally:
        worker.stop()


def test_fill_and_target_are_ignored():
    print("\n5. fill and target are the two fields the panel must ignore")
    display = RecordingDisplay()
    worker = LcdWorker(display, splash_hold=0.0)
    worker.start()
    try:
        drive(worker, display, RenderConfig())
        # The panel always fills, whatever the terminal is doing. If the
        # worker ever adopted `fill` the picture would letterbox on the glass.
        check("the worker's processor fills regardless",
              worker.processor.fill is True)

        drive(worker, display, RenderConfig(fill=True))
        check("...still, after the config says otherwise",
              worker.processor.fill is True)

        # `target` is the main loop's business: it simply stops submitting.
        # Nothing here should react to it.
        before = display.frames
        drawn = drive(worker, display, RenderConfig(target="terminal"))
        check("a frame submitted with target=terminal is still drawn",
              drawn > 0, f"{display.frames - before} frames")
    finally:
        worker.stop()


def main():
    print("=" * 66)
    print("The LCD worker's adoption of config changes")
    print("=" * 66)

    test_font_size_reaches_the_panel()
    test_ramp_reaches_the_panel()
    test_fill_and_target_are_ignored()

    print("\n" + "=" * 66)
    if failures:
        print(f"RESULT: {len(failures)} CHECK(S) FAILED")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("RESULT: config changes reach the panel as they should.")
    print("        This is the wiring, not the glass - see")
    print("        tests/lcd_font_size_test.py for the hardware half.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
