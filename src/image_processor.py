"""
Image processing for ASCII art generation.

Pipeline per frame: rotate -> resize to the ASCII grid -> level adjust.

Note on colour: the Android app converts YUV420 -> RGB -> greyscale, but the
luminance formula (0.299R + 0.587G + 0.114B) is *definitionally* what the Y
plane of YUV420 already holds.  Reconstructing RGB just to throw the colour
away again costs six full-resolution float array operations per frame, which is
not affordable on a Zero 2.  We take Y directly and skip straight to resizing.
"""

import logging

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# A terminal character cell is roughly twice as tall as it is wide.  Without
# correcting for this the picture comes out squashed vertically.
DEFAULT_CELL_ASPECT = 2.0


def fit_grid(img_width, img_height, max_cols, max_rows,
             cell_aspect=DEFAULT_CELL_ASPECT):
    """
    Largest undistorted ASCII grid that fits in max_cols x max_rows cells.

    The displayed picture is `cols * cell_width` wide and `rows * cell_height`
    tall, so its on-screen aspect is cols / (rows * cell_aspect).  Matching that
    to the source aspect gives rows = cols / (src_aspect * cell_aspect).

    Returns:
        (cols, rows)
    """
    src_aspect = img_width / img_height

    cols = max(1, max_cols)
    rows = max(1, round(cols / (src_aspect * cell_aspect)))

    if rows > max_rows:
        rows = max(1, max_rows)
        cols = max(1, min(max_cols, round(rows * src_aspect * cell_aspect)))

    return cols, rows


class ImageProcessor:
    """Turns a raw greyscale camera frame into an ASCII-grid-sized array."""

    def __init__(self, contrast=1.0, auto_levels=True, rotation=180,
                 fill=False, cell_aspect=DEFAULT_CELL_ASPECT):
        """
        Args:
            contrast: Multiplier applied about mid-grey (1.0 = unchanged).
            auto_levels: Stretch each frame's own brightness range to 0-255.
                Cheap (it runs on the tiny output grid) and makes an enormous
                difference indoors, where raw camera luma often spans only a
                fraction of the range and the ASCII collapses to two or three
                distinct characters.
            rotation: 0, 90, 180 or 270 degrees.
            fill: Crop the frame to fill the whole grid instead of letterboxing
                it.  Fills the window at the cost of some field of view.
            cell_aspect: Terminal character height/width ratio.
        """
        self.contrast = contrast
        self.auto_levels = auto_levels
        self.rotation = rotation
        self.fill = fill
        self.cell_aspect = cell_aspect

    def rotate(self, frame):
        """Rotate to correct for how the camera module is mounted."""
        if self.rotation == 90:
            return np.rot90(frame, k=3)
        if self.rotation == 180:
            return np.rot90(frame, k=2)
        if self.rotation == 270:
            return np.rot90(frame, k=1)
        return frame

    def crop_to_aspect(self, frame, target_aspect):
        """
        Centre-crop the frame to a given width/height ratio.

        Used by fill mode: rather than leaving the unused part of the grid
        blank, throw away the edges of the frame that do not fit.
        """
        height, width = frame.shape
        current = width / height

        if abs(current - target_aspect) < 1e-3:
            return frame

        if current > target_aspect:      # too wide - trim the sides
            new_width = max(1, int(round(height * target_aspect)))
            left = (width - new_width) // 2
            return frame[:, left:left + new_width]

        new_height = max(1, int(round(width / target_aspect)))  # too tall
        top = (height - new_height) // 2
        return frame[top:top + new_height, :]

    def resize(self, frame, cols, rows):
        """
        Resample down to the ASCII grid.

        BOX (area averaging) is the right filter here: each output cell should
        be the mean brightness of the source region it covers, which is exactly
        what an ASCII cell represents.  It is also markedly faster than LANCZOS,
        whose extra sharpness is invisible at one character per pixel.
        """
        img = Image.fromarray(frame, mode="L")
        img = img.resize((cols, rows), Image.Resampling.BOX)
        return np.asarray(img)

    def adjust_levels(self, frame):
        """Apply auto-levels and/or a fixed contrast multiplier."""
        if self.auto_levels:
            lo = int(np.percentile(frame, 2))
            hi = int(np.percentile(frame, 98))
            if hi - lo >= 8:  # Guard against amplifying noise on a flat frame.
                scaled = (frame.astype(np.float32) - lo) * (255.0 / (hi - lo))
                frame = np.clip(scaled, 0, 255).astype(np.uint8)

        if self.contrast != 1.0:
            centred = frame.astype(np.float32) - 128.0
            frame = np.clip(centred * self.contrast + 128.0, 0, 255).astype(np.uint8)

        return frame

    def process(self, luma, cols, rows):
        """
        Full pipeline.

        Args:
            luma: 2D uint8 greyscale array straight from the camera.
            cols, rows: Target ASCII grid size.

        Returns:
            uint8 array of shape (rows, cols).
        """
        rotated = self.rotate(luma)
        if self.fill:
            # On-screen aspect of the grid, which the source must be cropped to
            # match if it is to fill the grid without distortion.
            rotated = self.crop_to_aspect(rotated, cols / (rows * self.cell_aspect))
        scaled = self.resize(rotated, cols, rows)
        return self.adjust_levels(scaled)

    def source_size(self, width, height):
        """Frame dimensions after rotation, for grid-fitting purposes."""
        if self.rotation in (90, 270):
            return height, width
        return width, height
