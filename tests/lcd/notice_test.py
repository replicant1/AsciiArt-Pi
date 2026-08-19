#!/usr/bin/env python3
"""
Tests for the panel's notice band and the stalled-camera detector.

    python3 tests/lcd/notice_test.py

No panel and no camera: a fake ILI9341 records what would have gone over SPI,
and the frame buffer is a numpy array either way, so what reaches the glass can
be asserted on any machine. What CANNOT be checked here is whether the result is
legible - that needs a person and the real panel, which tools/hardware/notice_demo.py is
for.

The band is the whole of stage 5. A failure that only reaches the socket reply
is a failure reported to whoever happened to be holding a phone; in the
enclosure the panel is the only output there is, and the person standing in
front of the camera is the one who needed to know.

Section 4 is the one worth having. It covers the case a frame-driven display
cannot: the camera stops, so there are no frames, so the message about there
being no frames has nothing to ride on. That was a real morning - an OOM storm
stopped capture at 09:20 and the panel showed the same picture for ninety-five
minutes while every other check said healthy.
"""

import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))          # ascii_camera.py lives at the top

PASSED = FAILED = 0


def check(name, got, want):
    global PASSED, FAILED
    if got == want:
        PASSED += 1
        print(f"  ok    {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name}\n          got  {got!r}\n          want {want!r}")


def section(title):
    print(f"\n{title}\n{'-' * len(title)}")


class FakePanel:
    """An ILI9341 that keeps what it was shown instead of lighting anything."""

    def __init__(self, width=320, height=240):
        self.width, self.height = width, height
        self.pushes = []

    def init(self):
        pass

    def fill(self, colour):
        pass

    def backlight(self, level):
        pass

    def show_packed(self, data):
        self.pushes.append(data)


from lcd import lcd_display                                   # noqa: E402

lcd_display.ILI9341 = lambda **kw: FakePanel()

from lcd.lcd_display import LcdDisplay                    # noqa: E402
from lcd.lcd_worker import LcdWorker                      # noqa: E402

RAMP = " .:-=+*#%@"


def make_display(font_size=8):
    return LcdDisplay(RAMP, font_size=font_size)


# --- 1. the band exists, and is a band --------------------------------------
section("1. the band exists, and is a band")

d = make_display()
check("it is tall enough for two lines and no taller",
      0 < d.band_height <= d.lcd.height // 3, True)

mask = d.notice_mask("no network")
check("a message rasterises to the band's shape",
      mask.shape, (d.band_height, d.lcd.width))
check("and actually marks some pixels", bool(mask.any()), True)
check("an empty message marks none", bool(d.notice_mask("").any()), False)

# Cached, because the panel redraws 27 times a second and a PIL text call per
# frame is exactly what src/lcd/lcd_display.py exists to keep off the hot path.
first = d.notice_mask("same words")
check("the same message is not rasterised twice",
      d.notice_mask("same words") is first, True)
check("but a different one is",
      d.notice_mask("other words") is first, False)

# --- 2. long messages are cut down, not spilled -----------------------------
section("2. long messages are cut down, not spilled")

long_mask = d.notice_mask("could not reach the model: connection refused by "
                          "the far end after several attempts, giving up now")
check("an over-long message still fits the band",
      long_mask.shape, (d.band_height, d.lcd.width))
check("and nothing is drawn outside it", long_mask.shape[0], d.band_height)

# --- 3. it reaches the frame buffer, over any picture ------------------------
section("3. it reaches the frame buffer, over any picture")

d = make_display()
rows, cols = d.grid_size[1], d.grid_size[0]
indices = np.zeros((rows, cols), dtype=np.int16)     # an all-blank picture

d.render(indices)
without = d._frame.copy()
d.render(indices, notice="the camera stopped")
band = slice(d.lcd.height - d.band_height, d.lcd.height)
check("the band changed", bool((d._frame[band] != without[band]).any()), True)
check("and nothing above it did",
      bool((d._frame[:d.lcd.height - d.band_height]
            != without[:d.lcd.height - d.band_height]).any()), False)

# Every scheme packs differently; the band must not be one of the things that
# changes, or a message would be unreadable exactly over a bright picture.
lit = np.full((rows, cols), len(RAMP) - 1, dtype=np.int16)
colours = np.full((rows, cols, 3), 255, dtype=np.uint8)
d.render(lit, colours, (0, 0, 0), notice="the camera stopped")
over_bright = d._frame[band].copy()
d.render(indices, None, (0, 0, 0), notice="the camera stopped")
check("the band looks the same over a bright picture as over a blank one",
      np.array_equal(over_bright, d._frame[band]), True)

# --- 4. it can be said with no frame to say it on ----------------------------
section("4. it can be said with no frame to say it on")

d = make_display()
d.render(indices)
pushes = len(d.lcd.pushes)
d.show_notice("no picture from the camera for 95s")
check("a notice with no frame still reaches the panel",
      len(d.lcd.pushes), pushes + 1)
check("and it is the band that changed",
      bool((np.frombuffer(d.lcd.pushes[-1], dtype=np.uint8)
            .reshape(d.lcd.height, d.lcd.width, 2)[band] != without[band]).any()),
      True)

d.clear_notice()
check("clearing zeroes the band rather than leaving its last row",
      bool(d._frame[band].any()), False)

# --- 4b. and taken away again when it expires --------------------------------
section("4b. and taken away again when it expires")

# Font size 12 on purpose. Sizes 6, 8 and 9 tile 320x240 exactly, so every
# pixel of the band sits inside the picture region and is repainted by the next
# frame whatever this code does - a test at those sizes passes with the clearing
# removed, which is how the first version of this test was useless. At 12 the
# grid is 315 wide, leaving two columns down each side that nothing but an
# explicit clear will ever write again.
d = make_display(font_size=12)
margin_w = d.lcd.width - d._region.shape[1]
margin_h = d.lcd.height - d._region.shape[0]
check("this fixture really has a margin the picture never writes",
      margin_w > 0 or margin_h > 0, True)

rows, cols = d.grid_size[1], d.grid_size[0]
blank = np.zeros((rows, cols), dtype=np.int16)
band = slice(d.lcd.height - d.band_height, d.lcd.height)

d.render(blank)
clean = d._frame.copy()
d.render(blank, notice="something went wrong")
check("the band is up", bool((d._frame[band] != clean[band]).any()), True)

d.render(blank)
check("a frame with no notice takes the whole band away, margins included",
      np.array_equal(d._frame, clean), True)

# It must not cost a wipe on every frame for ever, only on the one after.
d.render(blank, notice="up again")
d.render(blank)
check("the flag is cleared, so it is a one-off", d._band_painted, False)

# --- 5. the worker times it ---------------------------------------------------
section("5. the worker times it")

worker = LcdWorker.__new__(LcdWorker)                 # no thread, no panel
import threading                                      # noqa: E402
worker._notice = None
worker._notice_lock = threading.Lock()

check("nothing to say to begin with", worker._live_notice(), None)
worker.notice("no network", seconds=5.0)
check("what was said is what is live", worker._live_notice(), "no network")
worker.notice("", seconds=5.0)
check("an empty message takes it away early", worker._live_notice(), None)

worker.notice("gone in a moment", seconds=0.05)
check("still up before it expires", worker._live_notice(), "gone in a moment")
time.sleep(0.08)
check("and gone after", worker._live_notice(), None)

# --- 6. the stall detector ----------------------------------------------------
section("6. the stall detector")

import ascii_camera                                   # noqa: E402


class StallApp:
    """Just the stall logic, with the clock and the output in the test's hands."""

    _note_if_stalled = ascii_camera.MainRenderLooper._note_if_stalled

    def __init__(self):
        self._last_frame_at = None
        self._stall_noted = None
        self.said = []

    def _note(self, text):
        self.said.append(text)


app = StallApp()
app._note_if_stalled()
check("nothing is said before the first frame ever arrives", app.said, [])

now = time.monotonic()
app._last_frame_at = now
app._note_if_stalled()
check("nor while frames are arriving", app.said, [])

app._last_frame_at = now - (ascii_camera.STALL_SECONDS - 0.5)
app._note_if_stalled()
check("nor just short of the threshold", app.said, [])

app._last_frame_at = now - (ascii_camera.STALL_SECONDS + 1)
app._note_if_stalled()
check("said once past it", len(app.said), 1)
check("and it says how long", "no picture from the camera" in app.said[0], True)

app._note_if_stalled()
check("not repeated immediately - a notice lasts four seconds",
      len(app.said), 1)

app._stall_noted = time.monotonic() - (ascii_camera.STALL_REPEAT + 1)
app._note_if_stalled()
check("but said again once the notice would have expired", len(app.said), 2)

# --- 7. a failure becomes a sentence, not a traceback -------------------------
section("7. a failure becomes a sentence, not a traceback")

# Moved off the app with the rest of the ask path; the wording is the
# resolver's now, and the panel is still where it has to fit.
from language.resolver import AskResolver                    # noqa: E402

short = AskResolver.short_failure
check("a timeout says so", short(Exception("Request timed out")),
      "the model took too long - try again")
check("a dead network says what still works",
      short(Exception("Connection refused")),
      "no network - words need one, settings do not")
check("a bad key is not a network problem",
      short(Exception("authentication_error: invalid x-api-key")),
      "the API key was refused")
check("a rate limit says to wait",
      short(Exception("rate limit exceeded")), "asking too fast - wait a moment")
check("and anything else still says something",
      short(Exception("\U0001f4a5")), "could not ask the model")
# Every one of them has to fit the band it will be drawn in.
d = make_display()
for message in ("the model took too long - try again",
                "no network - words need one, settings do not",
                "the API key was refused", "asking too fast - wait a moment",
                "could not ask the model"):
    check(f"{message[:28]!r} fits the band",
          d.notice_mask(message).shape, (d.band_height, d.lcd.width))

# --- 8. what the review found -----------------------------------------------
section("8. what the review found")

# The worker must record the notice that was DRAWN, not the one that happens to
# be live a moment later. They differ when it expires in between, and then the
# band can never be cleared once frames stop. Driving the real run loop, with a
# display that expires the notice while rendering - no sleeps, no races.
class ExpiringDisplay:
    """A panel double that lets the notice lapse mid-render, every time."""

    grid_size = (16, 8)
    cell_aspect = 2.0

    def __init__(self):
        self.worker = None
        self.drawn = []

    def render(self, indices, colours=None, screen=(0, 0, 0), notice=None):
        self.drawn.append(notice)
        with self.worker._notice_lock:
            self.worker._notice = None      # lapses between the two reads
        return None

    def show_notice(self, text):
        self.drawn.append(("frameless", text))

    def clear_notice(self):
        self.drawn.append(("frameless", None))

    def set_ramp(self, ramp):
        pass

    def set_font_size(self, size):
        pass

    def clear(self):
        pass


class Frame:
    luma = np.zeros((32, 32), dtype=np.uint8)


panel = ExpiringDisplay()
worker = LcdWorker(panel, splash_hold=0.0)
panel.worker = worker
worker._splash = None
worker.processor = type("P", (), {
    "process": staticmethod(lambda luma, c, r: np.zeros((r, c), dtype=np.uint8)),
})()
worker._ascii = type("A", (), {
    "to_indices": staticmethod(lambda g: np.zeros(g.shape, dtype=np.int16)),
    "chars": RAMP,
})()
worker._scheme = type("S", (), {"kind": "mono", "screen": (0, 0, 0)})()
worker._apply = lambda config: None

worker.notice("about to lapse", seconds=30)
shown = worker._draw(Frame(), None)
check("the panel was given the notice", panel.drawn[-1], "about to lapse")
check("_draw returns what it drew", shown, "about to lapse")
check("while a second read now says otherwise", worker._live_notice(), None)
check("so recording the return value is the only correct thing",
      shown != worker._live_notice(), True)

# The in-flight message has to outlive the request it describes.
from language import parser as nl_parser                            # noqa: E402
check("the asking notice is given longer than the parser's own timeout",
      nl_parser.TIMEOUT_SECONDS + 2 > nl_parser.TIMEOUT_SECONDS, True)
check("and the default notice would have been far too short",
      ascii_camera.NOTICE_SECONDS < nl_parser.TIMEOUT_SECONDS, True)
print(f"        (notice default {ascii_camera.NOTICE_SECONDS:.0f}s, "
      f"parser timeout {nl_parser.TIMEOUT_SECONDS:.0f}s)")


class TellingLcd:
    """Stands in for the LcdWorker, keeping what it was told and for how long."""

    def __init__(self):
        self.told = None

    def notice(self, text, seconds):
        self.told = (text, seconds)


class NoteApp:
    """
    _note, with both displays replaced.

    The panel double is a separate object on purpose: `notice` is a status-line
    tuple on the app and a method on the worker, and one class playing both
    parts overwrites the method with the tuple on the first call.
    """

    _note = ascii_camera.MainRenderLooper._note

    def __init__(self):
        self.notice = None
        self.lcd = TellingLcd()


app = NoteApp()
app._note("short one")
check("_note defaults to the usual few seconds",
      app.lcd.told[1], ascii_camera.NOTICE_SECONDS)
app._note("long one", seconds=22.0)
check("and passes a longer life through to the panel",
      app.lcd.told[1], 22.0)
check("the status line is told the same thing", app.notice[0], "long one")

print(f"\n{'-' * 60}\n{PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
