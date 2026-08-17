#!/usr/bin/env python3
"""
Check RenderConfig, and the app's single path for changing a setting.

    python3 tests/render_config_test.py

No camera, no panel, no terminal: RenderConfig is pure, and the app is built
without running __init__ so the key handler can be called directly. That is the
same trick tests/keymap_test.py uses, and for the same reason - one call is
exactly one keypress, with none of piinput's dropped and doubled events.

What is worth testing here is not that a dataclass stores what it is given. It
is the three things that can silently go wrong:

  * the clamp/refuse split, and in particular that `False` is not quietly
    accepted as rotation 0, which is what happens if you forget that bool is a
    subclass of int;
  * that a key still causes every side effect it used to - rebuilding the ASCII
    generator, invalidating the grid, repainting on a fill change - now that
    those live in _adopt rather than in the key handler;
  * that SPECS and the dataclass have not drifted apart, which is the failure
    that would otherwise show up as a setting nothing can change.
"""

import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import numpy as np                                # noqa: E402

import ascii_camera                                # noqa: E402
import palettes                                   # noqa: E402
import render_config                              # noqa: E402
from ascii_camera import AsciiArtLiveCamera       # noqa: E402
from image_processor import ImageProcessor        # noqa: E402
from render_config import ConfigError, RenderConfig  # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def refuses(delta):
    """(was it refused, what it said)."""
    try:
        RenderConfig().with_changes(delta)
    except ConfigError as e:
        return True, str(e)
    return False, ""


# --------------------------------------------------------------------------
# 1. The surface itself
# --------------------------------------------------------------------------

def test_surface():
    print("\n1. Every field is specified, and every spec is a field")
    from dataclasses import fields

    declared = [f.name for f in fields(RenderConfig)]
    specified = [s.name for s in render_config.SPECS]
    check("SPECS and the dataclass list the same fields in the same order",
          declared == specified, f"{declared} vs {specified}")

    # The point of SPECS is that a schema can be generated from it rather than
    # written out a second time, which needs every entry to be complete.
    for spec in render_config.SPECS:
        check(f"{spec.name} says what it is for", bool(spec.note.strip()))
        if spec.kind == "choice":
            check(f"{spec.name} lists its choices", len(spec.choices) >= 2,
                  str(spec.choices))
        elif spec.kind in ("int", "float"):
            check(f"{spec.name} has a range",
                  spec.low is not None and spec.high is not None
                  and spec.low < spec.high, f"{spec.low}..{spec.high}")
        else:
            check(f"{spec.name} is a bool with no choices or range",
                  spec.kind == "bool" and not spec.choices
                  and spec.low is None and spec.high is None)

    print("\n2. The defaults are the ones the app used to start with")
    default = RenderConfig()
    check("greyscale", default.scheme == "grey", default.scheme)
    check("the coarse ramp", default.ramp == "coarse", default.ramp)
    check("contrast 1.0", default.contrast == 1.0, str(default.contrast))
    check("auto-levels on", default.auto_levels is True)
    check("not inverted, not mirrored, not filling, not rotated",
          not (default.invert or default.mirror or default.fill
               or default.rotation))
    check("both displays", default.target == "both", default.target)
    check("not frozen", default.freeze is False)
    check("panel font 8", default.lcd_font_size == 8,
          str(default.lcd_font_size))
    check("colour_levels at its maximum, meaning no quantising",
          default.colour_levels == render_config.MAX_COLOUR_LEVELS,
          str(default.colour_levels))

    print("\n3. The scheme and ramp choices come from their own modules")
    # Restating them here would let a scheme be added to palettes.py and stay
    # unreachable through the config, which is exactly the drift SPECS exists
    # to prevent.
    check("every scheme is offerable",
          set(render_config.BY_NAME["scheme"].choices)
          == set(palettes.SCHEME_NAMES))
    from ascii_art import RAMPS
    check("every ramp is offerable",
          set(render_config.BY_NAME["ramp"].choices) == set(RAMPS))


# --------------------------------------------------------------------------
# 2. Validation: what is clamped, what is refused
# --------------------------------------------------------------------------

def test_accepts():
    print("\n4. A good delta is applied, and leaves the original alone")
    start = RenderConfig()
    after = start.with_changes({"scheme": "green", "contrast": 2.5})
    check("the new config has the change", after.scheme == "green"
          and after.contrast == 2.5, f"{after.scheme} {after.contrast}")
    check("the old config does not", start.scheme == "grey"
          and start.contrast == 1.0, f"{start.scheme} {start.contrast}")
    check("untouched fields are carried over", after.ramp == start.ramp
          and after.auto_levels == start.auto_levels)

    check("an empty delta is legal and changes nothing",
          start.with_changes({}) == start)


def test_clamping():
    print("\n5. A number outside its range is clamped, not refused")
    check("contrast 9 becomes 4.0",
          RenderConfig().with_changes({"contrast": 9}).contrast == 4.0)
    check("contrast -3 becomes 0.1",
          RenderConfig().with_changes({"contrast": -3}).contrast == 0.1)
    check("panel font 40 becomes 16",
          RenderConfig().with_changes({"lcd_font_size": 40}).lcd_font_size
          == 16)
    check("panel font 1 becomes 4",
          RenderConfig().with_changes({"lcd_font_size": 1}).lcd_font_size == 4)
    # colour_levels used to be an enumeration of 2..6 and so was refused when
    # out of range. With 31 values it is a range, and ranges clamp - which is
    # the documented rule, and the reason it changed kind rather than growing
    # thirty-one choices nobody would want listed in an error message.
    check("colour_levels 900 becomes the maximum",
          RenderConfig().with_changes({"colour_levels": 900}).colour_levels
          == render_config.MAX_COLOUR_LEVELS)
    check("colour_levels 1 becomes 2",
          RenderConfig().with_changes({"colour_levels": 1}).colour_levels == 2)

    print("\n6. And is normalised to the field's own type")
    got = RenderConfig().with_changes({"lcd_font_size": 8.6})
    check("a float font size is rounded to an int",
          got.lcd_font_size == 9 and isinstance(got.lcd_font_size, int),
          repr(got.lcd_font_size))
    got = RenderConfig().with_changes({"contrast": 2})
    check("an int contrast is stored as a float",
          isinstance(got.contrast, float), repr(got.contrast))
    got = RenderConfig().with_changes({"rotation": 90.0})
    check("a float rotation matching a choice is stored as that choice",
          got.rotation == 90 and isinstance(got.rotation, int),
          repr(got.rotation))


def test_refusals():
    print("\n7. A value outside an enumeration is refused")
    for delta, wanted in [
        ({"scheme": "purple"}, "scheme"),
        ({"rotation": 45}, "rotation"),
        ({"ramp": "blocks"}, "ramp"),
        ({"target": "printer"}, "target"),
    ]:
        refused, said = refuses(delta)
        check(f"{delta} is refused", refused, said)
        check(f"...and the message names {wanted}", wanted in said, said)

    print("\n8. So is an unknown field, and the wrong type")
    refused, said = refuses({"brightness": 3})
    check("an unknown setting is refused", refused, said)
    check("...and the message lists the real ones", "scheme" in said, said)

    refused, said = refuses({"invert": 1})
    check("1 is not accepted for a bool", refused, said)
    refused, said = refuses({"invert": "yes"})
    check("'yes' is not accepted for a bool", refused, said)
    refused, said = refuses({"contrast": "a lot"})
    check("a string is not accepted for a number", refused, said)

    print("\n9. False is not silently accepted as rotation 0")
    # bool is a subclass of int, so `False in (0, 90, 180, 270)` is True and
    # `False == 0` is True. Without an explicit bool check, a delta meant for
    # freeze but addressed to rotation would be accepted as "no rotation" -
    # a wrong field taking a wrong value and reporting success.
    refused, said = refuses({"rotation": False})
    check("rotation False is refused", refused, said)
    refused, said = refuses({"colour_levels": True})
    check("colour_levels True is refused", refused, said)

    print("\n10. Every fault in a delta is reported, not just the first")
    try:
        RenderConfig().with_changes({"scheme": "purple", "rotation": 45,
                                     "nonsense": 1})
        check("a bad delta raises", False)
    except ConfigError as e:
        check("a bad delta raises", True)
        check("all three faults are listed", len(e.problems) == 3,
              f"{len(e.problems)}: {e.problems}")

    print("\n11. A refused delta changes nothing at all")
    start = RenderConfig(scheme="amber", contrast=2.0)
    try:
        # A good field alongside a bad one: the good one must not be applied.
        start.with_changes({"scheme": "green", "rotation": 45})
    except ConfigError:
        pass
    check("the config is untouched after a refusal",
          start.scheme == "amber" and start.contrast == 2.0,
          f"{start.scheme} {start.contrast}")


def test_diffing():
    print("\n12. Changes can be named, which is what the log and the app use")
    a = RenderConfig()
    b = a.with_changes({"scheme": "green", "invert": True})
    check("only the changed fields are reported",
          set(b.changes_from(a)) == {"scheme", "invert"},
          str(b.changes_from(a)))
    check("an identical config reports nothing", b.changes_from(b) == ())
    check("changes_from(None) reports every field",
          len(a.changes_from(None)) == len(render_config.SPECS))

    described = b.describe_changes(a)
    check("the description carries old and new", "grey" in described
          and "green" in described, described)
    check("an unchanged pair describes as nothing", b.describe_changes(b) == "")

    check("as_delta round-trips through with_changes",
          RenderConfig().with_changes(b.as_delta()) == b)


# --------------------------------------------------------------------------
# 3. The app: one path in, and every side effect still happening
# --------------------------------------------------------------------------

class StubDisplay:
    """Just enough display for apply() and the key handler to talk to."""

    draws = True

    def __init__(self):
        self.colour_ok = True
        self.scheme = palettes.SCHEMES[0]
        self.cleared = 0
        self.repaints = 0
        self.cols = 200

    def set_scheme(self, scheme):
        self.repaints += 1
        self.scheme = scheme

    def clear(self):
        self.cleared += 1

    def refresh_size(self):
        return False


class StubLcd:
    """Stands in for the LcdWorker, counting what the app asks of it."""

    class _Display:
        grid_size = (64, 24)

    def __init__(self):
        self.display = self._Display()
        self.blanks = 0
        self.submitted = 0
        self.splashes = []

    def blank(self):
        self.blanks += 1

    def submit(self, frame, config):
        self.submitted += 1

    def splash(self, message, detail=None):
        self.splashes.append(message)

    def stop(self, timeout=3.0):
        pass


def make_app(lcd=None, draws=True):
    """An AsciiArtLiveCamera with only what apply() and the keys touch."""
    app = object.__new__(AsciiArtLiveCamera)
    app.display = StubDisplay()
    app.display.draws = draws
    app.processor = ImageProcessor()
    app.config = RenderConfig()
    app.notice = None
    app.refusal = None
    app.previous_config = None
    app.grid_key = None
    app.grid = (80, 30)
    app.lcd = lcd
    app.encoder = None
    # Built without __init__, so every attribute the loop touches has to be
    # named here. None means "no command socket", which is what these tests
    # want: they drive the app through keys, and a socket would only add a
    # thread with nothing to say.
    app.commands = None
    app._held = None
    app._redraw = False
    app.frame_times = []
    app._rebuild_ascii()
    return app


def test_one_path_in():
    print("\n13. apply() pushes settings out to everything that needs them")
    app = make_app()

    app.apply({"contrast": 2.0, "rotation": 90, "mirror": True})
    check("the processor is given the new contrast",
          app.processor.contrast == 2.0, str(app.processor.contrast))
    check("...the new rotation", app.processor.rotation == 90,
          str(app.processor.rotation))
    check("...and the new mirror", app.processor.mirror is True)
    check("a rotation change invalidates the grid", app.grid_key is None)

    app.grid_key = "stale"
    app.apply({"contrast": 2.1})
    check("a contrast change does not invalidate the grid",
          app.grid_key == "stale", str(app.grid_key))

    print("\n14. A ramp or invert change rebuilds the ASCII generator")
    app = make_app()
    before = app.ascii_art
    app.apply({"invert": True})
    check("invert rebuilds it", app.ascii_art is not before)
    check("...and the ramp is actually reversed",
          app.ascii_art.chars == before.chars[::-1], app.ascii_art.chars)

    before = app.ascii_art
    app.apply({"ramp": "fine"})
    check("a ramp change rebuilds it", app.ascii_art is not before)

    before = app.ascii_art
    app.apply({"colour_levels": 3})
    check("a colour_levels change rebuilds it", app.ascii_art is not before)

    before = app.ascii_art
    app.apply({"contrast": 1.5})
    check("a contrast change does not", app.ascii_art is before)

    print("\n15. A fill change repaints; a scheme change tells the display")
    app = make_app()
    app.apply({"fill": True})
    check("fill clears the window", app.display.cleared == 1,
          f"{app.display.cleared} clears")
    check("fill invalidates the grid", app.grid_key is None)

    app = make_app()
    app.apply({"scheme": "green"})
    check("the display is given the scheme",
          app.display.scheme.name == "green", app.display.scheme.name)
    check("exactly one repaint", app.display.repaints == 1,
          f"{app.display.repaints} repaints")

    print("\n16. A no-op change costs nothing")
    app = make_app()
    app.apply({"scheme": "grey", "contrast": 1.0})
    check("setting a field to what it already is does not repaint",
          app.display.repaints == 0, f"{app.display.repaints} repaints")
    check("...and reports that nothing happened",
          app.apply({"contrast": 1.0}) is False)

    print("\n17. A refused change reaches neither the config nor the hardware")
    app = make_app()
    ok = app.apply({"scheme": "purple"})
    check("apply reports the refusal", ok is False)
    check("the config is unchanged", app.config.scheme == "grey",
          app.config.scheme)
    check("the display was not repainted", app.display.repaints == 0)
    check("and the user is told", app.notice is not None
          and "scheme" in app.notice[0], str(app.notice))


def test_keys_still_work():
    print("\n18. Every key still does what it did, through the new path")
    app = make_app()

    app._handle_key("i")
    check("i inverts", app.config.invert is True)

    app._handle_key("c")
    check("c changes the ramp", app.config.ramp != "coarse", app.config.ramp)

    app._handle_key("f")
    check("f toggles fill", app.config.fill is True)

    before = app.config.rotation
    app._handle_key("r")
    check("r rotates by 90", app.config.rotation == (before + 90) % 360,
          f"{before} -> {app.config.rotation}")

    app._handle_key("a")
    check("a toggles auto-levels", app.config.auto_levels is False)

    app._handle_key("s")
    check("s cycles the scheme", app.config.scheme == "live",
          app.config.scheme)

    contrast = app.config.contrast
    app._handle_key("+")
    check("+ raises contrast", app.config.contrast > contrast)
    app._handle_key("-")
    check("- lowers contrast", abs(app.config.contrast - contrast) < 1e-6,
          str(app.config.contrast))

    check("q quits", app._handle_key("q") is False)

    print("\n19. Contrast stops at the ends without any arithmetic to do it")
    app = make_app()
    for _ in range(60):
        app._handle_key("+")
    check("+ cannot push contrast past 4.0", app.config.contrast == 4.0,
          str(app.config.contrast))
    for _ in range(80):
        app._handle_key("-")
    check("- cannot push it below 0.1", app.config.contrast == 0.1,
          str(app.config.contrast))


def test_freeze():
    print("\n20. Space freezes and unfreezes")
    app = make_app()
    app._handle_key(" ")
    check("space freezes", app.config.freeze is True)
    app._handle_key(" ")
    check("space again unfreezes", app.config.freeze is False)

    print("\n21. A change while frozen asks for a redraw")
    # The frozen loop only draws when _redraw is set. If a setting change did
    # not set it, the panel would keep the old picture and the app would look
    # like it had ignored the key - which is the one failure mode freeze adds.
    app = make_app()
    app.apply({"freeze": True})
    app._redraw = False
    app.apply({"scheme": "amber"})
    check("changing a setting while frozen sets _redraw", app._redraw is True)


def test_target():
    print("\n22. The target moves the picture between outputs")
    lcd = StubLcd()
    app = make_app(lcd=lcd)
    check("both outputs draw to start with",
          app.terminal_on and app.lcd_on)

    app.apply({"target": "terminal"})
    check("the terminal keeps drawing", app.terminal_on)
    check("the panel stops", not app.lcd_on)
    check("and is blanked rather than left on a stale frame",
          lcd.blanks == 1, f"{lcd.blanks} blanks")

    app.apply({"target": "lcd"})
    check("the panel draws again", app.lcd_on)
    check("the terminal stops", not app.terminal_on)

    print("\n23. t steps through the targets")
    app = make_app(lcd=StubLcd())
    seen = [app.config.target]
    for _ in range(3):
        app._handle_key("t")
        seen.append(app.config.target)
    check("t visits all three and returns", seen == ["both", "terminal",
                                                     "lcd", "both"],
          " -> ".join(seen))

    print("\n24. A target that would show the picture to nobody is refused")
    app = make_app(lcd=None)
    ok = app.apply({"target": "lcd"})
    check("'lcd' with no panel is refused", ok is False)
    check("the target is unchanged", app.config.target == "both",
          app.config.target)
    check("and the user is told why", app.notice is not None, str(app.notice))

    app = make_app(lcd=StubLcd(), draws=False)
    ok = app.apply({"target": "terminal"})
    check("'terminal' with no window is refused", ok is False)
    check("the target is unchanged", app.config.target == "both",
          app.config.target)

    print("\n24b. 'both' is honourable whatever is missing")
    # The bug this pins down: "both" means "draw wherever you can", and the
    # constructor guarantees at least one output exists, so it can never mean
    # "draw nowhere". Refusing it rejected the most inclusive setting on the
    # headless service - and said the picture could not be shown on "both"
    # alone, which is not a sentence that means anything.
    app = make_app(lcd=None)                      # a terminal, no panel
    app.apply({"target": "terminal"})
    ok = app.apply({"target": "both"})
    check("'both' is accepted when there is no panel",
          ok and app.config.target == "both", app.config.target)

    app = make_app(lcd=StubLcd(), draws=False)    # a panel, no terminal
    app.apply({"target": "lcd"})
    ok = app.apply({"target": "both"})
    check("'both' is accepted when there is no terminal",
          ok and app.config.target == "both", app.config.target)

    print("\n24c. A refusal names the missing output, and never says 'alone'")
    app = make_app(lcd=None)
    app.apply({"target": "lcd"})
    check("asking for the panel with none running says so",
          app.refusal is not None and "LCD panel is not running"
          in app.refusal, str(app.refusal))
    check("...and suggests --lcd", "--lcd" in (app.refusal or ""),
          str(app.refusal))

    app = make_app(lcd=StubLcd(), draws=False)
    app.apply({"target": "terminal"})
    check("asking for a terminal with none says so",
          app.refusal is not None and "no terminal" in app.refusal,
          str(app.refusal))
    check("...and blames --no-terminal", "--no-terminal" in (app.refusal or ""),
          str(app.refusal))
    check("no refusal describes an output as being 'alone'",
          "alone" not in (app.refusal or ""), str(app.refusal))

    print("\n25. t does not stop on a target this run cannot honour")
    # With no panel, "both" and "terminal" both mean the same thing and "lcd"
    # is impossible, so the key must skip it rather than appear dead.
    app = make_app(lcd=None)
    for _ in range(4):
        app._handle_key("t")
        check("t never lands on 'lcd' without a panel",
              app.config.target != "lcd", app.config.target)


def test_lcd_font_size():
    print("\n26. l steps through the panel font sizes that tile exactly")
    import ascii_camera

    app = make_app(lcd=StubLcd())
    seen = [app.config.lcd_font_size]
    for _ in range(len(ascii_camera.LCD_FONT_CYCLE)):
        app._handle_key("l")
        seen.append(app.config.lcd_font_size)

    check("every size in the cycle is visited",
          set(seen) == set(ascii_camera.LCD_FONT_CYCLE), str(seen))
    check("and it returns to where it started", seen[0] == seen[-1], str(seen))

    # These are not arbitrary: the panel is 320x240 and DejaVu Sans Mono at
    # these sizes tiles it with no remainder, which is why the cycle stops on
    # them and not on every size the config would accept.
    check("the cycle is a subset of what the config allows",
          all(render_config.RenderConfig().with_changes(
              {"lcd_font_size": size}).lcd_font_size == size
              for size in ascii_camera.LCD_FONT_CYCLE),
          str(ascii_camera.LCD_FONT_CYCLE))



# --------------------------------------------------------------------------
# 4. The render loop itself, where freeze and target actually live
# --------------------------------------------------------------------------
#
# Everything above stops at the config and its immediate collaborators. But
# `freeze` and `target` are not settings the processor reads - they change the
# shape of the loop in run(), and until this section existed nothing in
# software ran that loop at all. Both were verified only by hand, on the Pi.
#
# The camera and the display are fakes, but the loop is the real one.

class LoopCamera:
    """A camera that hands out identical frames and counts how many."""

    class Frame:
        def __init__(self):
            self.luma = np.zeros((240, 320), dtype=np.uint8)

        @property
        def shape(self):
            return (240, 320)

    def __init__(self):
        self.served = 0
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def get_frame(self, timeout=1.0):
        self.served += 1
        return self.Frame()

    def stop(self):
        self.stopped = True


class LoopDisplay:
    """A display that records what it drew and plays back scripted keys."""

    draws = True

    def __init__(self, keys=(), draws=True):
        self.draws = draws
        self.colour_ok = True
        self.scheme = palettes.SCHEMES[0]
        self.cols, self.rows = 200, 60
        self.keys = list(keys)
        self.polls = 0
        self.renders = []           # the ascii_lines of every render
        self.cleared = 0
        self.repaints = 0
        self.messages = []

    # Running out of scripted keys quits, so a test can never hang: the loop
    # always terminates, whatever the behaviour under test turns out to be.
    def get_key(self):
        self.polls += 1
        return self.keys.pop(0) if self.keys else "q"

    @property
    def canvas_size(self):
        return self.cols, max(1, self.rows - 1)

    def cell_metrics(self):
        return None

    def refresh_size(self):
        return False

    def set_scheme(self, scheme):
        self.repaints += 1
        self.scheme = scheme

    def clear(self):
        self.cleared += 1

    def render(self, ascii_lines, status="", colours=None):
        self.renders.append(tuple(ascii_lines))

    def message(self, text):
        self.messages.append(text)


def run_loop(keys, lcd=None, draws=True, config=None):
    """Drive the real run() with fakes. Returns (app, camera, display)."""
    app = make_app(lcd=lcd, draws=draws)
    app.display = LoopDisplay(keys, draws=draws)
    app.camera = LoopCamera()
    app.frame_count = 0
    app.dropped = 0
    app.frame_times = deque(maxlen=20)
    app.is_running = False
    app.cell_aspect = 2.0
    if config is not None:
        app.config = config
    app.run()
    return app, app.camera, app.display


def test_freeze_stops_the_loop_working():
    print("\n27. Freezing stops the camera being read and the picture redrawn")
    # One frame, then space, then a long quiet stretch. If freeze did nothing,
    # the camera would be read once per pass for all of it.
    app, camera, display = run_loop([None, " "] + [None] * 30)

    check("the camera was read only while unfrozen", camera.served <= 3,
          f"{camera.served} frames served")
    check("the picture was drawn only when something changed",
          len(display.renders) <= 3, f"{len(display.renders)} renders")
    check("but the controls kept being polled", display.polls > 10,
          f"{display.polls} polls")
    check("the loop still ended cleanly and released the camera",
          camera.stopped)

    print("\n28. Unfreezing starts it again")
    app, camera, display = run_loop([None, " "] + [None] * 15
                                    + [" "] + [None] * 15)
    check("the camera is read again after the second press",
          camera.served > 3, f"{camera.served} frames served")
    check("and the config ended up unfrozen", app.config.freeze is False)


def test_frozen_picture_still_responds_to_settings():
    print("\n29. A frozen picture is still redrawn when a setting changes")
    # The point of freezing: adjust a still picture and watch it change. If a
    # setting change did not force a redraw, the app would look like it had
    # ignored the key.
    app, camera, display = run_loop([None, " ", None, None, "i"]
                                    + [None] * 10)
    frozen_at = 3
    check("inverting while frozen caused another draw",
          len(display.renders) > frozen_at,
          f"{len(display.renders)} renders")
    check("and the camera was still not read for it", camera.served <= 3,
          f"{camera.served} frames served")
    check("the invert actually took effect", app.config.invert is True)


def test_target_reshapes_the_loop():
    print("\n30. The target decides which outputs do work at all")
    lcd = StubLcd()
    app, camera, display = run_loop([None, None] + [None] * 3, lcd=lcd)
    check("with target=both, frames reach the panel", lcd.submitted > 0,
          f"{lcd.submitted} submitted")
    full = display.renders[-1]
    check("...and the terminal gets a real picture", len(full) > 5,
          f"{len(full)} lines")

    print("\n31. target=terminal stops the panel being fed")
    lcd = StubLcd()
    app, camera, display = run_loop([None, "t"] + [None] * 6, lcd=lcd)
    at_switch = lcd.submitted
    check("the panel was blanked once", lcd.blanks == 1,
          f"{lcd.blanks} blanks")
    check("the terminal still draws a real picture",
          len(display.renders[-1]) > 5, f"{len(display.renders[-1])} lines")
    check("and the panel is fed no further frames",
          lcd.submitted == at_switch or lcd.submitted < 4,
          f"{lcd.submitted} submitted in total")

    print("\n32. target=lcd says so in the window, and skips the build")
    lcd = StubLcd()
    app, camera, display = run_loop([None, "t", "t"] + [None] * 6, lcd=lcd)
    check("the target arrived at the panel alone", app.config.target == "lcd",
          app.config.target)
    last = display.renders[-1]
    check("the window says where the picture went",
          last == (ascii_camera.TERMINAL_OFF,), str(last))
    check("...which is one line, not a rendered grid", len(last) == 1,
          f"{len(last)} lines")
    check("and the panel is being fed", lcd.submitted > 0,
          f"{lcd.submitted} submitted")


def test_headless_builds_nothing():
    print("\n33. With no terminal at all, no picture is built for one")
    lcd = StubLcd()
    app, camera, display = run_loop([None] * 5, lcd=lcd, draws=False,
                                    config=RenderConfig(target="lcd"))
    check("the panel is fed", lcd.submitted > 0, f"{lcd.submitted} submitted")
    check("and nothing is built for the terminal",
          all(lines == () for lines in display.renders),
          f"{display.renders[:2]}")



# --------------------------------------------------------------------------
# 5. The "ask" path: a language model's delta, treated as an ordinary one
# --------------------------------------------------------------------------
#
# No network here. A stub parser stands in for the model, because what needs
# pinning down is the wiring - that a parsed delta goes through the same
# apply() a typed one does, that a refusal changes nothing, and that a failure
# to reach the model is a sentence rather than a traceback. Whether the model
# picks good settings is a different question, and tools/ask_parser.py is where
# it gets asked.
#
# The property that matters most is the one that is invisible in the output:
# the parse happens in _resolve_ask, which the command socket runs on its own
# thread. If it ever migrated into _run_command, every parse would stop the
# render loop - and both displays - for the seconds it takes.

class StubParser:
    """Stands in for src/parser.py, with no API key and no network."""

    KEY_FILE = "/nowhere/api_key"

    class ParseError(RuntimeError):
        pass

    class _Parsed:
        def __init__(self, delta=None, declined=None, unmet=None):
            self.delta = delta
            self.declined = declined
            self.unmet = unmet
            self.seconds = 1.5

        @property
        def ok(self):
            return self.delta is not None

    def __init__(self, key="k", result=None, raises=None):
        self._key = key
        self._result = result
        self._raises = raises
        self.calls = []

    def api_key(self):
        return self._key

    def parse(self, utterance, config, previous=None):
        self.calls.append((utterance, config, previous))
        if self._raises is not None:
            raise self._raises
        return self._result


def with_parser(app, stub):
    """Put the stub where _resolve_ask's `import parser` will find it."""
    import sys
    sys.modules["parser"] = stub
    return app


def test_ask_is_resolved_off_the_loop():
    print("\n34. An ordinary line is not touched by the ask resolver")
    from command_server import Ask, Reply

    app = make_app()
    stub = StubParser(result=StubParser._Parsed(delta={"scheme": "green"}))
    with_parser(app, stub)

    check("a typed line passes straight through",
          app._resolve_ask("scheme green") is None)
    check("...and the model was never called", stub.calls == [])

    print("\n35. An ask becomes a delta, worked out before the loop sees it")
    resolved = app._resolve_ask("ask make it green")
    check("the resolver returns an Ask", isinstance(resolved, Ask),
          type(resolved).__name__)
    check("carrying the delta", resolved.delta == {"scheme": "green"},
          str(resolved.delta))
    check("the model was asked exactly once", len(stub.calls) == 1)
    check("...and given the live config to resolve against",
          stub.calls[0][1] is app.config)
    # Nothing has moved yet: resolving is not applying.
    check("resolving on its own changes nothing", app.config.scheme == "grey",
          app.config.scheme)

    print("\n36. The loop applies it exactly like a typed delta")
    before = app.config
    reply = app._run_command(resolved)
    check("the setting actually changed", app.config.scheme == "green",
          app.config.scheme)
    check("the display was told", app.display.scheme.name == "green")
    check("the reply names the change", "green" in reply, reply.strip())
    check("...and how long the model took", "1.5s" in reply, reply.strip())
    check("it went through the real validator",
          app.config == before.with_changes({"scheme": "green"}))


def test_ask_failures_are_sentences():
    print("\n37. A refusal from the model changes nothing")
    from command_server import Reply

    app = make_app()
    with_parser(app, StubParser(
        result=StubParser._Parsed(declined="I only change display settings.")))
    resolved = app._resolve_ask("ask make me a sandwich")
    check("a decline comes straight back", isinstance(resolved, Reply),
          type(resolved).__name__)
    check("with the model's own words",
          "display settings" in resolved.text, resolved.text)
    check("and nothing changed", app.config == RenderConfig())

    print("\n38. An unreachable model is a sentence, not a traceback")
    app = make_app()
    stub = StubParser(raises=StubParser.ParseError("connection refused"))
    with_parser(app, stub)
    resolved = app._resolve_ask("ask make it green")
    check("the failure is caught", isinstance(resolved, Reply),
          type(resolved).__name__)
    check("and says what went wrong",
          "connection refused" in resolved.text, resolved.text)
    check("the config is untouched", app.config == RenderConfig())

    print("\n39. With no key, ask says so and points at the fix")
    app = make_app()
    with_parser(app, StubParser(key=None))
    resolved = app._resolve_ask("ask make it green")
    check("it is refused politely", isinstance(resolved, Reply))
    check("...naming the key file",
          "api_key" in resolved.text, resolved.text)
    check("...and saying the rest still works",
          "other command" in resolved.text, resolved.text)

    print("\n40. A bare 'ask' asks for words rather than failing")
    app = make_app()
    with_parser(app, StubParser())
    resolved = app._resolve_ask("ask")
    check("bare ask is answered", isinstance(resolved, Reply))
    check("...with an example", "warmer" in resolved.text, resolved.text)

    print("\n41. A model delta the config refuses is refused in the usual words")
    # The two-layer boundary, exercised deliberately. tools/ask_parser.py's
    # smoke run never got here - the schema's enum stopped the model producing
    # an invalid value - so nothing else in the suite covers it.
    app = make_app()
    with_parser(app, StubParser(
        result=StubParser._Parsed(delta={"rotation": 45})))
    resolved = app._resolve_ask("ask rotate it 45 degrees")
    reply = app._run_command(resolved)
    check("the delta is refused", "must be one of" in reply, reply.strip())
    check("...naming rotation", "rotation" in reply, reply.strip())
    check("and the config is untouched", app.config.rotation == 0,
          str(app.config.rotation))


def main():
    print("=" * 68)
    print("RenderConfig: the app's settings surface")
    print("=" * 68)

    test_surface()
    test_accepts()
    test_clamping()
    test_refusals()
    test_diffing()
    test_one_path_in()
    test_keys_still_work()
    test_freeze()
    test_target()
    test_lcd_font_size()
    test_freeze_stops_the_loop_working()
    test_frozen_picture_still_responds_to_settings()
    test_target_reshapes_the_loop()
    test_headless_builds_nothing()
    test_ask_is_resolved_off_the_loop()
    test_ask_failures_are_sentences()

    print("\n" + "=" * 68)
    if failures:
        print(f"RESULT: {len(failures)} CHECK(S) FAILED")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("RESULT: the settings surface behaves as documented.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
