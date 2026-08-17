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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

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
        ({"colour_levels": 7}, "colour_levels"),
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

    def blank(self):
        self.blanks += 1

    def submit(self, frame, config):
        self.submitted += 1


def make_app(lcd=None, draws=True):
    """An AsciiArtLiveCamera with only what apply() and the keys touch."""
    app = object.__new__(AsciiArtLiveCamera)
    app.display = StubDisplay()
    app.display.draws = draws
    app.processor = ImageProcessor()
    app.config = RenderConfig()
    app.notice = None
    app.grid_key = None
    app.grid = (80, 30)
    app.lcd = lcd
    app.encoder = None
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
