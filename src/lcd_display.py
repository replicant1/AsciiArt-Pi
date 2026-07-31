"""
ASCII picture output on the ILI9341 SPI panel.

Nothing but the picture goes on the glass: no status line, no border, no window
furniture.  The grid is a fixed size chosen once from the font, independent of
whatever the terminal on the HDMI screen is doing, and it always occupies the
whole panel.

The interesting part is how the characters are drawn.  The obvious approach -
one PIL `draw.text()` per cell - costs 1,536 calls per frame at 64x24, which is
far beyond a Zero 2's budget.  Instead every glyph in the ramp is rendered once
into an atlas, and a frame becomes a single numpy gather: index the atlas with
the whole grid at once to get (rows, cols, cell_h, cell_w), then transpose the
cell axes into place and reshape.  That is one vectorised operation per frame
regardless of how many characters are on screen.

Font sizes 6, 8 and 9 are worth knowing about: each tiles 320x240 exactly and
yields a grid whose on-screen aspect is exactly 4:3, matching the camera, so
filling the panel crops nothing.  Other sizes leave a few pixels over, which are
left black and the picture centred in them.
"""

import logging

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from lcd import ILI9341

logger = logging.getLogger(__name__)

DEFAULT_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
DEFAULT_FONT_SIZE = 8


class GlyphAtlas:
    """Every character of a ramp, pre-rendered into a fixed-size cell."""

    def __init__(self, chars, font_path=DEFAULT_FONT,
                 font_size=DEFAULT_FONT_SIZE):
        """
        Args:
            chars: The ramp, already inverted if that was asked for.
            font_path: A monospace TrueType font.
            font_size: Point size; the cell size follows from it.
        """
        self.chars = chars
        self.font = ImageFont.truetype(font_path, font_size)

        # Monospace, so every glyph advances the same; "M" is just a witness.
        self.cell_w = max(1, round(self.font.getlength("M")))
        ascent, descent = self.font.getmetrics()
        self.cell_h = max(1, ascent + descent)

        self.tiles = self._render()
        logger.info("Glyph atlas: %d chars at %dx%d px (font size %d)",
                    len(chars), self.cell_w, self.cell_h, font_size)

    def _render(self):
        """
        Rasterise each glyph to a greyscale coverage tile.

        Returns:
            uint8 array of shape (len(chars), cell_h, cell_w).
        """
        tiles = np.zeros((len(self.chars), self.cell_h, self.cell_w),
                         dtype=np.uint8)
        missing = []

        for i, char in enumerate(self.chars):
            cell = Image.new("L", (self.cell_w, self.cell_h), 0)
            # PIL's default anchor puts the ascender line at y=0, which is
            # exactly the top of a cell of height ascent+descent.
            ImageDraw.Draw(cell).text((0, 0), char, fill=255, font=self.font)
            tiles[i] = np.asarray(cell)
            if char != " " and not tiles[i].any():
                missing.append(char)

        if missing:
            # A ramp containing glyphs the font lacks (the block characters are
            # the usual casualty) would silently render as blank or as .notdef
            # boxes, so say so rather than let the picture look broken.
            logger.warning("Font has no glyph for %r - those cells will be "
                           "blank", "".join(missing))
        return tiles


class LcdDisplay:
    """Draws an ASCII grid onto the ILI9341, filling the panel."""

    def __init__(self, ramp, font_path=DEFAULT_FONT,
                 font_size=DEFAULT_FONT_SIZE, landscape=True, spi_freq=40_000_000,
                 brightness=100):
        """
        Args:
            ramp: Initial character ramp (post-invert).
            font_path, font_size: Glyph source; the grid size follows.
            landscape: True for 320x240, False for 240x320.
            spi_freq: SPI clock in Hz.
            brightness: Backlight duty cycle, 0-100.
        """
        self.lcd = ILI9341(landscape=landscape, spi_freq=spi_freq)
        self.lcd.init()
        self.lcd.backlight(brightness)
        self.lcd.fill(0x0000)

        self.font_path = font_path
        self.font_size = font_size

        # Persistent RGB565 frame buffer.  Cells that the grid does not reach
        # stay zero, so the leftover strip is black without being redrawn.
        self._frame = np.zeros((self.lcd.height, self.lcd.width, 2),
                               dtype=np.uint8)

        self.atlas = None
        self.set_ramp(ramp)

    def set_ramp(self, ramp):
        """
        Swap the character set, rebuilding the atlas.

        Called when the ramp changes or `invert` is toggled on the main display,
        both of which change the string this has to draw.  The grid size is
        unaffected - it depends only on the font - so nothing downstream has to
        be told about it.
        """
        if self.atlas is not None and self.atlas.chars == ramp:
            return

        self.atlas = GlyphAtlas(ramp, self.font_path, self.font_size)
        self.cols = max(1, self.lcd.width // self.atlas.cell_w)
        self.rows = max(1, self.lcd.height // self.atlas.cell_h)

        used_w = self.cols * self.atlas.cell_w
        used_h = self.rows * self.atlas.cell_h
        x0 = (self.lcd.width - used_w) // 2
        y0 = (self.lcd.height - used_h) // 2
        # A view, so writes through it land in the persistent frame buffer.
        self._region = self._frame[y0:y0 + used_h, x0:x0 + used_w]

        logger.info("LCD grid: %dx%d chars, picture %dx%d px at (%d,%d) "
                    "on a %dx%d panel", self.cols, self.rows, used_w, used_h,
                    x0, y0, self.lcd.width, self.lcd.height)

    @property
    def grid_size(self):
        """(cols, rows) - fixed, and independent of the terminal's grid."""
        return self.cols, self.rows

    @property
    def cell_aspect(self):
        """Character cell height/width, for correcting the picture's shape."""
        return self.atlas.cell_h / self.atlas.cell_w

    def render(self, indices, colours=None):
        """
        Draw one frame.

        Args:
            indices: (rows, cols) integer array of ramp positions, from
                AsciiArt.to_indices.
            colours: Optional (rows, cols, 3) uint8 array, one RGB per cell.
                When None the picture is drawn white-on-black.

        Note the colours are used at full RGB565 depth rather than being
        quantised to the xterm-256 cube the terminal is limited to - the panel
        has no such limit, and skipping the quantisation is cheaper as well.
        """
        coverage = self._blit(indices)

        if colours is None:
            self._pack_grey(coverage)
        else:
            self._pack_colour(coverage, colours)

        self.lcd.show_packed(self._frame.tobytes())

    def _blit(self, indices):
        """
        Expand a grid of ramp positions into a per-pixel coverage image.

        Returns:
            uint8 array of shape (rows*cell_h, cols*cell_w).
        """
        rows, cols = indices.shape
        # (rows, cols, cell_h, cell_w) -> interleave so cell rows sit inside
        # picture rows -> (rows*cell_h, cols*cell_w).
        tiles = self.atlas.tiles[indices]
        return (tiles.transpose(0, 2, 1, 3)
                .reshape(rows * self.atlas.cell_h, cols * self.atlas.cell_w))

    def _pack_grey(self, coverage):
        """Write white-on-black RGB565 straight from the coverage image."""
        # Packing from the single coverage channel avoids ever materialising a
        # 3-channel image: r=g=b=coverage, so the bit twiddling collapses.
        self._region[..., 0] = (coverage & 0xF8) | (coverage >> 5)
        self._region[..., 1] = ((coverage << 3) & 0xE0) | (coverage >> 3)

    def _pack_colour(self, coverage, colours):
        """Write RGB565 with each glyph tinted by its cell's colour."""
        # One colour per cell, stretched to one per pixel.
        cell_h, cell_w = self.atlas.cell_h, self.atlas.cell_w
        big = np.repeat(np.repeat(colours, cell_h, axis=0), cell_w, axis=1)

        # Modulate the cell colour by glyph coverage. The >> 8 rather than
        # / 255 costs one count of brightness at full white and saves a divide
        # over 76,800 pixels.
        cov = coverage.astype(np.uint16)
        r = (cov * big[..., 0]) >> 8
        g = (cov * big[..., 1]) >> 8
        b = (cov * big[..., 2]) >> 8

        self._region[..., 0] = ((r & 0xF8) | (g >> 5)).astype(np.uint8)
        self._region[..., 1] = (((g << 3) & 0xE0) | (b >> 3)).astype(np.uint8)

    def clear(self):
        """Blank the panel."""
        self._frame[:] = 0
        self.lcd.fill(0x0000)

    def close(self):
        """Blank and release the panel."""
        try:
            self.clear()
        except OSError:
            pass                # already gone; still release the pins below
        self.lcd.close()
