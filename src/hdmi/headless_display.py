"""
A stand-in display for when there is no terminal to draw on.

Used when the app runs with only the SPI panel attached: no curses, no window,
nothing on the HDMI screen. It implements the same surface NcursesDisplay does
so the render loop needs no special cases - the one thing that differs is
`draws`, which is False, and which the loop reads to skip building the ASCII
text and colour grid altogether. That is not just tidiness: at 267x100 those
two steps are most of the per-frame cost, and in this mode nothing would ever
look at the result.

Keyboard control still works when there is a terminal on the *other* end, as
there is over SSH. stdin is put in cbreak mode and polled without blocking, so
the same single-key controls apply. When stdin is not a terminal - a systemd
unit, a cron job, output piped somewhere - key reading is simply disabled and
the app runs on whatever the command line asked for.
"""

import logging
import os
import select
import sys
import time

logger = logging.getLogger(__name__)

try:
    import termios
    import tty
    _POSIX_TTY = True
except ImportError:                     # not POSIX; keys just stay unavailable
    _POSIX_TTY = False

# How often the status line is reprinted. The terminal build redraws it every
# frame, but here it goes to a scrolling stdout, so once every few seconds is
# informative rather than a flood.
STATUS_INTERVAL = 5.0


class HeadlessDisplay:
    """Draws nothing, but still carries the settings and reads the keyboard."""

    # The render loop reads this to decide whether to build a picture at all.
    draws = False

    def __init__(self, status_interval=STATUS_INTERVAL, stream=None):
        """
        Args:
            status_interval: Seconds between status lines on stdout.
            stream: Where status lines go. Defaults to stdout.
        """
        # Schemes are still meaningful - the panel renders them - so this must
        # not report a colourless display, or scheme cycling would be refused.
        self.colour_ok = True
        self.scheme = None

        # A plausible width so the status line's own trimming behaves; nothing
        # is laid out against it.
        self.cols = 80
        self.rows = 24

        self.stream = stream or sys.stdout
        self.status_interval = status_interval
        self._last_status = 0.0
        self._last_message = None

        self._fd = None
        self._saved = None
        self._start_keyboard()

    # ---- keyboard -------------------------------------------------------

    def _start_keyboard(self):
        """Put stdin in cbreak mode, if stdin is a terminal at all."""
        if not _POSIX_TTY:
            return
        try:
            if not sys.stdin.isatty():
                logger.info("stdin is not a terminal; live keys are disabled")
                return
            self._fd = sys.stdin.fileno()
            self._saved = termios.tcgetattr(self._fd)
            # cbreak rather than raw: it delivers keys immediately without
            # waiting for a newline, while leaving Ctrl-C working as normal.
            tty.setcbreak(self._fd)
            logger.info("Live keys enabled on stdin")
        except (termios.error, ValueError, OSError) as e:
            logger.info("Could not set up the keyboard: %s", e)
            self._fd = None

    def get_key(self):
        """Return the pressed key as a string, or None. Never blocks."""
        if self._fd is None:
            return None
        try:
            if not select.select([self._fd], [], [], 0)[0]:
                return None
            data = os.read(self._fd, 1)
        except OSError:
            return None
        if not data:
            return None
        return data.decode("ascii", "ignore") or None

    def close(self):
        """Give stdin back the settings it had."""
        if self._fd is not None and self._saved is not None:
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
            except (termios.error, OSError):
                pass
            self._fd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    # ---- the display surface, mostly doing nothing ----------------------

    def set_scheme(self, scheme):
        """Remember the scheme; the panel is what actually shows it."""
        self.scheme = scheme
        logger.info("Scheme: %s (%s)", scheme.name, scheme.note)

    @property
    def canvas_size(self):
        """Nominal only - nothing is drawn here, so nothing is fitted to it."""
        return self.cols, self.rows

    def cell_metrics(self):
        """No cells, so no metrics; the caller keeps its --cell-aspect."""
        return None

    def refresh_size(self):
        """Nothing can resize, so nothing ever changed."""
        return False

    def clear(self):
        pass

    def render(self, ascii_lines, status="", colours=None):
        """
        Print the status line occasionally, and discard the picture.

        `ascii_lines` arrives empty in this mode - the loop skips building it -
        so there is nothing to throw away in practice.
        """
        now = time.monotonic()
        if status and now - self._last_status >= self.status_interval:
            self._last_status = now
            self._write(status.strip())

    def message(self, text):
        """Show a one-off line, but only when it changes."""
        if text != self._last_message:
            self._last_message = text
            self._write(text)

    def _write(self, text):
        try:
            # \r first: in cbreak mode the cursor may not be at column 0.
            self.stream.write("\r" + text + "\n")
            self.stream.flush()
        except (OSError, ValueError):
            pass
