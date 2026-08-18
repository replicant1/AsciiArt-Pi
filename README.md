# ASCII Art Live Camera for Raspberry Pi Zero 2

Live view from the Pi Camera Module 2, rendered as ASCII art in a terminal on
the HDMI screen. This is the Python counterpart of the Live Camera pipeline in
the Android ASCII Art app.

![The ASCII Art Camera window running on a Raspberry Pi Zero 2](docs/images/screenshot.png)

*Greyscale, running on the Pi at 15.0 fps in a 120 by 43 window. The status bar
along the bottom reports the frame rate, ASCII grid size, and the current state
of every toggle — rotation, contrast, colour scheme, character ramp,
auto-levels, fill and invert.*

![The same app in the live colour scheme, 133 by 50 characters at 14.9 fps](docs/images/screenshot-colour.png)

*Colour, in a 133x50 window at the full 15 fps. Press `s` to switch, or pass
`--colour` at launch. The character still comes from the brightness, so the two
modes draw the same shapes; the colour comes from the camera's chroma, which
greyscale mode discards. Colour costs roughly three times the redraw, and the
grid is no longer shrunk to hide that — at a full-screen 267x100 the same scene
runs at about 3 fps.*

![The HDMI monitor and the 2.4 inch SPI panel both showing the ASCII camera, with the camera module and breadboard in front](docs/images/both-displays.jpg)

*Both displays at once, with `--lcd`. This is a photograph rather than a screen
capture because it has to be: `grim` records the Wayland/HDMI output, and the
ILI9341 is driven from userspace over SPI with no kernel framebuffer, so nothing
on that panel can be screenshotted. On the monitor is a 67 by 25 grid with the
fine ramp — `sch:grey chr:fine` on the status bar — and the 2.4 inch panel at
bottom right is rendering the same camera frames on its own 64 by 24 grid. The
camera module is on the stand in the middle, wired back to the Pi through the
breadboard.*

Three hardware guides go with this code, published at
**[replicant1.github.io/AsciiArt-Pi](https://replicant1.github.io/AsciiArt-Pi/)**.
Read them there rather than in this repo: GitHub shows HTML as source, and its
raw view serves these as `text/plain`, so neither renders the drawings.

- **[Choosing a display](https://replicant1.github.io/AsciiArt-Pi/display-selection-guide.html)**
  — a ranked guide to running this on something other than an HDMI monitor:
  vintage terminals, VFDs, graphic LCDs and OLED modules, priced in AUD and
  sourced for a buyer in Sydney.
- **[From breadboard to enclosure](https://replicant1.github.io/AsciiArt-Pi/enclosure-build-guide.html)**
  — the rebuild into a self-contained, mains-powered box: a soldered perfboard
  HAT that replaces every friction-fit joint, a pin-by-pin cut list for the
  panel, encoder and shutdown-button harnesses, a measured power budget, and the
  enclosure cutouts.
- **[Panel connectors and controls](https://replicant1.github.io/AsciiArt-Pi/panel-connectors-guide.html)**
  — section drawings and specs for the three things that have to cross the
  enclosure wall: video out, power in and the shutdown button.

Each is a single self-contained page with no scripts or external assets, so
saving one to disk works as well as reading it online.

Alongside them is a gallery, **[The enclosure,
rendered](https://replicant1.github.io/AsciiArt-Pi/enclosure-renders.html)** —
four raytraced views of the sloped console those guides arrive at, built from
their stated dimensions rather than sketched to look right.

[![The enclosure, rendered: a grey 3D-printed sloped console seen from the low southern side, with a lit amber ASCII panel on the sloped face, a knurled metal encoder knob above it and a red illuminated button below it](docs/images/enclosure-hero-thumb.png)](https://replicant1.github.io/AsciiArt-Pi/enclosure-renders.html)

*Not yet built — this is a render of a design on paper, not a photograph. The
geometry comes from the connectors guide: 92 by 105 mm, 62 mm tall at the north
and 25 at the south, a 19° fascia, and a parting plane at z = 25 mm that halves
both connectors so a printed pocket can capture them. Encoder at the high north
end, panel in the middle, shutdown button nearest the hand.
[Three more views, and what is spec versus what is
invented](https://replicant1.github.io/AsciiArt-Pi/enclosure-renders.html).*


## Where everything is

This page is the front door. Each subject below is one document, and each is
short enough to read in a sitting — which the 2,369-line README this replaced
was not.

**Start here, in this order.** Three documents explain the machine:

1. **[Module map](docs/module-map.md)** — every file in the app, what it is
   for, one line each. Generated from the code, so it cannot go stale. Its
   companion, the **[class map](docs/class-map.md)**, answers the question one
   level down: what the *things* are, and which of them run on their own thread.
2. **[Architecture](docs/architecture.md)** — how a frame becomes characters,
   how a setting reaches both displays, and why there is exactly one way in.
3. **[Telling it what to do](docs/subsystems/language.md)** — the control surface: typed
   settings, natural language, the phone page, and what happens when any of it
   fails.

**Then whatever you need:**

| Document | What is in it |
|---|---|
| [Using it](docs/using-it.md) | Running it, the live keys, every command-line argument, logging, troubleshooting |
| [Telling it what to do](docs/subsystems/language.md) | Typed settings, `ask`, the shortcut table, the phone page, honest failure |
| [Architecture](docs/architecture.md) | The pipeline, `RenderConfig`, the classes, start-up, the main loop |
| [Module map](docs/module-map.md) | Every module and what it is for — generated |
| [Class map](docs/class-map.md) | Every class, what it inherits and how much surface it has — generated |
| [Colour schemes](docs/subsystems/colour-schemes.md) | The nine schemes, how one is drawn, what it costs |
| [The SPI panel](docs/subsystems/panel.md) | The ILI9341, wiring, why it cannot be verified in software, rotation |
| [The rotary encoder](docs/subsystems/encoder.md) | The KY-040 knob, quadrature decoding, the button |
| [Performance](docs/project/performance.md) | Measured frame rates, where the time goes, window sizing |
| [Running it at boot](docs/project/deployment.md) | The systemd services, boot timing, the enclosure |
| [How this is built](docs/project/workflow.md) | Agent on the Mac, app on the Pi, and syncing between them |
| [What the model is told](docs/subsystems/what-the-model-is-told.md) | The system prompt and tool schema, and the eval cases |

`docs/` is arranged the same way as the code:

```
docs/using-it.md          the documents the front page sends you to first
docs/architecture.md
docs/module-map.md        generated
docs/class-map.md         generated
docs/subsystems/          one per part of the machine: panel, encoder,
                          language, colour schemes, what the model is told
docs/project/             performance, running it at boot, how this is built
docs/images/              every screenshot and render
docs/*.html               the published hardware guides - these are public
                          URLs at replicant1.github.io/AsciiArt-Pi/, so their
                          names stay put
```

Three hardware guides are published separately as HTML — see the links above.

## The app in one screen

`src/` is six packages, one per subsystem, and `tests/` and `tools/` mirror
them — so "where does this live" and "where are its tests" are answered by
looking rather than by grepping.

```
ascii_camera.py          the process, the render loop, the wiring
src/capture/             camera.py            frames off the Pi Camera Module 2
                         image_processor.py   rotate, crop, resize, levels
src/art/                 ascii_art.py         brightness -> characters
                         palettes.py          the nine colour schemes
                         window_plan.py       a terminal geometry that fits
src/screen/              display.py           ncurses on the HDMI monitor
                         headless.py          the stand-in when there is none
src/panel/               lcd.py               ILI9341 over SPI, RGB565
                         lcd_display.py       the character grid, as pixels
                         lcd_worker.py        its own thread, so SPI never stalls
                         lcd_splash.py        the start-up screen
src/control/             render_config.py     every live setting, one typed object
                         commands.py          typed lines -> settings deltas
                         command_server.py    the Unix socket the CLI talks to
                         web_server.py        the phone page, LAN only
                         encoder.py           the knob
src/language/            parser.py            words -> a validated delta, via a model
                         shortcuts.py         the words that need no model
                         asklog.py            every request written down
```

Each package's `__init__.py` says in one line what the subsystem is for, and
that is where the architecture is stated — the module map reads it rather than
keeping a second copy.

Line counts and the full summaries are in the **[module
map](docs/module-map.md)**, which is generated by `tools/docs/module_map.py` and
guarded by `tests/docs/module_map_test.py` — so it describes the code that is
actually there, not the code that was there when somebody last wrote it down.

## Requirements

Everything needed is already present in Raspberry Pi OS Bookworm:
`python3-picamera2`, `python3-numpy`, `python3-pil`, and `curses` from the
standard library. `bash deploy/setup.sh` verifies this and installs anything missing.

Prefer the apt packages over pip — building numpy or Pillow from source on a
Zero 2 exhausts its ~416 MB of RAM.


## Differences from the Android implementation

| Aspect | Android | Raspberry Pi |
|--------|---------|--------------|
| Language | Kotlin | Python |
| Camera API | CameraX | picamera2 |
| Concurrency | Coroutines | Threads, one-frame queue |
| Display | Jetpack Compose | curses |
| Frame rate | 30 fps | 15 fps default, 30 fps achievable |
| Input | Touch, live camera + video file | Keyboard, live camera |
