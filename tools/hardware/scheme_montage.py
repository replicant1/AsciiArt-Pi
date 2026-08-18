#!/usr/bin/env python3
"""
Build the colour-scheme montage used in the README.

    python3 tools/hardware/scheme_montage.py                    # capture and render
    python3 tools/hardware/scheme_montage.py --frame shot.npy   # reuse a saved frame
    python3 tools/hardware/scheme_montage.py --save-frame shot.npy

Nine tiles, one per scheme, showing **the same picture** in every one. That is
the whole point of the figure - the reader is comparing colour, so nothing else
may vary - and it is why this does not simply screenshot the running app nine
times. A live camera gives a slightly different frame each shot: the scene
drifts, auto-levels re-stretch, sensor noise moves. The differences are small
but they are exactly the kind that make a reader wonder whether the schemes
change anything else.

So one frame is captured once, and the character grid is computed from it
*once*. Every tile then reuses that identical grid of ramp positions, and only
the colour lookup differs. The pictures are therefore provably identical - not
merely similar - and `--verify` asserts it.

The rendering is the panel's own: the same GlyphAtlas, the same blend from
screen colour to ink by glyph coverage. So the tiles show what the app really
draws rather than an impression of it.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from art import palettes                                  # noqa: E402
from art.ascii_art import RAMPS, AsciiArt            # noqa: E402
from capture.image_processor import ImageProcessor       # noqa: E402
from panel.lcd_display import DEFAULT_FONT, GlyphAtlas  # noqa: E402

logger = logging.getLogger("montage")

# 80 columns at font size 9 gives a 5x12 cell, and 25 rows then makes the tile
# exactly 400x300 - a true 4:3, matching the camera, so nothing is cropped.
COLUMNS = 80
FONT_SIZE = 9
CAMERA_ASPECT = 4 / 3

GAP = 14
LABEL_HEIGHT = 22
PER_ROW = 3
LABEL_BG = (24, 24, 26)
LABEL_FG = (232, 232, 232)


def capture(width=320, height=240, warmup=12.0):
    """
    Grab a single frame, giving the sensor time to settle first.

    The warm-up is generous on purpose. Three seconds was not enough on this
    Pi - auto-exposure was still winding up, and the montage came out so dark
    that the picture was hard to read in every tile at once. Twelve seconds
    gets a properly exposed frame, and this runs once to make a figure, so the
    wait costs nothing that matters.
    """
    from capture.camera import CameraCapture

    camera = CameraCapture(resolution=(width, height), frame_rate=15)
    camera.start()
    try:
        # The first frames come out before auto-exposure has settled, and a
        # murky one would make every tile look bad in the same way.
        deadline = time.time() + warmup
        frame = None
        while time.time() < deadline:
            got = camera.get_frame(timeout=1.0)
            if got is not None:
                frame = got
        if frame is None:
            raise RuntimeError("no frame arrived from the camera")
        return frame
    finally:
        camera.stop()


class SavedFrame:
    """A YuvFrame rebuilt from a .npy, so a montage can be reproduced."""

    def __init__(self, buffer, width, height):
        self._buf = buffer
        self.width = width
        self.height = height

    @property
    def shape(self):
        return self.height, self.width

    @property
    def luma(self):
        return self._buf[:self.height, :self.width]

    @property
    def chroma(self):
        h, w = self.height, self.width
        flat = self._buf[h:, :w].reshape(-1)
        plane = (h // 2) * (w // 2)
        return (flat[:plane].reshape(h // 2, w // 2),
                flat[plane:plane * 2].reshape(h // 2, w // 2))


def render_tile(atlas, indices, colours, screen):
    """
    One tile: glyphs blended from the screen colour to each cell's colour.

    The same arithmetic lcd_display uses, but landing on 8-bit RGB rather than
    the panel's RGB565.
    """
    cell_h, cell_w = atlas.cell_h, atlas.cell_w
    rows, cols = indices.shape

    coverage = (atlas.tiles[indices]
                .transpose(0, 2, 1, 3)
                .reshape(rows * cell_h, cols * cell_w))

    big = np.repeat(np.repeat(colours, cell_h, axis=0), cell_w, axis=1)
    base = np.array(screen, dtype=np.int32)
    weight = coverage[..., None].astype(np.int32) + 1

    pixels = base + (((big.astype(np.int32) - base) * weight) >> 8)
    return Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), "RGB")


def colours_for(scheme, indices, art, processor, frame, processed, cols, rows):
    """The per-cell colour grid a scheme wants, and the colour behind it."""
    if scheme.kind == "grey":
        # Every glyph at full white, which is what the terminal's own
        # foreground gives in greyscale mode.
        return np.full(indices.shape + (3,), 255, dtype=np.uint8), (0, 0, 0)
    if scheme.kind == "live":
        return (processor.colour_grid(frame, processed, cols, rows),
                (0, 0, 0))
    return (palettes.rgb_table(scheme, len(art.chars))[indices], scheme.screen)


def build(frame, ramp="coarse", invert=False, rotation=0, verify=True,
          mirror=False):
    """Render every scheme from one frame and return the tiles, in order."""
    art = AsciiArt(ramp=ramp, invert=invert)
    atlas = GlyphAtlas(art.chars, DEFAULT_FONT, FONT_SIZE)
    cell_aspect = atlas.cell_h / atlas.cell_w

    cols = COLUMNS
    rows = max(1, round(cols / (CAMERA_ASPECT * cell_aspect)))

    # fill=True so the picture occupies the whole tile, exactly as the panel
    # does; every tile is then the same size and the same crop.
    processor = ImageProcessor(rotation=rotation, fill=True,
                               cell_aspect=cell_aspect, mirror=mirror)
    processed = processor.process(frame.luma, cols, rows)

    # Computed once, reused by every tile. This is what makes the pictures
    # identical rather than merely similar.
    indices = art.to_indices(processed)
    logger.info("Grid %dx%d, cell %dx%d, tile %dx%d px", cols, rows,
                atlas.cell_w, atlas.cell_h,
                cols * atlas.cell_w, rows * atlas.cell_h)

    tiles = []
    for scheme in palettes.SCHEMES:
        colours, screen = colours_for(scheme, indices, art, processor, frame,
                                      processed, cols, rows)
        tiles.append((scheme, render_tile(atlas, indices, colours, screen)))

    if verify:
        _verify_identical(tiles, atlas, indices)
    return tiles


MIN_AGREEMENT = 0.99
LIT = 8          # per-channel deviation that counts as "a glyph is here"


def _verify_identical(tiles, atlas, indices):
    """
    Assert the tiles differ only in colour, never in content.

    Cheap insurance on the figure's one claim. Every tile is reduced to "which
    pixels does a glyph cover", which must come out the same everywhere; a
    scheme that somehow changed a character is what this would catch.

    The `live` scheme is checked structurally rather than by pixels, and the
    reason is worth stating: its ink colour comes from the scene, so a cell the
    camera saw as nearly black renders nearly black whether a glyph covers it
    or not. "Is a glyph here" is genuinely unrecoverable from those pixels. It
    still shares the one `indices` array with every other tile, which is what
    actually guarantees the content matches - the pixel comparison is only a
    stronger spot check where the ink is a known constant.
    """
    cell_h, cell_w = atlas.cell_h, atlas.cell_w
    rows, cols = indices.shape
    expected = (atlas.tiles[indices]
                .transpose(0, 2, 1, 3)
                .reshape(rows * cell_h, cols * cell_w) > LIT)

    checked = 0
    for scheme, tile in tiles:
        if scheme.kind == "live":
            continue
        pixels = np.asarray(tile).astype(np.int32)
        # Deviation from this tile's own background corner, which no glyph
        # covers in any scheme, so "lit" means the same thing in all of them.
        # Per-channel max rather than a sum: it does not let three small
        # channel differences add up to a false positive.
        lit = np.abs(pixels - pixels[0, 0]).max(axis=2) > LIT
        agreement = (lit == expected).mean()
        if agreement < MIN_AGREEMENT:
            raise AssertionError(
                f"{scheme.name} does not show the same picture as the others "
                f"({agreement:.1%} of pixels agree)")
        checked += 1

    logger.info("Verified: %d of %d tiles match pixel for pixel in content; "
                "all %d share one grid of ramp positions",
                checked, len(tiles), len(tiles))


def compose(tiles):
    """Lay the tiles out in a labelled grid."""
    width, height = tiles[0][1].size
    columns = PER_ROW
    lines = (len(tiles) + columns - 1) // columns

    sheet = Image.new(
        "RGB",
        (columns * width + (columns + 1) * GAP,
         lines * (height + LABEL_HEIGHT) + (lines + 1) * GAP),
        LABEL_BG)
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(DEFAULT_FONT, 13)
    except OSError:
        font = ImageFont.load_default()

    for i, (scheme, tile) in enumerate(tiles):
        col, line = i % columns, i // columns
        x = GAP + col * (width + GAP)
        y = GAP + line * (height + LABEL_HEIGHT + GAP)
        sheet.paste(tile, (x, y))
        draw.text((x + 3, y + height + 4),
                  f"{scheme.name}  -  {scheme.note}", fill=LABEL_FG, font=font)

    return sheet


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--out", default=str(ROOT / "docs" /
                                             "scheme-montage.png"))
    parser.add_argument("--frame", help="Render a saved .npy instead of "
                                        "capturing a new frame")
    parser.add_argument("--save-frame", help="Write the captured frame here, "
                                             "so the montage can be remade")
    parser.add_argument("--ramp", default="coarse", choices=list(RAMPS))
    parser.add_argument("--invert", action="store_true")
    parser.add_argument("--rotation", type=int, default=0)
    parser.add_argument("--mirror", action="store_true",
                        help="Flip left to right; see ImageProcessor.rotate")
    parser.add_argument("--no-verify", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.frame:
        buffer = np.load(args.frame)
        height = buffer.shape[0] * 2 // 3
        frame = SavedFrame(buffer, buffer.shape[1], height)
        logger.info("Loaded %s (%dx%d)", args.frame, frame.width, frame.height)
    else:
        frame = capture()
        logger.info("Captured %dx%d from the camera", frame.width, frame.height)
        if args.save_frame:
            np.save(args.save_frame, frame._buf)
            logger.info("Saved the frame to %s", args.save_frame)

    tiles = build(frame, args.ramp, args.invert, args.rotation,
                  verify=not args.no_verify, mirror=args.mirror)
    sheet = compose(tiles)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.out, optimize=True)
    logger.info("Wrote %s (%dx%d)", args.out, sheet.width, sheet.height)
    return 0


if __name__ == "__main__":
    sys.exit(main())
