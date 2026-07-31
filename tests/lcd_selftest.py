#!/usr/bin/env python3
"""
Self-test for the ILI9341 panel, run on the Pi:

    python3 tests/lcd_selftest.py

Deliberately structured so most of it can FAIL rather than just print things.
The colour-packing maths is checked against hand-computed RGB565 values, and
every SPI call is left unguarded so a wiring or permissions problem surfaces as
a traceback instead of a silent no-op.

What this cannot do is confirm what is actually lit up.  `grim` photographs the
Wayland/HDMI output and an SPI panel is not part of that, so the last step puts
a distinctive pattern on the glass and asks a human to confirm it.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

from src.lcd import ILI9341, pack_rgb565, rgb565

# (name, 8-bit RGB, expected RGB565) worked out by hand from the bit layout
# RRRRRGGG GGGBBBBB, so a regression in the packing shows up as a mismatch
# rather than as slightly-off colours nobody notices.
COLOUR_CASES = [
    ("black",   (0, 0, 0),       0x0000),
    ("white",   (255, 255, 255), 0xFFFF),
    ("red",     (255, 0, 0),     0xF800),
    ("green",   (0, 255, 0),     0x07E0),
    ("blue",    (0, 0, 255),     0x001F),
    ("yellow",  (255, 255, 0),   0xFFE0),
    ("cyan",    (0, 255, 255),   0x07FF),
    ("magenta", (255, 0, 255),   0xF81F),
    ("grey50",  (128, 128, 128), 0x8410),
]

failures = []


def check(label, condition, detail=""):
    """Record a pass/fail line; collect failures for the final verdict."""
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def test_packing():
    """RGB565 conversion, checked without touching any hardware."""
    print("\n1. Colour packing (no hardware needed)")

    for name, rgb, expected in COLOUR_CASES:
        got = rgb565(*rgb)
        check(f"rgb565{rgb} -> 0x{expected:04X}", got == expected,
              f"got 0x{got:04X}")

    # The array path must agree with the scalar one, including byte order:
    # the panel takes the high byte first.
    swatch = Image.new("RGB", (len(COLOUR_CASES), 1))
    swatch.putdata([rgb for _, rgb, _ in COLOUR_CASES])
    packed = pack_rgb565(swatch)

    check("pack_rgb565 length is 2 bytes/pixel",
          len(packed) == len(COLOUR_CASES) * 2, f"{len(packed)} bytes")

    for i, (name, _, expected) in enumerate(COLOUR_CASES):
        hi, lo = packed[i * 2], packed[i * 2 + 1]
        got = (hi << 8) | lo
        check(f"pack_rgb565 {name} big-endian", got == expected,
              f"got 0x{got:04X}")


def read_register(lcd, cmd, count):
    """
    Attempt an ILI9341 register read.

    Informational only.  spidev deasserts CS between transfers, and the panel
    wants CS held low across the whole command-then-read, so a module that does
    not wire SDO - or one that minds the CS glitch - returns 0x00s or 0xFFs
    without anything actually being wrong.  Reported, never asserted on.
    """
    original = lcd.spi.max_speed_hz
    lcd.spi.max_speed_hz = 5_000_000        # reads are spec'd far slower
    try:
        lcd.GPIO.output(lcd.dc, lcd.GPIO.LOW)
        lcd.spi.writebytes([cmd])
        lcd.GPIO.output(lcd.dc, lcd.GPIO.HIGH)
        return bytes(lcd.spi.readbytes(count))
    finally:
        lcd.spi.max_speed_hz = original


def test_hardware(hold):
    """Bring the panel up, time a frame, then leave a pattern on screen."""
    print("\n2. Panel bring-up")

    lcd = ILI9341(landscape=True)
    print(f"  geometry: {lcd.width}x{lcd.height} landscape")
    lcd.init()
    check("init() completed without an SPI/GPIO error", True)

    print("\n3. Register read-back (informational, not a verdict)")
    for cmd, name, n in [(0x04, "RDDID", 4), (0x09, "RDDST", 5),
                         (0x0A, "power mode", 2), (0x0C, "pixel format", 2)]:
        raw = read_register(lcd, cmd, n)
        print(f"  0x{cmd:02X} {name:<13} -> {raw.hex(' ')}")
    print("  (all-00 or all-FF here means SDO/MISO is not readable,"
          " not that the panel is broken)")

    print("\n4. Full-frame write timing")
    frame_bytes = lcd.width * lcd.height * 2
    for colour, name in [(0xF800, "red"), (0x07E0, "green"), (0x001F, "blue")]:
        start = time.perf_counter()
        lcd.fill(colour)
        elapsed = time.perf_counter() - start
        rate = frame_bytes / elapsed / 1e6
        print(f"  fill {name:<6} {elapsed * 1000:6.1f} ms"
              f"  ({rate:5.2f} MB/s, {1 / elapsed:4.1f} fps)")
        # A wildly out-of-range time means the transfer is not really happening.
        check(f"fill {name} took a plausible time",
              0.005 < elapsed < 5.0, f"{elapsed * 1000:.1f} ms")

    print("\n5. Image path")
    image = build_test_card(lcd.width, lcd.height)
    start = time.perf_counter()
    lcd.show(image)
    elapsed = time.perf_counter() - start
    print(f"  show() test card: {elapsed * 1000:.1f} ms"
          f"  ({1 / elapsed:.1f} fps)")

    # show() must refuse a wrongly-sized image rather than corrupt the screen.
    try:
        lcd.show(Image.new("RGB", (10, 10)))
        check("show() rejects a wrong-sized image", False, "it accepted 10x10")
    except ValueError:
        check("show() rejects a wrong-sized image", True)

    print(f"\n  Holding the test card for {hold}s - LOOK AT THE PANEL.")
    time.sleep(hold)
    lcd.close()
    check("close() released SPI and GPIO", True)


def build_test_card(width, height):
    """
    A pattern that is hard to mistake for a fluke.

    Named colour bars in a known left-to-right order, plus a grey ramp and
    text, so a report of what is on screen either matches exactly or does not.
    """
    bars = [("R", (255, 0, 0)), ("G", (0, 255, 0)), ("B", (0, 0, 255)),
            ("C", (0, 255, 255)), ("M", (255, 0, 255)), ("Y", (255, 255, 0)),
            ("W", (255, 255, 255)), ("K", (0, 0, 0))]

    image = Image.new("RGB", (width, height), "black")
    draw = ImageDraw.Draw(image)

    bar_width = width / len(bars)
    bar_bottom = int(height * 0.55)
    for i, (letter, colour) in enumerate(bars):
        x0, x1 = int(i * bar_width), int((i + 1) * bar_width) - 1
        draw.rectangle([x0, 0, x1, bar_bottom], fill=colour)
        # Label each bar in the opposite luminance so it stays readable.
        ink = "black" if sum(colour) > 380 else "white"
        draw.text((x0 + bar_width / 2 - 3, bar_bottom - 18), letter, fill=ink)

    # Grey ramp: banding here would mean the RGB565 conversion is wrong.
    ramp_top, ramp_bottom = bar_bottom + 6, bar_bottom + 36
    for x in range(width):
        level = int(255 * x / max(1, width - 1))
        draw.line([(x, ramp_top), (x, ramp_bottom)], fill=(level, level, level))

    # A 1px border proves no row or column is being clipped by the window.
    draw.rectangle([0, 0, width - 1, height - 1], outline=(255, 255, 0))

    draw.text((6, ramp_bottom + 10), f"ILI9341 {width}x{height}", fill="white")
    draw.text((6, ramp_bottom + 26), "ASCIIART SELFTEST OK", fill=(0, 255, 0))
    draw.text((6, ramp_bottom + 42), "bars: R G B C M Y W K", fill="white")
    return image


def main():
    hold = int(sys.argv[1]) if len(sys.argv) > 1 else 20

    print("=" * 60)
    print("ILI9341 self-test  --  DC=25 RST=27 BL=18, spidev0.0")
    print("=" * 60)

    test_packing()
    test_hardware(hold)

    print("\n" + "=" * 60)
    if failures:
        print(f"RESULT: {len(failures)} CHECK(S) FAILED")
        for name in failures:
            print(f"  - {name}")
        return 1

    print("RESULT: all automated checks passed.")
    print("These prove the maths and that SPI accepted every byte.")
    print("They do NOT prove anything is visible - confirm the panel showed")
    print("8 colour bars (R G B C M Y W K, left to right), a grey ramp,")
    print("a yellow border and the text 'ASCIIART SELFTEST OK'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
