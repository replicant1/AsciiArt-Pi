"""
The command line: every option the app takes, and what each one is for.

The settings half is **generated from `SPECS`**, not written out here. Every
field of `RenderConfig` already carries a one-line `note` that the socket's
`help` prints and the model's tool schema quotes, and this used to say the same
thing again in its own words. The two had drifted: `--help` called the ramp a
"character ramp" where the Spec calls it a character set, and said nothing
about the panel ignoring `--fill`, which the Spec does say. Adding a setting
meant editing three places and hoping.

What is written out by hand is everything with no setting behind it, which is
most of the count: the camera geometry, the panel's wiring and clock, the
encoder's pins, the socket path, the log. Those are facts about how a run is
started rather than about a value that can change while it runs, so there is
nothing for them to be generated from.
"""

import argparse
from pathlib import Path

from art import palettes
from art.ascii_art import RAMPS
from control import render_config
from lcd.lcd_worker import DEFAULT_SPLASH_HOLD
from version import APP_NAME, __version__

RAMP_CYCLE = list(RAMPS)

# The socket and the log belong beside the app, not beside this module.
# `Path(__file__).parent` said that while these lived in ascii_camera.py and
# quietly stopped saying it when they moved here: the service came up with its
# socket at src/control/asciicam.sock, where no client looks, and the CLI
# answered "Is it running?" about an app that was. Anchoring on the package
# root states what is meant and cannot drift with the file again.
APP_ROOT = Path(__file__).resolve().parents[2]


def _setting_argument(parser, name, flag=None, negate=False, **overrides):
    """
    Add the command-line argument for one setting, described by its own Spec.

    The wording comes from `Spec.note` - the same line the socket's `help`
    prints and the same line the model's tool schema carries. It used to be
    written out a second time here, and the two had already drifted: `--help`
    called the ramp a "character ramp" where the Spec calls it a character set,
    and said nothing about the panel ignoring `--fill`, which the Spec does say.
    Three places had to be edited to add a setting; now the Spec is the only
    one that describes it.

    Args:
        flag: the option string, when it is not the field name with hyphens -
            `--no-auto-levels` for `auto_levels`.
        negate: for a flag that turns a default-on setting off. The help is
            phrased as the negative of the Spec's own line rather than written
            again, so the two cannot say different things.
        overrides: anything argparse should be told instead, for the cases the
            Spec cannot know about - `--scheme` defaulting to None so that
            `--colour` can still win, and the scheme list appended to its help.
    """
    spec = render_config.BY_NAME[name]
    default = getattr(render_config.RenderConfig(), name)
    note = spec.note
    kw = {"help": f"Do not {note[0].lower()}{note[1:]}" if negate else note}

    if spec.kind == "bool":
        kw["action"] = "store_true"
    elif spec.kind == "choice":
        kw.update(choices=spec.choices, type=type(spec.choices[0]),
                  default=default)
    else:
        kw.update(type=int if spec.kind == "int" else float, default=default)

    kw.update(overrides)
    return parser.add_argument(flag or "--" + name.replace("_", "-"), **kw)


def build_parser():
    """
    The whole command line, ready to parse or to inspect.

    Separate from parse_args so that a test can read the arguments off it
    without running one - which is what pins the help text to the Specs.
    """
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
    _setting_argument(
        parser, "scheme", default=None,
        help=render_config.BY_NAME["scheme"].note
             + " Step through them live with s. "
             + "; ".join(f"{s.name}: {s.note}" for s in palettes.SCHEMES))
    parser.add_argument("--colour", "--color", action="store_true",
                        dest="colour",
                        help="Shorthand for --scheme live. Ignored if "
                             "--scheme is given")
    _setting_argument(parser, "colour_levels")
    _setting_argument(parser, "fill")
    _setting_argument(parser, "mirror")
    _setting_argument(parser, "rotation")
    _setting_argument(parser, "contrast")
    _setting_argument(parser, "auto_levels", flag="--no-auto-levels",
                      negate=True)
    _setting_argument(parser, "ramp")
    _setting_argument(parser, "invert")
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
    _setting_argument(
        lcd, "lcd_font_size",
        help=render_config.BY_NAME["lcd_font_size"].note
             + " 8 gives 64x24, 6 gives 80x30 and 9 gives 64x20; all three "
               "match the camera's 4:3, so nothing is cropped or letterboxed. "
               "Step through those three live with l")
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
                       default=str(APP_ROOT / "asciicam.sock"),
                       help="Path to the command socket")
    typed.add_argument("--no-commands", action="store_const", const="",
                       dest="command_socket",
                       help="Do not open the command socket at all")
    parser.add_argument("--log", default=str(APP_ROOT / "ascii_camera.log"),
                        help="Log file (stderr is redirected here too)")
    parser.add_argument("--verbose", action="store_true",
                        help="Debug-level logging")
    return parser


def parse_args(argv=None):
    """The parsed command line."""
    return build_parser().parse_args(argv)
