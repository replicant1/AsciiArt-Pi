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
    "standard": " .:-=+*#%@",
    "fine": " .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$",
    "blocks": " .:-=+*#%@▓█",
}

# xterm-256 puts a 6x6x6 colour cube at indices 16..231, with these intensities
# on each axis. The steps are deliberately uneven - a large gap from 0 to 95,
# then 40 apart - so nearest-level quantisation needs the real values, not a
# uniform division.
CUBE_LEVELS = np.array([0, 95, 135, 175, 215, 255], dtype=np.int16)


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

    def __init__(self, ramp="standard", invert=False, colour_levels=6):
        """
        Args:
            ramp: Key into RAMPS, or a literal character ramp (light -> dark).
            invert: Swap the ramp.  The default suits light-on-dark terminals,
                where a bright part of the scene should be drawn with a dense
                character (more lit pixels).  Invert for a light background.
            colour_levels: Cube steps per channel used in colour mode, 2 to 6.
        """
        self.chars = RAMPS.get(ramp, ramp)
        if not self.chars:
            raise ValueError("ASCII ramp must not be empty")
        if invert:
            self.chars = self.chars[::-1]

        self.lut = self._build_lut()
        self.colour_levels = max(2, min(6, colour_levels))
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

    def _build_lut(self):
        """
        Map each of the 256 possible brightness values to a character.

        Two encodings, both of which turn a whole row into a string with a
        single tobytes()/decode() and no Python-level loop:

          * Pure-ASCII ramp -> uint8 table, decoded as ASCII (1 byte/char).
          * Ramp with non-ASCII glyphs (e.g. the block characters) -> numpy
            'U1' table, whose buffer is UCS-4 and so decodes as UTF-32-LE.

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
