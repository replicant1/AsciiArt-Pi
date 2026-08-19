#!/usr/bin/env python3
"""
Check the live control keys, without a camera, a panel or a terminal.

    python3 tests/control/keymap_test.py

Driving the real app with synthetic keypresses turned out to be no way to test
a key binding: piinput drops the first event and repeats later ones, so a run
can show a scheme advancing five times when three keys were sent, and the log
cannot tell you which key did it. This calls _handle_key directly instead, so
one call is exactly one keypress and the result is unambiguous.

The object is built without running __init__ - that would want a camera and a
display - and given only the handful of attributes _handle_key actually reads.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from art import palettes                                   # noqa: E402
from ascii_camera import AsciiArtLiveCamera       # noqa: E402
from control.scheme_cycle import SchemeCycle      # noqa: E402
from capture.image_processor import ImageProcessor        # noqa: E402
from control.render_config import RenderConfig            # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


class StubDisplay:
    """Just enough display for the key handler to talk to."""

    # Read by the target key and by apply()'s feasibility check: with no panel
    # attached, whether there is a window at all is what decides where the
    # picture is allowed to go.
    draws = True

    def __init__(self):
        self.colour_ok = True
        self.scheme = palettes.SCHEMES[0]
        self.cleared = 0
        self.cols = 80

    def set_scheme(self, scheme):
        self.scheme = scheme

    def clear(self):
        self.cleared += 1

    def refresh_size(self):
        return False


def make_app():
    """An AsciiArtLiveCamera with only what _handle_key touches."""
    app = object.__new__(AsciiArtLiveCamera)
    app.display = StubDisplay()
    app.processor = ImageProcessor()
    # One object now, instead of six attributes that had to agree with each
    # other and with the processor. See tests/control/render_config_test.py.
    app.config = RenderConfig()
    app.notice = None
    app.refusal = None
    app.previous_config = None
    app.grid_key = None
    app.lcd = None
    app._redraw = False
    app._rebuild_ascii()
    # The `s` key goes through the cycle, so it has to exist even
    # where no knob does.
    app.schemes = SchemeCycle(settings=lambda: app.config,
                              apply=app.apply,
                              colour_ok=lambda: app.display.colour_ok)
    return app


def test_scheme_key():
    print("\n1. 's' cycles colour schemes, one scheme per press")
    app = make_app()
    seen = [app.scheme.name]
    for _ in range(len(palettes.SCHEMES)):
        app._handle_key("s")
        seen.append(app.scheme.name)

    check("first press leaves grey for live", seen[1] == "live", seen[1])
    check("one press advances exactly one scheme",
          seen[:len(palettes.SCHEME_NAMES)] == list(palettes.SCHEME_NAMES),
          " -> ".join(seen))
    check("cycling wraps back to the start",
          seen[-1] == palettes.SCHEME_NAMES[0], seen[-1])
    check("the display was told about the change",
          app.display.scheme.name == app.scheme.name)

    print("\n2. 'S' does the same as 's'")
    upper = make_app()
    upper._handle_key("S")
    check("uppercase is accepted", upper.scheme.name == "live",
          upper.scheme.name)


def test_g_is_free():
    print("\n3. 'g' no longer does anything")
    app = make_app()
    before = app.config
    for _ in range(5):
        alive = app._handle_key("g")

    # The whole config, not a hand-picked tuple of five fields: an unbound key
    # that quietly changed a sixth would have slipped past the old check.
    check("'g' changes nothing", app.config == before,
          app.config.describe_changes(before))
    check("'g' does not quit the app", alive)


def test_other_keys_intact():
    print("\n4. The other bindings still work, and match their first letter")
    app = make_app()

    # Asserted against the processor, not the config, on purpose: the config is
    # what the key sets, and the processor is what actually renders. Checking
    # the processor is what proves the change was carried all the way out.
    app._handle_key("i")
    check("i inverts", app.config.invert)

    app._handle_key("c")
    check("c changes the character ramp", app.config.ramp != "coarse",
          app.config.ramp)

    app._handle_key("f")
    check("f toggles fill", app.processor.fill)

    # Relative to wherever it started, so this does not have to be revisited
    # every time the default rotation changes.
    before = app.processor.rotation
    app._handle_key("r")
    check("r rotates by 90", app.processor.rotation == (before + 90) % 360,
          f"{before} -> {app.processor.rotation}")

    app._handle_key("a")
    check("a toggles auto-levels", not app.processor.auto_levels)

    contrast = app.processor.contrast
    app._handle_key("+")
    check("+ raises contrast", app.processor.contrast > contrast)
    app._handle_key("-")
    check("- lowers contrast",
          abs(app.processor.contrast - contrast) < 1e-6)

    app._handle_key(" ")
    check("space freezes the picture", app.config.freeze)

    check("q quits", app._handle_key("q") is False)

    # Every scheme-affecting letter should be the first letter of what it does.
    # Space is the exception and is deliberately not in this list: "freeze"
    # cannot have 'f', which fill already owns.
    for key, word in [("s", "scheme"), ("i", "invert"), ("c", "chars"),
                      ("f", "fill"), ("r", "rotate"), ("a", "auto"),
                      ("q", "quit"), ("t", "target"), ("l", "lcdfont")]:
        check(f"'{key}' matches {word!r}", word.startswith(key))


def main():
    print("=" * 60)
    print("Live control keys")
    print("=" * 60)

    test_scheme_key()
    test_g_is_free()
    test_other_keys_intact()

    print("\n" + "=" * 60)
    if failures:
        print(f"RESULT: {len(failures)} CHECK(S) FAILED")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("RESULT: all key bindings behave as documented.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
