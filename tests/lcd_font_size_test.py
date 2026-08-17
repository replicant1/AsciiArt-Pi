#!/usr/bin/env python3
"""
Check that changing the panel's font size live re-fits its grid.

    python3 tests/lcd_font_size_test.py

Needs the real ILI9341: LcdDisplay drives it directly, so stop the
ascii-camera service first or the panel is already claimed.

Two things are being checked, and only the first can be checked here:

  * the geometry - grid, picture size and offset - is recomputed for the new
    font, and the persistent frame buffer is zeroed so that a picture which no
    longer reaches the margin cannot leave the old one's pixels stranded there.
    Nothing ever writes to that margin again, so anything left is left for good.
  * that the panel actually shows it. Nothing in this process can read the
    glass back, so it prints what should be on it and leaves that to a human.
"""

import pathlib
import sys
import time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ascii_art import AsciiArt          # noqa: E402
from lcd_display import LcdDisplay      # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        failures.append(label)


art = AsciiArt(ramp="coarse")
lcd = LcdDisplay(ramp=art.chars, font_size=8)

try:
    # Fill the panel at a font that tiles exactly, so every pixel is written.
    print("\n1. Font 8, which tiles 320x240 exactly")
    cols, rows = lcd.grid_size
    check("64x24 grid", (cols, rows) == (64, 24), f"{cols}x{rows}")
    bright = np.full((rows, cols), len(art.chars) - 1, dtype=np.uint16)
    lcd.render(bright, np.full((rows, cols, 3), 255, np.uint8), (0, 0, 0))
    check("the picture covers the whole panel",
          lcd._region.shape[:2] == (240, 320), str(lcd._region.shape))
    lit_before = int((lcd._frame != 0).sum())
    check("and the frame buffer is not blank", lit_before > 0, str(lit_before))
    time.sleep(2)

    # 10 does NOT tile: cell 6x19 -> 53x12 -> 318x228, leaving a 2x12 px margin.
    print("\n2. Font 10, which does not tile - this is the margin case")
    lcd.set_font_size(10)
    cols, rows = lcd.grid_size
    used_h, used_w = lcd._region.shape[:2]
    check("the grid shrank", (cols, rows) != (64, 24), f"{cols}x{rows}")
    check("and no longer covers the panel", used_w < 320 or used_h < 240,
          f"{used_w}x{used_h} of 320x240")

    # The margin must be black *before* anything new is drawn: that is what
    # zeroing the buffer on rebuild buys, and the only moment it is visible.
    outside = int((lcd._frame != 0).sum())
    check("every pixel is cleared by the rebuild, margin included",
          outside == 0, f"{outside} pixels still lit")

    lcd.render(np.full((rows, cols), len(art.chars) - 1, dtype=np.uint16),
               np.full((rows, cols, 3), 255, np.uint8), (0, 0, 0))
    margin = int((lcd._frame != 0).sum()) - int((lcd._region != 0).sum())
    check("and the margin stays black once the picture is drawn",
          margin == 0, f"{margin} lit pixels outside the picture")
    time.sleep(2)

    print("\n3. Back to 8, and on to 6 and 9 - the sizes the l key uses")
    for size, wanted in [(8, (64, 24)), (6, (80, 30)), (9, (64, 20))]:
        lcd.set_font_size(size)
        check(f"font {size} gives {wanted[0]}x{wanted[1]}",
              lcd.grid_size == wanted, str(lcd.grid_size))
        check(f"font {size} fills the panel exactly",
              lcd._region.shape[:2] == (240, 320), str(lcd._region.shape[:2]))
        cols, rows = lcd.grid_size
        lcd.render(np.full((rows, cols), len(art.chars) - 1, dtype=np.uint16),
                   np.full((rows, cols, 3), 255, np.uint8), (0, 0, 0))
        time.sleep(2)

    print("\n4. What should have been on the glass, in order:")
    print("   a solid white rectangle filling the panel, twice, then a")
    print("   slightly smaller one with a thin black margin down the right")
    print("   and along the bottom, then three more full-panel white ones.")
finally:
    lcd.close()

print("\n" + "=" * 62)
if failures:
    print(f"RESULT: {len(failures)} CHECK(S) FAILED")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("RESULT: the geometry is right. Whether the PANEL showed it is not")
print("        something this process can know - see CLAUDE.md.")
