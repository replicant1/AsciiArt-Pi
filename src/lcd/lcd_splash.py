"""
Start-up screen for the ILI9341 panel.

The camera needs 15-20 seconds to hand over its first frame on a Zero 2 -
libcamera's initialisation dominates - and until then LcdDisplay has nothing to
draw, so the panel sits black.  On the HDMI side that gap is covered by
"Starting camera, please wait..." in the terminal.  Inside a closed box, or with
--no-terminal, there is no terminal to read it on, and a black panel for twenty
seconds is indistinguishable from a panel that is not working.  This fills the
gap, and its real job is that second one: to prove the panel is alive before
there is any picture to prove it with.

Rendering is kept away from the panel on purpose.  render() returns a PIL image
and knows nothing about SPI, so the layout can be checked on any machine - which
matters more here than usual, since nothing can screenshot this display (see
CLAUDE.md).  The constraint that shapes LcdDisplay - one draw.text() per cell
being far too slow at 1,536 cells a frame - does not apply: this draws four
short strings a few times a second, and stops the moment a camera frame lands.

The activity bar is a comet of ramp characters sweeping left to right, rather
than a percentage.  Nothing here knows how long libcamera will take, and a bar
that claims to be at 60% when it is only guessing is worse than one that admits
it is merely alive.
"""

import logging

from PIL import Image, ImageDraw, ImageFont

from version import APP_NAME, __version__

logger = logging.getLogger(__name__)

DEFAULT_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

# Dark to light.  Deliberately not the app's own ramp: that one is reversed when
# --invert is on, which would silently turn the comet into a gap travelling
# through a bright bar.  The splash should look the same however the app is
# configured.
SWEEP_RAMP = " .:-=+*#%@"

# Cells in the activity bar, and how many of them the comet's tail spans.
BAR_CELLS = 28
TAIL = 9

# Cells the comet advances per drawn frame.  Speed cannot come from drawing more
# often: a full panel write is about 33 ms, so the redraw rate is already a
# meaningful share of the thread during start-up, and doubling it buys nothing
# once the motion is legible.  Moving further per frame is free.  Keep it well
# under TAIL, or consecutive frames stop overlapping and the comet reads as a
# blinking smear rather than something travelling.
SWEEP_STEP = 3


class SplashScreen:
    """Renders the start-up screen as a PIL image, ready for the panel."""

    def __init__(self, width, height, ink=(255, 255, 255), screen=(0, 0, 0),
                 font_path=DEFAULT_FONT, version=__version__):
        """
        Args:
            width, height: Panel size in pixels, in its current orientation.
            ink: RGB the text is drawn in - the active scheme's ink, so the
                splash comes up in the colours the picture will use.
            screen: RGB behind it, the scheme's unlit screen.
            font_path: A monospace TrueType font.
            version: What to print along the bottom.  Defaults to the app's own
                version, which is the only thing that ever passes anything else
                being a test.
        """
        self.width = width
        self.height = height
        self.ink = tuple(ink)
        self.screen = tuple(screen)
        self.version = version

        # Sized off the panel rather than fixed, so portrait (240x320) and
        # landscape (320x240) both come out proportioned rather than one of them
        # being laid out for the other.
        base = min(width, height)
        self.f_title = self._font(font_path, max(11, round(base * 0.092)))
        self.f_body = self._font(font_path, max(8, round(base * 0.058)))
        self.f_small = self._font(font_path, max(7, round(base * 0.045)))

    @staticmethod
    def _font(path, size):
        """Load the mono font, or fall back rather than refusing to draw."""
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            # A missing font must not be the reason the panel stays black - a
            # coarse splash still does the job this screen exists for.
            logger.warning("No font at %s; splash falls back to the bitmap "
                           "default", path)
            return ImageFont.load_default()

    def _dim(self, factor):
        """Blend the ink toward the screen, for secondary text."""
        return tuple(round(s + (i - s) * factor)
                     for i, s in zip(self.ink, self.screen))

    def _centre(self, draw, y, text, font, fill):
        """Draw one line horizontally centred on the panel."""
        w = draw.textlength(text, font=font)
        draw.text(((self.width - w) / 2, y), text, font=font, fill=fill)

    def bar_text(self, phase):
        """
        The activity bar's characters for a given tick.

        Split out from render() because it is the part worth asserting on: a
        test can check the comet moves, wraps, and keeps its shape without
        needing to look at pixels.

        Args:
            phase: Monotonic tick counter; each step moves the comet one cell.

        Returns:
            A BAR_CELLS-long string of characters from SWEEP_RAMP.
        """
        # The cycle runs past the end of the bar by a whole tail length so the
        # comet leaves the right-hand edge completely before re-entering at the
        # left.  Wrapping it instead puts the head at one end and its tail at
        # the other, which reads as two unrelated smudges rather than one moving
        # object.  The dark cells at the turnaround are the pause between
        # sweeps, not a stall.
        head = phase % (BAR_CELLS + TAIL)
        out = []
        for i in range(BAR_CELLS):
            behind = head - i          # cells the head is ahead of this one
            level = 1.0 - behind / TAIL if 0 <= behind < TAIL else 0.0
            out.append(SWEEP_RAMP[round(level * (len(SWEEP_RAMP) - 1))])
        return "".join(out)

    def render(self, message, detail="", phase=0):
        """
        Draw the whole screen.

        Args:
            message: What is happening now, e.g. "starting camera".
            detail: A quieter second line, e.g. the grid size.
            phase: Tick counter driving the activity bar.

        Returns:
            A PIL RGB image of exactly the panel's size, ready for
            LcdDisplay.show_image.
        """
        img = Image.new("RGB", (self.width, self.height), self.screen)
        draw = ImageDraw.Draw(img)

        h = self.height
        # Proportional so the same layout works in either orientation.
        self._centre(draw, h * 0.15, APP_NAME, self.f_title, self.ink)

        # Clear of the title's descenders: "ascii_camera" ends in an underscore,
        # which sits below the baseline and touched the rule when this was any
        # tighter.
        rule_y = round(h * 0.34)
        margin = round(self.width * 0.18)
        draw.line([(margin, rule_y), (self.width - margin, rule_y)],
                  fill=self._dim(0.45), width=1)

        self._centre(draw, h * 0.44, message, self.f_body, self.ink)
        self._centre(draw, h * 0.60, self.bar_text(phase), self.f_body,
                     self.ink)
        if detail:
            self._centre(draw, h * 0.79, detail, self.f_small, self._dim(0.55))

        # Last in the reading order but not faint: at this size on a 2.4 inch
        # panel it was legible in a rendering and not on the glass, which is
        # the only test that counts. Brighter than the detail line above it
        # on purpose - a version nobody can read is not serving its purpose.
        if self.version:
            self._centre(draw, h * 0.89, f"v{self.version}", self.f_small,
                         self._dim(0.85))

        return img
