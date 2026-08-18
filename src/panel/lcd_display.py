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
import textwrap

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from panel.lcd import ILI9341

logger = logging.getLogger(__name__)

# The notice band. Two lines is enough for every message the app can produce -
# the longest is "could not reach the model: ..." with an OSError on the end -
# and a third would start eating the picture.
NOTICE_FONT_SIZE = 12
NOTICE_LINES = 2
NOTICE_PAD = 3
NOTICE_INK = (255, 236, 200)     # warm white, the project's own cast
NOTICE_BG = (28, 12, 8)          # near-black, so the band reads as an overlay

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
        # Blank first, light second. The other order lights undefined frame
        # memory and shows a bright flash of garbage before anything is drawn -
        # about 200 ms, and very visible in a dark room.
        self.lcd.fill(0x0000)
        self.lcd.backlight(brightness)

        self.font_path = font_path
        self.font_size = font_size

        # Persistent RGB565 frame buffer.  Cells that the grid does not reach
        # stay zero, so the leftover strip is black without being redrawn.
        self._frame = np.zeros((self.lcd.height, self.lcd.width, 2),
                               dtype=np.uint8)

        # Its own font and size, independent of the ramp's: the picture's
        # glyphs are chosen to tile the panel exactly, and at font size 6 that
        # is four pixels wide - fine for a picture, unreadable as a sentence.
        self._notice_font = ImageFont.truetype(font_path, NOTICE_FONT_SIZE)
        ascent, descent = self._notice_font.getmetrics()
        self._line_h = ascent + descent
        self._band_h = min(self.lcd.height,
                           NOTICE_LINES * self._line_h + 2 * NOTICE_PAD)
        self._notice_cache = None
        # Whether anything is currently in the band. Without it, a
        # frame with no notice cannot tell 'nothing to clean up' from
        # 'a message just expired'.
        self._band_painted = False

        self.atlas = None
        self._rebuild(ramp)

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
        self._rebuild(ramp)

    def set_font_size(self, font_size):
        """
        Change the glyph size, and with it the panel's whole character grid.

        Unlike a ramp change this *does* move the grid, so every caller holding
        a (cols, rows) or a cell aspect has a stale one afterwards - which is
        why LcdWorker re-reads both from here rather than caching them at
        start-up.

        Must be called on the thread that owns the panel.  Rebuilding the atlas
        rasterises every glyph in the ramp, which at font size 8 is 10 glyphs
        and a few milliseconds; it is not something to do per frame, and
        nothing here does.
        """
        if font_size == self.font_size:
            return
        logger.info("LCD font size %d -> %d", self.font_size, font_size)
        self.font_size = font_size
        self._rebuild(self.atlas.chars)

    def _rebuild(self, ramp):
        """Re-rasterise the atlas and re-fit the grid to the panel."""
        self.atlas = GlyphAtlas(ramp, self.font_path, self.font_size)
        self.cols = max(1, self.lcd.width // self.atlas.cell_w)
        self.rows = max(1, self.lcd.height // self.atlas.cell_h)

        used_w = self.cols * self.atlas.cell_w
        used_h = self.rows * self.atlas.cell_h
        x0 = (self.lcd.width - used_w) // 2
        y0 = (self.lcd.height - used_h) // 2
        # Zero the whole buffer before re-pointing the view.  A larger font
        # gives a smaller picture, and without this the old picture's outer
        # pixels would survive in the margin the new one no longer reaches -
        # nothing ever writes there again, so they would stay for good.
        self._frame[:] = 0
        self._band_painted = False
        # A view, so writes through it land in the persistent frame buffer.
        self._region = self._frame[y0:y0 + used_h, x0:x0 + used_w]

        logger.info("LCD grid: %dx%d chars, picture %dx%d px at (%d,%d) "
                    "on a %dx%d panel", self.cols, self.rows, used_w, used_h,
                    x0, y0, self.lcd.width, self.lcd.height)

    # --- notices ------------------------------------------------------------
    #
    # A band along the bottom of the panel, drawn straight into the RGB565
    # buffer *after* the picture is packed. Deliberately not part of the
    # character grid: the atlas holds only the ramp, so the grid cannot spell
    # anything, and a message tinted by whatever cell colours sit under it
    # would be unreadable exactly when it matters. Fixed ink on a fixed band is
    # legible over every scheme, including `live`.
    #
    # It writes to self._frame rather than self._region so it lands on the
    # panel edge whatever the grid fit leaves as margin.

    def notice_mask(self, text):
        """
        Rasterise one message to a coverage mask, cached.

        Returns a (band_h, width) uint8 array. Cached because a notice stands
        for seconds and the panel redraws 27 times a second; rasterising per
        frame would put a PIL text call back on the hot path, which is the one
        thing src/panel/lcd_display.py exists to keep off it.
        """
        if self._notice_cache is not None and self._notice_cache[0] == text:
            return self._notice_cache[1]

        width = self.lcd.width
        lines = self._wrap(text, width)
        band = Image.new("L", (width, self._band_h), 0)
        draw = ImageDraw.Draw(band)
        for i, line in enumerate(lines[:NOTICE_LINES]):
            draw.text((NOTICE_PAD, NOTICE_PAD + i * self._line_h), line,
                      font=self._notice_font, fill=255)
        mask = np.asarray(band, dtype=np.uint8)
        self._notice_cache = (text, mask)
        return mask

    def _wrap(self, text, width):
        """Break a message into at most NOTICE_LINES that fit the panel."""
        per_line = max(8, int(width - 2 * NOTICE_PAD)
                       // max(1, round(self._notice_font.getlength("M"))))
        lines = textwrap.wrap(text, per_line) or [""]
        if len(lines) > NOTICE_LINES:
            lines = lines[:NOTICE_LINES]
            lines[-1] = lines[-1][:max(1, per_line - 1)] + "\u2026"
        return lines

    def _paint_notice(self, text):
        """Blend one message into the bottom band of the frame buffer."""
        mask = self.notice_mask(text)
        band = self._frame[self.lcd.height - self._band_h:, :, :]
        cover = mask[:, :, None].astype(np.uint16)
        ink = np.array(NOTICE_INK, dtype=np.uint16)
        back = np.array(NOTICE_BG, dtype=np.uint16)
        rgb = (back + ((ink - back) * cover) // 255).astype(np.uint8)
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        band[..., 0] = (r & 0xF8) | (g >> 5)
        band[..., 1] = ((g << 3) & 0xE0) | (b >> 3)
        self._band_painted = True

    def show_notice(self, text):
        """
        Put a message on the panel without a frame to go with it.

        This is the case that matters most: when the camera stops delivering,
        the render loop has nothing to draw and the panel would otherwise sit
        showing the last good picture for ever, which looks exactly like a
        working camera. The frame buffer is persistent, so the band can be
        painted over whatever is already there and pushed on its own.
        """
        self._paint_notice(text)
        self.lcd.show_packed(self._frame.tobytes())

    def clear_notice(self):
        """
        Take the band away and push what is underneath.

        The picture region repaints itself on the next frame, but the margin
        strip outside it is never written again - so it has to be zeroed here
        or the band's last row survives for good, the same trap _rebuild has.
        """
        self._frame[self.lcd.height - self._band_h:, :, :] = 0
        self._band_painted = False
        self.lcd.show_packed(self._frame.tobytes())

    @property
    def band_height(self):
        """Pixels the notice band occupies, for tests and for the log."""
        return self._band_h

    @property
    def grid_size(self):
        """(cols, rows) - fixed, and independent of the terminal's grid."""
        return self.cols, self.rows

    @property
    def cell_aspect(self):
        """Character cell height/width, for correcting the picture's shape."""
        return self.atlas.cell_h / self.atlas.cell_w

    def render(self, indices, colours=None, screen=(0, 0, 0), notice=None):
        """
        Draw one frame.

        Args:
            indices: (rows, cols) integer array of ramp positions, from
                AsciiArt.to_indices.
            colours: Optional (rows, cols, 3) uint8 array, one RGB per cell.
                When None the picture is drawn white-on-black.
            screen: RGB behind the glyphs - a colour scheme's unlit screen.
                Every pixel a glyph does not cover becomes this.
            notice: Optional message for the bottom band. Painted after the
                picture, so it is legible whatever the picture is doing.

        Note the colours are used at full RGB565 depth rather than being
        quantised to the xterm-256 palette the terminal is limited to - the
        panel has no such limit, and skipping the quantisation is cheaper too.
        """
        if not notice and self._band_painted:
            # The band has to go before the picture is packed, not after: only
            # the intersection of band and picture region is repainted below,
            # and the rest of the band - the bottom margin, and the left and
            # right margins when the grid does not tile the panel exactly - is
            # never written again. Leaving it is the same trap _rebuild guards
            # against for the picture, reintroduced one band lower.
            self._frame[self.lcd.height - self._band_h:, :, :] = 0
            self._band_painted = False

        coverage = self._blit(indices)

        if colours is None:
            self._pack_grey(coverage)
        else:
            self._pack_colour(coverage, colours, screen)

        if notice:
            self._paint_notice(notice)

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

    def _pack_colour(self, coverage, colours, screen=(0, 0, 0)):
        """
        Write RGB565, fading from the screen colour to each cell's own colour.

        Glyph coverage is the fade: a pixel the glyph misses entirely comes out
        as the unlit screen, one the glyph fully covers as the cell's colour,
        and the antialiased edge in between. With a black screen this reduces
        to the old "tint the glyph, leave the rest black" behaviour.
        """
        # One colour per cell, stretched to one per pixel.
        cell_h, cell_w = self.atlas.cell_h, self.atlas.cell_w
        big = np.repeat(np.repeat(colours, cell_h, axis=0), cell_w, axis=1)

        if not any(screen):
            # A black screen - the live and greyscale schemes - collapses the
            # blend to a plain modulate, which stays in uint16 and so skips the
            # int32 promotion the general case needs. Worth the special case:
            # it is about 7 ms a frame on this Pi.
            cov = coverage.astype(np.uint16)
            r, g, b = ((cov * big[..., i]) >> 8 for i in range(3))
        else:
            # (coverage + 1) >> 8 rather than / 255: exact at both ends - 0
            # gives the screen colour, 255 the cell's colour - and saves a
            # divide over 76,800 pixels.
            weight = coverage.astype(np.int32) + 1
            # int32 because the product reaches 255*256, well past int16. No
            # clipping needed: delta >= -base bounds the result to 0..255.
            r, g, b = (base
                       + (((big[..., i].astype(np.int32) - base) * weight) >> 8)
                       for i, base in enumerate(screen))

        self._region[..., 0] = ((r & 0xF8) | (g >> 5)).astype(np.uint8)
        self._region[..., 1] = (((g << 3) & 0xE0) | (b >> 3)).astype(np.uint8)

    @property
    def panel_size(self):
        """(width, height) in pixels, in the panel's current orientation."""
        return self.lcd.width, self.lcd.height

    def show_image(self, image):
        """
        Push a whole PIL image, bypassing the character grid.

        Only the start-up screen uses this.  It deliberately does not touch
        `_frame`, so the first real camera frame overwrites the whole panel and
        leaves nothing of the splash behind - including in the leftover strip
        outside the character grid, which `_frame` keeps black.
        """
        self.lcd.show(image)

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
