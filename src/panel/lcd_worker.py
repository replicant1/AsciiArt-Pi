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
always fully occupied.  `lcd_font_size` is the one setting that is the panel's
alone, and changing it does move the grid - see _apply.

What arrives with each frame is the app's whole RenderConfig, not a private
copy of the fields the panel happens to care about.  There used to be an
`LcdConfig` here listing eight of them, which meant adding a setting required
remembering to add it in two places; the field it was missing was never going
to announce itself.

Frames are safe to share without copying.  CameraCapture already detaches each
YuvFrame from the driver's recycled buffers, and both readers only ever read.
"""

import logging
import threading
import time
from queue import Empty, Full, Queue

from art import palettes
from art.ascii_art import AsciiArt
from capture.image_processor import ImageProcessor

logger = logging.getLogger(__name__)

# How long the worker waits on an empty inbox. The splash rate is the animation
# frame rate as well as a poll interval, hence the two values: a panel write
# costs about 33 ms, so 0.1 s is a third of the thread's time during start-up
# and none of it afterwards.
IDLE_TICK = 0.2
SPLASH_TICK = 0.1

# Default seconds to keep the start-up screen up once frames start arriving.
# The camera on this Pi is ready in well under two seconds, which is not long
# enough to read anything, so without a floor the screen is a flicker.
DEFAULT_SPLASH_HOLD = 3.0

# What the start-up screen says once frames are actually arriving and it is only
# still up because of the hold.
SPLASH_READY = "ready"

# How long a notice stays up. Four seconds is the terminal status line's own
# NOTICE_SECONDS, and the two displays saying the same thing for the same
# length of time is the point - the panel is not a second-class output.
NOTICE_SECONDS = 4.0


class LcdWorker(threading.Thread):
    """Renders camera frames to the LCD without blocking the main loop."""

    def __init__(self, display, scheme=None, splash_hold=DEFAULT_SPLASH_HOLD,
                 name="lcd"):
        """
        Args:
            display: An LcdDisplay to draw on.  Owned by this thread once
                start() is called; the main loop must not touch it.
            scheme: The scheme the app is starting in, used only to colour the
                start-up screen so it comes up in the same colours the picture
                will.  Frames carry their own scheme in the config.
            splash_hold: Seconds to keep the start-up screen up after the first
                frame is ready.  0 hands over the moment there is a picture.
        """
        super().__init__(name=name, daemon=True)
        self.display = display

        # Depth 1 with drop-oldest: the LCD should always be working on the
        # newest frame, never a backlog.
        self._inbox = Queue(maxsize=1)
        self._stopping = threading.Event()
        # Not sent through the inbox: a blank is asked for precisely when
        # frames have stopped arriving, and the inbox drops its oldest entry,
        # so a blank queued there could sit behind a frame and then be thrown
        # away by the next one. A flag cannot be lost.
        self._blanking = threading.Event()

        self.processor = ImageProcessor(
            fill=True,                          # always, by design
            cell_aspect=display.cell_aspect,
        )
        self._ascii = None
        self._config = None
        self._scheme = scheme or palettes.SCHEMES[0]

        # Start-up screen state.  `_splash` is a (message, detail) tuple while
        # the panel is still waiting for a first frame, and None afterwards.
        # A plain attribute rather than a lock: CPython makes the assignment
        # atomic, the main thread only ever writes and this thread only ever
        # reads, and a tick landing either side of a change is of no
        # consequence - it just shows the previous message for 200 ms longer.
        self._splash = None
        self._splash_screen = None
        self._splash_logged = None
        self._splash_hold = max(0.0, splash_hold)
        # Set on the first tick that actually reaches the glass, not when the
        # message is queued: the hold is about how long a human had to look at
        # it, so it cannot start before anything was drawn.
        self._splash_since = None
        self._last_tick = None
        self._phase = 0

        # Set from the main thread, read on this one, and cleared by whichever
        # gets there first - hence the lock rather than a bare tuple.
        self._notice = None
        self._notice_lock = threading.Lock()
        self._notice_shown = None

        self.frames = 0
        self.dropped = 0
        self.errors = 0

    def splash(self, message, detail=None):
        """
        Put a message on the panel until the first camera frame arrives.

        Safe to call from the main thread even though the display belongs to
        this one: nothing is drawn here, only recorded.  The drawing happens on
        this thread's next idle tick, so a message replaced within 200 ms is
        never seen - which is the normal fate of the first one.

        Args:
            message: What is happening now, e.g. "starting camera".
            detail: A quieter second line, e.g. the grid size.  Omitted means
                keep whatever is already there, so the caller that knows the
                grid size can set it once and every later message keeps it.
        """
        if detail is None:
            detail = self._splash[1] if self._splash else ""
        self._splash = (message, detail)

    def notice(self, text, seconds=NOTICE_SECONDS):
        """
        Say something on the panel for a few seconds, over the picture.

        Safe from any thread: nothing is drawn here, only recorded. Passing an
        empty text takes the band away early.

        The panel is the only output a sealed box has, so this is where a
        failure has to end up. A message that only reaches the socket reply is
        a message for whoever happened to be holding a phone, and the person
        standing in front of the camera watching nothing happen is exactly who
        needed it.
        """
        with self._notice_lock:
            if not text:
                self._notice = None
            else:
                self._notice = (text, time.monotonic() + max(0.0, seconds))

    def _live_notice(self):
        """The message that should be on screen now, or None."""
        with self._notice_lock:
            if self._notice is None:
                return None
            text, until = self._notice
            if time.monotonic() >= until:
                self._notice = None
                return None
            return text

    def submit(self, frame, config):
        """
        Offer a frame to the LCD.  Never blocks; never raises.

        A frame arriving while the previous one is still being drawn simply
        replaces it, so the LCD lags at most one frame behind reality.
        """
        if self._stopping.is_set():
            return
        # A frame settles any outstanding blank request: the panel is wanted
        # again, so clearing it first would only cost a black flash.
        self._blanking.clear()
        try:
            self._inbox.get_nowait()
            self.dropped += 1
        except Empty:
            pass
        try:
            self._inbox.put_nowait((frame, config))
        except Full:
            self.dropped += 1

    def blank(self):
        """
        Ask for the panel to be cleared, without touching it from here.

        Used when the picture is sent to the terminal alone: the panel would
        otherwise keep showing whichever frame happened to be last, which reads
        as a crashed display rather than a switched-off one.  Honoured on the
        worker's next tick, so within the idle timeout.

        Cancelling any pending start-up screen is part of blanking, not a
        separate courtesy.  The screen is retired on the *frame* path, and
        blanking happens precisely when frames have stopped arriving - so
        without this the idle tick would redraw the start-up screen over the
        cleared panel, every tick, with nothing left that could ever retire it.
        The panel would sit animating "starting camera" until the target was
        switched back. Clearing it here is safe from this thread for the same
        reason splash() is: the assignment is atomic, and the blank is honoured
        at the top of the loop, *after* any tick already in flight.
        """
        self._splash = None
        self._blanking.set()

    def run(self):
        logger.info("LCD worker started: %dx%d grid", *self.display.grid_size)
        while not self._stopping.is_set():
            if self._blanking.is_set():
                self._blanking.clear()
                try:
                    self.display.clear()
                    logger.info("LCD blanked")
                except Exception as e:
                    logger.error("Blanking the LCD failed: %s", e)

            # Ticking faster while the splash is up is what makes the sweep
            # readable: the comet advances one cell per tick, so at the idle
            # rate a full pass would take BAR_CELLS+TAIL ticks - over seven
            # seconds, far longer than the screen is ever up for.
            timeout = SPLASH_TICK if self._splash is not None else IDLE_TICK
            try:
                item = self._inbox.get(timeout=timeout)
            except Empty:
                # The idle timeout is the splash's clock: no extra thread and no
                # sleep of its own. It stops when _splash goes to None, which
                # happens on the frame path below - or in blank(), which has to
                # do it explicitly, since it is called exactly when frames have
                # stopped and the frame path can no longer be reached.
                self._tick_splash()
                # Notices have to reach the glass without a frame to ride on.
                # That is not an edge case: "the camera stopped" is precisely
                # the message nobody can deliver on the frame path, because
                # there are no frames. The buffer is persistent, so the band
                # goes over whatever picture is already up there.
                if self._splash is None:
                    self._tick_notice()
                continue
            if item is None:
                break

            frame, config = item
            try:
                if self._splash is not None:
                    # Frames are arriving, so whatever the screen was waiting
                    # for has happened. Saying "waiting for first frame" for the
                    # rest of the hold would be untrue, and the hold is most of
                    # the time the screen is up.
                    if self._splash[0] != SPLASH_READY:
                        self._splash = (SPLASH_READY, self._splash[1])

                    # Draw before deciding. The camera here can produce a frame
                    # before the first idle tick ever runs, and the hold is
                    # measured from when the screen reached the glass - so
                    # checking first would find it owed nothing, clear it, and
                    # hand over without it having been shown at all.
                    self._tick_splash()
                    if self._splash is not None and self._hold_remaining() > 0:
                        # Frames are arriving but the start-up screen has not
                        # been up long enough to read yet. Keep it, and drop
                        # this frame: the panel runs a few seconds behind the
                        # terminal at start-up, which is what a linger costs.
                        self.dropped += 1
                        continue
                    # The picture supersedes the start-up screen, and nothing
                    # redraws it afterwards even if the camera stalls later: by
                    # then a stale "starting camera" would be a lie.
                    self._splash = None
                    logger.info("Start-up screen cleared after %.1f s "
                                "(%d ticks)",
                                time.monotonic() - self._splash_since,
                                self._phase)
                self._notice_shown = self._draw(frame, config)
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

    def _tick_notice(self):
        """Paint or remove the band when no frames are arriving to carry it."""
        text = self._live_notice()
        if text == self._notice_shown:
            return                      # already on the glass, or already gone
        try:
            if text:
                self.display.show_notice(text)
            else:
                self.display.clear_notice()
            self._notice_shown = text
        except Exception as e:
            self.errors += 1
            logger.error("LCD notice failed: %s", e, exc_info=True)

    def _hold_remaining(self):
        """Seconds the start-up screen is still owed, 0 once it has had them."""
        if self._splash_since is None:
            # Queued but never drawn - usually because the panel failed. Owing
            # it time it cannot use would stall the picture forever.
            return 0.0
        return max(0.0, self._splash_hold
                   - (time.monotonic() - self._splash_since))

    def _tick_splash(self):
        """
        Advance and redraw the start-up screen, if one is showing.

        Rate-limited rather than drawing on every call: during the hold this is
        driven once per incoming frame instead of by the idle timeout, and at
        15 fps that would be a 33 ms panel write every 66 ms for no visible
        gain - the comet only has to move at a readable speed, not the camera's.
        """
        pending = self._splash
        if pending is None:
            return

        now = time.monotonic()
        if self._last_tick is not None and now - self._last_tick < SPLASH_TICK:
            return

        try:
            # Imported here rather than at module scope so PIL is only needed
            # when the panel is. Repeat imports hit sys.modules, so the cost
            # after the first tick is a dict lookup.
            from panel.lcd_splash import SWEEP_STEP, SplashScreen

            if self._splash_screen is None:
                width, height = self.display.panel_size
                self._splash_screen = SplashScreen(
                    width, height,
                    ink=self._scheme.ink, screen=self._scheme.screen)

            message, detail = pending
            self.display.show_image(
                self._splash_screen.render(message, detail, self._phase))
            self._phase += SWEEP_STEP
            self._last_tick = now
            if self._splash_since is None:
                self._splash_since = now

            # Nothing can photograph this panel, so the log is the only record
            # that the start-up screen was ever on it. One line per message,
            # not per tick.
            if message != self._splash_logged:
                self._splash_logged = message
                logger.info("Start-up screen: %s", message)
        except Exception as e:
            # The splash is a courtesy. If it cannot draw, give up on it
            # entirely rather than logging once per tick forever, and let the
            # camera frames arrive on a black panel as they did before.
            self._splash = None
            logger.error("Start-up screen failed, carrying on without it: %s",
                         e, exc_info=True)

    def _draw(self, frame, config):
        """
        Downscale, map to characters and push one frame to the panel.

        Returns the notice drawn with it, or None, so the caller records what
        actually reached the glass.
        """
        self._apply(config)
        cols, rows = self.display.grid_size
        scheme = self._scheme

        grey = self.processor.process(frame.luma, cols, rows)
        indices = self._ascii.to_indices(grey)

        colours = None
        if scheme.kind == "live":
            colours = self.processor.colour_grid(frame, grey, cols, rows)
            # The panel has no palette to quantise against, so colour_levels
            # has to be applied to the RGB itself. The terminal gets the same
            # effect for free by choosing among fewer cube steps. At the top of
            # the range this returns the frame untouched.
            colours = self._ascii.posterise(colours)
        elif scheme.kind == "tint":
            # One gather: ramp position -> the scheme's blend from screen to
            # ink. Full RGB here, not the terminal's palette approximation.
            table = palettes.rgb_table(scheme, len(self._ascii.chars),
                                       config.invert)
            colours = table[indices]

        # Returned rather than re-read by the caller: asking twice can give
        # two different answers if the notice expires between them, and then
        # _notice_shown describes a band that is not what is on the glass -
        # which stops _tick_notice ever clearing it once frames stop.
        notice = self._live_notice()
        self.display.render(indices, colours, scheme.screen, notice=notice)
        return notice

    def _apply(self, config):
        """
        Adopt the main display's settings, rebuilding only what changed.

        `fill` and `target` are read from the config by nobody here, on
        purpose: the panel always fills, and whether it should be drawing at
        all is the main loop's decision - it simply stops submitting.
        """
        if config == self._config:
            return

        previous = self._config
        self._config = config
        self._scheme = palettes.by_name(config.scheme)

        self.processor.rotation = config.rotation
        self.processor.contrast = config.contrast
        self.processor.auto_levels = config.auto_levels
        self.processor.mirror = config.mirror

        # Font size first, because it rebuilds the atlas out of the ramp
        # already loaded; doing it after would leave the ramp check below with
        # nothing to notice and the glyphs at the old size.
        if previous is None or previous.lcd_font_size != config.lcd_font_size:
            self.display.set_font_size(config.lcd_font_size)
            # The grid and the cell shape both moved with the font. The
            # processor was given a cell aspect once at construction, and a
            # stale one would squash the picture on the panel while leaving the
            # terminal's correct - which looks like a panel fault rather than a
            # missed assignment.
            self.processor.cell_aspect = self.display.cell_aspect

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
