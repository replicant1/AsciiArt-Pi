# Using it

## Running it

```bash
bash run_ascii_camera.sh fit            # biggest window the picture fills exactly
bash run_ascii_camera.sh 120            # 120 columns, rows chosen to match
bash run_ascii_camera.sh 80x80          # exactly 80x80 (picture is letterboxed)
bash run_ascii_camera.sh 80x80 --fill   # 80x80, cropped to fill the window
bash run_ascii_camera.sh fit --colour   # start in colour (or press s)
bash run_ascii_camera.sh 120 --fps 10 --rotation 0
python3 ascii_camera.py                 # in the terminal you are already in
python3 ascii_camera.py --help          # all options
```

`run_ascii_camera.sh` exists because launching over SSH needs the desktop's
Wayland environment, because lxterminal takes its font size from a config file
rather than the command line, and because the window shape that avoids
letterboxing depends on the font — see "Window sizing" below.

### Live controls

Click the window first so it has keyboard focus.

| Key   | Effect | Shown in status bar as |
|-------|--------|------------------------|
| `q`   | Quit | — |
| `r`   | Rotate 90 degrees | `rot180` |
| `f`   | Toggle fill (crop to fill the window) vs fit (whole field of view) | `fill:on` / `fill:off` |
| `i`   | Invert the character ramp | `inv:on` / `inv:off` |
| `c`   | Cycle character ramp: coarse / fine | `chr:coarse` |
| `s`   | Cycle colour scheme: grey / live / green / amber / cyan / navy / azure / lime / paper | `sch:grey` / `sch:green` |
| `+` `-` | Contrast | `con1.0` |
| `a`   | Toggle per-frame auto-levels | `auto:on` / `auto:off` |
| space | Freeze the picture on the last frame, and unfreeze it | `frozen` in place of the frame rate |
| `t`   | Move the picture between the outputs: both / terminal / panel | `tgt:both` / `tgt:lcd` |
| `l`   | Cycle the panel's glyph size: 8 / 9 / 6 | `lcd:64x24@8` |

Space rather than a letter for freeze: every other binding is the first letter
of what it does, and `f` was already fill.

Freezing does not stop the camera — unfreezing would then cost the 15–20
seconds libcamera takes to come back — and it does not stop the settings
working. A frozen picture can be recoloured, inverted and rotated while you
look at it, which is easier than chasing a moving one. Nothing is redrawn while
it sits there unchanged, so a frozen app is close to idle.

`t` skips any output this run does not have, rather than appearing dead: with
no panel attached it steps between `both` and `terminal` only. Asking for an
output that would show the picture to nobody is refused and says so in the
status bar.

### Command-line arguments

| Argument | Values | Default | Effect |
|---|---|---|---|
| `-h`, `--help` | — | — | Print usage and exit |
| `--width` | integer | `320` | Camera capture width. The ISP downscales in hardware, so smaller is much cheaper than resizing on the CPU |
| `--height` | integer | `240` | Camera capture height |
| `--fps` | integer | `15` | Target frame rate. The sensor is capped to this, which saves real CPU |
| `--scheme` | `grey`, `live`, `green`, `amber`, `cyan`, `navy`, `azure`, `lime`, `paper` | `grey` | Colour scheme to start in. Step through them live with `s`. See [Colour schemes](colour-schemes.md#colour-schemes) |
| `--colour`, `--color` | flag | off | Shorthand for `--scheme live`. Ignored if `--scheme` is given |
| `--colour-levels` | 2–32 | `32` | Steps per channel in the live-colour scheme. Fewer gives longer runs of one colour and a cheaper redraw, at the cost of banding. Applies to both displays: the terminal quantises to that many steps of the xterm cube, the panel posterises its RGB to the same number. `32` means “as many colours as this display can manage” and leaves the panel at full RGB565. Out of range is clamped |
| `--fill` | flag | off | Crop the picture to fill the window rather than letterboxing it. Toggle with `f` |
| `--rotation` | 0, 90, 180, 270 | `0` | Camera rotation. Cycle with `r`. See [Rotation and handedness](panel.md#rotation-and-handedness) |
| `--mirror` | flag | off | Flip the picture left to right, after any rotation |
| `--contrast` | float | `1.0` | Contrast multiplier about mid-grey. Adjust with `+`/`-` |
| `--no-auto-levels` | flag | off | Disable per-frame brightness normalisation. Toggle with `a` |
| `--ramp` | `coarse`, `fine` | `coarse` | Character ramp, ordered light to dark. Cycle with `c` |
| `--invert` | flag | off | Invert the ramp, for light-background terminals and positive-mode LCDs. Toggle with `i` |
| `--cell-aspect` | float | `2.0` | Terminal character height/width ratio, which keeps the picture from looking squashed |
| `--no-terminal` | flag | off | Draw nothing on the HDMI screen: no curses, no window. Needs `--lcd`. Keys still work when stdin is a terminal, as it is over SSH |
| `--lcd` | flag | off | Also render to the ILI9341 SPI panel, alongside the terminal. See [The ILI9341 SPI panel](panel.md#the-ili9341-spi-panel) |
| `--lcd-font-size` | 4-16 | `8` | Glyph size, which sets the panel's grid. `8` gives 64x24; `6` gives 80x30 and `9` gives 64x20. All three tile 320x240 exactly and match the camera's 4:3, and `l` steps through those three live. Other sizes are accepted and leave a black margin |
| `--lcd-portrait` | flag | off | Run the panel as 240x320 instead of 320x240 |
| `--lcd-spi-hz` | integer | `40000000` | SPI clock. Lower it if the wiring is long or on a breadboard |
| `--lcd-brightness` | 0–100 | `100` | Backlight duty cycle, driven as PWM |
| `--lcd-splash-seconds` | float | `3.0` | How long the start-up screen stays up once the camera is ready. `0` hands over the moment there is a picture. See [The start-up screen](panel.md#the-start-up-screen) |
| `--version` | flag | — | Print `ascii_camera <version>` and exit |
| `--encoder` | flag | off | Cycle colour schemes with a KY-040 rotary encoder. See [The rotary encoder](encoder.md#the-rotary-encoder) |
| `--encoder-clk` | integer | `19` | BCM pin for the encoder's CLK |
| `--encoder-dt` | integer | `26` | BCM pin for the encoder's DT |
| `--encoder-sw` | integer | `6` | BCM pin for the push switch, which jumps back to `grey`. Negative if the switch is not wired; harmless to leave set either way, since an unwired pin idles high and stays quiet |
| `--encoder-reverse` | flag | off | Swap which way the knob steps, if it runs backwards |
| `--log` | path | `ascii_camera.log` beside the app | Log file. stderr is redirected here too, since nothing may reach the terminal while curses owns the screen |
| `--verbose` | flag | off | Debug-level logging |

Two things the table does not show on its own.

**Eight of these arguments have live equivalents** — `--fill`, `--rotation`,
`--contrast`, `--no-auto-levels`, `--ramp`, `--invert`, `--scheme` and
`--colour`, reachable as `f`, `r`, `+`/`-`, `a`, `c`, `i` and `s` — so those
flags mostly just set a starting state. The arguments fixed at startup are
`--width`, `--height`, `--fps`, `--log`, `--verbose`, the five `--lcd*`
arguments, and the four `--encoder*` arguments. `--colour-levels` is no longer
among them — like everything else in `RenderConfig` it can be set live, by name,
from `tools/asciicam_cli.py`.

**`run_ascii_camera.sh` supplies one of these arguments for you.** The launcher
always passes `--cell-aspect`, computed from real Pango font metrics for the
font the launcher chose. Anything given to the launcher after the geometry is
forwarded through, so `bash run_ascii_camera.sh 120 --fps 10 --rotation 0` works
as expected. It does nothing special for `--colour` — the window is planned the
same way whatever scheme you start in.

## Logging

**Nothing is ever written to the terminal while the app is running.** curses
owns the screen, and a single stray line garbles the picture. All Python
logging goes to `ascii_camera.log`, and file descriptor 2 is redirected there
as well, which also captures libcamera's C++ layer — it logs straight to stderr
and never passes through Python's logging at all.

If the app appears to do nothing, read `ascii_camera.log`.

## Troubleshooting

**No camera detected** — `python3 tests/capture/capture_reference.py` will say so;
check the CSI ribbon cable.

**Camera busy** — only one process can open it. Stop any other instance:
`pkill -f '[a]scii_camera.py'` (the bracket stops the pattern matching the
`pkill` command itself, which over SSH would kill the session).

**Picture is flat or washed out** — `a` toggles auto-levels, `+`/`-` adjust
contrast. Auto-levels stretches each frame's own 2nd–98th percentile range to
full black-to-white, which matters indoors where raw camera luma often spans
only a fraction of the range.

**Window is the wrong size** — check the `Terminal size:` line in
`ascii_camera.log` for what the app actually got, and override the font with
`ASCII_FONT=6 bash run_ascii_camera.sh 100x100`.
