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
change to one is a validated delta applied through AsciiArtLiveCamera.apply().
Nothing here assigns a setting directly - not the keyboard, not the knob - so
there is a single place that knows what each change costs to make.
"""

import argparse
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
from screen.display import NcursesDisplay  # noqa: E402
from screen.headless import HeadlessDisplay  # noqa: E402
from capture.image_processor import ImageProcessor, fit_grid  # noqa: E402
# Only the default, so --help can state it. Safe at module scope where
# LcdDisplay is not: the lazy imports in _start_lcd are there for spidev and
# RPi.GPIO, which live in lcd.py, and lcd_worker pulls in neither.
from panel.lcd_worker import DEFAULT_SPLASH_HOLD  # noqa: E402
from control.render_config import ConfigError  # noqa: E402
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


def _on_off(flag):
    """Render a toggle's state for the status line."""
    return "on" if flag else "off"


class AsciiArtLiveCamera:
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
        self.refusal = None         # why the last apply() said no, if it did
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
        self.encoder = None

        # Everything the config touches is pushed out from here, so start-up
        # and a later change go down exactly the same path. `previous=None`
        # means "nothing has been told anything yet", so every field counts.
        self._adopt(self.config, previous=None)

        if args.lcd:
            self.lcd = self._start_lcd()
        if args.encoder:
            self.encoder = self._start_encoder()
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
            True if the config changed, False if it was refused or was a no-op.
            On a refusal `self.refusal` carries why, so a caller that shows the
            user something other than the status line - the command socket - can
            say what happened rather than only "nothing changed".
        """
        self.refusal = None
        try:
            proposed = self.config.with_changes(delta)
        except ConfigError as e:
            logger.warning("Refused %r: %s", delta, e)
            self.refusal = "\n".join(e.problems)
            if note:
                self._note(str(e))
            return False

        if proposed.target != self.config.target:
            problem = self._target_problem(proposed.target)
            if problem is not None:
                logger.warning("Refused target %r: %s; staying on %r",
                               proposed.target, problem, self.config.target)
                self.refusal = problem
                if note:
                    self._note(problem)
                return False

        if proposed == self.config:
            return False

        previous, self.config = self.config, proposed
        self._adopt(proposed, previous)
        return True

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

    @staticmethod
    def _short_failure(error):
        """
        Turn a ParseError into something that fits a 320-pixel band.

        The socket reply keeps the full text - whoever typed it can read a
        sentence. The panel gets the kind of failure, because "the network is
        down" and "the key was refused" call for different actions and the
        difference between them is worth the two words it costs.
        """
        text = str(error).lower()
        if "timeout" in text or "timed out" in text:
            return "the model took too long - try again"
        if "connection" in text or "network" in text or "resolve" in text:
            return "no network - words need one, settings do not"
        if "authentication" in text or "api key" in text or "401" in text:
            return "the API key was refused"
        if "rate" in text and "limit" in text:
            return "asking too fast - wait a moment"
        return "could not ask the model"

    def _start_lcd(self):
        """
        Bring the SPI panel up as a second, independent output.

        Deliberately not fatal on failure.  The terminal is the primary display
        and a missing, unwired or misbehaving panel should cost a log line, not
        the whole app.  The imports are done here rather than at module level so
        that spidev and RPi.GPIO are only required when the panel is asked for.
        """
        try:
            from panel.lcd_display import LcdDisplay
            from panel.lcd_worker import LcdWorker

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

    def _start_encoder(self):
        """
        Bring the rotary encoder up, or carry on without it.

        Not fatal on failure, for the same reason the LCD is not: the knob is a
        convenience over a key that still works, so an unplugged or misconfigured
        encoder should cost a log line rather than the whole app.  lgpio is
        imported inside RotaryEncoder so this stays runnable off the Pi.
        """
        try:
            from control.encoder import RotaryEncoder

            return RotaryEncoder(clk=self.args.encoder_clk,
                                 dt=self.args.encoder_dt,
                                 sw=self.args.encoder_sw,
                                 reverse=self.args.encoder_reverse).start()
        except Exception as e:
            logger.error("Rotary encoder unavailable, continuing without "
                         "it: %s", e, exc_info=True)
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

            server = CommandServer(self.args.command_socket,
                                   resolver=self._resolve_ask).start()
            try:
                from language import asklog

                self.asklog = asklog.AskLog()
            except Exception as e:
                # Asks still work; they are just not written down.
                logger.error("Ask log unavailable: %s", e, exc_info=True)
            self._warm_parser()
            return server
        except Exception as e:
            logger.error("Command socket unavailable, continuing without "
                         "it: %s", e, exc_info=True)
            return None

    def _warm_parser(self):
        """
        Import the model SDK in the background, so the first ask is not slow.

        Measured on this Pi: `import anthropic` alone costs 11 seconds, which
        is longer than the CLI used to wait for any reply at all. Left lazy,
        the first "ask" after every restart timed out on the client while
        quietly succeeding on the app - the worst of both, a reported failure
        and a changed setting.

        A daemon thread, started once, and only when there is a key to make it
        worth paying for: without one, ask is off and an 11-second import buys
        nothing but resident memory on a 416 MB machine.
        """
        try:
            from language import parser as nl_parser
        except Exception as e:
            logger.info("Natural language unavailable: %s", e)
            return
        if nl_parser.api_key() is None:
            logger.info("No API key found, so \"ask\" is off; every other "
                        "command still works")
            return

        def warm():
            import time
            started = time.monotonic()
            try:
                import anthropic                            # noqa: F401
            except Exception as e:
                logger.error("Could not load the model SDK: %s", e)
                return
            logger.info("Model SDK ready in %.1f s; \"ask\" is available",
                        time.monotonic() - started)

        threading.Thread(target=warm, name="warm-parser", daemon=True).start()

    # Set when the command socket comes up, which is the only way an ask can
    # arrive. A class attribute rather than an __init__ line so that anything
    # holding an app built without running __init__ - the tests do exactly
    # this - still finds the name and gets a no-op instead of AttributeError.
    asklog = None

    def _resolve_ask(self, line):
        """
        Turn "ask warmer, and blockier" into a delta - on the caller's thread.

        This is the one piece of the app that is allowed to be slow. It runs on
        the command socket's client thread, never the render loop: a parse
        crosses a network and takes seconds, and the loop cannot stop for that
        without stopping both displays with it.

        Returns None for any line that is not an ask, which is every ordinary
        typed command - those go straight through untouched.
        """
        from control.command_server import Ask, Reply

        head, _, rest = line.partition(" ")
        if head.lower() != "ask":
            return None

        utterance = rest.strip()
        if not utterance:
            return Reply('say what you want changed, e.g. ask make it warmer')

        # Read the config from this thread. It is a frozen dataclass replaced
        # wholesale on the loop's thread, so this either sees the change or does
        # not - never a half-applied one.
        config, previous = self.config, self.previous_config

        # The table first, and deliberately before the key check: "green" and
        # "freeze it" are answerable with no key and no network, so an ask is no
        # longer all or nothing when the WiFi is down. A hit costs nothing and
        # takes no measurable time.
        delta = shortcuts.look_up(utterance, config, previous)
        if delta is not None:
            logger.info("Ask %r -> %s (table)", utterance, delta)
            self._log_ask(utterance, config, previous, delta=delta,
                          source="table", seconds=0.0)
            return Ask(utterance=utterance, delta=delta, note="instant")

        try:
            from language import parser as nl_parser
        except Exception as e:
            return Reply(f"the language model parser is unavailable: {e}")
        if nl_parser.api_key() is None:
            self._note("no API key, so words are off")
            return Reply("no API key, so ask is off. Put one in "
                         f"{nl_parser.KEY_FILE} to switch it on; every other "
                         "command works without it.")

        # A parse takes two to four seconds, and on a panel with no spinner
        # that is indistinguishable from a camera that ignored you. Say so - and
        # for longer than the parser's own timeout, since the point is that the
        # message cannot expire while the request is still out. The default four
        # seconds was wrong for exactly this: a request may run for twenty, and
        # the panel would go quiet two-thirds of the way through it.
        self._note(f"asking: {utterance[:40]}",
                   seconds=nl_parser.TIMEOUT_SECONDS + 2)

        # A parse that raced a keypress resolves against settings one change
        # stale, which for "a bit warmer" is not worth a lock.
        try:
            parsed = nl_parser.parse(utterance, config, previous=previous)
        except nl_parser.ParseError as e:
            # Network down, key rejected, timeout. The panel and the terminal
            # both have to survive this, so it is a sentence, not a traceback.
            logger.warning("Ask failed for %r: %s", utterance, e)
            self._log_ask(utterance, config, previous, error=str(e))
            # Said on the panel as well as returned to whoever asked. This is
            # the whole of "honest failure": the camera did not do what it was
            # told, and the only display in the box has to admit it rather than
            # carry on showing a picture as though nothing was asked.
            self._note(self._short_failure(e))
            return Reply(f"could not reach the model: {e}")

        if parsed.declined is not None:
            logger.info("Ask declined %r: %s", utterance, parsed.declined)
            self._log_ask(utterance, config, previous, parsed=parsed)
            # A decline is an answer, not a failure - but it is still an answer
            # nobody sees if it only goes back down the socket.
            self._note("cannot do that: " + parsed.declined)
            return Reply(f"  {parsed.declined}")

        note = f"{parsed.seconds:.1f}s"
        if parsed.unmet:
            note += f" - {parsed.unmet}"
        logger.info("Ask %r -> %s (%s)", utterance, parsed.delta, note)
        self._log_ask(utterance, config, previous, parsed=parsed)
        return Ask(utterance=utterance, delta=parsed.delta, note=note)

    def _log_ask(self, utterance, config, previous, parsed=None, error=None,
                 delta=None, seconds=None, source="model"):
        """
        Write one ask down, if there is anywhere to write it.

        Runs on the socket's client thread with the parse, never the render
        loop. Silent when there is no log: an ask that works is worth more than
        a record of it, so this is the one place in the path allowed to do
        nothing at all.
        """
        if self.asklog is None:
            return
        self.asklog.record(
            utterance, config, previous=previous, error=error, source=source,
            delta=delta if parsed is None else parsed.delta or None,
            declined=None if parsed is None else parsed.declined,
            unmet=None if parsed is None else parsed.unmet,
            seconds=seconds if parsed is None else parsed.seconds,
            usage=None if parsed is None else parsed.usage)

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
        One request in, the text to print back out.

        Usually a line somebody typed. Sometimes an Ask: a delta the resolver
        already worked out on another thread, which from here is just a delta
        like any other and goes down the same path with the same validation.
        """
        from control.command_server import Ask

        if isinstance(request, Ask):
            logger.info("Command: ask %s", request.utterance)
            before = self.config
            if self.apply(request.delta, note=False):
                return (f"  {self.config.describe_changes(before)}"
                        f"\n  ({request.note})")
            if self.refusal:
                return "\n".join("  " + line
                                  for line in self.refusal.splitlines())
            return f"  nothing changed ({request.note})"

        line = request
        logger.info("Command: %s", line)
        try:
            kind, payload = commands.parse(line)
        except commands.CommandError as e:
            return str(e)

        if kind == "none":
            return ""
        if kind == "help":
            return commands.help_text(payload, self.config)
        if kind == "show":
            return commands.show_text(self.config)
        if kind == "reset":
            payload = commands.defaults_delta(self.config)
            # A delta is applied whole or not at all, so a single field this
            # run cannot honour would take the other eleven down with it. That
            # is right for a delta somebody typed - it says what they asked for
            # and they should be told no - but wrong for "put everything back",
            # which should restore what it can. Headless, the default target of
            # "both" is unreachable, and reset used to refuse outright and
            # report "nothing changed" over five non-default settings.
            if "target" in payload:
                payload["target"] = self._feasible_target(payload["target"])
            payload = {name: value for name, value in payload.items()
                       if getattr(self.config, name) != value}
            if not payload:
                return "already at the defaults"

        # From here it is an ordinary delta, applied down the same path a
        # keypress uses - so a typed setting and a pressed key cannot diverge,
        # and neither can get past the validation the other would have hit.
        before = self.config
        # note=False: the reply says what happened, and a status-line notice
        # would be saying it a second time to someone looking elsewhere.
        if self.apply(payload, note=False):
            return "  " + self.config.describe_changes(before)
        if self.refusal:
            return "\n".join("  " + line
                             for line in self.refusal.splitlines())
        return "  nothing changed"

    def _poll_encoder(self):
        """Turn accumulated knob movement and presses into scheme changes."""
        if self.encoder is None:
            return
        steps = self.encoder.take()
        pressed = self.encoder.take_presses()

        # A press wins over rotation banked in the same frame, and the rotation
        # is dropped rather than applied on top. Only counts survive the wait
        # between frames, not the order they happened in, so there is no way to
        # tell "turn then press" from "press then turn" - and of the two
        # answers available, going home is the one the user can see is right,
        # since it is the same wherever the knob had got to. Applying both would
        # also cost two repaints for one glance at the screen.
        if pressed:
            self._home_scheme()
            return

        # Handed over as one move, not one call per detent: everything banked
        # since the last frame lands on a single repaint. See _cycle_scheme.
        if steps:
            self._cycle_scheme(steps)

    def _home_scheme(self):
        """
        Jump straight back to greyscale, however far the knob has wandered.

        Found by kind rather than by name, so renaming the scheme cannot turn
        this into a lookup that raises. The greyscale scheme is also the one
        scheme every terminal can show, so this is the one jump that is always
        available - see the colour_ok test in _cycle_scheme.
        """
        home = next(scheme for scheme in palettes.SCHEMES
                    if scheme.kind == "grey")
        # apply() is a no-op when the value is already there, so being home
        # already costs nothing and no repaint flashes.
        if self.apply({"scheme": home.name}):
            logger.info("Scheme: %s (%s) - knob pressed", home.name, home.note)

    @property
    def scheme(self):
        """The active colour scheme."""
        return palettes.by_name(self.config.scheme)

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
        start = palettes.SCHEME_NAMES.index(self.config.scheme)

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
        index = start
        for _ in range(abs(step) % count):
            for offset in range(1, count + 1):
                candidate = (index + direction * offset) % count
                if (palettes.SCHEMES[candidate].kind == "grey"
                        or self.display.colour_ok):
                    index = candidate
                    break
            else:
                return

        if index == start:
            return
        # No grid invalidation on purpose: the grid does not depend on the
        # scheme any more, so recomputing it would only produce the same answer
        # and log a line claiming a change that did not happen. _adopt knows
        # this - the scheme is not in the set that clears grid_key.
        scheme = palettes.SCHEMES[index]
        if self.apply({"scheme": scheme.name}):
            logger.info("Scheme: %s (%s)", scheme.name, scheme.note)

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
        Text for the bottom status line, trimmed to what the window can show.

        Rather than let a fixed string get chopped mid-word, drop whole
        sections from the right until it fits.
        """
        config = self.config
        if config.freeze:
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
        geometry = f"{cols}x{rows}" if self.display.draws else "headless"
        stats = (f" {rate} {geometry} rot{config.rotation}"
                 f" con{config.contrast:.1f}"
                 f" sch:{config.scheme}"
                 f" chr:{config.ramp}"
                 f" auto:{_on_off(config.auto_levels)}"
                 f" fill:{_on_off(config.fill)}"
                 f" inv:{_on_off(config.invert)}"
                 f" tgt:{config.target}")

        if self.lcd is not None:
            # Showing the panel's own grid makes its independence from the
            # terminal's visible: resizing the window moves one and not the
            # other, and changing the panel font moves the panel's alone.
            stats += " lcd:%dx%d@%d" % (self.lcd.display.grid_size
                                        + (config.lcd_font_size,))

        width = self.display.cols - 1

        # A refusal or a clamp beats the key list: the list is the same every
        # frame and the message is the answer to what was just pressed.
        if self.notice is not None:
            text, expires = self.notice
            if time.monotonic() < expires:
                return f"{stats} | {text}"[:width]
            self.notice = None

        for keys in (" | q:quit r:rotate f:fill i:invert c:chars +/-:contrast"
                     " a:auto s:scheme SPC:freeze t:target l:lcdfont",
                     " | q:quit r:rotate f:fill i:invert c:chars s:scheme"
                     " SPC:freeze t:target",
                     " | q:quit r:rotate f:fill s:scheme SPC:freeze",
                     " | q:quit",
                     ""):
            if len(stats) + len(keys) <= width:
                return stats + keys
        return stats

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
            self._cycle_scheme()
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

    def run(self):
        """Main loop."""
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

                if self.config.freeze and self._held is not None:
                    # Frozen, so the picture is whatever was last captured. The
                    # camera is deliberately left running: stopping it would
                    # make unfreezing cost the 15-20 seconds libcamera takes to
                    # come back, and its queue is one deep, so nothing piles up.
                    if not self._redraw and self.notice is None:
                        # Nothing has changed and nothing is moving, so there is
                        # no picture to draw. Without this the loop would redraw
                        # a still frame at the full rate - and push it down the
                        # SPI bus - for no visible difference at all.
                        #
                        # A live notice is the exception: it has to appear and
                        # then, four seconds later, go away, and _status is what
                        # retires it. This settles by itself - the redraw that
                        # shows the expired notice is the one that clears it.
                        if not self._drain_input():
                            break
                        time.sleep(FROZEN_TICK)
                        continue
                    frame = self._held
                else:
                    frame = self.camera.get_frame(timeout=1.0)
                    if frame is None:
                        # The camera caps its own rate, so a miss here means it
                        # is still warming up (or has stalled) rather than that
                        # we are polling too fast.
                        self.dropped += 1
                        self.display.message("Waiting for camera...")
                        self._note_if_stalled()
                        if not self._drain_input():
                            break
                        continue
                    self._held = frame
                    self._last_frame_at = time.monotonic()
                    self._stall_noted = None

                self._redraw = False

                # Hand the panel the frame before doing any work for the
                # terminal, so the two renders overlap instead of queueing.
                if self.lcd_on:
                    self.lcd.submit(frame, self.config)

                if self.terminal_on:
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
                elif self.display.draws:
                    # There is a window, but the picture has been sent to the
                    # panel alone. Say so rather than leave it blank, and skip
                    # the build - which is the whole saving being asked for.
                    ascii_lines, colours = (TERMINAL_OFF,), None
                else:
                    # No terminal at all: the panel does its own downscale and
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
            if self.commands is not None:
                # Same reasoning again, for the socket file: one left behind
                # makes the next run's bind fail with the address still in use.
                self.commands.stop()
            logger.info("Rendered %d frames in %.1fs (%.1f avg fps), "
                        "%d camera timeouts", self.frame_count, elapsed,
                        avg, self.dropped)

    def _drain_input(self):
        """
        Apply everything the user has done since the last frame.

        The knob is read here rather than on its own timer so that it lands in
        the same place in the loop as a keypress: one scheme change per frame
        at most, applied before the next frame is drawn. Typed commands arrive
        by the same route, from the socket thread - and later, a phone's HTTP
        handler will deliver into the same queue.
        """
        self._poll_encoder()
        self._poll_commands()
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
    parser.add_argument("--version", action="version",
                        version=f"{APP_NAME} {__version__}",
                        help="Print the version and exit")
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
    parser.add_argument("--colour-levels", type=int,
                        default=render_config.MAX_COLOUR_LEVELS,
                        help=f"Steps per channel in the live-colour scheme, "
                             f"2 to {render_config.MAX_COLOUR_LEVELS}. Fewer "
                             "means longer runs of one colour and a cheaper "
                             "redraw, at the cost of banding. The maximum "
                             "quantises nothing. The terminal saturates at 6 "
                             "of these, which is all the xterm cube has; the "
                             "panel uses the whole range. Out of range is "
                             "clamped")
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
                             "work when stdin is a terminal, as it is over "
                             "SSH. Distinct from t, which moves the picture "
                             "between outputs that both exist; this one "
                             "declines to open a window at all")
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
                          "nothing is cropped or letterboxed. Step through "
                          "those three live with l")
    lcd.add_argument("--lcd-portrait", action="store_true",
                     help="Run the panel as 240x320 instead of 320x240")
    lcd.add_argument("--lcd-spi-hz", type=int, default=40_000_000,
                     help="SPI clock. Lower it if the wiring is long or on a "
                          "breadboard")
    lcd.add_argument("--lcd-brightness", type=int, default=100,
                     help="Backlight duty cycle, 0-100")
    lcd.add_argument("--lcd-splash-seconds", type=float,
                     default=DEFAULT_SPLASH_HOLD,
                     help="How long the start-up screen stays on the panel "
                          "once the camera is ready. The camera beats it by "
                          "some margin, so without this the screen would be a "
                          "flicker. 0 hands over as soon as there is a "
                          "picture")
    knob = parser.add_argument_group(
        "KY-040 rotary encoder",
        "A knob that steps through the colour schemes, doing what s does from "
        "the keyboard - except that it also goes backwards. Pressing it jumps "
        "back to greyscale. Works headless, where there is no keyboard to "
        "press s on.")
    knob.add_argument("--encoder", action="store_true",
                      help="Cycle colour schemes with the rotary encoder")
    knob.add_argument("--encoder-clk", type=int, default=19,
                      help="BCM pin for CLK")
    knob.add_argument("--encoder-dt", type=int, default=26,
                      help="BCM pin for DT")
    knob.add_argument("--encoder-sw", type=int, default=6,
                      help="BCM pin for the push switch, which jumps back to "
                           "greyscale. Give a negative number if the switch is "
                           "not wired; leaving it set costs nothing either way, "
                           "since an unwired pin idles high and stays quiet")
    knob.add_argument("--encoder-reverse", action="store_true",
                      help="Swap which way the knob steps. Which rotation "
                           "counts as forwards depends on which pin was wired "
                           "to CLK, so if the knob runs backwards, add this")
    typed = parser.add_argument_group(
        "Typed commands",
        "A local socket for setting things by name rather than by key - "
        "\"scheme green\", \"contrast 2.4 invert on\". Drive it with "
        "tools/app/asciicam_cli.py from any shell, including against the systemd "
        "service, which has no terminal to type at. It is a Unix socket with "
        "mode 0600, so it is not reachable from the network and only this user "
        "can connect.")
    typed.add_argument("--command-socket",
                       default=str(Path(__file__).resolve().parent
                                   / "asciicam.sock"),
                       help="Path to the command socket")
    typed.add_argument("--no-commands", action="store_const", const="",
                       dest="command_socket",
                       help="Do not open the command socket at all")
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
    logger.info("=== %s %s starting: %s ===", APP_NAME, __version__,
                vars(args))

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
