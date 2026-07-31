"""
Vintage display colour schemes.

Each scheme imitates a real screen from the reference photographs: a green
phosphor terminal, an amber CRT, a blue-backlit character LCD, e-ink, and so
on. The user cycles through them with one key and stops when they like what
they see, so the schemes are chosen to be unmistakable from across the room
rather than subtly graded - no two "yellow on black" variants differing only in
the exact hue.

Three kinds, because they need different amounts of work per frame:

  grey  The original greyscale. Every character is drawn in the terminal's own
        foreground colour, so no per-cell colour is computed at all and this
        stays the cheapest path.
  live  The original live colour, one RGB per cell taken from the camera.
  tint  A monochrome screen. The cell's colour is a blend from the screen
        colour to the ink colour, chosen by how dense a character the ramp
        picked for it - so a bright part of the scene gets both a denser glyph
        and a fuller-strength ink, the way a brighter area of a real CRT is
        genuinely brighter.

The blend has to track how much ink the chosen glyph actually lays down, not
how bright the scene was. Those are the same thing until `invert` is on, and
then they are opposites: AsciiArt reverses its character string but still
indexes it with a brightness-derived position, so a bright cell keeps a high
index while picking a *sparse* glyph. Tinting by the raw index would then leave
a bright, nearly empty cell - the characters would go negative and the colour
would not. Passing `invert` here reverses the blend table to match, so both
halves of the picture invert together.

(Verified by tests/palette_test.py, which caught exactly this: the first
version of this module tinted by the raw index and got it wrong.)

Both displays share these definitions but consume them differently. The LCD
takes RGB and draws it directly. The terminal can only address the 256-colour
xterm palette, so each scheme's blend is matched to the nearest palette entry
once, when the ramp changes - an exact nearest-neighbour search over all 240
usable colours, which is affordable precisely because it is not per frame and
gives noticeably better near-greys than quantising to the 6x6x6 cube would.
"""

import logging
from typing import NamedTuple

import numpy as np

logger = logging.getLogger(__name__)

# The 6x6x6 colour cube's axis values. Deliberately uneven - a big step from 0
# to 95, then 40 apart - so a nearest match needs the real numbers.
CUBE_LEVELS = [0, 95, 135, 175, 215, 255]

# xterm palette entries 16..255: the cube, then a 24-step grey ramp.
XTERM_BASE = 16


def _xterm_palette():
    """RGB of xterm indices 16..255, in order. Row i is index i + XTERM_BASE."""
    colours = [(r, g, b)
               for r in CUBE_LEVELS for g in CUBE_LEVELS for b in CUBE_LEVELS]
    colours += [(v, v, v) for v in range(8, 8 + 24 * 10, 10)]
    return np.array(colours, dtype=np.int16)


XTERM_RGB = _xterm_palette()


class Scheme(NamedTuple):
    """One display look."""

    name: str           # short label for the status line
    kind: str           # "grey", "live" or "tint"
    ink: tuple          # lit/foreground RGB
    screen: tuple       # unlit/background RGB
    note: str           # what it imitates, for --help and the log


SCHEMES = (
    Scheme("grey",  "grey", (255, 255, 255), (0, 0, 0),
           "Greyscale - characters only, no colour"),
    Scheme("live",  "live", (255, 255, 255), (0, 0, 0),
           "Live colour from the camera"),
    Scheme("green", "tint", (0x33, 0xFF, 0x33), (0x00, 0x1A, 0x00),
           "Green phosphor terminal"),
    Scheme("amber", "tint", (0xFF, 0xB7, 0x33), (0x1A, 0x0D, 0x00),
           "Amber CRT"),
    Scheme("cyan",  "tint", (0x66, 0xE6, 0xFF), (0x00, 0x14, 0x19),
           "Ice-blue vacuum fluorescent"),
    Scheme("navy",  "tint", (0xEA, 0xF6, 0xFF), (0x0B, 0x3F, 0xBF),
           "White on a blue-backlit LCD"),
    Scheme("azure", "tint", (0x12, 0x3A, 0x9E), (0xDF, 0xE6, 0xE2),
           "Blue STN LCD on grey-white"),
    Scheme("lime",  "tint", (0x14, 0x21, 0x0A), (0xC4, 0xDC, 0x1E),
           "Black on an acid-lime backlight"),
    Scheme("paper", "tint", (0x2B, 0x2B, 0x28), (0xE9, 0xE7, 0xDF),
           "E-ink on paper"),
)

SCHEME_NAMES = tuple(s.name for s in SCHEMES)

# Blend tables are rebuilt only when the ramp length changes, which happens on a
# ramp or invert change - never per frame.
_rgb_cache = {}
_index_cache = {}


def by_name(name):
    """Look a scheme up by name, or raise ValueError naming the valid ones."""
    for scheme in SCHEMES:
        if scheme.name == name:
            return scheme
    raise ValueError(f"unknown scheme {name!r}; choose from "
                     f"{', '.join(SCHEME_NAMES)}")


def nearest_xterm(rgb):
    """
    The xterm-256 index whose colour is closest to `rgb`.

    Searches all 240 usable entries, cube and grey ramp alike. Used for scheme
    backgrounds and blend tables, both of which are computed rarely.
    """
    distance = np.linalg.norm(XTERM_RGB - np.array(rgb, dtype=np.int16), axis=1)
    return int(distance.argmin()) + XTERM_BASE


def rgb_table(scheme, levels, invert=False):
    """
    RGB for each ramp position, blending screen -> ink.

    Args:
        scheme: the Scheme.
        levels: how many characters the ramp has.
        invert: True when AsciiArt has reversed its ramp, in which case a high
            position now means a sparse glyph and so must get the screen end of
            the blend, not the ink end.

    Returns:
        uint8 array of shape (levels, 3). Index it with a grid of ramp
        positions to colour a whole frame in one gather.
    """
    key = (scheme.name, levels, invert)
    if key not in _rgb_cache:
        screen = np.array(scheme.screen, dtype=np.float32)
        ink = np.array(scheme.ink, dtype=np.float32)
        # levels == 1 would divide by zero; such a ramp is degenerate anyway.
        t = (np.arange(levels, dtype=np.float32)
             / max(1, levels - 1))[:, None]
        blend = screen + (ink - screen) * t
        table = np.clip(blend, 0, 255).astype(np.uint8)
        _rgb_cache[key] = table[::-1].copy() if invert else table
    return _rgb_cache[key]


def index_table(scheme, levels, invert=False):
    """
    The same blend, as xterm-256 palette indices for the terminal.

    Returns:
        uint8 array of shape (levels,).
    """
    key = (scheme.name, levels, invert)
    if key not in _index_cache:
        table = np.array([nearest_xterm(c)
                          for c in rgb_table(scheme, levels, invert)],
                         dtype=np.uint8)
        _index_cache[key] = table
        logger.info("Scheme %s: %d levels%s -> xterm indices %d..%d",
                    scheme.name, levels, " inverted" if invert else "",
                    int(table.min()), int(table.max()))
    return _index_cache[key]
