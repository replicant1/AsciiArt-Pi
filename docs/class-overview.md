# Class overview

Every class in the running app: what it offers, and the one or two
ideas worth carrying away about it. The page is organised around three
diagrams, and each class is described beneath the one it appears in.

**Partly generated.** The diagrams, the headings and the public surface
are read from the source by `python3 tools/docs/class_map.py --write`,
so they cannot drift. The synopses are written by hand in
`tools/docs/class_synopses.py`, because what a class is *for* is a
judgement about the design rather than a fact recoverable from it.
`tests/docs/class_map_test.py` fails if the page is stale, if a class
has no synopsis, or if a synopsis outlives its class.

**Each class heading is a link to the file the class is written in.**
The file rather than the line: a class is what its file is for, so the
line number would add nothing and would go stale on every edit above
it. The scenarios do link to lines, because there the line is most of
what is being pointed at.

**Each class also lists the scenarios that cast it**, read from those
documents' own cast tables rather than from a search for the name - a
scenario that merely mentions a class in passing does not claim it. A
class no scenario has reached yet says so, because a gap in the
coverage is worth seeing.

A synopsis is deliberately not an inventory of the members listed above
it. It is meant to be small enough to hold in mind while reading a
scenario or the architecture.

**A box carries a class's whole public surface** - its fields, its
properties and its methods - so the diagram is where to look for what a
class offers, and the paragraph beneath it is prose rather than a second
copy of the same list. Attributes are the exception: `MainRenderLooper`
assigns nineteen of them to `self`, so only the few that carry meaning
are drawn.

Three kinds of arrow, told apart by their shaft and their head:

| Arrow | Means |
|---|---|
| Solid shaft, hollow triangle | **Inheritance.** The triangle points at the base class, which is drawn above its subclasses. |
| Solid shaft, filled diamond | **Composition.** The class builds the part itself and holds it, so the part cannot outlive the whole. The diamond sits at the owner. |
| Solid shaft, hollow diamond | **Aggregation.** The class holds a part it did not build, which could outlive it. |
| Dotted shaft, open arrowhead | **Dependency.** The class mentions another without keeping it - raising it, returning it, or building it and handing it straight on. |

`MainRenderLooper` shows the contrast worth having. It **builds and**
**owns** the camera and the image processor, so those are diamonds; it
merely **names** `LcdWorker`, so that one is dotted.

No hollow diamonds appear on any of the three diagrams, and that is a
fact about the derivation rather than about the app. Aggregation here
means a part handed in as a constructor argument, and a class never
names the type of what it is given - so those relationships are
invisible to a parser and are left to the scenarios to draw.

All three are read from the source, so none of them can drift. A
collaborator that arrives as a constructor argument has no arrow at all,
because the class never names its type - `MainRenderLooper` is handed a
display and never says which kind. Those are the edges a scenario draws.

## The frame's path

Everything one camera frame passes through, from the sensor to the glass.
The densest part of the app, and the only part that runs on every frame.

```mermaid
---
config:
  layout: elk
---
classDiagram
    direction TB

    class NamedTuple {
        <<external>>
    }
    class threading.Thread {
        <<external>>
    }

    class MainRenderLooper {
        +config
        +terminal_on
        +lcd_on
        +scheme
        +apply()
        +run()
    }
    class CameraCapture {
        +frame_queue
        +start()
        +get_frame()
        +stop()
    }
    class YuvFrame {
        +shape
        +luma
        +chroma
    }
    class ImageProcessor {
        +rotate()
        +crop_to_aspect()
        +resize()
        +adjust_levels()
        +process()
        +to_grid()
        +colour_grid()
        +source_size()
    }
    class AsciiArt {
        +index_lut
        +to_colour_indices()
        +posterise()
        +to_indices()
        +to_ascii_text()
    }
    class Scheme {
        +str name
        +str kind
        +tuple ink
        +tuple screen
        +str note
    }
    class LcdWorker {
        +splash()
        +notice()
        +submit()
        +blank()
        +run()
        +stop()
    }
    class SplashScreen {
        +bar_text()
        +render()
    }
    class LcdDisplay {
        +band_height
        +grid_size
        +cell_aspect
        +panel_size
        +set_ramp()
        +set_font_size()
        +notice_mask()
        +show_notice()
        +clear_notice()
        +render()
        +show_image()
        +clear()
        +close()
    }
    class GlyphAtlas {
        +cell_h
        +cell_w
        +tiles
    }
    class ILI9341 {
        +height
        +width
        +reset()
        +init()
        +set_window()
        +fill()
        +show_packed()
        +show()
        +backlight()
        +close()
    }
    class NcursesDisplay {
        +scheme
        +canvas_size
        +set_scheme()
        +cell_metrics()
        +refresh_size()
        +clear()
        +render()
        +get_key()
        +close()
        +message()
    }
    class HeadlessDisplay {
        +scheme
        +canvas_size
        +get_key()
        +close()
        +set_scheme()
        +cell_metrics()
        +refresh_size()
        +clear()
        +render()
        +message()
    }

    NamedTuple <|-- Scheme
    threading.Thread <|-- LcdWorker
    MainRenderLooper *-- AsciiArt
    MainRenderLooper *-- CameraCapture
    MainRenderLooper *-- ImageProcessor
    MainRenderLooper *-- LcdWorker
    LcdWorker *-- AsciiArt
    LcdWorker *-- ImageProcessor
    LcdWorker *-- SplashScreen
    LcdDisplay *-- GlyphAtlas
    LcdDisplay *-- ILI9341
    MainRenderLooper ..> LcdDisplay
    CameraCapture ..> YuvFrame
```

**Fig 1: The frame's path**

### The classes in this diagram

#### [`AsciiArt`](../src/art/ascii_art.py)

*ascii_art.py* — Generates ASCII art from a greyscale array.

Turns brightness into characters using a table built once, rather than a
calculation repeated for every cell. The same table answers two questions.
The terminal asks for a character, and the panel asks for a position in the
ramp, because it draws its glyphs from an atlas. Deriving both from one
table is what stops the two displays disagreeing about which character a
brightness deserves.

**Cast in these scenarios:**

- [Pixel brightness is mapped to ramp characters](scenarios/pixel-brightness-is-mapped-to-ramp-characters.md)
- [The chroma planes give each character cell its colour](scenarios/the-chroma-planes-give-each-character-cell-its-colour.md)

#### [`CameraCapture`](../src/capture/camera.py)

*camera.py* — Captures greyscale frames from the Pi Camera Module 2.

Owns the camera and the thread that reads it, and keeps only the newest
frame in a queue one item deep. When the render loop falls behind it
therefore loses frames rather than falling behind reality. The camera's
timing also stays its own, and never comes to depend on how expensive the
current colour scheme is.

**Cast in these scenarios:**

- [A camera that stopped delivering frames is detected and announced](scenarios/a-camera-that-stopped-delivering-frames-is-detected-and-announced.md)
- [A capture thread hands the render loop its newest frame through a one-slot queue](scenarios/a-capture-thread-hands-the-render-loop-its-newest-frame-through-a-one-slot-queue.md)
- [One YUV420 capture carries greyscale and colour without converting either](scenarios/one-yuv420-capture-carries-greyscale-and-colour-without-converting-either.md)
- [The camera, panel, encoder and socket are released on shutdown](scenarios/the-camera-panel-encoder-and-socket-are-released-on-shutdown.md)

#### [`GlyphAtlas`](../src/lcd/lcd_display.py)

*lcd_display.py* — Every character of a ramp, pre-rendered into a fixed-size cell.

Holds every character of a ramp, rasterised once into a tile of fixed size.
Drawing a frame is then a single array lookup. The alternative is 1,536
separate text-drawing calls per frame, which is the difference between the
panel keeping up and falling behind.

**Cast in these scenarios:**

- [The character grid is packed into RGB565 pixels for the ILI9341](scenarios/the-character-grid-is-packed-into-rgb565-pixels-for-the-ili9341.md)

#### [`HeadlessDisplay`](../src/hdmi/headless_display.py)

*headless_display.py* — Draws nothing, but still carries the settings and reads the keyboard.

Stands in for the terminal when a run has none, which in the enclosure is
every run. It draws nothing, but it still holds the settings and still reads
the keyboard. The app therefore has a single display interface, rather than
a scattering of checks for whether a screen exists.

**Cast in no scenario yet.**

#### [`ILI9341`](../src/lcd/lcd.py)

*lcd.py* — Drives the panel over SPI, taking whole frames as PIL images.

The panel itself, at the level of pins and bytes. Everything above it works
in pixels. Only this class knows the initialisation sequence the controller
expects, and that a frame has to leave in 4,096-byte pieces, because that is
all the kernel's SPI buffer will accept.

**Cast in these scenarios:**

- [A failure notice is painted over the picture on the SPI panel](scenarios/a-failure-notice-is-painted-over-the-picture-on-the-spi-panel.md)
- [A frame reaches the SPI panel without stalling the render loop](scenarios/a-frame-reaches-the-spi-panel-without-stalling-the-render-loop.md)
- [The SPI panel shows a start-up screen before the first camera frame](scenarios/the-spi-panel-shows-a-start-up-screen-before-the-first-camera-frame.md)
- [The character grid is packed into RGB565 pixels for the ILI9341](scenarios/the-character-grid-is-packed-into-rgb565-pixels-for-the-ili9341.md)

#### [`ImageProcessor`](../src/capture/image_processor.py)

*image_processor.py* — Turns a raw greyscale camera frame into an ASCII-grid-sized array.

Reduces a camera frame to exactly one pixel per character cell. Everything
downstream works on a few thousand values instead of tens of thousands,
because this runs first. The luma and chroma planes go through the same
reduction, which keeps them in register. If they drifted apart, colour would
fringe along every edge in the picture.

**Cast in these scenarios:**

- [ImageProcessor rotates, crops and resizes a frame to the character grid](scenarios/imageprocessor-rotates-crops-and-resizes-a-frame-to-the-character-grid.md)
- [One YUV420 capture carries greyscale and colour without converting either](scenarios/one-yuv420-capture-carries-greyscale-and-colour-without-converting-either.md)
- [Pixel brightness is mapped to ramp characters](scenarios/pixel-brightness-is-mapped-to-ramp-characters.md)
- [The chroma planes give each character cell its colour](scenarios/the-chroma-planes-give-each-character-cell-its-colour.md)

#### [`LcdDisplay`](../src/lcd/lcd_display.py)

*lcd_display.py* — Draws an ASCII grid onto the ILI9341, filling the panel.

Turns a grid of ramp positions into a frame of RGB565 pixels. Glyph coverage
is treated as a fade from the scheme's unlit screen colour to each cell's
own colour, rather than as a stencil. Its frame buffer persists between
calls, which is what allows a message to be painted over a picture that is
not being redrawn.

**Cast in these scenarios:**

- [A camera that stopped delivering frames is detected and announced](scenarios/a-camera-that-stopped-delivering-frames-is-detected-and-announced.md)
- [A colour scheme is compiled into a per-cell lookup table](scenarios/a-colour-scheme-is-compiled-into-a-per-cell-lookup-table.md)
- [A failure notice is painted over the picture on the SPI panel](scenarios/a-failure-notice-is-painted-over-the-picture-on-the-spi-panel.md)
- [A frame reaches the SPI panel without stalling the render loop](scenarios/a-frame-reaches-the-spi-panel-without-stalling-the-render-loop.md)
- [Pixel brightness is mapped to ramp characters](scenarios/pixel-brightness-is-mapped-to-ramp-characters.md)
- [The character grid is packed into RGB565 pixels for the ILI9341](scenarios/the-character-grid-is-packed-into-rgb565-pixels-for-the-ili9341.md)

#### [`LcdWorker`](../src/lcd/lcd_worker.py) — `threading.Thread`

*lcd_worker.py* — Renders camera frames to the LCD without blocking the main loop.

A thread that owns the panel, so the render loop never waits for the 33
milliseconds a frame costs over SPI. It is handed the app's whole live
configuration with each frame, rather than a private copy of the fields it
cares about. A setting added to the app therefore reaches the panel without
anyone having to remember to add it in a second place.

**Cast in these scenarios:**

- [A camera that stopped delivering frames is detected and announced](scenarios/a-camera-that-stopped-delivering-frames-is-detected-and-announced.md)
- [A failure notice is painted over the picture on the SPI panel](scenarios/a-failure-notice-is-painted-over-the-picture-on-the-spi-panel.md)
- [A frame reaches the SPI panel without stalling the render loop](scenarios/a-frame-reaches-the-spi-panel-without-stalling-the-render-loop.md)
- [One configuration change is pushed to both displays](scenarios/one-configuration-change-is-pushed-to-both-displays.md)
- [The SPI panel shows a start-up screen before the first camera frame](scenarios/the-spi-panel-shows-a-start-up-screen-before-the-first-camera-frame.md)
- [The camera, panel, encoder and socket are released on shutdown](scenarios/the-camera-panel-encoder-and-socket-are-released-on-shutdown.md)

#### [`MainRenderLooper`](../ascii_camera.py)

*ascii_camera.py* — Capture -> process -> ASCII -> terminal, once per frame.

The whole process hangs off this one object. It owns the render loop, and it
is the only thread on which a setting may be changed. Every way of changing
one - a key, the knob, a line off the socket, a phrase a language model
turned into a delta - ends at its `apply` method. That is why there is a
single place that knows what each setting costs to change.

**Cast in these scenarios:**

- [A camera that stopped delivering frames is detected and announced](scenarios/a-camera-that-stopped-delivering-frames-is-detected-and-announced.md)
- [A capture thread hands the render loop its newest frame through a one-slot queue](scenarios/a-capture-thread-hands-the-render-loop-its-newest-frame-through-a-one-slot-queue.md)
- [A frame reaches the SPI panel without stalling the render loop](scenarios/a-frame-reaches-the-spi-panel-without-stalling-the-render-loop.md)
- [A frozen picture is held without redrawing or SPI traffic](scenarios/a-frozen-picture-is-held-without-redrawing-or-spi-traffic.md)
- [A keypress updates the render configuration](scenarios/a-keypress-updates-the-render-configuration.md)
- [A render configuration change is refused](scenarios/a-render-configuration-change-is-refused.md)
- [A rotary encoder detent changes the colour scheme](scenarios/a-rotary-encoder-detent-changes-the-colour-scheme.md)
- [A spoken phrase is turned into a config delta by the language model](scenarios/a-spoken-phrase-is-turned-into-a-config-delta-by-the-language-model.md)
- [A typed command updates the render configuration](scenarios/a-typed-command-updates-the-render-configuration.md)
- [ImageProcessor rotates, crops and resizes a frame to the character grid](scenarios/imageprocessor-rotates-crops-and-resizes-a-frame-to-the-character-grid.md)
- [One configuration change is pushed to both displays](scenarios/one-configuration-change-is-pushed-to-both-displays.md)
- [The camera, panel, encoder and socket are released on shutdown](scenarios/the-camera-panel-encoder-and-socket-are-released-on-shutdown.md)
- [The character grid is drawn on the HDMI terminal](scenarios/the-character-grid-is-drawn-on-the-hdmi-terminal.md)

#### [`NcursesDisplay`](../src/hdmi/ncurses_display.py)

*ncurses_display.py* — Renders ASCII art frames to the terminal.

Draws the picture on the HDMI terminal. While it is running, curses owns the
screen. That is the fact worth remembering: nothing anywhere else in the app
may write to standard output or standard error, or the picture is corrupted.

**Cast in these scenarios:**

- [A colour scheme is compiled into a per-cell lookup table](scenarios/a-colour-scheme-is-compiled-into-a-per-cell-lookup-table.md)
- [A keypress updates the render configuration](scenarios/a-keypress-updates-the-render-configuration.md)
- [One configuration change is pushed to both displays](scenarios/one-configuration-change-is-pushed-to-both-displays.md)
- [Pixel brightness is mapped to ramp characters](scenarios/pixel-brightness-is-mapped-to-ramp-characters.md)
- [The character grid is drawn on the HDMI terminal](scenarios/the-character-grid-is-drawn-on-the-hdmi-terminal.md)

#### [`Scheme`](../src/art/palettes.py) — `NamedTuple`

*palettes.py* — One display look.

One display's whole appearance, held as a value: the lit ink, the unlit
screen behind it, and which of the three kinds of colour scheme it is. It
has no behaviour of its own. That is deliberate, because it lets the nine
schemes be an ordinary list, which the `s` key and the knob step through.

**Cast in these scenarios:**

- [A colour scheme is compiled into a per-cell lookup table](scenarios/a-colour-scheme-is-compiled-into-a-per-cell-lookup-table.md)

#### [`SplashScreen`](../src/lcd/lcd_splash.py)

*lcd_splash.py* — Renders the start-up screen as a PIL image, ready for the panel.

Gives the panel something to show before there is a picture to show. The
camera takes about twenty seconds to produce its first frame. In a sealed
box, twenty seconds of blank glass is indistinguishable from broken
hardware.

**Cast in these scenarios:**

- [The SPI panel shows a start-up screen before the first camera frame](scenarios/the-spi-panel-shows-a-start-up-screen-before-the-first-camera-frame.md)

#### [`YuvFrame`](../src/capture/camera.py)

*camera.py* — One YUV420 frame, exposing its planes as views rather than copies.

One frame from the camera, before anything has been converted. Its planes
are views into the capture buffer rather than copies, so reading the
greyscale image costs nothing, and colour costs only the chroma a scheme
actually asks for. Keeping all three planes together also lets the render
loop and the panel's thread read the same frame at once, since neither of
them writes to it.

**Cast in these scenarios:**

- [A capture thread hands the render loop its newest frame through a one-slot queue](scenarios/a-capture-thread-hands-the-render-loop-its-newest-frame-through-a-one-slot-queue.md)
- [One YUV420 capture carries greyscale and colour without converting either](scenarios/one-yuv420-capture-carries-greyscale-and-colour-without-converting-either.md)
- [The chroma planes give each character cell its colour](scenarios/the-chroma-planes-give-each-character-cell-its-colour.md)

## Getting a change in

Every route by which a setting changes - a typed line, the knob, a phrase
for the model - and the one object that decides whether a value is allowed.
`MainRenderLooper` appears again because it is where all of them arrive.

```mermaid
---
config:
  layout: elk
---
classDiagram
    direction TB

    class NamedTuple {
        <<external>>
    }
    class ValueError {
        <<external>>
    }
    class threading.Thread {
        <<external>>
    }
    class RuntimeError {
        <<external>>
    }

    class MainRenderLooper {
        +config
        +terminal_on
        +lcd_on
        +scheme
        +apply()
        +run()
    }
    class RenderConfig {
        +str scheme
        +str ramp
        +bool invert
        +int colour_levels
        +float contrast
        +bool auto_levels
        +int rotation
        +bool mirror
        +bool fill
        +int lcd_font_size
        +str target
        +bool freeze
        +with_changes()
        +changes_from()
        +describe_changes()
        +as_delta()
    }
    class Spec {
        +str name
        +str kind
        +str note
        +tuple choices
        +float low
        +float high
    }
    class ConfigError {
        +problems
    }
    class CommandServer {
        +resolver
        +start()
        +run()
        +take()
        +stop()
    }
    class Ask {
        +str utterance
        +dict delta
        +str note
    }
    class Reply {
        +str text
    }
    class CommandError
    class SchemeCycle {
        +start_encoder()
        +poll()
        +stop()
        +home()
        +step()
    }
    class RotaryEncoder {
        +start()
        +take()
        +take_presses()
        +stop()
    }
    class QuadratureDecoder {
        +feed()
    }
    class AskResolver {
        +warm()
        +resolve()
        +short_failure()
        +record()
    }
    class Parsed {
        +declined
        +delta
        +unmet
        +ok
    }
    class ParseError
    class AskLog {
        +record()
    }

    NamedTuple <|-- Spec
    ValueError <|-- ConfigError
    threading.Thread <|-- CommandServer
    NamedTuple <|-- Ask
    NamedTuple <|-- Reply
    ValueError <|-- CommandError
    RuntimeError <|-- ParseError
    MainRenderLooper *-- AskResolver
    MainRenderLooper *-- CommandServer
    MainRenderLooper *-- SchemeCycle
    SchemeCycle *-- RotaryEncoder
    RotaryEncoder *-- QuadratureDecoder
    MainRenderLooper ..> ConfigError
    RenderConfig ..> ConfigError
    CommandServer ..> Reply
    AskResolver ..> Ask
    AskResolver ..> Reply
```

**Fig 2: Getting a change in**

[`MainRenderLooper`](#mainrenderlooper) appears here too, and is described above.

### The classes in this diagram

#### [`Ask`](../src/control/command_server.py) — `NamedTuple`

*command_server.py* — A delta already worked out, on its way to the render loop.

A delta that has already been worked out, on its way to the render loop. Its
value is that it is a distinct type. An answer that took four seconds to
obtain from a language model reaches the loop the same way a typed line
does, and by then nothing about it reveals which it was.

**Cast in no scenario yet.**

#### [`AskLog`](../src/language/asklog.py)

*asklog.py* — Append-only record of asks, one JSON object per line.

Writes down every ask, with what it cost and how it was answered. The
load-bearing part is the source it records. That separates what the shortcut
table answered for nothing from what a language model was paid to answer,
which is what makes the hit rate and the cost countable rather than
estimated.

**Cast in these scenarios:**

- [A spoken phrase is answered from the shortcut table, with no model call](scenarios/a-spoken-phrase-is-answered-from-the-shortcut-table-with-no-model-call.md)
- [A spoken phrase is turned into a config delta by the language model](scenarios/a-spoken-phrase-is-turned-into-a-config-delta-by-the-language-model.md)
- [Every ask is recorded with its source, its cost and its elapsed time](scenarios/every-ask-is-recorded-with-its-source-its-cost-and-its-elapsed-time.md)

#### [`AskResolver`](../src/language/resolver.py)

*resolver.py* — Turns "ask <words>" into a delta, on whatever thread called it.

The whole of the ask path, and the one part of the app allowed to be slow.
It tries the exact table before it even looks for an API key. That ordering
is why `green` and `freeze it` still work with the network down, and why
asking is never all or nothing.

**Cast in these scenarios:**

- [A model parse fails and the panel says which kind of failure it was](scenarios/a-model-parse-fails-and-the-panel-says-which-kind-of-failure-it-was.md)
- [A spoken phrase is answered from the shortcut table, with no model call](scenarios/a-spoken-phrase-is-answered-from-the-shortcut-table-with-no-model-call.md)
- [A spoken phrase is turned into a config delta by the language model](scenarios/a-spoken-phrase-is-turned-into-a-config-delta-by-the-language-model.md)
- [Every ask is recorded with its source, its cost and its elapsed time](scenarios/every-ask-is-recorded-with-its-source-its-cost-and-its-elapsed-time.md)
- [The language model declines a request it cannot satisfy](scenarios/the-language-model-declines-a-request-it-cannot-satisfy.md)

#### [`CommandError`](../src/control/commands.py) — `ValueError`

*commands.py* — A line that could not be turned into a delta, with a reason to print.

Raised when a typed line cannot be turned into a delta, and it carries the
reason why. It exists so that the layer settling what type a word has can
refuse in a sentence rather than in a traceback. Whether a value is actually
allowed is a separate question, answered elsewhere.

**Cast in no scenario yet.**

#### [`CommandServer`](../src/control/command_server.py) — `threading.Thread`

*command_server.py* — Accepts typed lines on a Unix socket and queues them for the app.

The Unix socket, and a thread for each client that connects. It does nothing
else, on purpose. It accepts a line, offers it to whoever resolves it, and
leaves the result where the render loop will collect it. A request that
takes several seconds therefore costs the picture nothing.

**Cast in these scenarios:**

- [A spoken phrase is answered from the shortcut table, with no model call](scenarios/a-spoken-phrase-is-answered-from-the-shortcut-table-with-no-model-call.md)
- [A typed command updates the render configuration](scenarios/a-typed-command-updates-the-render-configuration.md)
- [Text typed on a phone reaches the render loop over the LAN](scenarios/text-typed-on-a-phone-reaches-the-render-loop-over-the-lan.md)
- [The camera, panel, encoder and socket are released on shutdown](scenarios/the-camera-panel-encoder-and-socket-are-released-on-shutdown.md)

#### [`ConfigError`](../src/control/render_config.py) — `ValueError`

*render_config.py* — A delta that could not be applied, carrying every reason rather than one.

Raised when a delta is refused, and it carries every reason rather than only
the first one found. A caller can then correct a whole change in a single
pass. That also matters to the eval that scores a language model's
proposals, which wants the entire list.

**Cast in these scenarios:**

- [A render configuration change is refused](scenarios/a-render-configuration-change-is-refused.md)

#### [`ParseError`](../src/language/parser.py) — `RuntimeError`

*parser.py* — The parse could not be completed - network, key, or a refusal.

Raised when a parse cannot be completed. A dead network, a refused key and a
model that declined all arrive as this one type. The caller's job is to put
something useful on a 240x320 panel, not to tell those three apart.

**Cast in these scenarios:**

- [A model parse fails and the panel says which kind of failure it was](scenarios/a-model-parse-fails-and-the-panel-says-which-kind-of-failure-it-was.md)

#### [`Parsed`](../src/language/parser.py)

*parser.py* — What one utterance came back as.

What one utterance came back as. Exactly one of the delta and the refusal is
ever set, so nothing downstream has a third shape to handle. The remaining
field is the honest one. It says what the request asked for that these
settings cannot express, which is not the same as being refused.

**Cast in these scenarios:**

- [A spoken phrase is turned into a config delta by the language model](scenarios/a-spoken-phrase-is-turned-into-a-config-delta-by-the-language-model.md)
- [The language model declines a request it cannot satisfy](scenarios/the-language-model-declines-a-request-it-cannot-satisfy.md)

#### [`QuadratureDecoder`](../src/control/encoder.py)

*encoder.py* — Pin levels in, detents out.  No GPIO, no threads, no clock.

Takes pin levels and returns detents. It has no GPIO, no thread and no clock
of its own. That purity is the point rather than tidiness. This is the part
that can be wrong in a way nobody notices until the knob feels bad, so it
has to be testable on a machine with no encoder attached.

**Cast in these scenarios:**

- [A rotary encoder detent changes the colour scheme](scenarios/a-rotary-encoder-detent-changes-the-colour-scheme.md)

#### [`RenderConfig`](../src/control/render_config.py) — `@dataclass`

*render_config.py* — The complete live render state.

Holds the complete live render state. It is frozen, so a change replaces it
rather than editing it, and no reader can ever catch it half-applied. It is
also the only code that decides whether a value is allowed. It gives the
same answer whoever asked, which is what makes comparing a keypress, a knob
and a language model meaningful.

**Cast in these scenarios:**

- [A frozen picture is held without redrawing or SPI traffic](scenarios/a-frozen-picture-is-held-without-redrawing-or-spi-traffic.md)
- [A keypress updates the render configuration](scenarios/a-keypress-updates-the-render-configuration.md)
- [A render configuration change is refused](scenarios/a-render-configuration-change-is-refused.md)
- [A spoken phrase is answered from the shortcut table, with no model call](scenarios/a-spoken-phrase-is-answered-from-the-shortcut-table-with-no-model-call.md)
- [A spoken phrase is turned into a config delta by the language model](scenarios/a-spoken-phrase-is-turned-into-a-config-delta-by-the-language-model.md)
- [A typed command updates the render configuration](scenarios/a-typed-command-updates-the-render-configuration.md)
- [One configuration change is pushed to both displays](scenarios/one-configuration-change-is-pushed-to-both-displays.md)

#### [`Reply`](../src/control/command_server.py) — `NamedTuple`

*command_server.py* — A resolver's answer to send straight back, without troubling the loop.

An answer that never reaches the render loop. It carries a message straight
back to whoever asked for it. Refusals, help text and failures therefore
stay off the one thread that has to keep drawing.

**Cast in no scenario yet.**

#### [`RotaryEncoder`](../src/control/encoder.py)

*encoder.py* — A KY-040 on two GPIO pins, read through lgpio's edge callbacks.

Claims the knob's three GPIO pins and accumulates what it did, under a lock,
because the edges arrive on a thread the render loop does not control. What
it hands over is a net count rather than a list of events. The loop
therefore learns how far the knob moved, and not how noisily it got there.

**Cast in these scenarios:**

- [A rotary encoder detent changes the colour scheme](scenarios/a-rotary-encoder-detent-changes-the-colour-scheme.md)
- [The camera, panel, encoder and socket are released on shutdown](scenarios/the-camera-panel-encoder-and-socket-are-released-on-shutdown.md)

#### [`SchemeCycle`](../src/control/scheme_cycle.py)

*scheme_cycle.py* — Steps the colour scheme, from a key or a knob.

Walks through the colour schemes, whichever input asked for the move. It
applies a whole banked move at once, rather than one detent at a time. Every
scheme change repaints every cell, so a spin applied step by step would
strobe through pictures nobody is on screen long enough to see.

**Cast in these scenarios:**

- [A rotary encoder detent changes the colour scheme](scenarios/a-rotary-encoder-detent-changes-the-colour-scheme.md)

#### [`Spec`](../src/control/render_config.py) — `NamedTuple`

*render_config.py* — What one setting accepts, and what it is for.

Describes what one setting accepts and what it is for. The twelve of them
are the single source from which the validator, the `help` text, the
command-line arguments and the language model's tool schema are all built. A
setting therefore cannot exist in this app and be undocumented, and adding
one is a single edit.

**Cast in these scenarios:**

- [A render configuration change is refused](scenarios/a-render-configuration-change-is-refused.md)

## The phone page

A second process, sharing no memory with the app and reaching it only down a
Unix socket. Its own diagram because that separation is the most important
thing about it.

```mermaid
---
config:
  layout: elk
---
classDiagram
    direction TB

    class ThreadingHTTPServer {
        <<external>>
    }
    class BaseHTTPRequestHandler {
        <<external>>
    }

    class WebServer {
        +forwarder
        +limit
    }
    class Handler {
        +do_GET()
        +do_POST()
        +log_message()
    }
    class AskLimit {
        +allow()
    }
    class Forwarder {
        +send()
        +alive()
    }

    ThreadingHTTPServer <|-- WebServer
    BaseHTTPRequestHandler <|-- Handler
    WebServer *-- AskLimit
    WebServer ..> Handler
```

**Fig 3: The phone page**

### The classes in this diagram

#### [`AskLimit`](../src/control/web_server.py)

*web_server.py* — A sliding window over the requests that cost money.

Counts the requests that cost money over a sliding window, and refuses them
past a ceiling. A phone left face up on a table can post the same form for
hours. This is the only thing standing between that and an unattended API
bill.

**Cast in these scenarios:**

- [Text typed on a phone reaches the render loop over the LAN](scenarios/text-typed-on-a-phone-reaches-the-render-loop-over-the-lan.md)

#### [`Forwarder`](../src/control/web_server.py)

*web_server.py* — Sends one line to the app's command socket and returns its reply.

Sends one line to the app's command socket and returns the reply. It is the
only thing in the web process that knows the camera exists. That keeps the
phone page a client of the app, rather than a second copy of it.

**Cast in these scenarios:**

- [Text typed on a phone reaches the render loop over the LAN](scenarios/text-typed-on-a-phone-reaches-the-render-loop-over-the-lan.md)

#### [`Handler`](../src/control/web_server.py) — `BaseHTTPRequestHandler`

*web_server.py* — One request. The server instance carries the forwarder and the limit.

Serves one HTTP request: the page itself, the form on it, and the forwarding
of whatever was typed. Each request runs on a thread of its own. One slow
ask therefore cannot make the page unreachable for anybody else.

**Cast in these scenarios:**

- [Text typed on a phone reaches the render loop over the LAN](scenarios/text-typed-on-a-phone-reaches-the-render-loop-over-the-lan.md)

#### [`WebServer`](../src/control/web_server.py) — `ThreadingHTTPServer`

*web_server.py* — A LAN-bound listener, IPv4 only, holding the socket path it forwards to.

Listens on the LAN, over IPv4 only, and holds the socket path it forwards
to. The narrow binding is the security posture. There is no authentication
anywhere on this path, so what limits the damage is who can reach it at all.

**Cast in no scenario yet.**

---

31 classes.
