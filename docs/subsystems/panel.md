## The ILI9341 SPI panel

A 2.4 inch 240x320 ILI9341 LCD, 65K colours over SPI, runs **alongside** the
terminal on the HDMI screen rather than instead of it:

```bash
bash run_ascii_camera.sh fit --lcd
bash run_ascii_camera.sh fit --lcd --scheme amber
```

The panel shows only the picture — no status bar, no border, no window
furniture.

### The start-up screen

Between the panel coming up and the first camera frame arriving, there is
nothing to draw. A black panel in that gap is indistinguishable from a panel
that is not working, which matters here more than it looks: **nothing can
screenshot this display** (see below), so "is it alive?" is otherwise
unanswerable until a picture appears. So the panel shows its own start-up
screen — the app name, what it is currently waiting on, an activity bar, the
character grid it has chosen, and the version.

It is drawn in the colours of the scheme you launched with, so `--scheme amber`
comes up amber. The activity bar is a comet of ramp characters sweeping left to
right rather than a percentage: nothing in the app knows how long libcamera will
take, and a bar claiming 60% while guessing is worse than one that only shows it
is alive.

**The gap it covers is about 1.4 seconds**, measured on this Pi — LCD ready to
first frame. That is worth stating because `docs/guides/enclosure-build-guide.html`
quotes 15–20 seconds for libcamera; that figure is from the Qt `camera_preview`
program, not this one. A second and a half is too short to read anything, so the
screen is held for `--lcd-splash-seconds` (3 by default) after frames start
arriving, and camera frames are dropped until it expires. Pass `0` to hand over
as soon as there is a picture.

The animation is driven by the LCD worker's existing idle timeout rather than a
thread of its own, and it stops by construction once the first frame is drawn.
The comet advances three cells per redraw rather than one: a full panel write is
about 33 ms, so speed has to come from distance per frame rather than frames per
second, and the step is kept below the tail length so consecutive frames still
overlap.

`tests/panel/lcd_splash_test.py` checks the layout, colours and the hold without any
hardware, and `--panel` puts it on the real glass and holds it there, since a
clean test run is not evidence that anything was lit.

**The panel comes up dark on purpose.** `ILI9341.__init__` starts the backlight
PWM at 0 and the caller turns it on once there is something worth seeing:
lighting an uninitialised panel shows a bright flash of undefined frame memory
for the ~200 ms that `init()` and the first `fill()` take. `LcdDisplay` blanks
and then lights, in that order. Anything constructing `ILI9341` directly has to
call `backlight()` itself — `tests/panel/lcd_selftest.py` does, and without it that
test runs on a dark panel and looks exactly like dead hardware.

### Version

`src/version.py` is the one place the version is written down, and it is
deliberately a module with no imports so that argparse and the LCD worker can
both read it without loading numpy, PIL or the camera. It is **not** derived
from git: the copy that runs lives on the Pi, which is not a git checkout, so
git would report nothing on the only machine where the number is visible.

```bash
python3 ascii_camera.py --version      # ascii_camera 1.0.0
```

It also appears at the bottom of the start-up screen and on the first line of
every log file.

### Which displays to run

The two outputs are independent, so there are four combinations and three of
them are useful:

| Terminal | Panel | How | Notes |
|----------|-------|-----|-------|
| yes | no | `bash run_ascii_camera.sh fit` | The default |
| yes | yes | `bash run_ascii_camera.sh fit --lcd` | Both at once, independently sized |
| no | yes | `python3 ascii_camera.py --lcd --no-terminal` | Headless: no window, no curses |
| no | no | — | Refused, with exit code 2 |

The last row is refused rather than allowed, because it would open the camera,
render frames and show them to nobody — which is indistinguishable from a hang.
The check happens before the log file is even opened, so the complaint lands on
the terminal you are standing at.

Headless mode is the reason the app can run without a desktop session at all.
The launcher script is not used, since there is no window to size or profile to
write; run `ascii_camera.py` directly. A status line goes to stdout every five
seconds instead of being redrawn in place:

```
15.0fps headless rot180 con1.0 sch:amber chr:coarse auto:on fill:off inv:off lcd:64x24
```

`headless` stands where the terminal grid usually reads, and `lcd:64x24` is the
panel's own grid — the only one there is in this mode.

**The single-key controls still work over SSH.** stdin is put in cbreak mode
and polled without blocking, so `s`, `i`, `c` and the rest behave as they do in
the window. When stdin is *not* a terminal — a systemd unit, a cron job, output
piped elsewhere — key reading is disabled and the run uses whatever the command
line asked for. Which it is gets logged either way.

**Stopping it.** With no terminal on stdin there is no `q` to press, so a signal
is the normal way a headless run ends. `SIGTERM` and `SIGINT` are both handled:
the loop is asked to stop, and the camera and panel are released on the way out.
Without that, Python's default `SIGTERM` exits without unwinding, leaving the
panel lit with a frozen frame and its GPIO pins still claimed — which then
breaks the next run.

### Wiring

Taken from the manufacturer's own working example, and confirmed by running it.
`CS` is driven by the SPI peripheral itself, not by this code.

| Panel | Pi | Panel | Pi |
|-------|----|-------|----|
| VCC | 3.3V | SDI/MOSI | GPIO 10 |
| GND | GND | SCK | GPIO 11 |
| CS | GPIO 8 (CE0) | RESET | GPIO 27 |
| DC/RS | GPIO 25 | LED/BL | GPIO 18 (PWM) |

The panel is on `/dev/spidev0.0`. SPI is enabled with `dtparam=spi=on`, and
there is deliberately **no kernel driver bound to it** — no `fbtft`, no
`mipi-dbi-spi` overlay. It is driven from userspace with `spidev`, which is
what `src/panel/lcd.py` does. `/dev/fb0` is the HDMI framebuffer and has nothing to
do with this panel.

### It is an independent display, not a mirror

The panel's grid is fixed by its font, so **resizing the terminal window leaves
it alone**. Observed while testing: the terminal went 267x100 to 133x50 while
the panel stayed 64x24. The status bar shows the panel's own grid as
`lcd:64x24`, which makes the independence visible.

| Setting | Follows the main display? |
|---------|---------------------------|
| Colour scheme (`s`) | Yes |
| Invert (`i`) | Yes |
| Character ramp (`c`) | Yes |
| Rotation (`r`), contrast (`+`/`-`), auto-levels (`a`) | Yes |
| Fill (`f`) | **No** — the panel is always fully occupied |
| Grid size | **No** — fixed by `--lcd-font-size` |

Font sizes 6, 8 and 9 each tile 320x240 exactly *and* give a character grid
whose on-screen aspect is exactly 4:3 — the same as the camera. So filling the
panel crops nothing at all. Other sizes leave a few pixels over, which are left
black with the picture centred in them.

### How it is drawn

Every glyph in the ramp is rendered once into an atlas, and a frame becomes a
single numpy gather: index the atlas with the whole grid at once, then transpose
the cell axes into place and reshape. The obvious alternative — one
`draw.text()` per cell — would be 1,536 PIL calls per frame at 64x24, far beyond
this hardware.

The SPI write is kept off the main render loop by a worker thread that takes the
latest frame and drops anything it falls behind on. That only pays off if
`spidev` releases the GIL during the transfer, which `tests/panel/lcd_concurrency.py`
measures rather than assumes: **the main thread keeps 93% of its throughput**
while the panel renders at 27 fps.

| Stage | Cost per frame |
|-------|----------------|
| Blit glyphs from the atlas | 1.2 ms |
| Pack RGB565 | 2.5 ms |
| SPI transfer | ~32 ms |

The panel is transfer-bound, not CPU-bound. `/sys/module/spidev/parameters/bufsiz`
is 4096, so a full 153,600-byte frame is 38 writes, and that syscall count
dominates rather than the clock rate — `spidev.bufsiz=65536` on the kernel
command line would help if refresh rate ever mattered more than memory.

**Rebuilding the atlas is not a per-frame cost, and is cheap enough not to
matter.** It happens when the ramp changes, when `invert` is toggled, or when
`l` changes the panel's font size — never per frame. Measured over eleven
rebuilds driven from the keyboard: **168 ms for the first, then 13–24 ms**. The
first is the outlier by an order of magnitude, almost certainly because the font
file is read from disk that once and found in the page cache afterwards; that
explanation is inferred from the shape of the numbers rather than measured, but
the numbers themselves are from the log. Either way it is a one-off at start-up,
and a font change mid-run costs about one frame.

The rebuild runs on the worker's own thread, which is what keeps it off the main
loop — the terminal does not stutter when the panel's font changes. It also
zeroes the frame buffer, because a larger font gives a *smaller* picture and
nothing ever writes to the margin it no longer reaches; without that, the old
picture's outer pixels would survive there for good.
`tests/panel/lcd_font_size_test.py` checks exactly that, on the real panel.

### You cannot verify this panel in software

Two facts combine, and they are worth knowing before trying:

- `grim` captures the Wayland/HDMI output. An SPI panel is not part of that
  output, so **no screenshot ever shows what is on the panel.**
- This module does not wire SDO usefully. Register read-back was tried — `0x04`
  RDDID, `0x09` RDDST, `0x0A` power mode, `0x0C` pixel format — and every one
  returns all `00`.

So nothing can confirm what is actually lit except looking at it. The tests are
built accordingly: they check everything up to the SPI boundary with assertions
that can genuinely fail — hand-computed RGB565 values, geometry, and whether the
panel path picks the same glyph the terminal would — and then say plainly that
the rest needs a human.

```bash
python3 tests/panel/lcd_selftest.py       # colour bars and the RGB565 maths
python3 tests/panel/lcd_render_bench.py   # render path correctness and timing
python3 tests/panel/lcd_concurrency.py    # proves the SPI write does not stall the app
```

## Choosing a different display

[**Choosing a display**](https://replicant1.github.io/AsciiArt-Pi/guides/display-selection-guide.html)
is a ranked guide to running this app on something other than an HDMI monitor — vintage
terminals, VFDs, graphic LCDs and OLED modules — priced in AUD and sourced for a buyer in
Sydney.

Each option carries a live sample of the same scene rendered at that display's real character
grid, so the difference between 80x24 and 42x8 is visible rather than asserted.

The finding that matters most is a single ratio:

```
frame kept = camera aspect (4:3) / panel aspect
```

The font decides how many characters you get; the panel's own shape decides how much of the
picture survives. A 256x64 panel is 4:1, so it throws away two thirds of the frame no matter
what font you choose, while a plain 4:3 panel keeps all of it. That one line reorders the
whole list, and it is why a 320x240 graphic LCD beats parts costing five times as much.

**None of these need code changes.** The app fits its grid to whatever the terminal reports,
and `--cell-aspect` handles the rest. The one thing to know is that positive-mode LCDs, which
put dark ink on a pale ground, need the ramp reversed — that is the `i` key.

The guide's own conclusion has since been acted on: the 320x240 graphic LCD it
ranks first is the ILI9341 now wired to this Pi and documented above. It bore
the prediction out — being a true 4:3 panel, it keeps the whole frame, and at
`--lcd-font-size 8` the grid comes out at exactly 4:3 as well, so nothing is
cropped or letterboxed. Driving it *did* need code, but only because it is a
second simultaneous display rather than a terminal the app could fit itself to.

## Rotation and handedness

Two settings between them reach any orientation: `--rotation` (0, 90, 180, 270)
and `--mirror`, a left-to-right flip applied after the rotation. Four rotations
times the flip covers all eight possible orientations, so no third control is
needed.

Both default to off — as currently mounted, this camera delivers the picture
the right way round and the correction is the identity. If yours is mounted
differently, press `r` to cycle rotation live, then make it permanent with
`--rotation`; add `--mirror` if the picture comes out as a mirror image.

That default was arrived at by looking, not by deriving, and it took three
goes. `libcamera` reports this module's mounted rotation as 180 degrees, which
was the original default — but a 180 degree rotation flips *both* axes, so the
picture came out correctly inverted and **silently mirrored**. Adding the
horizontal flip gave a net vertical flip, which was confirmed correct. The
camera was then remounted, and the identity became right.

The lesson worth keeping is that a mirrored picture is very hard to spot: it is
not upside down and not squashed, and on a roughly symmetrical scene it looks
perfectly fine. It shows only on something with a handedness — text, a face, a
hand. `tests/capture/orientation_test.py` therefore checks orientation with a frame of
numbered quadrants, where left and right are distinguishable by construction
rather than by eye.
