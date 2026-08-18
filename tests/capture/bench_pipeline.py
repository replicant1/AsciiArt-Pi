#!/usr/bin/env python3
"""
Headless benchmark for the ASCII camera pipeline.

Runs capture -> process -> ASCII without curses, so it can be driven over SSH,
and reports the sustained frame rate at several target rates.  Use it to pick a
sensible --fps default after changing the pipeline.

    python3 tests/capture/bench_pipeline.py
"""

import logging
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("LIBCAMERA_LOG_LEVELS", "*:ERROR")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

logging.disable(logging.CRITICAL)

from art.ascii_art import AsciiArt          # noqa: E402
from capture.camera import CameraCapture        # noqa: E402
from capture.image_processor import ImageProcessor, fit_grid  # noqa: E402

DURATION = 6.0
COLS, ROWS = 80, 79


def measure(target_fps, size=(320, 240)):
    camera = CameraCapture(resolution=size, frame_rate=target_fps)
    camera.start()
    processor = ImageProcessor(rotation=180)
    ascii_art = AsciiArt()
    cols, rows = fit_grid(size[0], size[1], COLS, ROWS)

    camera.get_frame(timeout=15)  # discard warm-up frame
    frames = 0
    start = time.time()
    while time.time() - start < DURATION:
        luma = camera.get_frame(timeout=2)
        if luma is None:
            break
        ascii_art.to_ascii_text(processor.process(luma, cols, rows))
        frames += 1
    elapsed = time.time() - start
    camera.stop()
    return frames / elapsed if elapsed else 0.0


def main():
    for size in [(320, 240), (640, 480)]:
        for target in [12, 20, 30]:
            actual = measure(target, size)
            print(f"{size[0]}x{size[1]}  target {target:>2} fps  ->  "
                  f"{actual:5.1f} fps actual")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
