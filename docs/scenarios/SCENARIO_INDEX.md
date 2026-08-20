# Scenarios, by category and priority

One document per mind-sized chunk of behaviour: two to five classes, a sequence
diagram, a table explaining every message in it, and links into the source.
[How to write one](../how-to-write-scenario-docs.md).

The five categories follow the shape of the machine — light in at the top,
pixels out, and the ways a person changes what happens last. An empty category
is listed rather than omitted: saying where the gaps are is most of the point.

**Twenty written, five still to write.** Unwritten entries are in bold
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
- `HIGH` · [One YUV420 capture carries greyscale and colour without converting either](one-yuv420-capture-carries-greyscale-and-colour-without-converting-either.md)
  — the Y plane already is the greyscale image, and 38 KB more buys the colour
  path without a conversion anywhere.
- `HIGH` · [ImageProcessor rotates, crops and resizes a frame to the character grid](imageprocessor-rotates-crops-and-resizes-a-frame-to-the-character-grid.md)
  — the step that makes everything downstream grid-sized, and the shared path
  that keeps the three planes in register.

## Art

Turning brightness into characters, and characters into colour.

- `HIGH` · [Pixel brightness is mapped to ramp characters](pixel-brightness-is-mapped-to-ramp-characters.md)
  — a 256-entry table built once and applied to the whole grid at a stroke,
  feeding both displays from one calculation.
- `MEDIUM` · [The chroma planes give each character cell its colour](the-chroma-planes-give-each-character-cell-its-colour.md)
  — the conversion runs after the downscale, so colour costs about 6,650 sums a
  frame rather than 76,800.
- `MEDIUM` · [A colour scheme is compiled into a per-cell lookup table](a-colour-scheme-is-compiled-into-a-per-cell-lookup-table.md)
  — one blend, compiled twice, because the panel takes RGB and the terminal has
  only 240 palette entries to snap to.

## The two displays

The HDMI terminal and the ILI9341 panel, which run at the same time and at
different rates.

- `MEDIUM` · [The character grid is drawn on the HDMI terminal](the-character-grid-is-drawn-on-the-hdmi-terminal.md)
  — centred, padded rather than cleared, and written as coloured runs. Every
  frame, but `--no-terminal` in the enclosure.
- `HIGH` · [A frame reaches the SPI panel without stalling the render loop](a-frame-reaches-the-spi-panel-without-stalling-the-render-loop.md)
  — 153,600 bytes and 33 ms of SPI, on a thread the render loop never waits
  on.
- `HIGH` · [The character grid is packed into RGB565 pixels for the ILI9341](the-character-grid-is-packed-into-rgb565-pixels-for-the-ili9341.md)
  — 3.7 ms of CPU against 33 ms of SPI, because glyphs are gathered from an
  atlas rather than drawn per cell.
- `MEDIUM` · [The SPI panel shows a start-up screen before the first camera frame](the-spi-panel-shows-a-start-up-screen-before-the-first-camera-frame.md)
  — twenty seconds of unlit glass is what broken hardware looks like, so the
  panel says what is happening, and keeps saying something true.
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
- `MEDIUM` · [Text typed on a phone reaches the render loop over the LAN](text-typed-on-a-phone-reaches-the-render-loop-over-the-lan.md)
  — a second process that shares no memory with the camera and reaches it only
  down the socket a shell would use.
- `MEDIUM` · [A keypress updates the render configuration](a-keypress-updates-the-render-configuration.md)
  — the shortest route in, and only short: every branch builds a delta and none
  assigns a setting.
- `HIGH` · [A rotary encoder detent changes the colour scheme](a-rotary-encoder-detent-changes-the-colour-scheme.md)
  — the only control on a sealed box that needs no second device. Bounce is
  rejected by construction, and a banked move costs one repaint.
- `HIGH` · [One configuration change is pushed to both displays](one-configuration-change-is-pushed-to-both-displays.md)
  — where every route above ends. The terminal is pushed to; the panel reads
  the config it is handed with the next frame.
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
