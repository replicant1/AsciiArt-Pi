#!/usr/bin/env python3
"""
Check which way round the picture comes out.

    python3 tests/orientation_test.py

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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from image_processor import ImageProcessor      # noqa: E402

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
    print("\n1. The default: rotation 180 with the flip on")
    out = ImageProcessor(rotation=180, mirror=True).rotate(marked())

    # Upside down but NOT mirrored: top-left should hold what was bottom-left,
    # i.e. a pure vertical flip of the original.
    check("it is a pure vertical flip", corners(out) == (3, 4, 1, 2),
          f"corners {corners(out)}")

    expected = np.flipud(marked())
    check("it equals flipud exactly", np.array_equal(out, expected))
    check("it is not the unmirrored 180 rotation",
          not np.array_equal(out, np.rot90(marked(), k=2)))


def test_the_old_behaviour_was_mirrored():
    print("\n2. The old behaviour, for comparison")
    out = ImageProcessor(rotation=180, mirror=False).rotate(marked())

    check("without the flip it is rot90(k=2)",
          np.array_equal(out, np.rot90(marked(), k=2)))
    check("which is the vertical flip, mirrored",
          np.array_equal(out, np.fliplr(np.flipud(marked()))))
    check("and so differs from what is wanted",
          not np.array_equal(out, np.flipud(marked())))


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
    processor = ImageProcessor(rotation=180, mirror=True, fill=False)

    # Chroma is half resolution on both axes, which is exactly the case that
    # would go wrong if the flip were applied per-plane at the wrong stage.
    got_luma = processor.to_grid(marked(8), 2, 2)
    got_chroma = processor.to_grid(marked(4), 2, 2)

    # to_grid is the shared path both planes take, so both must land the same
    # way round - any difference would show as colour fringing on edges.
    check("both planes agree on which corner is which",
          np.array_equal(got_luma, got_chroma),
          f"luma {corners(got_luma)} chroma {corners(got_chroma)}")
    check("and that agreement is the corrected orientation",
          corners(got_luma) == (3, 4, 1, 2), f"{corners(got_luma)}")


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
    test_the_old_behaviour_was_mirrored()
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
