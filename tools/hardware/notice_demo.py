#!/usr/bin/env python3
"""
Put a notice on the real ILI9341 panel and hold it there to be looked at.

    sudo systemctl stop ascii-camera            # it owns the panel
    python3 tools/hardware/notice_demo.py                # every message, 20 s each
    python3 tools/hardware/notice_demo.py --message stall --seconds 120
    python3 tools/hardware/notice_demo.py --list
    sudo systemctl start ascii-camera

Nothing on the Mac can see this panel - grim photographs the HDMI output and
the ILI9341 is not part of it, and the module does not wire SDO usefully, so
register read-back returns zeros. The automated half of stage 5 lives in
tests/lcd/notice_test.py and genuinely can fail; what it cannot tell you is whether
the result is *readable*, which is the only question that matters for a band of
text on a 320x240 panel. That needs a person, and this puts something still
enough for a person to judge.

The picture underneath is a gradient at full brightness on purpose. A notice is
easy to read over a dark frame and the failure mode worth finding is the other
one - warm white on a near-black band, over the brightest picture the panel can
produce.
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lcd.lcd_display import LcdDisplay                     # noqa: E402

RAMP = " .:-=+*#%@"

# The real sentences, taken from the code that produces them rather than
# written out again - a demo that showed different words from the app would be
# reassuring about the wrong thing.
MESSAGES = {
    "stall": "no picture from the camera for 95s",
    "network": "no network - words need one, settings do not",
    "timeout": "the model took too long - try again",
    "key": "the API key was refused",
    "rate": "asking too fast - wait a moment",
    "asking": "asking: make it warmer and blockier",
    "decline": ("cannot do that: I only change how the picture is drawn, "
                "and that is not one of those things."),
}


def picture(display):
    """A bright gradient, so the band is judged against the hardest case."""
    cols, rows = display.grid_size
    ramp = np.linspace(0, len(RAMP) - 1, cols)
    return np.tile(ramp, (rows, 1)).astype(np.int16)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--message", choices=sorted(MESSAGES),
                    help="show one message instead of all of them")
    ap.add_argument("--seconds", type=float, default=20.0,
                    help="how long each message is held (default 20)")
    ap.add_argument("--font-size", type=int, default=8)
    ap.add_argument("--list", action="store_true",
                    help="print the messages and exit, touching no hardware")
    args = ap.parse_args(argv)

    if args.list:
        for key, text in sorted(MESSAGES.items()):
            print(f"{key:9s} {text}")
        return 0

    chosen = ([args.message] if args.message else sorted(MESSAGES))

    try:
        display = LcdDisplay(RAMP, font_size=args.font_size)
    except Exception as e:
        print(f"Could not open the panel: {e}\n"
              "Is ascii-camera still running? It owns /dev/spidev0.0:\n"
              "    sudo systemctl stop ascii-camera", file=sys.stderr)
        return 1

    frame = picture(display)
    print(f"Panel {display.lcd.width}x{display.lcd.height}, "
          f"grid {display.grid_size[0]}x{display.grid_size[1]}, "
          f"band {display.band_height}px tall.\n")

    try:
        for key in chosen:
            text = MESSAGES[key]
            display.render(frame, notice=text)
            print(f"  [{key}] holding {args.seconds:.0f}s. The bottom "
                  f"{display.band_height} pixels should read:\n      {text}\n")
            time.sleep(args.seconds)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        # Leave the panel showing the picture without a band, so whatever is
        # looked at next is not a leftover from this.
        display.clear_notice()

    print("Done. Start the camera again:  sudo systemctl start ascii-camera")
    return 0


if __name__ == "__main__":
    sys.exit(main())
