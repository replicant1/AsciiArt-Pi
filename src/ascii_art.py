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


class AsciiArt:
    """Generates ASCII art from a greyscale array."""

    def __init__(self, ramp="standard", invert=False):
        """
        Args:
            ramp: Key into RAMPS, or a literal character ramp (light -> dark).
            invert: Swap the ramp.  The default suits light-on-dark terminals,
                where a bright part of the scene should be drawn with a dense
                character (more lit pixels).  Invert for a light background.
        """
        self.chars = RAMPS.get(ramp, ramp)
        if not self.chars:
            raise ValueError("ASCII ramp must not be empty")
        if invert:
            self.chars = self.chars[::-1]

        self.lut = self._build_lut()

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

        encoded = self.chars.encode("utf-8")
        self.is_ascii = len(encoded) == n
        if self.is_ascii:
            table = np.frombuffer(encoded, dtype=np.uint8)
        else:
            table = np.array(list(self.chars), dtype="U1")

        return table[indices]

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
