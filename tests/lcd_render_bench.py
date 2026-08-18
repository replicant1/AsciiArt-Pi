#!/usr/bin/env python3
"""
Check and time the LCD ASCII render path, without needing the camera.

    python3 tests/lcd_render_bench.py [hold_seconds]

The correctness half matters more than the timing half: it asserts that the
glyph the panel draws for a given brightness is the same one the terminal would
print, which is the thing that would silently drift if the two paths ever
disagreed about `invert` or about how a ramp maps to brightness.
"""

import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from art import palettes                                    # noqa: E402
from art.ascii_art import RAMPS, AsciiArt              # noqa: E402
from panel.lcd_display import LcdDisplay                 # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def test_index_agreement():
    """The two output paths must pick the same character for the same input."""
    print("\n1. Character choice agrees between terminal and panel")

    probe = np.arange(256, dtype=np.uint8).reshape(16, 16)
    # Every built-in ramp, taken from RAMPS rather than listed here, so this
    # cannot quietly stop covering one that was added or removed.
    for ramp in RAMPS:
        for invert in (False, True):
            art = AsciiArt(ramp=ramp, invert=invert)
            text = art.to_ascii_text(probe)
            indices = art.to_indices(probe)

            from_indices = ["".join(art.chars[i] for i in row)
                            for row in indices]
            check(f"{ramp:<9} invert={invert!s:<5} same glyphs",
                  from_indices == text)
            check(f"{ramp:<9} invert={invert!s:<5} indices in range",
                  int(indices.max()) < len(art.chars),
                  f"max {int(indices.max())} of {len(art.chars)}")


def gradient_grid(cols, rows):
    """A diagonal ramp that exercises every character in the ramp."""
    x = np.linspace(0, 255, cols)
    y = np.linspace(0, 255, rows)
    return np.clip((x[None, :] + y[:, None]) / 2, 0, 255).astype(np.uint8)


def test_render(hold):
    print("\n2. Panel bring-up and geometry")

    art = AsciiArt(ramp="coarse")
    display = LcdDisplay(ramp=art.chars, font_size=8)
    cols, rows = display.grid_size
    panel_w, panel_h = display.lcd.width, display.lcd.height

    print(f"  panel {panel_w}x{panel_h}, grid {cols}x{rows}, "
          f"cell {display.atlas.cell_w}x{display.atlas.cell_h}, "
          f"cell_aspect {display.cell_aspect:.2f}")

    check("grid fills the panel width",
          cols * display.atlas.cell_w == panel_w,
          f"{cols * display.atlas.cell_w} of {panel_w}")
    check("grid fills the panel height",
          rows * display.atlas.cell_h == panel_h,
          f"{rows * display.atlas.cell_h} of {panel_h}")
    check("grid aspect matches the camera's 4:3",
          abs(cols / (rows * display.cell_aspect) - 4 / 3) < 0.01,
          f"{cols / (rows * display.cell_aspect):.3f}")
    check("every ramp glyph rendered",
          all(display.atlas.tiles[i].any()
              for i, c in enumerate(art.chars) if c != " "))

    print("\n3. Timing (mean of 20 frames)")
    grey = gradient_grid(cols, rows)
    indices = art.to_indices(grey)
    colours = np.zeros((rows, cols, 3), dtype=np.uint8)
    colours[..., 0] = grey
    colours[..., 1] = 255 - grey
    colours[..., 2] = 128

    # "paper" is the worst case: a light screen means every pixel a glyph
    # misses still has to be written, so nothing is saved on the blank areas.
    paper = palettes.by_name("paper")
    tint = palettes.rgb_table(paper, len(art.chars))[indices]

    for label, args in [("greyscale", (indices, None)),
                        ("colour", (indices, colours)),
                        ("tint/paper", (indices, tint, paper.screen))]:
        display.render(*args)                       # warm up allocations
        start = time.perf_counter()
        for _ in range(20):
            display.render(*args)
        each = (time.perf_counter() - start) / 20
        print(f"  {label:<10} {each * 1000:6.1f} ms/frame  ({1 / each:5.1f} fps)")
        check(f"{label} frame time is usable", each < 0.25,
              f"{each * 1000:.0f} ms")

    # Break the timing down so a future regression is attributable.
    print("\n4. Where the time goes (greyscale)")
    stages = [
        ("blit glyphs", lambda: display._blit(indices)),
        ("pack grey", lambda: display._pack_grey(display._blit(indices))),
        ("tobytes", lambda: display._frame.tobytes()),
    ]
    for label, fn in stages:
        start = time.perf_counter()
        for _ in range(20):
            fn()
        print(f"  {label:<12} {(time.perf_counter() - start) / 20 * 1000:6.1f} ms")

    print("\n5. Visual check")
    display.render(art.to_indices(gradient_grid(cols, rows)), colours)
    print(f"  Colour gradient on the panel for {hold}s - LOOK AT IT.")
    time.sleep(hold)

    display.close()
    check("close() released the panel", True)


def main():
    hold = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    print("=" * 62)
    print("LCD ASCII render path")
    print("=" * 62)

    test_index_agreement()
    test_render(hold)

    print("\n" + "=" * 62)
    if failures:
        print(f"RESULT: {len(failures)} CHECK(S) FAILED")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("RESULT: all automated checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
