#!/usr/bin/env python3
"""
ASCII Art Live Camera Preview for Raspberry Pi Zero 2.

Captures video from the Camera Module 2 and renders it as ASCII art in the
terminal on the HDMI screen.

    python3 ascii_camera.py                        # sensible defaults
    python3 ascii_camera.py --fps 8 --width 160 --height 120   # even lighter
    python3 ascii_camera.py --help

Press 'q' to quit; other live controls are listed in the status line.

Every live setting lives in one RenderConfig (src/control/render_config.py) and every
change to one is a validated delta applied through MainRenderLooper.apply().
Nothing here assigns a setting directly - not the keyboard, not the knob - so
there is a single place that knows what each change costs to make.
"""

import logging
import os
import signal
import sys
import threading
import time
from collections import deque
from pathlib import Path

# libcamera's C++ layer logs to stderr unconditionally.  Quieten it here, and
# main() redirects fd 2 to the log file anyway - anything written to the
# terminal while curses owns it corrupts the picture.
os.environ.setdefault("LIBCAMERA_LOG_LEVELS", "*:ERROR")

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import curses  # noqa: E402

from control import commands  # noqa: E402
from art import palettes  # noqa: E402
from control import render_config  # noqa: E402
from language import shortcuts  # noqa: E402
from art.ascii_art import RAMPS, AsciiArt  # noqa: E402
from capture.camera import CameraCapture  # noqa: E402
from hdmi.display import NcursesDisplay  # noqa: E402
from hdmi.headless import HeadlessDisplay  # noqa: E402
from capture.image_processor import ImageProcessor, fit_grid  # noqa: E402
# Only the default, so --help can state it. Safe at module scope where
# LcdDisplay is not: the lazy imports in _start_lcd are there for spidev and
# RPi.GPIO, which live in lcd.py, and lcd_worker pulls in neither.
from control.render_config import ConfigError  # noqa: E402
from control.args import parse_args  # noqa: E402
from control.scheme_cycle import SchemeCycle  # noqa: E402
from hdmi.status_line import status_line  # noqa: E402
from version import APP_NAME, __version__  # noqa: E402

logger = logging.getLogger("ascii_camera")

# Derived from RAMPS rather than repeated, so adding or removing a ramp is a
# one-line change in ascii_art.py and cannot leave the c key cycling through a
# name that no longer exists.
RAMP_CYCLE = list(RAMPS)

# Panel font sizes the l key steps through. Every one of these tiles 320x240
# exactly and gives a 4:3 character grid, so the picture fills the panel with
# nothing cropped; the config accepts anything from 4 to 16, but there is no
# reason to stop the knob-and-key path on a size that leaves a black margin.
LCD_FONT_CYCLE = (6, 8, 9)

# What the terminal shows when the picture has been sent to the panel alone.
# Something has to be there: an empty window is what a crash looks like.
TERMINAL_OFF = "picture on the LCD panel - press t to bring it back"

# How long a refused or clamped change stays in the status line. Long enough to
# read after looking down at the keyboard, short enough not to outlive the
# next one.
NOTICE_SECONDS = 4.0

# How long the camera may deliver nothing before the panel says so. The capture
# thread caps its own rate, so a second of silence is normal and ten is not.
# This exists because of a real morning: an OOM storm killed the desktop
# session, the camera stopped delivering at 09:20, and the app kept redrawing
# its last frame for ninety-five minutes. Every check said healthy - the render
# loop answered the command socket in 1.4 s - and the panel showed a picture. A
# frozen picture and a working camera are indistinguishable by eye, which is
# exactly the kind of failure a sealed box must not be allowed to hide.
STALL_SECONDS = 10.0

# Re-said while it is still true, since a notice expires after four seconds and
# a fault that lasts an hour should not be announced once and then hidden.
STALL_REPEAT = 30.0

# Poll interval while the picture is frozen and nothing has changed. The camera
# normally paces the loop; with no frame being waited for, this is what stops it
# spinning a core for nothing.
FROZEN_TICK = 0.05


class MainRenderLooper:
    """Capture -> process -> ASCII -> terminal, once per frame."""

    def __init__(self, display, args):
        self.display = display
        self.args = args

        # The single source of truth for every setting that can change while
        # the camera runs. Nothing below keeps a second copy: the processor and
        # the ASCII generator are given values out of it, and are re-given them
        # by _adopt whenever it changes.
        self.config = render_config.from_args(args)
        self.notice = None          # (text, expiry), for the status line
        # The config as it stood before the most recent change. Only the
        # parser reads it, and only so that "undo that" has something to
        # undo to - a request that means nothing without a before.
        self.previous_config = None
        # When the last camera frame arrived, and when the panel was last
        # told the camera had stopped. See _note_if_stalled.
        self._last_frame_at = None
        self._stall_noted = None

        self.camera = CameraCapture(
            resolution=(args.width, args.height),
            frame_rate=args.fps,
        )
        self.processor = ImageProcessor(cell_aspect=args.cell_aspect)
        self.ascii_art = None

        self.grid = None            # (cols, rows), recomputed lazily
        self.grid_key = None        # inputs the grid was computed from
        self.cell_aspect = args.cell_aspect
        self._refresh_cell_aspect()
        self.frame_count = 0
        self.dropped = 0
        self.frame_times = deque(maxlen=20)
        self.is_running = False

        # The most recent frame, kept so that `freeze` has something to hold and
        # so a settings change while frozen has something to redraw.
        self._held = None
        # Set whenever something that affects the picture changes. Only read
        # while frozen, where it is the difference between redrawing on demand
        # and redrawing a still picture fifteen times a second.
        self._redraw = True

        # Declared before the first _adopt, which asks whether the panel is
        # being drawn to and would otherwise be reading an attribute that does
        # not exist yet. They are started below, once the settings they are
        # built from have been applied.
        self.lcd = None

        # Everything the config touches is pushed out from here, so start-up
        # and a later change go down exactly the same path. `previous=None`
        # means "nothing has been told anything yet", so every field counts.
        self._adopt(self.config, previous=None)

        if args.lcd:
            self.lcd = self._start_lcd()
        # Always built, even with no knob: the `s` key cycles schemes too, and
        # the walk that skips what this terminal cannot show is the same walk
        # either way. --encoder only decides whether a second way in exists.
        self.schemes = SchemeCycle(settings=lambda: self.config,
                                   apply=self.apply,
                                   colour_ok=lambda: self.display.colour_ok)
        if args.encoder:
            self.schemes.start_encoder(clk=args.encoder_clk,
                                       dt=args.encoder_dt,
                                       sw=args.encoder_sw,
                                       reverse=args.encoder_reverse)
        self.commands = (self._start_commands() if args.command_socket
                         else None)

        # Losing the panel is survivable when there is a terminal to fall back
        # on, and _start_lcd deliberately treats it that way. With no terminal
        # either, the app would run the camera and show the result to nobody,
        # so that combination is refused rather than left looking like a hang.
        if not display.draws and self.lcd is None:
            raise RuntimeError(
                "no output: the terminal is switched off and the LCD panel "
                f"did not start. See {args.log} for why.")

        # Which outputs actually exist is only known now, after both have had
        # their chance to start. A target naming one that never came up would
        # otherwise show the picture to nobody - see _feasible_target.
        settled = self._feasible_target(self.config.target)
        if settled != self.config.target:
            logger.warning("Target %r is not available; using %r instead",
                           self.config.target, settled)
            self.config = self.config.with_changes({"target": settled})

    @property
    def terminal_on(self):
        """True when the picture should be built for, and drawn in, the window."""
        return self.display.draws and self.config.target in ("both", "terminal")

    @property
    def lcd_on(self):
        """True when frames should be handed to the panel."""
        return self.lcd is not None and self.config.target in ("both", "lcd")

    def _target_problem(self, target):
        """
        Why this target cannot be honoured on this run, or None if it can.

        RenderConfig validates a target against the list of names; it cannot
        know whether the panel came up or whether there is a terminal, because
        those are facts about this run rather than about the setting. So the
        field-level check lives there and the runtime one lives here.

        Only the two targets that name a *specific* output can fail. "both"
        means "draw wherever you can", which is always honourable: the
        constructor refuses to start with no output at all, so there is always
        at least one, and asking for everything available can never ask for
        nothing. An earlier version refused "both" whenever the terminal was
        missing, which meant the most inclusive setting was rejected on the
        headless service - and told the user it could not draw on "both" alone,
        which is not a sentence that means anything.
        """
        if target == "terminal" and not self.display.draws:
            return ("there is no terminal to draw on - this run was started "
                    "with --no-terminal")
        if target == "lcd" and self.lcd is None:
            return ("the LCD panel is not running - start the app with --lcd "
                    "to use it")
        return None

    def _feasible_target(self, target):
        """The nearest target that actually draws something, given what ran."""
        if self._target_problem(target) is None:
            return target
        # Fall back to whatever exists. "both" covers the case where the one
        # remaining output is the one that was not asked for.
        if not self.display.draws:
            return "lcd"
        return "terminal" if self.lcd is None else "both"

    def apply(self, delta, note=True):
        """
        Validate a delta and adopt it. The single way settings ever change.

        Args:
            delta: {field name: value}, as produced by a key, the knob, or -
                once there is one - a parser. Values are checked by
                RenderConfig before anything here touches the hardware.
            note: Whether a refusal should be shown in the status line as well
                as logged.

        Returns:
            (changed, refusal). `changed` is True only if the config really
            moved; `refusal` is why it did not, or None when nothing was
            refused - a delta that asks for what is already set is a no-op, not
            a refusal, and the two need telling apart by anyone answering on a
            channel of their own.

            The reason used to be left on `self.refusal` for the caller to pick
            up afterwards, because this slot was taken by a bare bool. Exactly
            one caller ever read it, which makes it a return value wearing a
            disguise.
        """
        try:
            proposed = self.config.with_changes(delta)
        except ConfigError as e:
            logger.warning("Refused %r: %s", delta, e)
            if note:
                self._note(str(e))
            return False, "\n".join(e.problems)

        if proposed.target != self.config.target:
            problem = self._target_problem(proposed.target)
            if problem is not None:
                logger.warning("Refused target %r: %s; staying on %r",
                               proposed.target, problem, self.config.target)
                if note:
                    self._note(problem)
                return False, problem

        if proposed == self.config:
            return False, None

        previous, self.config = self.config, proposed
        self._adopt(proposed, previous)
        return True, None

    def _adopt(self, config, previous):
        """
        Push a config out to everything that has to be told about it.

        The one place that knows what each setting costs to change. Keeping it
        together is the point: before this, "invert also has to rebuild the
        ASCII generator" and "fill also has to invalidate the grid" were spread
        across the key handler, and a new setting had to remember them all.
        """
        changed = set(config.changes_from(previous))
        if not changed:
            return

        # Cheap: plain assignments the processor reads on the next frame.
        self.processor.contrast = config.contrast
        self.processor.auto_levels = config.auto_levels
        self.processor.rotation = config.rotation
        self.processor.fill = config.fill
        self.processor.mirror = config.mirror

        # The ramp string and its length; `invert` reverses it and
        # `colour_levels` sets the quantisation, so all three rebuild it.
        if changed & {"ramp", "invert", "colour_levels"}:
            self._rebuild_ascii()

        # The grid is fitted from the frame's shape and the window, so only the
        # settings that change one of those invalidate it.
        if changed & {"rotation", "fill"}:
            self.grid_key = None
        if "fill" in changed and self.display.draws:
            # Letterboxing leaves cells the picture no longer writes to; without
            # a clear they keep the previous frame's characters for good.
            self.display.clear()

        if "scheme" in changed:
            self.display.set_scheme(self.scheme)

        if "target" in changed:
            if self.lcd is not None and not self.lcd_on:
                self.lcd.blank()
            if self.display.draws:
                # Both directions need it: switching the terminal off leaves
                # the picture on screen, and switching it back on leaves the
                # off-message under a picture that no longer covers every cell.
                self.display.clear()
                self.grid_key = None

        # The panel reads lcd_font_size out of the config it is handed with the
        # next frame, so there is nothing to push here - but if the picture is
        # frozen, there is no next frame until something asks for one.
        self._redraw = True

        self.previous_config = previous
        logger.info("Config: %s", config.describe_changes(previous))

    def _note(self, text, seconds=NOTICE_SECONDS):
        """
        Say something on every display this run actually has.

        The terminal gets it in the status line, as it always did. The panel
        gets it too, because in the enclosure the panel is the *only* output -
        a message that reaches a status line nobody can see, or a socket reply
        for whoever happens to be holding a phone, has not been delivered to
        the person standing in front of the camera watching nothing happen.
        """
        self.notice = (text, time.monotonic() + seconds)
        if self.lcd is not None:
            self.lcd.notice(text, seconds)

    def _note_if_stalled(self):
        """
        Say so when the camera has stopped, rather than showing a stale frame.

        Only after a first frame has arrived: before that the start-up screen
        owns the panel and already says what is happening, and libcamera takes
        15-20 seconds to hand over frame one on this hardware - which is not a
        stall, it is a Zero 2.
        """
        if self._last_frame_at is None:
            return
        now = time.monotonic()
        idle = now - self._last_frame_at
        if idle < STALL_SECONDS:
            return
        if self._stall_noted is not None and now - self._stall_noted < STALL_REPEAT:
            return
        self._stall_noted = now
        logger.error("No camera frame for %.0f s", idle)
        self._note(f"no picture from the camera for {int(idle)}s")

    def _start_lcd(self):
        """
        Bring the SPI panel up as a second, independent output.

        Deliberately not fatal on failure.  The terminal is the primary display
        and a missing, unwired or misbehaving panel should cost a log line, not
        the whole app.  The imports are done here rather than at module level so
        that spidev and RPi.GPIO are only required when the panel is asked for.
        """
        try:
            from lcd.lcd_display import LcdDisplay
            from lcd.lcd_worker import LcdWorker

            font_size = self.config.lcd_font_size
            display = LcdDisplay(
                ramp=self.ascii_art.chars,
                font_size=font_size,
                landscape=not self.args.lcd_portrait,
                spi_freq=self.args.lcd_spi_hz,
                brightness=self.args.lcd_brightness,
            )
            worker = LcdWorker(display, scheme=self.scheme,
                               splash_hold=self.args.lcd_splash_seconds)
            worker.start()
            logger.info("LCD enabled: %dx%d grid", *display.grid_size)

            # Something to look at straight away. The camera is 15-20 seconds
            # off on a Zero 2, and until this existed the panel spent that time
            # black, which looks exactly like a panel that is not working.
            cols, rows = display.grid_size
            worker.splash("panel ready",
                          f"{cols}x{rows} grid - font {font_size}")
            return worker
        except Exception as e:
            logger.error("LCD unavailable, continuing without it: %s", e,
                         exc_info=True)
            return None

    def _start_commands(self):
        """
        Open the typed-command socket, or carry on without it.

        Not fatal, for the same reason the panel and the knob are not: the
        single-key controls still work, so a socket that cannot be bound should
        cost a log line rather than the camera. The likeliest cause is another
        instance already listening, and refusing to start over the top of a
        running app is the correct outcome there.
        """
        try:
            from control.command_server import CommandServer
            from language.resolver import AskResolver

            # Built before the socket because constructing it does nothing but
            # remember three references. The settings are read through a
            # callable rather than handed over: an ask arrives whenever
            # somebody types one, and it is about the settings as they are at
            # that moment, not as they were when the socket opened.
            self.asks = AskResolver(
                settings=lambda: (self.config, self.previous_config),
                note=self._note)
            server = CommandServer(self.args.command_socket,
                                   resolver=self.asks.resolve).start()
            try:
                from language import asklog

                self.asks.log = asklog.AskLog()
            except Exception as e:
                # Asks still work; they are just not written down.
                logger.error("Ask log unavailable: %s", e, exc_info=True)
            self.asks.warm()
            return server
        except Exception as e:
            logger.error("Command socket unavailable, continuing without "
                         "it: %s", e, exc_info=True)
            return None

    # Set when the command socket comes up, which is the only way an ask can
    # arrive. A class attribute rather than an __init__ line so that anything
    # holding an app built without running __init__ - the tests do exactly
    # this - still finds the name.
    asks = None


    def _poll_commands(self):
        """
        Apply everything typed since the last frame, and answer each line.

        Read here rather than on the socket's own thread because applying a
        setting repaints the window, rebuilds the ASCII generator and talks to
        the panel worker - none of which is safe off this thread. Every reply
        is sent, including for the lines that changed nothing, so a client is
        never left waiting.
        """
        if self.commands is None:
            return
        for request, answer in self.commands.take():
            try:
                answer.put_nowait(self._run_command(request))
            except Exception as e:
                logger.error("Command %r failed: %s", request, e, exc_info=True)
                try:
                    answer.put_nowait(f"that went wrong: {e}")
                except Exception:
                    pass

    def _run_command(self, request):
        """
        Answer one request, by binding this run's state to the dispatcher.

        The dispatching itself is `commands.run_command`, a function of its
        arguments, so that everything about typed commands - parsing, help,
        reset, and the wording of every answer - sits in one module. What only
        the app knows is supplied here: the live config, the one way settings
        change, and which targets this particular run can honour.
        """
        return commands.run_command(
            request,
            settings=lambda: self.config,
            apply=lambda delta: self.apply(delta, note=False),
            feasible_target=self._feasible_target)

    @property
    def scheme(self):
        """The active colour scheme."""
        return palettes.by_name(self.config.scheme)

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
                                     self.config.invert)
        return table[indices]

    def _rebuild_ascii(self):
        """Rebuild the generator, carrying every current setting."""
        self.ascii_art = AsciiArt(ramp=self.config.ramp,
                                  invert=self.config.invert,
                                  colour_levels=self.config.colour_levels)

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
        Text for the bottom status line.

        Everything here is state the formatting cannot work out for itself: how
        fast frames are arriving, whether a notice has outlived its few seconds,
        and how wide the window is this frame. The line itself is built by
        src/hdmi/status_line.py, which is a function of its arguments and can
        be tested without any of this.
        """
        if self.config.freeze:
            # A frozen picture stops appending frame times, so the number would
            # sit at whatever it was when the freeze started and slowly decay -
            # a reading that looks live and is not.
            rate = "frozen"
        elif len(self.frame_times) > 1:
            span = self.frame_times[-1] - self.frame_times[0]
            rate = "%4.1ffps" % ((len(self.frame_times) - 1) / span
                                 if span > 0 else 0.0)
        else:
            rate = " 0.0fps"

        cols, rows = self.grid or (0, 0)

        notice = None
        if self.notice is not None:
            text, expires = self.notice
            if time.monotonic() < expires:
                notice = text
            else:
                self.notice = None

        return status_line(
            self.config, rate,
            f"{cols}x{rows}" if self.display.draws else "headless",
            lcd_grid=None if self.lcd is None else self.lcd.display.grid_size,
            notice=notice, width=self.display.cols - 1)

    def _handle_key(self, key):
        """
        Apply a live control key. Returns False to quit.

        Every branch builds a delta and hands it to apply(); none of them
        assigns a setting. That is the whole point of the refactor - there is
        one path in, so a key cannot forget to invalidate the grid or to tell
        the panel, and the same path is the one a parser will use later.

        Contrast is nudged rather than set: apply() clamps it to the config's
        own range, so the end stops need no arithmetic here.
        """
        if key in ("q", "Q"):
            logger.info("User quit")
            return False
        if key == "RESIZE":
            self.display.refresh_size()
            self.grid_key = None
        elif key in ("r", "R"):
            self.apply({"rotation": (self.config.rotation + 90) % 360})
        elif key in ("s", "S"):
            self.schemes.step()
        elif key in ("f", "F"):
            self.apply({"fill": not self.config.fill})
        elif key in ("i", "I"):
            self.apply({"invert": not self.config.invert})
        elif key in ("c", "C"):
            index = RAMP_CYCLE.index(self.config.ramp)
            self.apply({"ramp": RAMP_CYCLE[(index + 1) % len(RAMP_CYCLE)]})
        elif key in ("+", "="):
            self.apply({"contrast": self.config.contrast + 0.1})
        elif key in ("-", "_"):
            self.apply({"contrast": self.config.contrast - 0.1})
        elif key in ("a", "A"):
            self.apply({"auto_levels": not self.config.auto_levels})
        elif key == " ":
            # The spacebar rather than a letter: every other binding is the
            # first letter of what it does, "freeze" collides with "fill", and
            # a pause key nobody has to be told about is better than a mnemonic
            # that has to be bent to fit.
            self.apply({"freeze": not self.config.freeze})
        elif key in ("t", "T"):
            order = render_config.TARGETS
            nxt = order[(order.index(self.config.target) + 1) % len(order)]
            # Step past any target this run cannot honour, rather than refusing
            # and leaving the key looking dead. Landing back where it started
            # means there is only one place to be, which is the honest answer.
            for _ in range(len(order)):
                if self._feasible_target(nxt) == nxt:
                    break
                nxt = order[(order.index(nxt) + 1) % len(order)]
            self.apply({"target": nxt})
        elif key in ("l", "L"):
            sizes = LCD_FONT_CYCLE
            here = (sizes.index(self.config.lcd_font_size)
                    if self.config.lcd_font_size in sizes else -1)
            self.apply({"lcd_font_size": sizes[(here + 1) % len(sizes)]})
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

    def _next_frame(self):
        """
        The frame to draw this pass, or None to skip it.

        Quitting is signalled by clearing `is_running` rather than by a return
        value, which is the same way the signal handler stops the loop - one
        mechanism for "stop", not two.
        """
        if self.config.freeze and self._held is not None:
            # Frozen, so the picture is whatever was last captured. The camera
            # is deliberately left running: stopping it would make unfreezing
            # cost the 15-20 seconds libcamera takes to come back, and its
            # queue is one deep, so nothing piles up.
            if not self._redraw and self.notice is None:
                # Nothing has changed and nothing is moving, so there is no
                # picture to draw. Without this the loop would redraw a still
                # frame at the full rate - and push it down the SPI bus - for
                # no visible difference at all.
                #
                # A live notice is the exception: it has to appear and then,
                # four seconds later, go away, and _status is what retires it.
                # This settles by itself - the redraw that shows the expired
                # notice is the one that clears it.
                if not self._drain_input():
                    self.is_running = False
                else:
                    time.sleep(FROZEN_TICK)
                return None
            return self._held

        frame = self.camera.get_frame(timeout=1.0)
        if frame is None:
            # The camera caps its own rate, so a miss here means it is still
            # warming up (or has stalled) rather than that we are polling too
            # fast.
            self.dropped += 1
            self.display.message("Waiting for camera...")
            self._note_if_stalled()
            if not self._drain_input():
                self.is_running = False
            return None

        self._held = frame
        self._last_frame_at = time.monotonic()
        self._stall_noted = None
        return frame

    def _build_picture(self, frame):
        """
        (lines, colours) for the terminal, or None if the frame could not be
        processed.

        Three cases, and two of them build nothing on purpose. The panel does
        its own downscale and character mapping on its own thread, so whenever
        the terminal is not showing the picture there is no reason to build one
        for it - that saving is the whole point of `--no-terminal` and of
        `tgt:lcd`.
        """
        if self.terminal_on:
            cols, rows = self._grid_for(frame.shape)
            try:
                processed = self.processor.process(frame.luma, cols, rows)
                return (self.ascii_art.to_ascii_text(processed),
                        self._colours_for(frame, processed, cols, rows))
            except Exception as e:
                logger.error("Frame processing failed: %s", e, exc_info=True)
                return None
        if self.display.draws:
            # There is a window, but the picture has been sent to the panel
            # alone. Say so rather than leave it blank, and skip the build.
            return (TERMINAL_OFF,), None
        # No terminal at all: nothing would ever look at what was built.
        return (), None

    def _shut_down(self, started):
        """
        Release every device this run claimed, and say what it managed.

        A claim left behind - the camera, the panel's GPIO, the encoder's pins,
        the socket file - makes the *next* run fail to start, which is a much
        worse failure than the one that got us here.
        """
        self.is_running = False
        elapsed = time.time() - started
        avg = self.frame_count / elapsed if elapsed > 0 else 0
        self.camera.stop()
        if self.lcd is not None:
            self.lcd.stop()
        self.schemes.stop()
        if self.commands is not None:
            self.commands.stop()
        logger.info("Rendered %d frames in %.1fs (%.1f avg fps), "
                    "%d camera timeouts", self.frame_count, elapsed,
                    avg, self.dropped)

    def run(self):
        """Main loop: a frame in, a picture out, until something says stop."""
        self._install_signal_handlers()
        self.display.message("Starting camera, please wait...")
        if self.lcd is not None:
            self.lcd.splash("starting camera")
        self.camera.start()
        if self.lcd is not None:
            # camera.start() returns once libcamera is up, which is not the same
            # as a frame being ready; the wait after it is short but not zero.
            self.lcd.splash("waiting for first frame")
        self.is_running = True
        started = time.time()

        try:
            while self.is_running:
                if self.display.refresh_size():
                    self.grid_key = None
                    # A resize may also mean the font changed under us.
                    self._refresh_cell_aspect()
                    self._redraw = True

                frame = self._next_frame()
                if frame is None:
                    continue
                self._redraw = False

                # Hand the panel the frame before doing any work for the
                # terminal, so the two renders overlap instead of queueing.
                if self.lcd_on:
                    self.lcd.submit(frame, self.config)

                picture = self._build_picture(frame)
                if picture is None:
                    continue
                ascii_lines, colours = picture

                self.frame_count += 1
                self.frame_times.append(time.time())
                self.display.render(ascii_lines, self._status(), colours)

                if not self._drain_input():
                    break
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self._shut_down(started)

    def _drain_input(self):
        """
        Apply everything the user has done since the last frame.

        The knob is read here rather than on its own timer so that it lands in
        the same place in the loop as a keypress: one scheme change per frame
        at most, applied before the next frame is drawn. Typed commands arrive
        by the same route, from the socket thread - and later, a phone's HTTP
        handler will deliver into the same queue.
        """
        self.schemes.poll()
        self._poll_commands()
        while True:
            key = self.display.get_key()
            if key is None:
                return True
            if not self._handle_key(key):
                return False




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
    logger.info("=== %s %s starting: %s ===", APP_NAME, __version__,
                vars(args))

    def bootstrap(stdscr):
        display = NcursesDisplay(stdscr)
        MainRenderLooper(display, args).run()

    try:
        if args.no_terminal:
            # No curses.wrapper here: there is no screen to put into a special
            # mode and restore afterwards. HeadlessDisplay still has stdin to
            # give back, which is what the context manager is for.
            with HeadlessDisplay() as display:
                MainRenderLooper(display, args).run()
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
