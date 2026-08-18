## Performance

Measured on this Pi Zero 2 (`python3 tests/bench_pipeline.py`):

| Capture size | Target | Actual |
|--------------|--------|--------|
| 320x240 | 12 | 12.0 fps |
| 320x240 | 20 | 20.0 fps |
| 320x240 | 30 | 29.9 fps |
| 640x480 | 30 | 29.9 fps |

It hits whatever rate is asked for, up to the sensor's 30 fps, with load
average below 1.0. The processing stage costs about **8 ms per frame**, so the
Zero 2 is not the bottleneck. The default of 15 fps is a deliberate compromise
that leaves the desktop responsive; raise it with `--fps` if you want.

This is well above the 8–12 fps originally predicted, for three reasons:

1. **The Y plane is used directly as greyscale.** YUV420's Y plane *is*
   luminance — it is by definition what `0.299R + 0.587G + 0.114B` computes.
   Converting YUV → RGB and then back to grey costs six full-resolution float
   array operations per frame to recover a number the camera already handed us.
2. **Brightness → character is a vectorised lookup table.** A nested Python
   loop over pixels costs one interpreter round trip per character; a 256-entry
   LUT plus one numpy fancy-index does the whole grid at C speed.
3. **The ISP does the downscaling.** Capturing at 320x240 rather than 640x480
   and scaling on the CPU moves the work to hardware that is already in the
   path. Set `--width/--height` higher if you want more detail.

Resizing uses PIL's `BOX` filter (area averaging) rather than `LANCZOS`: each
ASCII cell should hold the *mean* brightness of the region it covers, which is
exactly what area averaging computes, and it is faster besides.

### The live colour scheme

`s` steps through the colour schemes; this section is about `live`, the one that
takes its colour from the camera's chroma, with the character still coming from
the luma so the two agree. The other schemes are described under
[Colour schemes](colour-schemes.md#colour-schemes); they cost less than `live` does, because
their colours repeat along a row.

Measured in lxterminal on this Pi, redrawing the same scene with and without
per-character colour:

| Grid | Greyscale | Colour | Cost |
|------|-----------|--------|------|
| 267x100 | 91 ms (11.0 fps) | 244 ms (4.1 fps) | 2.7x |
| 133x50 | 32 ms (31.6 fps) | 61 ms (16.3 fps) | 1.9x |
| 80x30 | 6 ms (169 fps) | 28 ms (35 fps) | 4.8x |

**That cost is now simply paid.** The grid follows the window and the camera,
and nothing else — switching scheme with `s` never resizes the picture, and
`--colour` gets no special window sizing at launch. Colour in a full-screen
267x100 window therefore runs at about **3 fps** — measured on the Pi at 3.3,
3.4, 3.5, 2.5 and 3.0 — and that is the intended behaviour rather than a
regression. The table above is a synthetic render benchmark; the live app is
slightly slower again, since it is also capturing and driving curses.

This used to work the other way. The app halved the grid on both axes whenever
the `live` scheme was on, and the launcher halved the planned window to match so
the smaller grid still filled it. It held 15 fps, but at the price of the
picture changing size underneath you when you pressed `s`, a resolution that
depended on which scheme you happened to be in, and two different notions of
"the grid" that had to be kept in step. A steady picture that slows down is
easier to reason about than a fast one that changes shape.

If you want colour *and* frame rate, ask for a smaller window rather than
relying on the app to shrink one for you — the grid is yours to choose:

```bash
bash run_ascii_camera.sh 133 --colour     # 133x51, colour, back to about 15 fps
bash run_ascii_camera.sh fit --colour     # full window, colour, about 4 fps
```

`--colour-levels` is the other lever, and it does not touch the grid: fewer
palette steps mean longer runs of one colour and a cheaper redraw, at the cost
of banding.

Two things make it affordable:

1. **The conversion happens after the downscale.** Chroma is resampled to the
   character grid first, then converted, so at 133x50 that is about 6,650 pixels
   of arithmetic per frame instead of 76,800 at full resolution. Doing it the
   other way round was the most expensive thing in the original pipeline, and is
   why greyscale mode takes the luma plane directly.
2. **Cells sharing a colour are drawn as one run.** One `addstr` per run rather
   than per character, so ncurses emits a single escape sequence for each. A
   real scene averages a dozen or so runs per row at this grid size.

`--colour-levels` (2 to 32, default 32) sets how many steps per channel the
live-colour scheme uses. Fewer means longer runs of one colour and a cheaper
redraw, at the cost of banding — the main lever if colour feels slow.

**The two displays reach that number differently, and their ceilings differ.**
The terminal picks that many steps from the xterm-256 cube, which has only six
per axis, so it saturates at 6 whatever is asked for. The panel draws RGB
directly and has no palette to quantise against, so `AsciiArt.posterise` snaps
each channel to that many *even* steps — even rather than the cube's uneven
axis, which exists only to match a palette the panel does not have.

The cap used to be 6, which was xterm's limit imposed on a display that does
not share it. Measured on one frame, the band it hid is the interesting one:

| `--colour-levels` | 2 | 4 | 8 | 16 | 32 |
|---|---|---|---|---|---|
| Colours on the panel | 4 | 8 | 18 | 40 | 306 |

The maximum is a sentinel rather than a count: it returns the frame untouched,
so the default costs nothing and looks exactly as it always did.

Terminal support was checked rather than assumed: inside lxterminal, curses
reports `TERM=xterm-256color`, 256 colours and 65,536 pairs, so the 240 pairs
this uses are nowhere near a limit. If a terminal cannot manage 256 colours,
`s` skips every scheme but `grey` and logs the fact.

Greyscale mode costs nothing for the feature — the chroma planes are sliced from
the buffer that already had to be copied, and no conversion runs.

### The character ramp costs frame rate

At the full 267x100 grid, `c` (cycle ramp) is not free:

| Ramp | Chars | Observed |
|------|-------|----------|
| `coarse` | 10 | 15.1 fps |
| `fine` | 70 | 6.5 fps |

This is **terminal I/O, not the pipeline** — generating the text costs 1.3 ms
either way. With a 10-character ramp, large areas of the picture map to the
same character between frames and ncurses only redraws what changed; with 70
characters, nearly every cell differs every frame and the whole screen is
rewritten. Use a smaller grid or the coarse ramp if you want the frame rate.

A ramp may contain non-ASCII glyphs. Neither of the two does today, but the
fast path for them is kept because adding one back would otherwise be
expensive: mapping such a ramp with the obvious
`"".join(chr(c) for c in row)` costs 40 ms per frame at this grid size, more
than the entire rest of the pipeline. It instead uses a numpy `U1` table whose
buffer decodes directly as UTF-32-LE, which brings it to 4.3 ms.

There used to be a third built-in ramp, `blocks` — `coarse` plus `▓` and `█`.
It was removed. Its appeal was contrast rather than detail: those two glyphs
were the only ones in the project that came near a filled cell, reaching an ink
coverage of 227 out of 255 where `coarse` tops out at 71.

## Window sizing and aspect ratio

A terminal character cell is roughly twice as tall as it is wide, so the ASCII
grid must be about **half as tall in cells as the picture is in pixels** or the
scene comes out stretched.

An 80x80 *character* window is therefore a tall portrait shape on screen —
about 80 wide by 160 tall in pixel terms. A 4:3 camera image fitted into it
occupies only ~80x30 cells, which is why most of an 80x80 window is blank.

There are three ways to get rid of the letterboxing:

| | Field of view | Fills window |
|---|---|---|
| `bash run_ascii_camera.sh fit` | whole | yes |
| `bash run_ascii_camera.sh 120` | whole | yes |
| `--fill`, or the `f` key | cropped | yes |

`fit` and a bare column count both **shape the window to the picture** rather
than the picture to the window, so nothing is cropped and nothing is blank.
On this Pi's 2048x1080 screen, `fit` gives 267x101 characters at Monospace 6.

### Why the window planner exists

The picture fills the window exactly when

```
cols / canvas_rows == camera_aspect * cell_aspect
```

Assuming `cell_aspect` is 2.0 is close but wrong, and it is not even constant —
font hinting changes it with size:

| Font | Cell | cell_aspect |
|------|------|-------------|
| Monospace 6 | 5x10 px | 2.000 |
| Monospace 7 | 6x11 px | 1.833 |
| Monospace 8 | 6x13 px | 2.167 |
| Monospace 10 | 8x17 px | 2.125 |

So `src/window_plan.py` reads the real cell metrics from **Pango** — the same
font machinery VTE uses to lay out lxterminal — and sizes the window and font
to match. Checked against a screenshot: predicted 6.000x11.000 px, measured
6.025x11.165. The launcher passes the matching `--cell-aspect` to the app, so
the picture is correctly proportioned as well as unletterboxed.

At runtime the app also asks the terminal directly, via the pixel fields of
`TIOCGWINSZ` (`display.cell_metrics()`). When a terminal fills those in, the
cell aspect is derived exactly rather than assumed, and it is re-read on every
resize — so it stays correct even if the font size changes underneath.
lxterminal/VTE reports `0x0` there (measured), so on this Pi it falls back to
`--cell-aspect`; foot, kitty and xterm do report real values.

### Note on scaling the characters live

There is currently no way to change glyph size from inside lxterminal:

- VTE ignores `OSC 50` and `OSC 710`, the two "set font" escape sequences —
  they are echoed back as literal text, so an app cannot resize its own glyphs.
- lxterminal 0.4.1's own Edit > Zoom In/Out does nothing on this build.
  Measured cell width was 4.836 px both before and after, with the grid and
  window unchanged. `Shift+Ctrl+plus` likewise. (Not a testing artifact:
  Ctrl-modified keys do reach applications in that terminal.)

True glyph scaling therefore needs a different terminal (`foot` supports live
font-size changes and has `resize-by-cells=no`, which keeps the window size and
re-flows the grid) or a relaunch. A relaunch costs ~10-13 s, dominated by
picamera2: 5.4 s to import, 8.1 s from camera open to first frame.

### The lxterminal profile

`run_ascii_camera.sh` writes its own profile to
`~/.config/lxterminal/lxterminal-asciicam.conf`, so your normal terminal
settings are untouched. Two traps are worth recording:

- lxterminal 0.4.1 looks for `lxterminal-<NAME>.conf`, **not** `<NAME>.conf`,
  and silently falls back to the default profile when the name is wrong.
- Without a small enough font, lxterminal quietly clamps the window instead of
  honouring `--geometry`: an 80-row request became 57 rows at "Monospace 10"
  on a 1080px screen. Check the `Terminal size:` line in the log for what the
  app actually got.
