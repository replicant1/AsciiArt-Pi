#!/usr/bin/env python3
"""
Check the colour schemes, with no hardware and no camera.

    python3 tests/art/palette_test.py

The interesting test is the separation one. "The options need to be quite
obviously different to the naked eye" is a real requirement, so it gets a real
check rather than an assurance: every pair of schemes is compared in a
perceptual approximation of RGB distance, and the whole run fails if any two
sit closer than the threshold. That is what stops someone later adding a second
amber that differs from the first only in the third hex digit.
"""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from art import palettes                       # noqa: E402
from art.ascii_art import AsciiArt        # noqa: E402

# Redmean distance runs 0..~765. Two schemes closer than this in combined ink
# and screen distance would be a "which one am I looking at?" pair.
MIN_SEPARATION = 150

failures = []


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def redmean(a, b):
    """
    Approximate perceptual distance between two RGB colours.

    Plain Euclidean RGB badly overrates blue differences and underrates green
    ones. The redmean weighting is the cheap standard correction and needs no
    colour-space conversion, which matters here only for keeping the test
    dependency-free.
    """
    r1, g1, b1 = (float(v) for v in a)
    r2, g2, b2 = (float(v) for v in b)
    rbar = (r1 + r2) / 2
    dr, dg, db = r1 - r2, g1 - g2, b1 - b2
    return ((2 + rbar / 256) * dr * dr
            + 4 * dg * dg
            + (2 + (255 - rbar) / 256) * db * db) ** 0.5


def scheme_distance(x, y):
    """How different two schemes look: ink difference plus screen difference."""
    return redmean(x.ink, y.ink) + redmean(x.screen, y.screen)


def test_structure():
    print("\n1. Scheme list")
    names = [s.name for s in palettes.SCHEMES]
    check("names are unique", len(set(names)) == len(names))
    check("names are short enough for the status line",
          all(len(n) <= 5 for n in names),
          f"longest {max(names, key=len)!r}")
    check("exactly one greyscale scheme",
          sum(s.kind == "grey" for s in palettes.SCHEMES) == 1)
    check("exactly one live scheme",
          sum(s.kind == "live" for s in palettes.SCHEMES) == 1)
    check("every kind is known",
          all(s.kind in ("grey", "live", "tint") for s in palettes.SCHEMES))

    grey_at = names.index("grey")
    live_at = names.index("live")
    check("grey and live are adjacent in the cycle",
          abs(grey_at - live_at) == 1, f"positions {grey_at} and {live_at}")

    check("by_name rejects nonsense", _raises(lambda: palettes.by_name("nope")))


def _raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


def test_separation():
    print(f"\n2. Every pair differs by at least {MIN_SEPARATION}")
    tinted = [s for s in palettes.SCHEMES if s.kind != "live"]

    worst = (None, None, 1e9)
    for i, a in enumerate(tinted):
        for b in tinted[i + 1:]:
            d = scheme_distance(a, b)
            if d < worst[2]:
                worst = (a.name, b.name, d)

    print("       " + "".join(f"{s.name:>7}" for s in tinted))
    for a in tinted:
        row = "".join(f"{scheme_distance(a, b):7.0f}" if a is not b else
                      f"{'-':>7}" for b in tinted)
        print(f"{a.name:>6} {row}")

    check(f"closest pair is {worst[0]}/{worst[1]}",
          worst[2] >= MIN_SEPARATION, f"distance {worst[2]:.0f}")

    print("\n3. Ink and screen are far apart within each scheme")
    for scheme in tinted:
        contrast = redmean(scheme.ink, scheme.screen)
        check(f"{scheme.name:<5} is legible", contrast >= 250,
              f"ink/screen distance {contrast:.0f}")


def test_tables():
    print("\n4. Blend tables")
    for scheme in palettes.SCHEMES:
        if scheme.kind != "tint":
            continue
        for levels in (2, 10, 70):
            rgb = palettes.rgb_table(scheme, levels)
            check(f"{scheme.name:<5} n={levels:<2} shape",
                  rgb.shape == (levels, 3), str(rgb.shape))
            # The blend must actually span screen -> ink, or a scheme would
            # render as a washed-out version of itself.
            check(f"{scheme.name:<5} n={levels:<2} starts at the screen",
                  tuple(rgb[0]) == scheme.screen,
                  f"{tuple(rgb[0])} vs {scheme.screen}")
            check(f"{scheme.name:<5} n={levels:<2} ends at the ink",
                  tuple(rgb[-1]) == scheme.ink,
                  f"{tuple(rgb[-1])} vs {scheme.ink}")

            index = palettes.index_table(scheme, levels)
            check(f"{scheme.name:<5} n={levels:<2} palette in range",
                  index.shape == (levels,)
                  and int(index.min()) >= 16 and int(index.max()) <= 255,
                  f"{int(index.min())}..{int(index.max())}")

    print("\n5. Palette matching")
    for rgb, expect in [((0, 0, 0), "black"), ((255, 255, 255), "white")]:
        got = palettes.XTERM_RGB[palettes.nearest_xterm(rgb) - 16]
        check(f"nearest_xterm{rgb} is {expect}", tuple(got) == rgb,
              f"got {tuple(got)}")
    # A colour off the palette must land somewhere close, not somewhere silly.
    for probe in [(0x33, 0xFF, 0x33), (0xFF, 0xB7, 0x33), (0xE9, 0xE7, 0xDF)]:
        got = palettes.XTERM_RGB[palettes.nearest_xterm(probe) - 16]
        d = redmean(probe, got)
        check(f"nearest_xterm{probe} is close", d < 120, f"distance {d:.0f}")


def test_invert():
    print("\n6. Invert reverses the tint along with the characters")
    scheme = palettes.by_name("green")
    probe = np.array([[0, 128, 255]], dtype=np.uint8)

    plain = AsciiArt(ramp="coarse", invert=False)
    flipped = AsciiArt(ramp="coarse", invert=True)
    n = len(plain.chars)

    bright_plain = palettes.rgb_table(scheme, n, False)[
        plain.to_indices(probe)][0, 2]
    bright_flipped = palettes.rgb_table(scheme, n, True)[
        flipped.to_indices(probe)][0, 2]

    # Not inverted, a bright cell should sit at the ink end; inverted it should
    # sit at the screen end, matching the sparser character it now gets.
    check("bright cell tints towards ink normally",
          redmean(bright_plain, scheme.ink)
          < redmean(bright_plain, scheme.screen),
          f"{tuple(bright_plain)}")
    check("bright cell tints towards screen when inverted",
          redmean(bright_flipped, scheme.screen)
          < redmean(bright_flipped, scheme.ink),
          f"{tuple(bright_flipped)}")


def main():
    print("=" * 66)
    print("Colour schemes")
    print("=" * 66)

    test_structure()
    test_separation()
    test_tables()
    test_invert()

    print("\n" + "=" * 66)
    if failures:
        print(f"RESULT: {len(failures)} CHECK(S) FAILED")
        for name in failures:
            print(f"  - {name}")
        return 1
    print(f"RESULT: all checks passed for {len(palettes.SCHEMES)} schemes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
