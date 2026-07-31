"""
ncurses terminal rendering for the ASCII art frames.

Python's `curses` is a wrapper around the system ncurses library and ships with
the standard library on Linux - nothing to pip install.

Two things matter for a live view: never write anything to stdout/stderr while
curses owns the screen (see ascii_camera.py, which redirects both to a log
file), and avoid a full clear() per frame - clearing forces ncurses to repaint
every cell, which flickers.  Instead each content row is padded to the full
width so it overwrites whatever was there before.
"""

import curses
import fcntl
import logging
import struct
import sys
import termios

import numpy as np

import palettes

logger = logging.getLogger(__name__)

# Pair numbers 16..255 are spoken for - each carries the ink of the palette
# colour with the same number - so the pair used for cells that hold no
# character, and therefore only need the screen colour, is taken from below
# that range.
BACKGROUND_PAIR = 1


class NcursesDisplay:
    """Renders ASCII art frames to the terminal."""

    # True unlike HeadlessDisplay: the render loop reads this to decide whether
    # building the ASCII text and colour grid is worth doing at all.
    draws = True

    def __init__(self, stdscr):
        """
        Args:
            stdscr: The curses window from curses.wrapper().
        """
        self.stdscr = stdscr
        self.rows = 0
        self.cols = 0
        self._configure()

    def _configure(self):
        curses.noecho()
        curses.cbreak()
        self.stdscr.nodelay(True)      # getch() returns immediately
        self.stdscr.keypad(True)       # decode arrow keys / KEY_RESIZE
        try:
            curses.curs_set(0)         # hide the caret
        except curses.error:
            pass                       # not all terminals can
        self.rows, self.cols = self.stdscr.getmaxyx()
        logger.info("Terminal size: %dx%d characters", self.cols, self.rows)
        self.colour_ok = self._start_colour()

        self.scheme = None
        self._pad_attr = curses.A_NORMAL
        self.set_scheme(palettes.SCHEMES[0])

    def _start_colour(self):
        """
        Decide whether the terminal can do 256-colour work at all.

        Returns True if colour is usable. Measured on this Pi inside lxterminal:
        TERM=xterm-256color, 256 colours and 65,536 pairs available, so the 240
        pairs the schemes want are not close to any limit.
        """
        try:
            curses.start_color()
            if not curses.has_colors() or curses.COLORS < 256:
                logger.info("Colour unavailable: has_colors=%s COLORS=%s",
                            curses.has_colors(), getattr(curses, "COLORS", "?"))
                return False
            # Permits -1 as a colour, meaning "whatever the terminal already is".
            curses.use_default_colors()
            logger.info("Colour ready: %d colours, %d pairs",
                        curses.COLORS, curses.COLOR_PAIRS)
            return True
        except curses.error as e:
            logger.info("Colour setup failed: %s", e)
            return False

    def set_scheme(self, scheme):
        """
        Adopt a colour scheme, re-colouring the whole canvas.

        A terminal only ever paints a character's ink; whatever lies behind the
        glyph stays whatever the window already was.  That is fine for the
        dark-screen schemes, whose background is roughly the black already
        there, but a light-screen one (paper, lime, azure) would come out as
        near-black ink on black and all but vanish.  So the screen colour is
        attached to every pair as its *background*, and to the window itself,
        which covers the padding around the picture and any cell not written
        this frame.
        """
        self.scheme = scheme
        if not self.colour_ok or scheme.kind == "grey":
            # -1 keeps the terminal's own background, which is what greyscale
            # has always done and all a colourless terminal can manage.
            self._paint_pairs(-1)
            self._pad_attr = curses.A_NORMAL
        else:
            background = palettes.nearest_xterm(scheme.screen)
            self._paint_pairs(background)
            try:
                curses.init_pair(BACKGROUND_PAIR,
                                 palettes.nearest_xterm(scheme.ink), background)
                self._pad_attr = curses.color_pair(BACKGROUND_PAIR)
            except curses.error:
                self._pad_attr = curses.A_NORMAL

        try:
            # Applies to blanks and to anything not explicitly written.
            self.stdscr.bkgd(" ", self._pad_attr)
        except curses.error:
            pass
        self.stdscr.clear()
        logger.info("Scheme: %s (%s)", scheme.name, scheme.note)

    def _paint_pairs(self, background):
        """Point every colour pair at `background`, each keeping its own ink."""
        if not self.colour_ok:
            return
        for index in range(16, 256):
            try:
                curses.init_pair(index, index, background)
            except curses.error:
                pass

    @property
    def canvas_size(self):
        """(cols, rows) available for the picture, excluding the status line."""
        return self.cols, max(1, self.rows - 1)

    def cell_metrics(self):
        """
        (cell_width_px, cell_height_px), or None if the terminal won't say.

        TIOCGWINSZ carries optional pixel dimensions alongside the character
        grid. When a terminal fills them in, the cell shape - and so the aspect
        correction the picture needs - can be derived exactly instead of
        assumed, and it stays right across a live font-size change.

        lxterminal/VTE reports 0x0 here (measured), so this returns None there
        and the caller keeps its --cell-aspect value. foot, kitty and xterm do
        report real numbers.
        """
        try:
            packed = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ,
                                 b"\0" * 8)
            rows, cols, xpix, ypix = struct.unpack("HHHH", packed)
        except OSError:
            return None

        if not (rows and cols and xpix and ypix):
            return None
        return xpix / cols, ypix / rows

    def refresh_size(self):
        """
        Re-read the terminal size.

        Returns True if it changed, so the caller can refit the ASCII grid.
        """
        rows, cols = self.stdscr.getmaxyx()
        if (rows, cols) != (self.rows, self.cols):
            self.rows, self.cols = rows, cols
            self.stdscr.clear()
            logger.info("Terminal resized to %dx%d characters", cols, rows)
            return True
        return False

    def clear(self):
        """Force a full repaint on the next render."""
        self.stdscr.clear()

    def render(self, ascii_lines, status="", colours=None):
        """
        Draw one frame, centred, with a status line along the bottom.

        Args:
            ascii_lines: List of strings, one per grid row.
            status: Text for the reverse-video status line.
            colours: Optional (rows, cols) array of xterm palette indices, one
                per character. When given, each row is drawn as coloured runs.
        """
        canvas_rows = max(1, self.rows - 1)
        picture_height = min(len(ascii_lines), canvas_rows)
        top = (canvas_rows - picture_height) // 2
        use_colour = colours is not None and self.colour_ok

        for screen_row in range(canvas_rows):
            index = screen_row - top
            if not 0 <= index < picture_height:
                self._write(screen_row, 0, " " * self.cols, self._pad_attr)
                continue

            line = ascii_lines[index][:self.cols]
            left = (self.cols - len(line)) // 2
            if use_colour:
                self._write(screen_row, 0, " " * left, self._pad_attr)
                self._write_runs(screen_row, left, line, colours[index])
                trailing = self.cols - left - len(line)
                if trailing > 0:
                    self._write(screen_row, left + len(line),
                                " " * trailing, self._pad_attr)
            else:
                # Pad out to the full width so the previous frame's characters
                # are overwritten without needing a clear().
                self._write(screen_row, 0,
                            (" " * left + line).ljust(self.cols),
                            self._pad_attr)

        self._write_status(status)
        self.stdscr.refresh()

    def _write_status(self, status):
        try:
            self.stdscr.addstr(self.rows - 1, 0,
                               status[:self.cols - 1].ljust(self.cols - 1),
                               curses.A_REVERSE)
        except curses.error:
            pass

    def _write(self, row, col, text, attr=curses.A_NORMAL):
        try:
            self.stdscr.addstr(row, col, text, attr)
        except curses.error:
            # addstr on the final cell of a row is allowed to fail; the
            # character is written regardless.
            pass

    def _write_runs(self, row, col, line, colour_row):
        """
        Draw one row as runs of constant colour.

        One addstr per run rather than per character: at 133x50 a real scene
        averages a dozen or so runs per row, so this is roughly an order of
        magnitude fewer calls than colouring each cell, and it lets ncurses emit
        a single escape sequence per run.
        """
        indices = np.asarray(colour_row[:len(line)])
        if indices.size == 0:
            return
        # Boundaries wherever the palette index changes along the row.
        edges = np.flatnonzero(indices[1:] != indices[:-1]) + 1
        starts = np.concatenate(([0], edges))
        ends = np.concatenate((edges, [indices.size]))

        for start, end in zip(starts.tolist(), ends.tolist()):
            try:
                self.stdscr.addstr(row, col + start, line[start:end],
                                   curses.color_pair(int(indices[start])))
            except curses.error:
                pass

    def get_key(self):
        """Return the pressed key as a string, or None. Never blocks."""
        try:
            ch = self.stdscr.getch()
        except curses.error:
            return None
        if ch == curses.ERR or ch < 0:
            return None
        if ch == curses.KEY_RESIZE:
            return "RESIZE"
        if 0 <= ch < 256:
            return chr(ch)
        return None

    def close(self):
        """Nothing to release - curses.wrapper restores the terminal."""

    def message(self, text):
        """Show a single centred line - used while the camera warms up."""
        self.stdscr.erase()
        self._write(self.rows // 2, max(0, (self.cols - len(text)) // 2),
                    text[:self.cols - 1], self._pad_attr)
        self.stdscr.refresh()
