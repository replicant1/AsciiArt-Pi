#!/usr/bin/env python3
"""
Does driving the LCD actually cost the main loop anything?

    python3 tests/panel/lcd_concurrency.py

The whole point of putting the panel on its own thread is that ~32 ms of every
LCD frame is SPI transfer, which the kernel is doing rather than Python.  That
only helps if spidev drops the GIL for the duration - if it holds it, the main
loop stalls for 32 ms per panel frame and the thread has bought nothing.

So: measure how much work the main thread gets through in a fixed wall-clock
window, first alone and then with the LCD being hammered in the background, and
compare.  The Zero 2 is quad-core, so a result near 100% means the transfer
really is overlapping; a result near 50% or worse would mean the GIL is held
and the design needs rethinking.
"""

import sys
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from art.ascii_art import AsciiArt          # noqa: E402
from panel.lcd_display import LcdDisplay      # noqa: E402

WINDOW = 4.0        # seconds per measurement


def main_thread_work(seconds):
    """
    Stand-in for the terminal render loop: count numpy passes in `seconds`.

    Deliberately numpy rather than pure Python - the real main loop is numpy
    heavy, and numpy also drops the GIL, so this measures the same kind of
    contention the app would really see.
    """
    block = np.random.randint(0, 255, (240, 320), dtype=np.uint8)
    passes = 0
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        block.astype(np.float32).sum()
        passes += 1
    return passes


def main():
    print("=" * 62)
    print("LCD / main-loop contention")
    print("=" * 62)

    art = AsciiArt(ramp="coarse")
    display = LcdDisplay(ramp=art.chars, font_size=8)
    cols, rows = display.grid_size

    x = np.linspace(0, 255, cols)
    y = np.linspace(0, 255, rows)
    grey = np.clip((x[None, :] + y[:, None]) / 2, 0, 255).astype(np.uint8)
    indices = art.to_indices(grey)

    print(f"\nBaseline: main thread alone for {WINDOW}s...")
    alone = main_thread_work(WINDOW)
    print(f"  {alone} passes")

    stop = threading.Event()
    frames = [0]

    def hammer():
        while not stop.is_set():
            display.render(indices, None)
            frames[0] += 1

    worker = threading.Thread(target=hammer, daemon=True)
    worker.start()
    time.sleep(0.3)                     # let it get going

    print(f"With the LCD rendering flat out for {WINDOW}s...")
    together = main_thread_work(WINDOW)
    stop.set()
    worker.join(timeout=5)
    print(f"  {together} passes, LCD managed {frames[0]} frames "
          f"({frames[0] / WINDOW:.1f} fps)")

    display.close()

    retained = 100.0 * together / alone if alone else 0.0
    print(f"\nMain thread retained {retained:.0f}% of its throughput.")

    print("=" * 62)
    if retained >= 75:
        print("RESULT: PASS - the SPI transfer overlaps with the main loop,")
        print("so the panel is close to free for the terminal display.")
        return 0
    if retained >= 50:
        print("RESULT: MARGINAL - some contention. Usable, but expect the")
        print("terminal frame rate to drop somewhat with --lcd.")
        return 0
    print("RESULT: FAIL - the LCD is serialising against the main loop.")
    print("The worker thread is not buying anything; the SPI write is")
    print("holding the GIL and would need a different approach.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
