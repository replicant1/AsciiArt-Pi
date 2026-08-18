#!/usr/bin/env python3
"""
Checks the start-up screen without any hardware.

Nothing can photograph the SPI panel (see CLAUDE.md), so this is as far as
automated verification goes: it proves the geometry, the colours and the
animation are what they claim to be, and then leaves a PNG for a human to look
at.  A clean run here is NOT evidence that anything appeared on the glass.

Run:  python3 tests/lcd_splash_test.py            # no hardware needed
      python3 tests/lcd_splash_test.py --panel    # drive the real panel

--panel exists because the real thing is over in about a second and a half: the
camera on this Pi hands over its first frame far sooner than the enclosure notes'
15-20 s figure, which was measured on the Qt preview rather than on this app.
That is too quick to study, so this holds the start-up screen on the glass,
animating, for as long as asked.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np                                          # noqa: E402
from panel.lcd_splash import (BAR_CELLS, SWEEP_RAMP, SWEEP_STEP, TAIL,  # noqa: E402
                        SplashScreen)

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  [{PASS if condition else FAIL}] {name}"
          + (f"  - {detail}" if detail and not condition else ""))


def test_bar_is_one_moving_object():
    """The comet must be a single contiguous run, never split across the ends."""
    print("\nActivity bar")
    s = SplashScreen(320, 240)
    cycle = BAR_CELLS + TAIL

    widths = set()
    for phase in range(cycle * 2):
        bar = s.bar_text(phase)
        check_len = len(bar) == BAR_CELLS
        if not check_len:
            check("bar is always the same width", False, f"phase {phase}")
            return

        lit = [i for i, c in enumerate(bar) if c != " "]
        if lit:
            # Contiguity is the property that broke the first version: wrapping
            # put the head at one edge and its tail at the other.
            contiguous = lit == list(range(lit[0], lit[-1] + 1))
            if not contiguous:
                check("comet is contiguous", False,
                      f"phase {phase}: {bar!r}")
                return
            widths.add(len(lit))
        else:
            widths.add(0)

    check("bar is always the same width", True)
    check("comet is contiguous at every phase", True)
    # It enters and leaves the bar, so partial widths exist, but at full stretch
    # it is exactly the tail length.
    check("comet reaches full tail length", max(widths) == TAIL,
          f"max lit = {max(widths)}, TAIL = {TAIL}")
    check("comet fully clears the bar once per cycle", 0 in widths)


def test_bar_moves_and_repeats():
    print("\nAnimation")
    s = SplashScreen(320, 240)
    cycle = BAR_CELLS + TAIL

    distinct = {s.bar_text(p) for p in range(cycle)}
    check("every phase in a cycle differs", len(distinct) == cycle,
          f"{len(distinct)} distinct of {cycle}")
    check("the cycle repeats", s.bar_text(0) == s.bar_text(cycle))
    check("head is brightest ramp char",
          s.bar_text(0)[0] == SWEEP_RAMP[-1], repr(s.bar_text(0)[0]))

    # The worker advances by SWEEP_STEP, not 1, so successive drawn frames must
    # still overlap: a step at or past the tail length turns the sweep into a
    # smear that blinks in unrelated places.
    check("the sweep step keeps frames overlapping", SWEEP_STEP < TAIL,
          f"SWEEP_STEP={SWEEP_STEP}, TAIL={TAIL}")
    lit_a = {i for i, c in enumerate(s.bar_text(TAIL)) if c != " "}
    lit_b = {i for i, c in enumerate(s.bar_text(TAIL + SWEEP_STEP))
             if c != " "}
    check("consecutive drawn frames share cells", bool(lit_a & lit_b),
          f"{sorted(lit_a)} then {sorted(lit_b)}")


def test_image_geometry():
    print("\nImage geometry")
    for w, h in ((320, 240), (240, 320)):
        img = SplashScreen(w, h).render("starting camera", "64x24 grid", 5)
        check(f"{w}x{h} image is exactly panel-sized", img.size == (w, h),
              str(img.size))
        check(f"{w}x{h} image is RGB", img.mode == "RGB", img.mode)


def test_colours_follow_the_scheme():
    """Ink and screen must be the scheme's, since the panel cannot be checked."""
    print("\nColour")
    ink, screen = (0x33, 0xFF, 0x33), (0x00, 0x1A, 0x00)
    a = np.asarray(SplashScreen(320, 240, ink=ink, screen=screen)
                   .render("starting camera", "64x24 grid", 5))

    corner = tuple(int(v) for v in a[2, 2])
    check("background is the scheme's screen colour", corner == screen,
          f"{corner} != {screen}")

    # The brightest pixel should be the ink; antialiasing only ever darkens it
    # toward the screen, so an exact match proves no blending crept in.
    brightest = tuple(int(v) for v in a.reshape(-1, 3)[a.sum(axis=2).argmax()])
    check("brightest pixel is the scheme's ink", brightest == ink,
          f"{brightest} != {ink}")

    # A black-on-white scheme must not come out inverted.
    b = np.asarray(SplashScreen(320, 240, ink=(0x14, 0x21, 0x0A),
                                screen=(0xC4, 0xDC, 0x1E))
                   .render("starting camera", "", 5))
    light_bg = tuple(int(v) for v in b[2, 2]) == (0xC4, 0xDC, 0x1E)
    check("a light-screen scheme stays light", light_bg)


def test_something_is_actually_drawn():
    """A blank splash would pass every geometry check above."""
    print("\nContent")
    s = SplashScreen(320, 240)
    blank = np.asarray(s.render("", "", 0))
    drawn = np.asarray(s.render("starting camera", "64x24 grid", 5))

    check("the screen is not empty", drawn.any())
    check("the message changes the pixels", not np.array_equal(blank, drawn))

    moved_a = np.asarray(s.render("starting camera", "64x24 grid", 5))
    moved_b = np.asarray(s.render("starting camera", "64x24 grid", 6))
    check("advancing the phase changes the pixels",
          not np.array_equal(moved_a, moved_b))

    # Ink is only ever laid down inside the layout, so a stray full-width fill
    # or an off-by-one margin shows up as ink in the corners.
    corners = [drawn[0, 0], drawn[0, -1], drawn[-1, 0], drawn[-1, -1]]
    check("nothing is drawn in the corners",
          all(not c.any() for c in corners))


def test_version_is_shown():
    """
    The version has to reach the glass, since that is the point of it.

    Checked as pixels rather than by trusting the call: on a display nothing can
    photograph, "the string was passed in" is not evidence it was drawn.
    """
    print("\nVersion")
    from version import APP_NAME, __version__

    check("version is a non-empty string",
          isinstance(__version__, str) and __version__.strip() != "",
          repr(__version__))
    check("app name is a non-empty string",
          isinstance(APP_NAME, str) and APP_NAME.strip() != "",
          repr(APP_NAME))

    with_v = np.asarray(SplashScreen(320, 240, version="9.9.9")
                        .render("starting camera", "64x24 grid", 3))
    without = np.asarray(SplashScreen(320, 240, version="")
                         .render("starting camera", "64x24 grid", 3))
    check("the version changes what is drawn",
          not np.array_equal(with_v, without))

    # It must be in the bottom fifth, not tucked behind something else.
    band = slice(round(240 * 0.85), 240)
    check("the version is drawn near the bottom", with_v[band].any())
    check("that band is empty without a version", not without[band].any())

    # A longer version must not push it off the panel.
    wide = np.asarray(SplashScreen(320, 240, version="10.20.30-rc1")
                      .render("starting camera", "64x24 grid", 3))
    edges = wide[:, :2].any() or wide[:, -2:].any()
    check("a long version still fits inside the panel", not edges)


def test_missing_font_still_draws():
    """A missing font must not be the reason the panel stays black."""
    print("\nFallback")
    s = SplashScreen(320, 240, font_path="/nonexistent/font.ttf")
    img = s.render("starting camera", "64x24 grid", 3)
    check("renders without the TrueType font", np.asarray(img).any())
    check("still panel-sized", img.size == (320, 240))


class FakeDisplay:
    """Stands in for LcdDisplay so the worker can run with no panel attached."""

    grid_size = (64, 24)
    cell_aspect = 2.0
    panel_size = (320, 240)

    def __init__(self):
        self.splash_frames = 0
        self.picture_frames = 0
        self.last_notice = None
        self.clears = 0

    def show_image(self, image):
        self.splash_frames += 1

    def render(self, indices, colours=None, screen=(0, 0, 0), notice=None):
        self.picture_frames += 1
        self.last_notice = notice

    def show_notice(self, text):
        self.last_notice = text

    def clear_notice(self):
        self.last_notice = None

    def set_ramp(self, ramp):
        pass

    def set_font_size(self, font_size):
        # A real panel re-rasterises its atlas and re-fits the grid here. The
        # worker calls it on every config it has not seen before, so the stub
        # has to have it or the splash tests fail on an attribute error that
        # has nothing to do with the splash.
        pass

    def clear(self):
        self.clears += 1

    def close(self):
        pass


def test_hold_keeps_the_screen_up():
    """
    The hold must outlast the camera, or asking for it achieves nothing.

    This is the behaviour the whole change exists for, and it is timing
    dependent, so it is worth a real thread rather than an assertion about
    intent.  Frames are pushed at once; the panel must keep showing the splash
    and must then switch over.
    """
    print("\nSplash hold")
    import numpy as np
    from panel.lcd_worker import LcdWorker
    from control.render_config import RenderConfig

    display = FakeDisplay()
    worker = LcdWorker(display, splash_hold=1.0)
    worker.start()
    try:
        worker.splash("starting camera", "64x24 grid")

        class Frame:
            luma = np.zeros((48, 64), dtype=np.uint8)

        # The app's own config object, rather than a private copy of the
        # fields the panel reads, and its own defaults for the rest.
        config = RenderConfig(auto_levels=False)

        # Frames from the moment the splash goes up - the worst case, and what
        # actually happens on this Pi.
        deadline = time.time() + 0.6
        while time.time() < deadline:
            worker.submit(Frame(), config)
            time.sleep(0.02)

        early = display.picture_frames
        check("no picture drawn during the hold", early == 0,
              f"{early} picture frames before the hold expired")
        check("the splash animated while frames waited",
              display.splash_frames >= 3, f"{display.splash_frames} ticks")

        # Past the hold, the picture must take over.
        deadline = time.time() + 1.2
        while time.time() < deadline:
            worker.submit(Frame(), config)
            time.sleep(0.02)

        check("the picture takes over once the hold expires",
              display.picture_frames > 0,
              f"{display.picture_frames} picture frames after")
        settled = display.splash_frames
        time.sleep(0.4)
        check("the splash stops for good", display.splash_frames == settled,
              f"{display.splash_frames} vs {settled}")
    finally:
        worker.stop()


def test_zero_hold_hands_over_at_once():
    print("\nSplash hold disabled")
    import numpy as np
    from panel.lcd_worker import LcdWorker
    from control.render_config import RenderConfig

    display = FakeDisplay()
    worker = LcdWorker(display, splash_hold=0.0)
    worker.start()
    try:
        worker.splash("starting camera")
        time.sleep(0.25)                       # let one splash tick land

        class Frame:
            luma = np.zeros((48, 64), dtype=np.uint8)

        # The app's own config object, rather than a private copy of the
        # fields the panel reads, and its own defaults for the rest.
        config = RenderConfig(auto_levels=False)
        for _ in range(5):
            worker.submit(Frame(), config)
            time.sleep(0.05)

        check("a zero hold does not block the picture",
              display.picture_frames > 0, f"{display.picture_frames} frames")
    finally:
        worker.stop()


def test_blank_cancels_the_start_up_screen():
    """
    Blanking the panel must actually leave it blank, splash or no splash.

    Found by review on PR #22 and confirmed by reproduction before it was
    fixed. The start-up screen is retired on the *frame* path, and blank() is
    called precisely when frames have stopped arriving - so a blank raised
    while the screen was still up cleared the panel and then had the idle tick
    redraw the screen over it, every tick, with nothing left that could ever
    retire it. The panel sat animating "starting camera" until the target was
    switched back.

    The window this is reachable in is the first several seconds of every run
    with --lcd, which is exactly when someone is most likely to be pressing
    keys and wondering why nothing has appeared yet.
    """
    print("\nBlanking while the start-up screen is up")
    from panel.lcd_worker import LcdWorker

    display = FakeDisplay()
    worker = LcdWorker(display, splash_hold=3.0)
    worker.start()
    try:
        worker.splash("starting camera", "64x24 grid")
        time.sleep(0.6)
        check("the start-up screen is up to begin with",
              display.splash_frames > 0, f"{display.splash_frames} draws")

        worker.blank()
        time.sleep(0.4)
        at_blank = display.splash_frames
        check("blanking clears the panel", display.clears >= 1,
              f"{display.clears} clears")

        # No frames from here on, exactly as when the target has moved away.
        time.sleep(1.2)
        check("and nothing redraws the start-up screen over it",
              display.splash_frames == at_blank,
              f"{at_blank} draws at the blank, {display.splash_frames} after")
        check("the panel was cleared once, not repeatedly",
              display.clears == 1, f"{display.clears} clears")
    finally:
        worker.stop()


def hold_on_panel(seconds, message, detail):
    """
    Drive the real ILI9341 and leave the start-up screen on it.

    Deliberately the only thing here that touches hardware.  There is no
    assertion to make: nothing in this process can read back what the panel is
    displaying, so it prints what should be visible and leaves the judgement to
    whoever is looking at it.
    """
    from panel.lcd_display import LcdDisplay
    from panel.lcd_splash import SplashScreen

    display = LcdDisplay(ramp=" .:-=+*#%@")
    try:
        width, height = display.panel_size
        splash = SplashScreen(width, height)
        print(f"\nHolding the start-up screen on the panel for {seconds} s.")
        print("You should see, on the 2.4 inch panel and NOT on the monitor:")
        print("  - 'ascii_camera' in large white monospace, upper third")
        print("  - a thin horizontal rule under it, dimmer than the title")
        print(f"  - '{message}' centred below that")
        print("  - a row of ASCII characters that sweeps left to right,")
        print("    brightest at its leading edge, fading behind it, then")
        print("    clears and starts again from the left")
        print(f"  - '{detail}' in small dim text near the bottom")
        print("  - everything else black\n")

        phase, deadline = 0, time.time() + seconds
        while time.time() < deadline:
            display.show_image(splash.render(message, detail, phase))
            phase += 1
            time.sleep(0.2)
    finally:
        display.close()
    print("Panel released and blanked.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", action="store_true",
                        help="also drive the real ILI9341 so a human can look")
    parser.add_argument("--seconds", type=float, default=30.0,
                        help="how long --panel holds the screen")
    args = parser.parse_args()

    print("Start-up screen checks")
    test_bar_is_one_moving_object()
    test_bar_moves_and_repeats()
    test_image_geometry()
    test_colours_follow_the_scheme()
    test_something_is_actually_drawn()
    test_version_is_shown()
    test_missing_font_still_draws()
    test_hold_keeps_the_screen_up()
    test_zero_hold_hands_over_at_once()
    test_blank_cancels_the_start_up_screen()

    out = os.path.join(os.path.dirname(__file__), "..", "splash_test.png")
    SplashScreen(320, 240).render("starting camera",
                                  "64x24 grid - font 8", 14).save(out)

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    print(f"Sample written to {os.path.normpath(out)}")
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1

    print("\nThis proves the layout, not the panel. Nothing here can see the")
    print("ILI9341, so a clean run above is not evidence of anything lit.")

    if args.panel:
        hold_on_panel(args.seconds, "starting camera", "64x24 grid - font 8")
    else:
        print("Re-run with --panel to put it on the glass and judge by eye.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
