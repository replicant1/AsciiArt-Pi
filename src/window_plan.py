#!/usr/bin/env python3
"""
Work out a terminal geometry in which the ASCII picture is not letterboxed.

The picture fills the window exactly when

    cols / canvas_rows == camera_aspect * cell_aspect

where cell_aspect is the character cell's height/width ratio.  Assuming a
cell_aspect of 2.0 is close but not right: this Pi's "Monospace 7" cells are
6.0 x 11.0 px, an aspect of 1.833, and being 8% out is enough to leave a visible
band of unused rows.

Rather than guess, the true cell size is read from Pango - the same font
metrics VTE uses to lay out lxterminal - so the answer is exact for whatever
font size is chosen.  Verified against a screenshot: predicted 6.000 x 11.000
px, measured 6.025 x 11.165.

Usage:
    python3 src/window_plan.py fit          # largest window that fills the screen
    python3 src/window_plan.py 80           # 80 columns, rows to match
    python3 src/window_plan.py 80x33        # explicit; just reports the font

Prints: COLS ROWS FONT_SIZE CELL_ASPECT
"""

import sys

import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402

# Measured on this Pi's 2048x1080 screen: the desktop panel takes ~35px off the
# top and the window title bar another ~32px, leaving about 1010px of usable
# height for terminal content.
PANEL_AND_TITLEBAR = 70
SIDE_MARGIN = 20

FONT_SIZES = range(6, 15)
STATUS_ROWS = 1          # ascii_camera.py reserves the bottom row


def cell_size(font_size, family="Monospace"):
    """(width, height) of one character cell in pixels, from Pango metrics."""
    font_map = PangoCairo.FontMap.get_default()
    context = font_map.create_context()
    font = font_map.load_font(context,
                              Pango.FontDescription(f"{family} {font_size}"))
    metrics = font.get_metrics(None)
    width = metrics.get_approximate_char_width() / Pango.SCALE
    height = (metrics.get_ascent() + metrics.get_descent()) / Pango.SCALE
    return width, height


def plan(request, screen=(2048, 1080), camera_aspect=4 / 3):
    """
    Return (cols, rows, font_size, cell_aspect).

    `request` is "fit", a column count, or "COLSxROWS".
    """
    usable_w = screen[0] - SIDE_MARGIN
    usable_h = screen[1] - PANEL_AND_TITLEBAR

    request = str(request)
    fixed_cols = fixed_rows = None
    if "x" in request:
        fixed_cols, fixed_rows = (int(v) for v in request.split("x"))
    elif request != "fit":
        fixed_cols = int(request)

    best = None
    for font_size in FONT_SIZES:
        cw, ch = cell_size(font_size)
        cell_aspect = ch / cw
        # Window shape that exactly contains a `camera_aspect` picture.
        ratio = camera_aspect * cell_aspect

        max_cols = int(usable_w // cw)
        max_canvas = int(usable_h // ch) - STATUS_ROWS
        if max_cols < 20 or max_canvas < 10:
            continue

        if fixed_rows is not None:            # "COLSxROWS" - honour both
            cols, canvas = fixed_cols, fixed_rows - STATUS_ROWS
        elif fixed_cols is not None:          # "COLS" - derive the rows
            cols = fixed_cols
            canvas = max(1, round(cols / ratio))
        else:                                 # "fit" - as big as will fit
            canvas = min(max_canvas, int(max_cols / ratio))
            cols = round(canvas * ratio)

        # Reject font sizes at which this window would overflow the screen.
        if cols > max_cols or canvas > max_canvas or canvas < 1:
            continue

        # Prefer the biggest picture on screen; among equals, more characters.
        score = (cols * cw * canvas * ch, cols * canvas)
        if best is None or score > best[0]:
            best = (score, (cols, canvas + STATUS_ROWS, font_size,
                            round(cell_aspect, 3)))

    if best is None:
        # Nothing fits cleanly - fall back to something always safe.
        cw, ch = cell_size(7)
        return 80, 33, 7, round(ch / cw, 3)
    return best[1]


def main():
    """window_plan.py REQUEST [SCREEN_W SCREEN_H [CAMERA_ASPECT]]"""
    request = sys.argv[1] if len(sys.argv) > 1 else "fit"
    screen = (2048, 1080)
    if len(sys.argv) > 3:
        screen = (int(sys.argv[2]), int(sys.argv[3]))
    aspect = float(sys.argv[4]) if len(sys.argv) > 4 else 4 / 3
    cols, rows, font_size, cell_aspect = plan(request, screen, aspect)
    print(f"{cols} {rows} {font_size} {cell_aspect}")


if __name__ == "__main__":
    main()
