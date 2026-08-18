"""
Brightness -> ASCII character mapping.

The mapping is a 256-entry lookup table applied with a single numpy fancy-index
over the whole grid.  The obvious nested-loop version costs one Python
interpreter round trip per character - at 80x30 that is 2400 per frame, which
on a Zero 2 is slower than everything else in the pipeline combined.
"""

import logging

import numpy as np

logger = logging.getLogger(__name__)

# Characters ordered light -> dark (i.e. by increasing ink coverage).
RAMPS = {
    "coarse": " .:-=+*#%@",
    "fine": " .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$",
}

# xterm-256 puts a 6x6x6 colour cube at indices 16..231, with these intensities
# on each axis. The steps are deliberately uneven - a large gap from 0 to 95,
# then 40 apart - so nearest-level quantisation needs the real values, not a
# uniform division.
CUBE_LEVELS = np.array([0, 95, 135, 175, 215, 255], dtype=np.int16)

# The top of colour_levels' range, and the value that means "as many colours as
# this display can manage" rather than a specific count. For the terminal that
# is the whole 6x6x6 cube; for the panel it is full RGB565. Keeping the maximum
# a no-op is what lets the setting work on both displays without the default
# quietly degrading the panel, which draws far more than six steps per channel.
#
# 32 rather than 6, which is where this started. Six is xterm's ceiling - its
# cube has six steps per axis and there is no seventh to choose - and applying
# it to the panel threw away most of the useful range: measured on one frame,
# 6 steps gives 13 colours where 32 gives 85 and no posterising gives 107. The
# terminal is unharmed by the higher cap because it saturates: _level_lut picks
# N points along a six-step axis and dedupes back to six.
#
# 32 is also the panel's own weakest channel - RGB565 is 5 bits of red and blue
# - so asking for more steps than that buys little on two channels out of three.
MAX_COLOUR_LEVELS = 32

_posterise_cache = {}


def _posterise_lut(levels):
    """
    A 256-entry LUT snapping a channel value to one of `levels` even steps.

    Even steps, unlike CUBE_LEVELS: those exist to match xterm's own uneven
    axis, and the panel has no such constraint. Spreading the steps evenly over
    0-255 is what "posterise to N levels" ordinarily means, and it keeps black
    and white exact at both ends.
    """
    if levels not in _posterise_cache:
        values = np.linspace(0, 255, levels).round().astype(np.int16)
        nearest = np.abs(np.arange(256, dtype=np.int16)[:, None]
                         - values[None, :])
        _posterise_cache[levels] = values[nearest.argmin(axis=1)].astype(
            np.uint8)
    return _posterise_cache[levels]


def _level_lut(levels):
    """
    Map each of the 256 input values to a cube axis index, 0..5.

    `levels` is how many of the six cube steps to use. Fewer steps means fewer
    distinct colours, which makes runs of identical colour longer and the
    terminal redraw correspondingly cheaper - the main lever on colour-mode
    frame rate.
    """
    chosen = np.unique(np.linspace(0, 5, levels).round().astype(np.int16))
    values = CUBE_LEVELS[chosen]
    nearest = np.abs(np.arange(256, dtype=np.int16)[:, None] - values[None, :])
    return chosen[nearest.argmin(axis=1)].astype(np.uint8)


class AsciiArt:
    """Generates ASCII art from a greyscale array."""

    def __init__(self, ramp="coarse", invert=False,
                 colour_levels=MAX_COLOUR_LEVELS):
        """
        Args:
            ramp: Key into RAMPS. There is deliberately no way to supply the
                characters directly - see the check below.
            invert: Swap the ramp.  The default suits light-on-dark terminals,
                where a bright part of the scene should be drawn with a dense
                character (more lit pixels).  Invert for a light background.
            colour_levels: Steps per channel in colour mode, 2 to
                MAX_COLOUR_LEVELS. The maximum means no quantising at all.
                The terminal saturates at six of these whatever is asked
                for, since that is all its cube has; the panel uses the
                full range.
        """
        # A name only. This used to fall back to treating an unrecognised value
        # as a literal ramp, which meant a mistyped name silently drew the
        # picture out of the letters of the typo - "--ramp standard" rendered
        # an eight-character ramp spelling the word - rather than complaining.
        if ramp not in RAMPS:
            raise ValueError(f"unknown ramp {ramp!r}; choose from "
                             f"{', '.join(RAMPS)}")
        self.chars = RAMPS[ramp]
        if invert:
            self.chars = self.chars[::-1]

        self.lut = self._build_lut()
        self.colour_levels = max(2, min(MAX_COLOUR_LEVELS,
                                        colour_levels))
        self._level_lut = _level_lut(self.colour_levels)

    def to_colour_indices(self, rgb):
        """
        Map per-cell RGB to xterm-256 palette indices.

        Args:
            rgb: uint8 array of shape (rows, cols, 3).

        Returns:
            int array of shape (rows, cols), each value 16..231.
        """
        q = self._level_lut[rgb]
        return (16 + 36 * q[..., 0].astype(np.int16)
                + 6 * q[..., 1].astype(np.int16)
                + q[..., 2].astype(np.int16))

    def posterise(self, rgb):
        """
        Reduce per-cell RGB to `colour_levels` even steps per channel.

        For the panel, which draws RGB directly and has no palette to quantise
        against. The terminal gets the same effect for free from
        to_colour_indices, since choosing among fewer cube steps *is* the
        quantisation there - so this is the panel's half of one setting rather
        than a second setting of its own.

        Until this existed `colour_levels` did nothing at all on the panel:
        lcd_worker took the full-RGB grid straight from the processor, and the
        quantiser this class configures was only ever called by the terminal.
        On a headless run - the deployed one - that made the setting dead.

        At the top of the range the image is returned untouched, so the default
        look of the panel is exactly what it always was.

        Args:
            rgb: uint8 array of shape (rows, cols, 3).

        Returns:
            uint8 array of the same shape. One LUT gather over a few thousand
            values, which is nothing beside the frame's other work.
        """
        if self.colour_levels >= MAX_COLOUR_LEVELS:
            return rgb
        return _posterise_lut(self.colour_levels)[rgb]

    def _build_lut(self):
        """
        Map each of the 256 possible brightness values to a character.

        Two encodings, both of which turn a whole row into a string with a
        single tobytes()/decode() and no Python-level loop:

          * Pure-ASCII ramp -> uint8 table, decoded as ASCII (1 byte/char).
          * Ramp with non-ASCII glyphs -> numpy 'U1' table, whose buffer is
            UCS-4 and so decodes as UTF-32-LE.  No ramp in RAMPS needs this
            today - the block ramp that did has been removed - but adding one
            back would otherwise cost 40 ms a frame, so the path is kept.

        The obvious fallback for the second case, "".join(chr(c) for c in row),
        costs one interpreter round trip per character - at 267x100 that is
        26,700 per frame, and it dominates everything else in the pipeline.
        """
        n = len(self.chars)
        levels = np.arange(256)
        indices = np.minimum(levels * n // 256, n - 1)

        # Same mapping, but left as ramp positions rather than characters.  The
        # LCD backend draws glyphs from a pre-rendered atlas and so wants the
        # index, not the character; deriving it here keeps the two outputs
        # choosing identically, including when `invert` has reversed the ramp.
        self.index_lut = indices.astype(np.uint16)

        encoded = self.chars.encode("utf-8")
        self.is_ascii = len(encoded) == n
        if self.is_ascii:
            table = np.frombuffer(encoded, dtype=np.uint8)
        else:
            table = np.array(list(self.chars), dtype="U1")

        return table[indices]

    def to_indices(self, grayscale_frame):
        """
        Convert a greyscale array to ramp positions instead of characters.

        Args:
            grayscale_frame: uint8 array of shape (rows, cols).

        Returns:
            uint16 array of shape (rows, cols), each value indexing `chars`.
        """
        return self.index_lut[grayscale_frame]

    def to_ascii_text(self, grayscale_frame):
        """
        Convert a greyscale array to ASCII text.

        Args:
            grayscale_frame: uint8 array of shape (rows, cols).

        Returns:
            List of strings, one per row.
        """
        mapped = self.lut[grayscale_frame]
        codec = "ascii" if self.is_ascii else "utf-32-le"
        return [row.tobytes().decode(codec) for row in mapped]
