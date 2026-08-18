#!/usr/bin/env python3
"""
Grab one ordinary photo from the camera, for comparison against the ASCII view.

Useful for checking that --rotation is right and that the ASCII rendering
actually resembles the scene.  The camera can only be opened by one process at
a time, so stop ascii_camera.py first.

    python3 tests/capture/capture_reference.py reference.png
"""

import os
import sys

os.environ.setdefault("LIBCAMERA_LOG_LEVELS", "*:ERROR")

from picamera2 import Picamera2  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "reference.png"

picam2 = Picamera2()
picam2.configure(picam2.create_still_configuration(main={"size": (640, 480)}))
picam2.start()
picam2.capture_file(out, wait=True)
picam2.stop()
picam2.close()
print(f"Wrote {out}")
