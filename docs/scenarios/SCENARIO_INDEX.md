# Scenarios, by category and priority

One document per mind-sized chunk of behaviour: two to five classes, a sequence
diagram, a table explaining every message in it, and links into the source.
[How to write one](../how-to-write-scenario-docs.md).

The five categories follow the shape of the machine — light in at the top,
pixels out, and the ways a person changes what happens last. An empty category
is listed rather than omitted: saying where the gaps are is most of the point.

**Nine written, sixteen still to write.** Unwritten entries are in bold
rather than linked, because a link to a file that does not exist fails
`tests/docs/docs_links_test.py`.

## What the priorities mean

`HIGH` is on the path every frame takes, or the only route by which the shipped
device can be seen or driven at all. `MEDIUM` runs when a person interacts,
once per run, or every frame but only in a configuration the appliance does not
boot into. `LOW` is exceptional or optional — failure handling, record-keeping,
and the paths that need an API key and a network.

The criteria in full, and why the `HIGH`/`MEDIUM` line is drawn at the deployed
configuration rather than at per-frame, are in
[how to write a scenario](../how-to-write-scenario-docs.md). They are stated
there and applied here, so there is one definition rather than two that can
disagree.

**The distribution: 9 `HIGH`, 10 `MEDIUM`, 6 `LOW`.**

## Capture

Frames off the camera, and into a shape the rest can use.

- `HIGH` · [A capture thread hands the render loop its newest frame through a one-slot queue](a-capture-thread-hands-the-render-loop-its-newest-frame-through-a-one-slot-queue.md)
  — the camera runs at its own pace and the loop at its own, and the single
  slot is what makes the loop lose frames rather than currency.
- `HIGH` · **One YUV420 capture carries greyscale and colour without converting either**
  Cast: `YuvFrame`, `CameraCapture`
- `HIGH` · **`ImageProcessor` rotates, crops and resizes a frame to the character grid**
  Cast: `MainRenderLooper`, `ImageProcessor`

## Art

Turning brightness into characters, and characters into colour.

- `HIGH` · [Pixel brightness is mapped to ramp characters](pixel-brightness-is-mapped-to-ramp-characters.md)
  — a 256-entry table built once and applied to the whole grid at a stroke,
  feeding both displays from one calculation.
- `MEDIUM` · **The chroma planes give each character cell its colour** — only in
  the colour schemes, and the default is `grey`
  Cast: `YuvFrame`, `ImageProcessor`, `AsciiArt`
- `MEDIUM` · **A colour scheme is compiled into a per-cell lookup table** — on a
  scheme change, not per frame; the table is what stops it being per frame
  Cast: `Scheme`, `palettes`, `NcursesDisplay`, `LcdDisplay`

## The two displays

The HDMI terminal and the ILI9341 panel, which run at the same time and at
different rates.

- `MEDIUM` · **The character grid is drawn on the HDMI terminal by `NcursesDisplay`**
  — every frame, but `--no-terminal` in the enclosure
  Cast: `MainRenderLooper`, `NcursesDisplay`
- `HIGH` · [A frame reaches the SPI panel without stalling the render loop](a-frame-reaches-the-spi-panel-without-stalling-the-render-loop.md)
  — 153,600 bytes and 33 ms of SPI, on a thread the render loop never waits
  on.
- `HIGH` · **The character grid is packed into RGB565 pixels for the ILI9341**
  Cast: `LcdDisplay`, `GlyphAtlas`, `ILI9341`
- `MEDIUM` · **The SPI panel shows a start-up screen before the first camera frame**
  — once per run, and for twenty-three seconds it is the only sign the machine is alive
  Cast: `LcdWorker`, `SplashScreen`, `ILI9341`
- `LOW` · **A failure notice is painted over the picture on the SPI panel**
  Cast: `LcdWorker`, `LcdDisplay`, `ILI9341`

## Getting a change in

Every route by which a setting changes — a typed line, a key, the knob, a
phone, or words — and the one validator they all meet. All four written
scenarios are here, because this is where the app has the most ways in and
therefore the most that has to agree.

- `HIGH` · [A typed command updates the render configuration](a-typed-command-updates-the-render-configuration.md)
  — a line on the Unix socket crosses a thread boundary, is parsed into typed
  values, validated, and pushed to both displays. The spine every other route
  converges on.
- `MEDIUM` · [A render configuration change is refused](a-render-configuration-change-is-refused.md)
  — why `rotation 45` is refused in the same words whoever asked, and the one
  check `RenderConfig` is not in a position to make.
- `MEDIUM` · [A spoken phrase is answered from the shortcut table, with no model call](a-spoken-phrase-is-answered-from-the-shortcut-table-with-no-model-call.md)
  — how `a bit more contrast` becomes a delta in microseconds, with no API key,
  no network and no model. The only ask path that survives a dead network.
- `LOW` · [A spoken phrase is turned into a config delta by the language model](a-spoken-phrase-is-turned-into-a-config-delta-by-the-language-model.md)
  — what `something calmer` costs instead: a key, a network, and two and a half
  seconds. Off entirely without a key.
- `MEDIUM` · **Text typed on a phone reaches the render loop over the LAN**
  — its own service, and the richest way in for a box with no keyboard
  Cast: `Handler`, `AskLimit`, `Forwarder`, `CommandServer`
- `MEDIUM` · **A keypress updates the render configuration** — terminal
  sessions only, so never in the enclosure
  Cast: `NcursesDisplay`, `MainRenderLooper`, `RenderConfig`
- `HIGH` · **A rotary encoder detent changes the colour scheme** — the only
  control on a sealed box that needs no second device
  Cast: `RotaryEncoder`, `QuadratureDecoder`, `SchemeCycle`, `MainRenderLooper`
- `HIGH` · **One configuration change is pushed to both displays** — where every
  route above ends, on every change
  Cast: `MainRenderLooper`, `NcursesDisplay`, `LcdWorker`
- `LOW` · **A model parse fails and the panel says which kind of failure it was**
  Cast: `AskResolver`, `parser`, `ParseError`
- `LOW` · **The language model declines a request it cannot satisfy**
  Cast: `AskResolver`, `parser`, `Parsed`

## Lifecycle

Starting, stalling, freezing and stopping — the states the machine is in when
it is not simply running.

- `MEDIUM` · [A camera that stopped delivering frames is detected and announced](a-camera-that-stopped-delivering-frames-is-detected-and-announced.md)
  — a frozen picture and a working camera are indistinguishable by eye, so the
  only output a sealed box has must be able to admit it has nothing new.
- `LOW` · **A frozen picture is held without redrawing or SPI traffic**
  Cast: `MainRenderLooper`, `RenderConfig`
- `MEDIUM` · [The camera, panel, encoder and socket are released on shutdown](the-camera-panel-encoder-and-socket-are-released-on-shutdown.md)
  — four claims given back in a fixed order, because a leak on the way out
  breaks the next start rather than this one.
- `LOW` · **Every ask is recorded with its source, its cost and its elapsed time**
  Cast: `AskResolver`, `AskLog`

---

One scenario is missing from every category above on purpose: window planning
happens in `run_ascii_camera.sh` calling `window_plan.plan()` before any object
exists, so it cannot be drawn as a collaboration between classes. Draw it with
the module named as a module, or leave it to [using it](../using-it.md).

The last two entries under *Getting a change in* are the outcomes the language
model scenario deliberately does not draw: one document per outcome, rather
than one diagram with a branch in it. They inherit its `LOW`, since a failure
of an optional path is not more urgent than the path.
