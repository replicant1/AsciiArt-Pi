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

from ascii_art import RAMPS, AsciiArt  # noqa: E402
from camera import CameraCapture  # noqa: E402
from display import NcursesDisplay  # noqa: E402
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
        )
        # Track the ramp by name, not just by index into RAMP_CYCLE: --ramp
        # also accepts a literal character string, which is not in the cycle.
        self.ramp_name = args.ramp
        self.ramp_index = (RAMP_CYCLE.index(args.ramp)
                           if args.ramp in RAMP_CYCLE else 0)
        self.invert = args.invert
        self.ascii_art = AsciiArt(ramp=self.ramp_name, invert=self.invert)

        self.grid = None            # (cols, rows), recomputed lazily
        self.grid_key = None        # inputs the grid was computed from
        self.cell_aspect = args.cell_aspect
        self._refresh_cell_aspect()
        self.frame_count = 0
        self.dropped = 0
        self.frame_times = deque(maxlen=20)
        self.is_running = False

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
        # A literal --ramp string has no name to show, so label it "custom".
        ramp = self.ramp_name if self.ramp_name in RAMPS else "custom"
        stats = (f" {fps:4.1f}fps {cols}x{rows} rot{self.processor.rotation}"
                 f" con{self.processor.contrast:.1f}"
                 f" chr:{ramp}"
                 f" auto:{_on_off(self.processor.auto_levels)}"
                 f" fill:{_on_off(self.processor.fill)}"
                 f" inv:{_on_off(self.invert)}")

        width = self.display.cols - 1
        for keys in (" | q:quit r:rotate f:fill i:invert c:chars +/-:contrast"
                     " a:auto",
                     " | q:quit r:rotate f:fill i:invert c:chars",
                     " | q:quit r:rotate f:fill",
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
        elif key in ("f", "F"):
            self.processor.fill = not self.processor.fill
            self.grid_key = None
            self.display.clear()
        elif key in ("i", "I"):
            self.invert = not self.invert
            self.ascii_art = AsciiArt(ramp=self.ramp_name, invert=self.invert)
        elif key in ("c", "C"):
            self.ramp_index = (self.ramp_index + 1) % len(RAMP_CYCLE)
            self.ramp_name = RAMP_CYCLE[self.ramp_index]
            self.ascii_art = AsciiArt(ramp=self.ramp_name, invert=self.invert)
        elif key in ("+", "="):
            self.processor.contrast = min(4.0, self.processor.contrast + 0.1)
        elif key in ("-", "_"):
            self.processor.contrast = max(0.1, self.processor.contrast - 0.1)
        elif key in ("a", "A"):
            self.processor.auto_levels = not self.processor.auto_levels
        return True

    def run(self):
        """Main loop."""
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

                luma = self.camera.get_frame(timeout=1.0)
                if luma is None:
                    # The camera caps its own rate, so a miss here means it is
                    # still warming up (or has stalled) rather than that we are
                    # polling too fast.
                    self.dropped += 1
                    self.display.message("Waiting for camera...")
                    if not self._drain_keys():
                        break
                    continue

                cols, rows = self._grid_for(luma.shape)

                try:
                    processed = self.processor.process(luma, cols, rows)
                    ascii_lines = self.ascii_art.to_ascii_text(processed)
                except Exception as e:
                    logger.error("Frame processing failed: %s", e, exc_info=True)
                    continue

                self.frame_count += 1
                self.frame_times.append(time.time())
                self.display.render(ascii_lines, self._status())

                if not self._drain_keys():
                    break

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self.is_running = False
            elapsed = time.time() - started
            avg = self.frame_count / elapsed if elapsed > 0 else 0
            self.camera.stop()
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
    parser.add_argument("--fill", action="store_true",
                        help="Crop the picture to fill the whole window "
                             "instead of letterboxing it to fit")
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
    setup_logging(args.log, args.verbose)
    logger.info("=== ASCII Art Live Camera starting: %s ===", vars(args))

    def bootstrap(stdscr):
        display = NcursesDisplay(stdscr)
        AsciiArtLiveCamera(display, args).run()

    try:
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
