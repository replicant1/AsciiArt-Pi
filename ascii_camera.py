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

RAMP_CYCLE = ["standard", "fine", "blocks"]


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
        # Track the ramp by name, not just by index into RAMP_CYCLE: --ramp
        # also accepts a literal character string, which is not in the cycle.
        self.ramp_name = args.ramp
        self.ramp_index = (RAMP_CYCLE.index(args.ramp)
                           if args.ramp in RAMP_CYCLE else 0)
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

    @property
    def colour(self):
        """
        True when the picture's colour comes from the camera.

        Only the live scheme pays the coarser grid: it needs a different colour
        for every cell, whereas a tinted scheme gives neighbouring cells of
        equal brightness the same colour, so its runs stay long and its redraw
        cheap.
        """
        return self.scheme.kind == "live"

    def _cycle_scheme(self):
        """Step to the next scheme, skipping any this terminal cannot show."""
        count = len(palettes.SCHEMES)
        for step in range(1, count + 1):
            candidate = palettes.SCHEMES[(self.scheme_index + step) % count]
            if candidate.kind == "grey" or self.display.colour_ok:
                self.scheme_index = (self.scheme_index + step) % count
                break
        else:
            return

        self.display.set_scheme(self.scheme)
        self.grid_key = None        # the live scheme uses a coarser grid
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

        key = (width, height, max_cols, max_rows, self.cell_aspect,
               self.processor.fill, self.colour)
        if key != self.grid_key:
            if self.processor.fill:
                # Use every cell; process() crops the frame to suit.
                self.grid = (max_cols, max_rows)
            else:
                self.grid = fit_grid(width, height, max_cols, max_rows,
                                     self.cell_aspect)
            if self.colour:
                # Colour redraw costs several times greyscale, so coarsen the
                # grid. Dividing both axes equally keeps the aspect correct.
                d = max(1, self.args.colour_divisor)
                self.grid = (max(8, self.grid[0] // d),
                             max(4, self.grid[1] // d))
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
        # A literal --ramp string has no name to show, so label it "custom".
        ramp = self.ramp_name if self.ramp_name in RAMPS else "custom"
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
                    if not self._drain_keys():
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

                if not self._drain_keys():
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
            logger.info("Rendered %d frames in %.1fs (%.1f avg fps), "
                        "%d camera timeouts", self.frame_count, elapsed,
                        avg, self.dropped)

    def _drain_keys(self):
        """Process every buffered keypress. Returns False if asked to quit."""
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
    parser.add_argument("--colour-divisor", type=int, default=2,
                        help="How much coarser the grid becomes in colour "
                             "mode, on both axes")
    parser.add_argument("--fill", action="store_true",
                        help="Crop the picture to fill the whole window "
                             "instead of letterboxing it to fit")
    parser.add_argument("--no-mirror", action="store_false", dest="mirror",
                        help="Do not flip the picture left to right. The flip "
                             "is on by default because this camera's mounting "
                             "needs it: the sensor is upside down, and a 180 "
                             "degree rotation corrects that but mirrors the "
                             "picture as a side effect")
    parser.add_argument("--rotation", type=int, default=180,
                        choices=[0, 90, 180, 270],
                        help="Camera rotation in degrees")
    parser.add_argument("--contrast", type=float, default=1.0,
                        help="Contrast multiplier about mid-grey")
    parser.add_argument("--no-auto-levels", action="store_true",
                        help="Disable per-frame brightness normalisation")
    parser.add_argument("--ramp", default="standard",
                        help=f"Character ramp: {', '.join(RAMPS)}, or a "
                             f"literal string ordered light to dark")
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
