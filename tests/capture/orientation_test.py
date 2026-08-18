#!/usr/bin/env python3
"""
Check which way round the picture comes out.

    python3 tests/capture/orientation_test.py

This bug survived a long time because a mirrored picture looks perfectly
plausible: nothing is upside down, nothing is squashed, and on a roughly
symmetrical scene it is invisible. It only shows on something with a handedness
- text, a face, a hand. So the orientation gets a test with a deliberately
asymmetric input, where left and right are told apart by construction.

The important case is rotation=180 with the flip on, which is what this Pi's
camera mounting needs and what the app does by default. Expressed as a
transform: the sensor is upside down, so the picture wants flipping top to
bottom - and nothing else. np.rot90(k=2) flips both axes, so the horizontal
flip has to be put back.
"""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from capture.image_processor import ImageProcessor      # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def marked(size=8):
    """
    A frame whose every corner is distinguishable.

    Quadrants filled with 1, 2, 3, 4 - top-left, top-right, bottom-left,
    bottom-right - so any rotation or flip is identifiable from where they end
    up. Filled quadrants rather than single marker pixels because to_grid()
    downscales by area averaging: a lone pixel in an 8x8 frame reduced to 2x2
    is averaged over sixteen and rounds away to nothing, which measures the
    resampler rather than the orientation. A uniform quadrant averages to
    exactly its own value at any target size.
    """
    half = size // 2
    frame = np.zeros((size, size), dtype=np.uint8)
    frame[:half, :half] = 1
    frame[:half, half:] = 2
    frame[half:, :half] = 3
    frame[half:, half:] = 4
    return frame


def corners(frame):
    return (int(frame[0, 0]), int(frame[0, -1]),
            int(frame[-1, 0]), int(frame[-1, -1]))


def test_default():
    print("\n1. The default: no rotation, no flip")
    out = ImageProcessor().rotate(marked())

    # The sensor delivers the picture the right way round as currently
    # mounted, so the correction is the identity.
    check("it passes the frame through unchanged",
          np.array_equal(out, marked()), f"corners {corners(out)}")
    check("corners are untouched", corners(out) == (1, 2, 3, 4),
          f"{corners(out)}")


def test_the_settings_it_replaced():
    print("\n2. The two settings this replaced, for comparison")

    # Each was confirmed wrong by eye, and each is one composition away from
    # the next, so keeping them here makes the sequence auditable.
    rotated = ImageProcessor(rotation=180, mirror=False).rotate(marked())
    check("rotation 180 alone is rot90(k=2)",
          np.array_equal(rotated, np.rot90(marked(), k=2)))
    check("which is a vertical flip AND a mirror",
          np.array_equal(rotated, np.fliplr(np.flipud(marked()))))

    flipped = ImageProcessor(rotation=180, mirror=True).rotate(marked())
    check("rotation 180 with the flip is a pure flipud",
          np.array_equal(flipped, np.flipud(marked())),
          f"corners {corners(flipped)}")
    check("the default is that turned back up the right way",
          np.array_equal(np.flipud(flipped), ImageProcessor().rotate(marked())))


def test_every_rotation():
    print("\n3. The flip is applied at every rotation, and only once")
    for rotation in (0, 90, 180, 270):
        plain = ImageProcessor(rotation=rotation, mirror=False).rotate(marked())
        flipped = ImageProcessor(rotation=rotation, mirror=True).rotate(marked())

        check(f"rot{rotation:<3} flip is a horizontal mirror of no-flip",
              np.array_equal(flipped, np.fliplr(plain)),
              f"{corners(plain)} -> {corners(flipped)}")
        check(f"rot{rotation:<3} flipping twice returns the original",
              np.array_equal(np.fliplr(flipped), plain))


def test_planes_stay_in_register():
    print("\n4. Luma and chroma get the same treatment")
    # Deliberately not the default: a non-identity transform is the only one
    # that can catch the planes being treated differently.
    processor = ImageProcessor(rotation=90, mirror=True, fill=False)

    # Chroma is half resolution on both axes, which is exactly the case that
    # would go wrong if the flip were applied per-plane at the wrong stage.
    got_luma = processor.to_grid(marked(8), 2, 2)
    got_chroma = processor.to_grid(marked(4), 2, 2)

    # to_grid is the shared path both planes take, so both must land the same
    # way round - any difference would show as colour fringing on edges.
    check("both planes agree on which corner is which",
          np.array_equal(got_luma, got_chroma),
          f"luma {corners(got_luma)} chroma {corners(got_chroma)}")
    check("and that agreement is the transform asked for",
          corners(got_luma) == corners(
              ImageProcessor(rotation=90, mirror=True).rotate(marked(8))),
          f"{corners(got_luma)}")


def test_source_size_unaffected():
    print("\n5. A horizontal flip does not change the shape")
    for rotation in (0, 90, 180, 270):
        flipped = ImageProcessor(rotation=rotation, mirror=True)
        plain = ImageProcessor(rotation=rotation, mirror=False)
        check(f"rot{rotation:<3} source_size is unchanged by the flip",
              flipped.source_size(320, 240) == plain.source_size(320, 240))


def main():
    print("=" * 62)
    print("Picture orientation")
    print("=" * 62)

    test_default()
    test_the_settings_it_replaced()
    test_every_rotation()
    test_planes_stay_in_register()
    test_source_size_unaffected()

    print("\n" + "=" * 62)
    if failures:
        print(f"RESULT: {len(failures)} CHECK(S) FAILED")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("RESULT: the picture comes out the right way round.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
