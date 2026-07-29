"""
Camera capture for the Raspberry Pi Camera Module 2 (imx219).

A background thread pulls frames continuously and keeps only the most recent
one, so a slow render loop never builds up a backlog of stale frames.

Frames are delivered as the YUV420 *luma* (Y) plane, which is already an 8-bit
greyscale image - no YUV -> RGB -> grey round trip is needed (see
image_processor for the reasoning).
"""

import logging
import time
from queue import Queue, Empty, Full
from threading import Thread

import numpy as np
from picamera2 import Picamera2

logger = logging.getLogger(__name__)


class CameraCapture:
    """Captures greyscale frames from the Pi Camera Module 2."""

    def __init__(self, resolution=(320, 240), frame_rate=12):
        """
        Args:
            resolution: (width, height) requested from the ISP.  Ask for the
                smallest size that still feeds the ASCII grid - the ISP does
                the downscale in hardware, which is far cheaper than doing it
                on the Zero 2's CPU.
            frame_rate: Target sensor frame rate.  Capping this at what we can
                actually consume saves real CPU.
        """
        self.width, self.height = resolution
        self.frame_rate = frame_rate
        self.picam2 = None
        self.stride = self.width
        self.frame_queue = Queue(maxsize=1)
        self.is_running = False
        self.capture_thread = None

    def start(self):
        """Configure and start the camera plus its capture thread."""
        if self.is_running:
            return

        self.picam2 = Picamera2()

        # YUV420 is the sensor pipeline's native video format, so asking for it
        # avoids a format conversion inside the ISP as well.
        frame_us = int(1_000_000 / self.frame_rate)
        config = self.picam2.create_video_configuration(
            main={"format": "YUV420", "size": (self.width, self.height)},
            controls={"FrameDurationLimits": (frame_us, frame_us)},
            buffer_count=3,
        )
        self.picam2.configure(config)

        # picamera2 may pad each row out to a hardware-friendly stride; the
        # padding must be sliced off or the image comes out sheared.
        self.stride = self.picam2.camera_configuration()["main"]["stride"]
        actual = self.picam2.camera_configuration()["main"]["size"]
        if tuple(actual) != (self.width, self.height):
            logger.info("Camera returned %s instead of requested %s",
                        actual, (self.width, self.height))
            self.width, self.height = actual

        self.picam2.start()

        self.is_running = True
        self.capture_thread = Thread(target=self._capture_loop, daemon=True)
        self.capture_thread.start()
        logger.info("Camera started: %dx%d stride=%d @ %d fps",
                    self.width, self.height, self.stride, self.frame_rate)

    def _capture_loop(self):
        """Continuously capture, keeping only the newest frame."""
        consecutive_errors = 0
        while self.is_running:
            try:
                frame = self.picam2.capture_array("main")
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                logger.error("Error capturing frame: %s", e)
                # Back off rather than spinning the CPU on a repeating failure.
                time.sleep(min(0.05 * consecutive_errors, 1.0))
                continue

            luma = self._extract_luma(frame)
            if luma is None:
                continue

            # Drop the previous frame so the consumer always gets the latest.
            try:
                self.frame_queue.get_nowait()
            except Empty:
                pass
            try:
                self.frame_queue.put_nowait(luma)
            except Full:
                pass

    def _extract_luma(self, frame):
        """
        Pull the Y plane out of a YUV420 buffer.

        The full buffer is (height * 3 // 2) rows of `stride` bytes: `height`
        rows of luma followed by the half-resolution U and V planes.  Only the
        luma matters for greyscale ASCII.
        """
        h, w = self.height, self.width
        if frame.ndim == 1:
            frame = frame.reshape(-1, self.stride)
        elif frame.ndim == 3:
            frame = frame.reshape(frame.shape[0], -1)

        if frame.shape[0] < h:
            logger.warning("Short frame: %s rows, need %d", frame.shape[0], h)
            return None

        # np.ascontiguousarray both drops the stride padding and detaches the
        # slice from the (much larger) full YUV buffer.
        return np.ascontiguousarray(frame[:h, :w])

    def get_frame(self, timeout=0.5):
        """Return the most recent luma frame, or None if none arrived in time."""
        try:
            return self.frame_queue.get(timeout=timeout)
        except Empty:
            return None

    def stop(self):
        """Stop the capture thread and release the camera."""
        self.is_running = False
        if self.capture_thread:
            self.capture_thread.join(timeout=2)
        if self.picam2:
            try:
                self.picam2.stop()
            finally:
                self.picam2.close()
            self.picam2 = None
        logger.info("Camera stopped")
