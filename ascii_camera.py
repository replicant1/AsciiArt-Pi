#!/usr/bin/env python3
"""
ASCII Art Live Camera Preview for Raspberry Pi Zero 2.

Captures video from the Camera Module 2 and renders it as ASCII art in the
terminal on the HDMI screen.

    python3 ascii_camera.py                        # sensible defaults
    python3 ascii_camera.py --fps 8 --width 160 --height 120   # even lighter
    python3 ascii_camera.py --help

Press 'q' to quit; other live controls are listed in the status line.
"""

import argparse
import logging
import os
import signal
import sys
import time
from collections import deque
from pathlib import Path

# libcamera's C++ layer logs to stderr unconditionally.  Quieten it here, and
# main() redirects fd 2 to the log file anyway - anything written to the
# terminal while curses owns it corrupts the picture.
os.environ.setdefault("LIBCAMERA_LOG_LEVELS", "*:ERROR")

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import curses  # noqa: E402

import palettes  # noqa: E402
from ascii_art import RAMPS, AsciiArt  # noqa: E402
from camera import CameraCapture  # noqa: E402
from display import NcursesDisplay  # noqa: E402
from headless import HeadlessDisplay  # noqa: E402
from image_processor import ImageProcessor, fit_grid  # noqa: E402

logger = logging.getLogger("ascii_camera")

# Derived from RAMPS rather than repeated, so adding or removing a ramp is a
# one-line change in ascii_art.py and cannot leave the c key cycling through a
# name that no longer exists.
RAMP_CYCLE = list(RAMPS)


def _on_off(flag):
    """Render a toggle's state for the status line."""
    return "on" if flag else "off"


class AsciiArtLiveCamera:
    """Capture -> process -> ASCII -> terminal, once per frame."""

    def __init__(self, display, args):
        self.display = display
        self.args = args

        self.camera = CameraCapture(
            resolution=(args.width, args.height),
            frame_rate=args.fps,
        )
        self.processor = ImageProcessor(
            contrast=args.contrast,
            auto_levels=not args.no_auto_levels,
            rotation=args.rotation,
            fill=args.fill,
            cell_aspect=args.cell_aspect,
            mirror=args.mirror,
        )
        # argparse has already restricted --ramp to a name in the cycle, so the
        # index is always found and the two can never disagree.
        self.ramp_name = args.ramp
        self.ramp_index = RAMP_CYCLE.index(args.ramp)
        self.invert = args.invert
        self.colour_levels = args.colour_levels
        # --scheme wins; --colour is kept as the old way of asking for the
        # live-colour scheme, since run_ascii_camera.sh reads it to size the
        # window.
        start = args.scheme or ("live" if args.colour else "grey")
        self.scheme_index = palettes.SCHEME_NAMES.index(palettes.by_name(
            start).name)
        self.display.set_scheme(self.scheme)
        self._rebuild_ascii()

        self.grid = None            # (cols, rows), recomputed lazily
        self.grid_key = None        # inputs the grid was computed from
        self.cell_aspect = args.cell_aspect
        self._refresh_cell_aspect()
        self.frame_count = 0
        self.dropped = 0
        self.frame_times = deque(maxlen=20)
        self.is_running = False

        self._lcd_config_type = None
        self.lcd = self._start_lcd() if args.lcd else None
        self.encoder = self._start_encoder() if args.encoder else None

        # Losing the panel is survivable when there is a terminal to fall back
        # on, and _start_lcd deliberately treats it that way. With no terminal
        # either, the app would run the camera and show the result to nobody,
        # so that combination is refused rather than left looking like a hang.
        if not display.draws and self.lcd is None:
            raise RuntimeError(
                "no output: the terminal is switched off and the LCD panel "
                f"did not start. See {args.log} for why.")

    def _start_lcd(self):
        """
        Bring the SPI panel up as a second, independent output.

        Deliberately not fatal on failure.  The terminal is the primary display
        and a missing, unwired or misbehaving panel should cost a log line, not
        the whole app.  The imports are done here rather than at module level so
        that spidev and RPi.GPIO are only required when the panel is asked for.
        """
        try:
            from lcd_display import LcdDisplay
            from lcd_worker import LcdConfig, LcdWorker

            display = LcdDisplay(
                ramp=self.ascii_art.chars,
                font_size=self.args.lcd_font_size,
                landscape=not self.args.lcd_portrait,
                spi_freq=self.args.lcd_spi_hz,
                brightness=self.args.lcd_brightness,
            )
            worker = LcdWorker(display)
            worker.start()
            self._lcd_config_type = LcdConfig
            logger.info("LCD enabled: %dx%d grid", *display.grid_size)
            return worker
        except Exception as e:
            logger.error("LCD unavailable, continuing without it: %s", e,
                         exc_info=True)
            return None

    def _start_encoder(self):
        """
        Bring the rotary encoder up, or carry on without it.

        Not fatal on failure, for the same reason the LCD is not: the knob is a
        convenience over a key that still works, so an unplugged or misconfigured
        encoder should cost a log line rather than the whole app.  lgpio is
        imported inside RotaryEncoder so this stays runnable off the Pi.
        """
        try:
            from encoder import RotaryEncoder

            return RotaryEncoder(clk=self.args.encoder_clk,
                                 dt=self.args.encoder_dt,
                                 reverse=self.args.encoder_reverse).start()
        except Exception as e:
            logger.error("Rotary encoder unavailable, continuing without "
                         "it: %s", e, exc_info=True)
            return None

    def _poll_encoder(self):
        """Turn accumulated knob movement into scheme changes."""
        if self.encoder is None:
            return
        steps = self.encoder.take()
        if not steps:
            return

        # Handed over as one move, not one call per detent: everything banked
        # since the last frame lands on a single repaint. See _cycle_scheme.
        self._cycle_scheme(steps)

    def _lcd_config(self):
        """Snapshot of the settings the LCD mirrors from this display."""
        return self._lcd_config_type(
            rotation=self.processor.rotation,
            contrast=self.processor.contrast,
            auto_levels=self.processor.auto_levels,
            invert=self.invert,
            ramp=self.ramp_name,
            scheme=self.scheme.name,
            colour_levels=self.colour_levels,
            mirror=self.processor.mirror,
        )

    @property
    def scheme(self):
        """The active colour scheme."""
        return palettes.SCHEMES[self.scheme_index]

    def _cycle_scheme(self, step=1):
        """
        Step to the next scheme, skipping any this terminal cannot show.

        Args:
            step: +1 for the next scheme, -1 for the previous one.  The
                keyboard only ever goes forwards, but a knob that could not go
                back would be a poor knob.
        """
        count = len(palettes.SCHEMES)
        direction = 1 if step >= 0 else -1

        # Walk to the destination first and change the display once, rather
        # than changing it at every scheme on the way. set_scheme() repaints
        # the whole window - it has to, since a light-screen scheme needs a
        # different background on every cell - so a five-detent move applied
        # one scheme at a time is five full repaints of pictures that are never
        # on screen long enough to be seen. That is visible as a hard strobe,
        # and the slower the scheme the worse it gets, because a slow frame
        # gives the knob more time to bank detents before anything is drawn.
        #
        # A whole lap is the identity, so the count reduces modulo the list
        # length; clamping to it instead lands a lap off.
        index = self.scheme_index
        for _ in range(abs(step) % count):
            for offset in range(1, count + 1):
                candidate = (index + direction * offset) % count
                if (palettes.SCHEMES[candidate].kind == "grey"
                        or self.display.colour_ok):
                    index = candidate
                    break
            else:
                return

        if index == self.scheme_index:
            return
        self.scheme_index = index
        self.display.set_scheme(self.scheme)
        # No grid invalidation here on purpose: the grid does not depend on the
        # scheme any more, so recomputing it would only produce the same answer
        # and log a line claiming a change that did not happen.
        logger.info("Scheme: %s (%s)", self.scheme.name, self.scheme.note)

    def _colours_for(self, frame, processed, cols, rows):
        """
        Per-cell terminal palette indices for the active scheme, or None.

        None means "draw in the terminal's own foreground colour", which is
        what greyscale wants and is also the cheapest path.
        """
        scheme = self.scheme
        if not self.display.colour_ok or scheme.kind == "grey":
            return None
        if scheme.kind == "live":
            rgb = self.processor.colour_grid(frame, processed, cols, rows)
            return self.ascii_art.to_colour_indices(rgb)
        # Tinted: one gather straight from ramp position to palette index.
        indices = self.ascii_art.to_indices(processed)
        table = palettes.index_table(scheme, len(self.ascii_art.chars),
                                     self.invert)
        return table[indices]

    def _rebuild_ascii(self):
        """Rebuild the generator, carrying every current setting."""
        self.ascii_art = AsciiArt(ramp=self.ramp_name, invert=self.invert,
                                  colour_levels=self.colour_levels)

    def _refresh_cell_aspect(self):
        """
        Take the character cell shape from the terminal when it reports one.

        This is what lets the picture stay correctly proportioned if the font
        size changes underneath us - a terminal that reports pixel dimensions
        gives a new cell aspect the moment its font changes. lxterminal does
        not report them, so there --cell-aspect stands.
        """
        metrics = self.display.cell_metrics()
        if metrics is None:
            return

        cell_w, cell_h = metrics
        aspect = round(cell_h / cell_w, 3)
        if aspect != self.cell_aspect:
            logger.info("Cell aspect from terminal: %.3f (cell %.2fx%.2f px)",
                        aspect, cell_w, cell_h)
            self.cell_aspect = aspect
            self.processor.cell_aspect = aspect
            self.grid_key = None

    def _grid_for(self, frame_shape):
        """Fit the ASCII grid to the terminal, preserving the camera aspect."""
        src_h, src_w = frame_shape
        width, height = self.processor.source_size(src_w, src_h)
        max_cols, max_rows = self.display.canvas_size

        # The colour scheme is deliberately not part of this key. The grid
        # depends on the window and the camera, and on nothing else, so
        # switching scheme with `s` never resizes the picture.
        key = (width, height, max_cols, max_rows, self.cell_aspect,
               self.processor.fill)
        if key != self.grid_key:
            if self.processor.fill:
                # Use every cell; process() crops the frame to suit.
                self.grid = (max_cols, max_rows)
            else:
                self.grid = fit_grid(width, height, max_cols, max_rows,
                                     self.cell_aspect)
            self.grid_key = key
            logger.info("ASCII grid: %dx%d characters (source %dx%d, "
                        "terminal %dx%d, fill=%s)", self.grid[0], self.grid[1],
                        width, height, max_cols, max_rows + 1,
                        self.processor.fill)
        return self.grid

    def _status(self):
        """
        Text for the bottom status line, trimmed to what the window can show.

        Rather than let a fixed string get chopped mid-word, drop whole
        sections from the right until it fits.
        """
        if len(self.frame_times) > 1:
            span = self.frame_times[-1] - self.frame_times[0]
            fps = (len(self.frame_times) - 1) / span if span > 0 else 0.0
        else:
            fps = 0.0

        cols, rows = self.grid or (0, 0)
        geometry = f"{cols}x{rows}" if self.display.draws else "headless"
        ramp = self.ramp_name
        stats = (f" {fps:4.1f}fps {geometry} rot{self.processor.rotation}"
                 f" con{self.processor.contrast:.1f}"
                 f" sch:{self.scheme.name}"
                 f" chr:{ramp}"
                 f" auto:{_on_off(self.processor.auto_levels)}"
                 f" fill:{_on_off(self.processor.fill)}"
                 f" inv:{_on_off(self.invert)}")

        if self.lcd is not None:
            # Showing the panel's own grid makes its independence from the
            # terminal's visible: resizing the window moves one and not the
            # other.
            stats += " lcd:%dx%d" % self.lcd.display.grid_size

        width = self.display.cols - 1
        for keys in (" | q:quit r:rotate f:fill i:invert c:chars +/-:contrast"
                     " a:auto s:scheme",
                     " | q:quit r:rotate f:fill i:invert c:chars s:scheme",
                     " | q:quit r:rotate f:fill s:scheme",
                     " | q:quit",
                     ""):
            if len(stats) + len(keys) <= width:
                return stats + keys
        return stats

    def _handle_key(self, key):
        """Apply a live control key. Returns False to quit."""
        if key in ("q", "Q"):
            logger.info("User quit")
            return False
        if key == "RESIZE":
            self.display.refresh_size()
            self.grid_key = None
        elif key in ("r", "R"):
            self.processor.rotation = (self.processor.rotation + 90) % 360
            self.grid_key = None
        elif key in ("s", "S"):
            self._cycle_scheme()
        elif key in ("f", "F"):
            self.processor.fill = not self.processor.fill
            self.grid_key = None
            self.display.clear()
        elif key in ("i", "I"):
            self.invert = not self.invert
            self._rebuild_ascii()
        elif key in ("c", "C"):
            self.ramp_index = (self.ramp_index + 1) % len(RAMP_CYCLE)
            self.ramp_name = RAMP_CYCLE[self.ramp_index]
            self._rebuild_ascii()
        elif key in ("+", "="):
            self.processor.contrast = min(4.0, self.processor.contrast + 0.1)
        elif key in ("-", "_"):
            self.processor.contrast = max(0.1, self.processor.contrast - 0.1)
        elif key in ("a", "A"):
            self.processor.auto_levels = not self.processor.auto_levels
        return True

    def _install_signal_handlers(self):
        """
        Stop cleanly when signalled, not just when 'q' is pressed.

        This matters most headless. With no terminal on stdin there is no 'q'
        to press, so a signal is the only way such a run ever ends - and
        Python's default SIGTERM handling exits without unwinding, so the
        `finally` that stops the camera and releases the panel never runs. The
        panel is left lit with a frozen frame and its GPIO pins still claimed,
        which then breaks the next run.
        """
        def stop(signum, _frame):
            logger.info("Signal %d received; shutting down", signum)
            self.is_running = False

        for received in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(received, stop)
            except ValueError:
                # Only the main thread may install handlers; a caller running
                # this elsewhere keeps the default behaviour.
                logger.info("Could not handle signal %d here", received)

    def run(self):
        """Main loop."""
        self._install_signal_handlers()
        self.display.message("Starting camera, please wait...")
        self.camera.start()
        self.is_running = True
        started = time.time()

        try:
            while self.is_running:
                if self.display.refresh_size():
                    self.grid_key = None
                    # A resize may also mean the font changed under us.
                    self._refresh_cell_aspect()

                frame = self.camera.get_frame(timeout=1.0)
                if frame is None:
                    # The camera caps its own rate, so a miss here means it is
                    # still warming up (or has stalled) rather than that we are
                    # polling too fast.
                    self.dropped += 1
                    self.display.message("Waiting for camera...")
                    if not self._drain_input():
                        break
                    continue

                # Hand the panel the frame before doing any work for the
                # terminal, so the two renders overlap instead of queueing.
                if self.lcd is not None:
                    self.lcd.submit(frame, self._lcd_config())

                if self.display.draws:
                    cols, rows = self._grid_for(frame.shape)
                    try:
                        processed = self.processor.process(frame.luma,
                                                           cols, rows)
                        ascii_lines = self.ascii_art.to_ascii_text(processed)
                        colours = self._colours_for(frame, processed,
                                                    cols, rows)
                    except Exception as e:
                        logger.error("Frame processing failed: %s", e,
                                     exc_info=True)
                        continue
                else:
                    # No terminal: the panel does its own downscale and
                    # character mapping on its own thread, so building a
                    # picture here would be work nothing ever looks at.
                    ascii_lines, colours = (), None

                self.frame_count += 1
                self.frame_times.append(time.time())
                self.display.render(ascii_lines, self._status(), colours)

                if not self._drain_input():
                    break

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self.is_running = False
            elapsed = time.time() - started
            avg = self.frame_count / elapsed if elapsed > 0 else 0
            self.camera.stop()
            if self.lcd is not None:
                self.lcd.stop()
            if self.encoder is not None:
                # Releasing the pins matters as much as it does for the panel:
                # a claim left behind makes the next run's start() fail.
                self.encoder.stop()
            logger.info("Rendered %d frames in %.1fs (%.1f avg fps), "
                        "%d camera timeouts", self.frame_count, elapsed,
                        avg, self.dropped)

    def _drain_input(self):
        """
        Apply everything the user has done since the last frame.

        The knob is read here rather than on its own timer so that it lands in
        the same place in the loop as a keypress: one scheme change per frame
        at most, applied before the next frame is drawn.
        """
        self._poll_encoder()
        while True:
            key = self.display.get_key()
            if key is None:
                return True
            if not self._handle_key(key):
                return False


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="ASCII Art Live Camera Preview for Raspberry Pi",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--width", type=int, default=320,
                        help="Camera capture width (the ISP downscales in "
                             "hardware, so smaller is much cheaper)")
    parser.add_argument("--height", type=int, default=240,
                        help="Camera capture height")
    parser.add_argument("--fps", type=int, default=15,
                        help="Target frame rate")
    parser.add_argument("--scheme", choices=palettes.SCHEME_NAMES,
                        help="Colour scheme to start in; step through them "
                             "live with s. "
                             + "; ".join(f"{s.name}: {s.note}"
                                         for s in palettes.SCHEMES))
    parser.add_argument("--colour", "--color", action="store_true",
                        dest="colour",
                        help="Shorthand for --scheme live. Ignored if "
                             "--scheme is given")
    parser.add_argument("--colour-levels", type=int, default=6,
                        choices=[2, 3, 4, 5, 6],
                        help="Palette steps per channel in colour mode. "
                             "Fewer means longer runs of one colour and a "
                             "cheaper redraw")
    parser.add_argument("--fill", action="store_true",
                        help="Crop the picture to fill the whole window "
                             "instead of letterboxing it to fit")
    parser.add_argument("--mirror", action="store_true",
                        help="Flip the picture left to right, after any "
                             "rotation. Off by default: the sensor is "
                             "delivering the picture the right way round as "
                             "currently mounted")
    parser.add_argument("--rotation", type=int, default=0,
                        choices=[0, 90, 180, 270],
                        help="Camera rotation in degrees. Cycle with r")
    parser.add_argument("--contrast", type=float, default=1.0,
                        help="Contrast multiplier about mid-grey")
    parser.add_argument("--no-auto-levels", action="store_true",
                        help="Disable per-frame brightness normalisation")
    parser.add_argument("--ramp", default="coarse", choices=RAMP_CYCLE,
                        help="Character ramp, ordered light to dark. Cycle "
                             "with c")
    parser.add_argument("--invert", action="store_true",
                        help="Invert the ramp (for light-background terminals)")
    parser.add_argument("--cell-aspect", type=float, default=2.0,
                        help="Terminal character height/width ratio, used to "
                             "keep the picture from looking squashed")
    parser.add_argument("--no-terminal", action="store_true",
                        help="Draw nothing on the HDMI screen: no curses, no "
                             "window. Needs --lcd, since otherwise there is "
                             "no output at all. The single-key controls still "
                             "work when stdin is a terminal, as it is over SSH")
    lcd = parser.add_argument_group(
        "ILI9341 SPI panel",
        "A second, independent output. Its grid is fixed by the font and is "
        "unaffected by the terminal window's size; it always fills the panel, "
        "so --fill is not mirrored. Colour, invert, ramp, rotation, contrast "
        "and auto-levels are.")
    lcd.add_argument("--lcd", action="store_true",
                     help="Also render to the SPI panel")
    lcd.add_argument("--lcd-font-size", type=int, default=8,
                     help="Glyph size, which sets the panel's grid. 8 gives "
                          "64x24, 6 gives 80x30 and 9 gives 64x20; all three "
                          "tile 320x240 exactly and match the camera's 4:3, so "
                          "nothing is cropped or letterboxed")
    lcd.add_argument("--lcd-portrait", action="store_true",
                     help="Run the panel as 240x320 instead of 320x240")
    lcd.add_argument("--lcd-spi-hz", type=int, default=40_000_000,
                     help="SPI clock. Lower it if the wiring is long or on a "
                          "breadboard")
    lcd.add_argument("--lcd-brightness", type=int, default=100,
                     help="Backlight duty cycle, 0-100")
    knob = parser.add_argument_group(
        "KY-040 rotary encoder",
        "A knob that steps through the colour schemes, doing what s does from "
        "the keyboard - except that it also goes backwards. Works headless, "
        "where there is no keyboard to press s on.")
    knob.add_argument("--encoder", action="store_true",
                      help="Cycle colour schemes with the rotary encoder")
    knob.add_argument("--encoder-clk", type=int, default=19,
                      help="BCM pin for CLK")
    knob.add_argument("--encoder-dt", type=int, default=26,
                      help="BCM pin for DT")
    knob.add_argument("--encoder-reverse", action="store_true",
                      help="Swap which way the knob steps. Which rotation "
                           "counts as forwards depends on which pin was wired "
                           "to CLK, so if the knob runs backwards, add this")
    parser.add_argument("--log", default=str(Path(__file__).resolve().parent
                                             / "ascii_camera.log"),
                        help="Log file (stderr is redirected here too)")
    parser.add_argument("--verbose", action="store_true",
                        help="Debug-level logging")
    return parser.parse_args(argv)


def setup_logging(path, verbose):
    """
    Send all logging - and all of stderr - to a file.

    curses owns the terminal, so a single stray line written to it garbles the
    picture until the next full repaint.  Redirecting the file descriptor
    itself also captures output from libcamera's C++ layer, which never goes
    through Python's logging at all.
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        filename=path,
        filemode="a",
    )
    logging.getLogger("picamera2").setLevel(logging.WARNING)

    stderr_sink = open(path, "a", buffering=1)
    os.dup2(stderr_sink.fileno(), sys.stderr.fileno())
    return stderr_sink


def main(argv=None):
    args = parse_args(argv)

    # Caught before the log is even opened: this one is a usage mistake, not a
    # runtime failure, and the message belongs on the terminal the user is
    # standing at rather than in a file.
    if args.no_terminal and not args.lcd:
        print("--no-terminal needs --lcd: together they would produce no "
              "output at all.\nEither drop --no-terminal, or add --lcd.")
        return 2

    setup_logging(args.log, args.verbose)
    logger.info("=== ASCII Art Live Camera starting: %s ===", vars(args))

    def bootstrap(stdscr):
        display = NcursesDisplay(stdscr)
        AsciiArtLiveCamera(display, args).run()

    try:
        if args.no_terminal:
            # No curses.wrapper here: there is no screen to put into a special
            # mode and restore afterwards. HeadlessDisplay still has stdin to
            # give back, which is what the context manager is for.
            with HeadlessDisplay() as display:
                AsciiArtLiveCamera(display, args).run()
        else:
            curses.wrapper(bootstrap)
    except Exception as e:
        # The terminal has been restored by now, so this is safe to print.
        logger.error("Fatal error: %s", e, exc_info=True)
        print(f"ASCII camera failed: {e}\nSee {args.log} for details.")
        return 1

    print(f"ASCII camera stopped. Log: {args.log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
