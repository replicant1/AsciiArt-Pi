# Module map

Every module in the running app, what it is for, and how big it is.

**Generated - do not edit.** `python3 tools/module_map.py --write`
rebuilds it, and `tests/module_map_test.py` fails if it is stale. Each
summary is that module's own first docstring line, so this page cannot
describe code that is no longer there.

## Entry point

The process itself: argument parsing, the render loop, and the wiring that connects everything below.

| Module | Lines | What it is for |
|---|---:|---|
| `ascii_camera.py` | 1344 | ASCII Art Live Camera Preview for Raspberry Pi Zero 2. |
| `src/version.py` | 19 | The one place the app's version is written down. |

## Capture

Getting frames off the camera and into the right shape.

| Module | Lines | What it is for |
|---|---:|---|
| `src/camera.py` | 193 | Camera capture for the Raspberry Pi Camera Module 2 (imx219). |
| `src/image_processor.py` | 220 | Image processing for ASCII art generation. |

## ASCII

Turning brightness into characters, and characters into colour.

| Module | Lines | What it is for |
|---|---:|---|
| `src/ascii_art.py` | 219 | Brightness -> ASCII character mapping. |
| `src/palettes.py` | 172 | Vintage display colour schemes. |
| `src/window_plan.py` | 123 | Work out a terminal geometry in which the ASCII picture is not letterboxed. |

## Screen

The HDMI terminal, and the stand-in for when there is none.

| Module | Lines | What it is for |
|---|---:|---|
| `src/display.py` | 287 | ncurses terminal rendering for the ASCII art frames. |
| `src/headless.py` | 168 | A stand-in display for when there is no terminal to draw on. |

## Panel

The 2.4 inch ILI9341 over SPI - a second, independent display.

| Module | Lines | What it is for |
|---|---:|---|
| `src/lcd.py` | 273 | ILI9341 2.4" SPI LCD driver (240x320, RGB565). |
| `src/lcd_display.py` | 404 | ASCII picture output on the ILI9341 SPI panel. |
| `src/lcd_worker.py` | 453 | Background thread driving the LCD alongside the terminal display. |
| `src/lcd_splash.py` | 177 | Start-up screen for the ILI9341 panel. |

## Control

Every setting, and every way a human reaches one.

| Module | Lines | What it is for |
|---|---:|---|
| `src/render_config.py` | 310 | Every setting that can change while the camera is running, in one typed object. |
| `src/commands.py` | 244 | Typed commands to RenderConfig deltas. |
| `src/command_server.py` | 286 | A local command channel into the running app. |
| `src/web_server.py` | 699 | A phone, over WiFi, into the same queue a typed line lands in. |
| `src/encoder.py` | 288 | Rotary encoder input: a KY-040 knob on two GPIO pins. |

## Language

Words in, a validated settings change out.

| Module | Lines | What it is for |
|---|---:|---|
| `src/parser.py` | 548 | Natural language in, a validated RenderConfig delta out. |
| `src/shortcuts.py` | 251 | The phrases that do not need a language model. |
| `src/asklog.py` | 229 | A record of every natural-language request, so real use becomes evidence. |

---

21 modules, 6,907 lines.
