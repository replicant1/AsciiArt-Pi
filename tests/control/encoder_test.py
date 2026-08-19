#!/usr/bin/env python3
"""
Check the rotary encoder decode, without an encoder attached.

    python3 tests/control/encoder_test.py

The knob is the one part of this that cannot be judged by looking at it: a
decoder that miscounts under bounce still looks fine on an oscilloscope trace
and only shows up as a knob that sometimes jumps two schemes or stutters
backwards.  tools/hardware/probe_encoder.py measured what the real contacts do - 453
edges reducing to 88, about 5:1 - so the bounce here is not invented, it is
modelled on that, and the test demands an exact step count through it rather
than an approximate one.

The pin levels are driven directly, so one waveform is one turn of the knob and
there is nothing timing-dependent to make a run flaky.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from art import palettes                                   # noqa: E402
from ascii_camera import AsciiArtLiveCamera       # noqa: E402
from control.scheme_cycle import SchemeCycle      # noqa: E402
from control.encoder import QuadratureDecoder, RotaryEncoder   # noqa: E402
from capture.image_processor import ImageProcessor        # noqa: E402
from control.render_config import RenderConfig            # noqa: E402

failures = []

# One full quadrature cycle, which this encoder gives per detent.  Both start
# and end at rest with both pins high; they differ only in which pin drops
# first, and that is the whole of what direction means.
CW = [(1, 1), (0, 1), (0, 0), (1, 0), (1, 1)]
CCW = [(1, 1), (1, 0), (0, 0), (0, 1), (1, 1)]


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def turn(states, turns=1):
    """The pin states for `turns` repeats of one cycle, without the rest gaps."""
    out = list(states)
    for _ in range(turns - 1):
        out += states[1:]
    return out


def bouncy(states):
    """
    The same movement as a real contact makes it.

    Each state is held for several samples, and each transition is preceded by
    a rattle back to where it came from - the two things mechanical contacts
    actually do.  A decoder that counts edges reads this as far more movement
    than happened; one that tracks position reads it as exactly the same.
    """
    out = [states[0]]
    for previous, state in zip(states, states[1:]):
        out += [state, previous, state, state, state]
    return out


def feed(decoder, states):
    """Run a state sequence through the decoder, collecting the steps."""
    return [step for state in states
            if (step := decoder.feed(*state)) != 0]


def test_ideal():
    print("\n1. A clean turn gives exactly one step per detent")
    steps = feed(QuadratureDecoder(), turn(CW, 5))
    check("five clicks clockwise give five steps", len(steps) == 5, steps)
    check("all of them are forwards", set(steps) == {1}, steps)

    steps = feed(QuadratureDecoder(), turn(CCW, 5))
    check("five clicks anticlockwise give five steps", len(steps) == 5, steps)
    check("all of them are backwards", set(steps) == {-1}, steps)


def test_bounce():
    print("\n2. Contact bounce does not invent movement")
    states = bouncy(turn(CW, 5))
    steps = feed(QuadratureDecoder(), states)
    ratio = len(states) / len(turn(CW, 5))

    check("bounce inflates the waveform", ratio > 3, f"{ratio:.1f}:1")
    check("five bouncing clicks still give five steps", len(steps) == 5, steps)
    check("bounce never reverses a step", set(steps) == {1}, steps)

    steps = feed(QuadratureDecoder(), bouncy(turn(CCW, 5)))
    check("and the same anticlockwise", steps == [-1] * 5, steps)


def test_incomplete():
    print("\n3. Movement that does not complete a detent gives nothing")
    # Rocking against the detent: off rest and back, repeatedly, never round.
    rocking = [(1, 1), (0, 1), (1, 1)] * 10
    check("rocking short of a click gives no steps",
          feed(QuadratureDecoder(), rocking) == [],
          feed(QuadratureDecoder(), rocking))

    # Half a cycle, then back the way it came.
    half = [(1, 1), (0, 1), (0, 0), (0, 1), (1, 1)] * 5
    check("going half way and returning gives no steps",
          feed(QuadratureDecoder(), half) == [],
          feed(QuadratureDecoder(), half))


def test_direction_changes():
    print("\n4. Reversing mid-turn is followed exactly")
    decoder = QuadratureDecoder()
    steps = feed(decoder, turn(CW, 3)) + feed(decoder, turn(CCW, 2))
    check("three forwards then two back", steps == [1, 1, 1, -1, -1], steps)
    check("they net out to one", sum(steps) == 1, sum(steps))


def drive(knob, states):
    """Replay pin states into a RotaryEncoder as edge callbacks."""
    for previous, state in zip(states, states[1:]):
        for pin, before, now in ((knob.clk, previous[0], state[0]),
                                 (knob.dt, previous[1], state[1])):
            if before != now:
                knob._on_edge(0, pin, now, 0)


def test_accumulator():
    """Exercises the real class, minus lgpio - _on_edge touches no hardware."""
    print("\n5. Steps accumulate and take() hands them over once")
    knob = RotaryEncoder(clk=19, dt=26)
    knob._levels = {19: 1, 26: 1}

    drive(knob, turn(CW, 4))
    check("four clicks are banked", knob.take() == 4)
    check("taking them twice does not double-count", knob.take() == 0)

    drive(knob, turn(CW, 3))
    drive(knob, turn(CCW, 3))
    check("equal movement each way nets to nothing", knob.take() == 0)
    check("but both directions were still counted", knob.detents == 10,
          knob.detents)

    print("\n6. --encoder-reverse mirrors the knob")
    backwards = RotaryEncoder(clk=19, dt=26, reverse=True)
    backwards._levels = {19: 1, 26: 1}
    drive(backwards, turn(CW, 4))
    check("clockwise now counts backwards", backwards.take() == -4)


class StubDisplay:
    """Just enough display for the scheme cycling to talk to."""

    draws = True

    def __init__(self):
        self.colour_ok = True
        self.scheme = palettes.SCHEMES[0]
        self.cols = 80
        self.repaints = 0

    def set_scheme(self, scheme):
        # Counted because the real one ends in stdscr.clear(), which repaints
        # every cell in the window. How many times this is called is the whole
        # difference between a clean change and a strobe.
        self.repaints += 1
        self.scheme = scheme

    def clear(self):
        pass


class StubEncoder:
    """An encoder that reports whatever movement a test wants."""

    def __init__(self, steps, presses=0):
        self.steps = steps
        self.presses = presses

    def take(self):
        steps, self.steps = self.steps, 0
        return steps

    def take_presses(self):
        presses, self.presses = self.presses, 0
        return presses


def make_app(steps, presses=0):
    app = object.__new__(AsciiArtLiveCamera)
    app.display = StubDisplay()
    app.processor = ImageProcessor()
    # The scheme is a field of one config object now, not an index the app
    # kept alongside the ramp name and the invert flag. SchemeCycle.step
    # still walks the list by index; it just does not store the result as one.
    app.config = RenderConfig()
    app.notice = None
    app.previous_config = None
    app.grid_key = None
    app.lcd = None
    app._redraw = False
    app._rebuild_ascii()
    # The cycle is what the knob and the `s` key both go through now. The app
    # is still built around it on purpose: what these tests are really about is
    # how many times the window is repainted, and that only becomes visible at
    # the far end of apply() -> _adopt() -> display.set_scheme().
    app.schemes = SchemeCycle(settings=lambda: app.config,
                              apply=app.apply,
                              colour_ok=lambda: app.display.colour_ok)
    app.schemes.encoder = StubEncoder(steps, presses)
    return app


def test_app_wiring():
    print("\n7. The knob drives the schemes, both ways")
    names = list(palettes.SCHEME_NAMES)

    app = make_app(1)
    app.schemes.poll()
    check("one click forwards is one scheme forwards",
          app.scheme.name == names[1], app.scheme.name)

    app = make_app(-1)
    app.schemes.poll()
    check("one click back wraps to the last scheme",
          app.scheme.name == names[-1], app.scheme.name)

    app = make_app(3)
    app.schemes.poll()
    check("three clicks move three schemes",
          app.scheme.name == names[3], app.scheme.name)

    print("\n8. A hard spin lands where it should, without lapping")
    # One full lap plus two: the answer must be the same as two, since going
    # round the list changes nothing.
    app = make_app(len(names) + 2)
    app.schemes.poll()
    check("a spin past the end of the list still lands correctly",
          app.scheme.name == names[2], app.scheme.name)

    # The boundary the first version got wrong: clamping to the list length
    # instead of reducing modulo it lands here, on a full lap, and looks
    # plausible enough to miss.
    app = make_app(len(names))
    app.schemes.poll()
    check("an exact lap leaves the scheme alone",
          app.scheme.name == names[0], app.scheme.name)

    app = make_app(-(len(names) + 2))
    app.schemes.poll()
    check("and the same spinning backwards",
          app.scheme.name == names[-2], app.scheme.name)

    print("\n9. A multi-detent move repaints once, not once per scheme")
    # The bug this pins down was invisible to every check above: the knob
    # arrived at the right scheme, having repainted the window at each one it
    # passed through. On a slow colour scheme, where a single frame is long
    # enough to bank several detents, that reads as a hard strobe.
    app = make_app(5)
    app.schemes.poll()
    check("five detents land five schemes on", app.scheme.name == names[5],
          app.scheme.name)
    check("but cost exactly one repaint", app.display.repaints == 1,
          f"{app.display.repaints} repaints")

    app = make_app(-4)
    app.schemes.poll()
    check("and the same going backwards", app.display.repaints == 1,
          f"{app.display.repaints} repaints")

    print("\n10. A knob nobody touches changes nothing at all")
    app = make_app(0)
    app.schemes.poll()
    check("no movement means no repaint", app.display.repaints == 0,
          f"{app.display.repaints} repaints")

    app = make_app(len(names))
    app.schemes.poll()
    check("an exact lap does not repaint either", app.display.repaints == 0,
          f"{app.display.repaints} repaints")

    print("\n11. Pressing the knob goes home to greyscale")
    # From the far end of the list, so a pass cannot be an accident of
    # starting next door to grey.
    app = make_app(len(names) - 1)
    app.schemes.poll()
    check("wound round to the last scheme", app.scheme.name == names[-1],
          app.scheme.name)

    app.schemes.encoder.presses = 1
    app.schemes.poll()
    check("a press lands on grey", app.scheme.name == "grey", app.scheme.name)
    check("and it is the greyscale one, not just the name",
          app.scheme.kind == "grey", app.scheme.kind)

    print("\n12. Pressing when already home does nothing at all")
    app = make_app(0, presses=1)
    app.schemes.poll()
    check("still grey", app.scheme.name == "grey", app.scheme.name)
    check("and no repaint, so no flash", app.display.repaints == 0,
          f"{app.display.repaints} repaints")

    # Repaints are counted as a delta from here on, because the app always
    # starts on grey: getting somewhere else costs a repaint of its own, and
    # folding that into the total is how the first version of this test came to
    # assert the wrong number.
    app = make_app(3)
    app.schemes.poll()
    before = app.display.repaints
    app.schemes.encoder.presses = 4
    app.schemes.poll()
    check("four presses in one frame cost one repaint between them",
          app.display.repaints - before == 1,
          f"{app.display.repaints - before} repaints")

    print("\n13. A press beats rotation banked in the same frame")
    app = make_app(5)
    app.schemes.poll()                 # away from grey first
    before = app.display.repaints
    app.schemes.encoder.steps = 3
    app.schemes.encoder.presses = 1
    app.schemes.poll()
    check("the knob goes home, not to the turned-to scheme",
          app.scheme.name == "grey", app.scheme.name)
    check("and does it in one repaint, not two",
          app.display.repaints - before == 1,
          f"{app.display.repaints - before} repaints")

    print("\n14. 's' still works and still goes forwards")
    app = make_app(0)
    app._handle_key("s")
    check("the key is unaffected by the knob",
          app.scheme.name == names[1], app.scheme.name)
    check("and still costs one repaint", app.display.repaints == 1,
          f"{app.display.repaints} repaints")


def test_the_key_needs_no_knob():
    print("\n13. Cycling works with no encoder attached at all")
    # The point of the split: --encoder decides whether a *second* way in
    # exists, not whether schemes can be cycled. Before SchemeCycle this was
    # only true by accident of the walk living on the app beside a
    # self.encoder that happened to be None.
    names = list(palettes.SCHEME_NAMES)
    app = make_app(0)
    app.schemes.encoder = None

    app.schemes.poll()
    check("polling a cycle with no knob does nothing",
          app.display.repaints == 0, f"{app.display.repaints} repaints")

    app.schemes.step()
    check("but the key still steps it", app.scheme.name == names[1],
          app.scheme.name)
    check("...for one repaint", app.display.repaints == 1,
          f"{app.display.repaints} repaints")

    app.schemes.home()
    check("and home still goes home", app.scheme.name == "grey",
          app.scheme.name)

    app.schemes.stop()
    check("stopping a cycle that never claimed a pin is safe", True)


def main():
    print("=" * 60)
    print("Rotary encoder")
    print("=" * 60)

    test_ideal()
    test_bounce()
    test_incomplete()
    test_direction_changes()
    test_accumulator()
    test_app_wiring()
    test_the_key_needs_no_knob()

    print("\n" + "=" * 60)
    if failures:
        print(f"RESULT: {len(failures)} CHECK(S) FAILED")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("RESULT: the decode survives bounce and the knob drives the schemes.")
    print("NOTE: which physical direction is 'forwards' cannot be tested "
          "here.\n      Turn the real knob; if it runs backwards, add "
          "--encoder-reverse.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
