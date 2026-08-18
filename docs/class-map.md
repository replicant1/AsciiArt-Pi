# Class map

Every class in the running app: where it lives, what it inherits, how
much surface it has, and what it is for.

**Generated - do not edit.** `python3 tools/docs/class_map.py --write`
rebuilds it, and `tests/docs/class_map_test.py` fails if it is stale.
Each summary is the class's own first docstring line.

`Base` is what the class inherits, or its decorator when that is the
more useful fact - a `@dataclass` and a `NamedTuple` behave nothing
alike, and neither is an ordinary class. `Methods` counts public ones
only, so it reads as surface rather than size.

## Entry point

| Class | In | Base | Methods | What it is for |
|---|---|---|---:|---|
| `AsciiArtLiveCamera` | `ascii_camera.py` | — | 5 | Capture -> process -> ASCII -> terminal, once per frame. |

## Capture

| Class | In | Base | Methods | What it is for |
|---|---|---|---:|---|
| `YuvFrame` | `camera.py` | — | 3 | One YUV420 frame, exposing its planes as views rather than copies. |
| `CameraCapture` | `camera.py` | — | 3 | Captures greyscale frames from the Pi Camera Module 2. |
| `ImageProcessor` | `image_processor.py` | — | 8 | Turns a raw greyscale camera frame into an ASCII-grid-sized array. |

## Art

| Class | In | Base | Methods | What it is for |
|---|---|---|---:|---|
| `AsciiArt` | `ascii_art.py` | — | 4 | Generates ASCII art from a greyscale array. |
| `Scheme` | `palettes.py` | `NamedTuple` | 0 | One display look. |

## Screen

| Class | In | Base | Methods | What it is for |
|---|---|---|---:|---|
| `NcursesDisplay` | `display.py` | — | 9 | Renders ASCII art frames to the terminal. |
| `HeadlessDisplay` | `headless.py` | — | 9 | Draws nothing, but still carries the settings and reads the keyboard. |

## Panel

| Class | In | Base | Methods | What it is for |
|---|---|---|---:|---|
| `ILI9341` | `lcd.py` | — | 8 | Drives the panel over SPI, taking whole frames as PIL images. |
| `GlyphAtlas` | `lcd_display.py` | — | 0 | Every character of a ramp, pre-rendered into a fixed-size cell. |
| `LcdDisplay` | `lcd_display.py` | — | 13 | Draws an ASCII grid onto the ILI9341, filling the panel. |
| `SplashScreen` | `lcd_splash.py` | — | 2 | Renders the start-up screen as a PIL image, ready for the panel. |
| `LcdWorker` | `lcd_worker.py` | `threading.Thread` | 6 | Renders camera frames to the LCD without blocking the main loop. |

## Control

| Class | In | Base | Methods | What it is for |
|---|---|---|---:|---|
| `Ask` | `command_server.py` | `NamedTuple` | 0 | A delta already worked out, on its way to the render loop. |
| `Reply` | `command_server.py` | `NamedTuple` | 0 | A resolver's answer to send straight back, without troubling the loop. |
| `CommandServer` | `command_server.py` | `threading.Thread` | 4 | Accepts typed lines on a Unix socket and queues them for the app. |
| `CommandError` | `commands.py` | `ValueError` | 0 | A line that could not be turned into a delta, with a reason to print. |
| `QuadratureDecoder` | `encoder.py` | — | 1 | Pin levels in, detents out.  No GPIO, no threads, no clock. |
| `RotaryEncoder` | `encoder.py` | — | 4 | A KY-040 on two GPIO pins, read through lgpio's edge callbacks. |
| `ConfigError` | `render_config.py` | `ValueError` | 0 | A delta that could not be applied, carrying every reason rather than one. |
| `Spec` | `render_config.py` | `NamedTuple` | 0 | What one setting accepts, and what it is for. |
| `RenderConfig` | `render_config.py` | `@dataclass` | 4 | The complete live render state. |
| `Forwarder` | `web_server.py` | — | 2 | Sends one line to the app's command socket and returns its reply. |
| `AskLimit` | `web_server.py` | — | 1 | A sliding window over the requests that cost money. |
| `Handler` | `web_server.py` | `BaseHTTPRequestHandler` | 3 | One request. The server instance carries the forwarder and the limit. |
| `WebServer` | `web_server.py` | `ThreadingHTTPServer` | 0 | A LAN-bound listener, IPv4 only, holding the socket path it forwards to. |

## Language

| Class | In | Base | Methods | What it is for |
|---|---|---|---:|---|
| `AskLog` | `asklog.py` | — | 1 | Append-only record of asks, one JSON object per line. |
| `ParseError` | `parser.py` | `RuntimeError` | 0 | The parse could not be completed - network, key, or a refusal. |
| `Parsed` | `parser.py` | — | 1 | What one utterance came back as. |

---

29 classes.
