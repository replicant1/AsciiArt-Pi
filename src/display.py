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

logger = logging.getLogger(__name__)


class NcursesDisplay:
    """Renders ASCII art frames to the terminal."""

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

    def render(self, ascii_lines, status=""):
        """
        Draw one frame, centred, with a status line along the bottom.

        Args:
            ascii_lines: List of strings, one per grid row.
            status: Text for the reverse-video status line.
        """
        canvas_rows = max(1, self.rows - 1)
        picture_height = min(len(ascii_lines), canvas_rows)
        top = (canvas_rows - picture_height) // 2

        for screen_row in range(canvas_rows):
            index = screen_row - top
            if 0 <= index < picture_height:
                line = ascii_lines[index][:self.cols]
                left = (self.cols - len(line)) // 2
                # Pad out to the full width so the previous frame's characters
                # are overwritten without needing a clear().
                line = " " * left + line
            else:
                line = ""
            try:
                self.stdscr.addstr(screen_row, 0, line.ljust(self.cols))
            except curses.error:
                # addstr on the final cell of a row is allowed to fail; the
                # character is written regardless.
                pass

        try:
            self.stdscr.addstr(self.rows - 1, 0,
                               status[:self.cols - 1].ljust(self.cols - 1),
                               curses.A_REVERSE)
        except curses.error:
            pass

        self.stdscr.refresh()

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

    def message(self, text):
        """Show a single centred line - used while the camera warms up."""
        self.stdscr.erase()
        try:
            self.stdscr.addstr(self.rows // 2,
                               max(0, (self.cols - len(text)) // 2),
                               text[:self.cols - 1])
        except curses.error:
            pass
        self.stdscr.refresh()
