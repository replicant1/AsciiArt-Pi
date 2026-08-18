#!/usr/bin/env python3
"""
Losslessly recompress the renders.

enclosure_render.py writes every scanline with filter type 0 (None), which is
the simplest thing that is correct but leaves a lot on the table: these images
are mostly smooth gradients, where Sub/Up/Average/Paeth predict a pixel almost
exactly and leave near-zero residuals for zlib to eat.

This re-filters each row adaptively (the standard minimum-sum-of-absolute-
differences heuristic) and recompresses at level 9. Pixels are untouched --
decode both files and they are identical, which is asserted after each write.

    python3 optimise_png.py enclosure-*.png

The second mode makes the half-size copies the README embeds inline, so that
reading the front page does not pull a megabyte per picture. A 2x2 box average
is exactly right here rather than merely adequate: the full-size image was
itself produced by averaging a 2x supersampled render, so halving it again is
the same operation one step further on.

    python3 optimise_png.py --half big.png small.png
"""

import struct
import sys
import zlib


def read_png(path):
    data = open(path, "rb").read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "%s is not a PNG" % path
    pos, idat, hdr = 8, b"", None
    while pos < len(data):
        (ln,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        if tag == b"IHDR":
            hdr = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat += body
        pos += 12 + ln
    w, h, depth, ctype, comp, filt, inter = hdr
    assert (depth, ctype, inter) == (8, 2, 0), "only 8-bit truecolour, uninterlaced"
    raw = zlib.decompress(idat)
    stride = w * 3
    rows = []
    prev = bytearray(stride)
    for y in range(h):
        off = y * (stride + 1)
        ft = raw[off]
        line = bytearray(raw[off + 1:off + 1 + stride])
        rows.append(unfilter(ft, line, prev, 3))
        prev = rows[-1]
    return w, h, rows


def unfilter(ft, line, prev, bpp):
    if ft == 0:
        return line
    for i in range(len(line)):
        a = line[i - bpp] if i >= bpp else 0
        b = prev[i]
        c = prev[i - bpp] if i >= bpp else 0
        if ft == 1:
            line[i] = (line[i] + a) & 0xFF
        elif ft == 2:
            line[i] = (line[i] + b) & 0xFF
        elif ft == 3:
            line[i] = (line[i] + ((a + b) >> 1)) & 0xFF
        elif ft == 4:
            line[i] = (line[i] + paeth(a, b, c)) & 0xFF
        else:
            raise ValueError("bad filter %d" % ft)
    return line


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def filter_row(line, prev, bpp):
    """Try all five filters, keep the one with the smallest absolute sum."""
    n = len(line)
    best, best_score = None, None
    for ft in range(5):
        out = bytearray(n)
        for i in range(n):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            x = line[i]
            if ft == 0:
                out[i] = x
            elif ft == 1:
                out[i] = (x - a) & 0xFF
            elif ft == 2:
                out[i] = (x - b) & 0xFF
            elif ft == 3:
                out[i] = (x - ((a + b) >> 1)) & 0xFF
            else:
                out[i] = (x - paeth(a, b, c)) & 0xFF
        score = sum(v if v < 128 else 256 - v for v in out)
        if best_score is None or score < best_score:
            best, best_score, best_ft = out, score, ft
    return best_ft, best


def write_png(path, w, h, rows):
    body = bytearray()
    prev = bytearray(w * 3)
    for line in rows:
        ft, enc = filter_row(line, prev, 3)
        body.append(ft)
        body += enc
        prev = line
    co = zlib.compressobj(9, zlib.DEFLATED, 15, 9, zlib.Z_FILTERED)
    comp = co.compress(bytes(body)) + co.flush()

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    out = b"\x89PNG\r\n\x1a\n"
    out += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    out += chunk(b"IDAT", comp)
    out += chunk(b"IEND", b"")
    open(path, "wb").write(out)
    return len(out)


def halve(src, dst):
    """Write a 2x2 box-averaged copy. Needs numpy; the rest of this does not."""
    import numpy as np
    import os

    w, h, rows = read_png(src)
    a = np.frombuffer(b"".join(bytes(r) for r in rows), np.uint8)
    a = a.reshape(h, w, 3).astype(np.uint16)
    h2, w2 = h // 2, w // 2
    a = a[:h2 * 2, :w2 * 2].reshape(h2, 2, w2, 2, 3)
    small = ((a.sum(axis=(1, 3)) + 2) // 4).astype(np.uint8)
    out_rows = [bytearray(small[y].tobytes()) for y in range(h2)]
    n = write_png(dst, w2, h2, out_rows)
    print("  %-28s %dx%d %5.0f KB -> %-22s %dx%d %5.0f KB"
          % (os.path.basename(src), w, h, os.path.getsize(src) / 1024,
             os.path.basename(dst), w2, h2, n / 1024))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--half":
        halve(sys.argv[2], sys.argv[3])
        return
    total_before = total_after = 0
    for path in sys.argv[1:]:
        import os
        before = os.path.getsize(path)
        w, h, rows = read_png(path)
        after = write_png(path, w, h, rows)
        w2, h2, rows2 = read_png(path)
        assert (w, h) == (w2, h2) and rows == rows2, "%s changed pixels!" % path
        total_before += before
        total_after += after
        print("  %-28s %7.0f KB -> %7.0f KB  (%.0f%%)  pixels identical"
              % (os.path.basename(path), before / 1024, after / 1024,
                 100.0 * after / before))
    if len(sys.argv) > 2:
        print("  %-28s %7.0f KB -> %7.0f KB  (%.0f%%)"
              % ("TOTAL", total_before / 1024, total_after / 1024,
                 100.0 * total_after / total_before))


if __name__ == "__main__":
    main()
