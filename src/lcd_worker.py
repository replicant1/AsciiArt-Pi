"""
Background thread driving the LCD alongside the terminal display.

The two outputs must not be chained together.  A full LCD frame costs about 33
ms of SPI time alone, and doing that inside the main loop would drag the HDMI
picture down with it.  So the main loop hands over the camera frame and a
snapshot of the current settings, and moves straight on; this thread does its
own downscale, character mapping and panel write at whatever rate it can
manage, dropping frames when it falls behind.

That gives the property asked for: the terminal grid can be resized freely with
the mouse and the LCD grid never changes, while the settings that are about
*how* the picture looks - colour, invert, ramp, rotation, contrast, auto-levels
- follow the main display.  `fill` deliberately does not follow: the panel is
always fully occupied.

Frames are safe to share without copying.  CameraCapture already detaches each
YuvFrame from the driver's recycled buffers, and both readers only ever read.
"""

import logging
import threading
from queue import Empty, Full, Queue
from typing import NamedTuple

import palettes
from ascii_art import AsciiArt
from image_processor import ImageProcessor

logger = logging.getLogger(__name__)


class LcdConfig(NamedTuple):
    """
    The settings the LCD copies from the main display.

    `fill` is absent on purpose - the panel always fills - and so is the grid
    size, which the LCD decides for itself from its font.
    """

    rotation: int
    contrast: float
    auto_levels: bool
    invert: bool
    ramp: str
    scheme: str
    colour_levels: int


class LcdWorker(threading.Thread):
    """Renders camera frames to the LCD without blocking the main loop."""

    def __init__(self, display, name="lcd"):
        """
        Args:
            display: An LcdDisplay to draw on.  Owned by this thread once
                start() is called; the main loop must not touch it.
        """
        super().__init__(name=name, daemon=True)
        self.display = display

        # Depth 1 with drop-oldest: the LCD should always be working on the
        # newest frame, never a backlog.
        self._inbox = Queue(maxsize=1)
        self._stopping = threading.Event()

        self.processor = ImageProcessor(
            fill=True,                          # always, by design
            cell_aspect=display.cell_aspect,
        )
        self._ascii = None
        self._config = None
        self._scheme = palettes.SCHEMES[0]

        self.frames = 0
        self.dropped = 0
        self.errors = 0

    def submit(self, frame, config):
        """
        Offer a frame to the LCD.  Never blocks; never raises.

        A frame arriving while the previous one is still being drawn simply
        replaces it, so the LCD lags at most one frame behind reality.
        """
        if self._stopping.is_set():
            return
        try:
            self._inbox.get_nowait()
            self.dropped += 1
        except Empty:
            pass
        try:
            self._inbox.put_nowait((frame, config))
        except Full:
            self.dropped += 1

    def run(self):
        logger.info("LCD worker started: %dx%d grid", *self.display.grid_size)
        while not self._stopping.is_set():
            try:
                item = self._inbox.get(timeout=0.2)
            except Empty:
                continue
            if item is None:
                break

            frame, config = item
            try:
                self._draw(frame, config)
                self.frames += 1
            except Exception as e:
                # A failure here must never take the terminal display down with
                # it, so log and carry on with the next frame.
                self.errors += 1
                if self.errors <= 3 or self.errors % 100 == 0:
                    logger.error("LCD frame failed (%d so far): %s",
                                 self.errors, e, exc_info=True)

        logger.info("LCD worker stopped: %d frames, %d dropped, %d errors",
                    self.frames, self.dropped, self.errors)

    def _draw(self, frame, config):
        """Downscale, map to characters and push one frame to the panel."""
        self._apply(config)
        cols, rows = self.display.grid_size
        scheme = self._scheme

        grey = self.processor.process(frame.luma, cols, rows)
        indices = self._ascii.to_indices(grey)

        colours = None
        if scheme.kind == "live":
            colours = self.processor.colour_grid(frame, grey, cols, rows)
        elif scheme.kind == "tint":
            # One gather: ramp position -> the scheme's blend from screen to
            # ink. Full RGB here, not the terminal's palette approximation.
            table = palettes.rgb_table(scheme, len(self._ascii.chars),
                                       config.invert)
            colours = table[indices]

        self.display.render(indices, colours, scheme.screen)

    def _apply(self, config):
        """Adopt the main display's settings, rebuilding only what changed."""
        if config == self._config:
            return

        previous = self._config
        self._config = config
        self._scheme = palettes.by_name(config.scheme)

        self.processor.rotation = config.rotation
        self.processor.contrast = config.contrast
        self.processor.auto_levels = config.auto_levels

        # The ramp string is what the atlas is built from, and `invert` reverses
        # it, so either changing means both the mapping and the glyphs are stale.
        if (previous is None or previous.ramp != config.ramp
                or previous.invert != config.invert
                or previous.colour_levels != config.colour_levels):
            self._ascii = AsciiArt(ramp=config.ramp, invert=config.invert,
                                   colour_levels=config.colour_levels)
            self.display.set_ramp(self._ascii.chars)

    def stop(self, timeout=3.0):
        """Stop the thread and release the panel."""
        self._stopping.set()
        try:
            self._inbox.put_nowait(None)        # wake it if it is waiting
        except Full:
            pass
        if self.is_alive():
            self.join(timeout=timeout)
        try:
            self.display.close()
        except Exception as e:
            logger.error("Closing the LCD failed: %s", e)
