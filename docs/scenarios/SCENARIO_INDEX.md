# Scenarios, by category and priority

One document per mind-sized chunk of behaviour: two to five classes, a sequence
diagram, a table explaining every message in it, and links into the source.
[How to write one](../how-to-write-scenario-docs.md).

The five categories follow the shape of the machine — light in at the top,
pixels out, and the ways a person changes what happens last. An empty category
is listed rather than omitted: saying where the gaps are is most of the point.

**If you are reading these for the first time, do not start at the first
category.** [Where to start](#where-to-start) puts the same twenty documents in
the order that gets the whole machine into your head fastest, in six.

**All twenty-five are written.** No bold entries are left, so the check in
`tests/docs/docs_links_test.py` that catches a scenario still advertised as
unwritten now has nothing to find — which is the state it was built to protect,
not a reason to delete it.

## Where to start

The categories below answer *where does this live*. This section answers *what
do I read first*, which is a different question with a different answer. Read in
this order and each document leans on one already read; read in category order
and the first thing you meet is a camera thread explaining itself to a render
loop you have not been introduced to.

It is not priority order either. Priority describes the running machine — what
executes every frame, what only when somebody interacts. Reading order
describes a person, who needs the shape of the whole thing before the detail of
any part. The two disagree usefully: **the first five documents below introduce
every class that appears in four or more scenarios**, which taking them in
priority order does not manage until the sixth, and alphabetically not until
the eleventh.

### First lap — one frame in, one picture out, one change applied

Six documents that between them cross the entire machine. Stopping here leaves
you able to follow any of the others out of order.

| | Scenario | What it adds |
|---:|---|---|
| 1 | [A capture thread hands the render loop its newest frame through a one-slot queue](a-capture-thread-hands-the-render-loop-its-newest-frame-through-a-one-slot-queue.md) | The render loop itself, and the two independent rates that meet at a single slot. Everything below is one turn of this loop |
| 2 | [ImageProcessor rotates, crops and resizes a frame to the character grid](imageprocessor-rotates-crops-and-resizes-a-frame-to-the-character-grid.md) | Where a camera-shaped frame becomes a grid-shaped one, and where orientation and proportion are settled for everything downstream |
| 3 | [Pixel brightness is mapped to ramp characters](pixel-brightness-is-mapped-to-ramp-characters.md) | The conversion the app is named for — and the fact that one table serves both displays, so the two are never computed apart |
| 4 | [A frame reaches the SPI panel without stalling the render loop](a-frame-reaches-the-spi-panel-without-stalling-the-render-loop.md) | A picture, at last, and the second thread that carries it. Why 33 ms of SPI does not cost the loop 33 ms |
| 5 | [A typed command updates the render configuration](a-typed-command-updates-the-render-configuration.md) | The first change arriving from outside, and the crossing into the loop's thread. Introduces the configuration itself, and the one validator every route meets |
| 6 | [One configuration change is pushed to both displays](one-configuration-change-is-pushed-to-both-displays.md) | Closes the lap. The terminal is pushed to and the panel reads what it is handed, which is why the two displays never disagree |

### Second lap — the same path, closer

Nothing new in shape; the same five stops with the arithmetic filled in. Read
in this order they answer questions the first lap raises and leaves open.

| | Scenario | What it adds |
|---:|---|---|
| 7 | [One YUV420 capture carries greyscale and colour without converting either](one-yuv420-capture-carries-greyscale-and-colour-without-converting-either.md) | What a frame actually is, and why the greyscale image costs nothing to obtain |
| 8 | [The chroma planes give each character cell its colour](the-chroma-planes-give-each-character-cell-its-colour.md) | Where a cell's colour comes from, and why doing it after the downscale is the whole trick |
| 9 | [A colour scheme is compiled into a per-cell lookup table](a-colour-scheme-is-compiled-into-a-per-cell-lookup-table.md) | Why one blend is compiled twice — the panel takes RGB, the terminal must snap to 240 entries and sometimes cannot tell two steps apart |
| 10 | [The character grid is packed into RGB565 pixels for the ILI9341](the-character-grid-is-packed-into-rgb565-pixels-for-the-ili9341.md) | How the panel's pixels are really made, and why the glyphs are gathered rather than drawn |
| 11 | [The character grid is drawn on the HDMI terminal](the-character-grid-is-drawn-on-the-hdmi-terminal.md) | The other display — the one you will be watching while you work, though the sealed box runs without it |

### The other ways in

Document 5 showed one route to a changed setting. These are the rest, ordered
by how much machinery stands between a person and the configuration — a knob is
almost none, a language model is a great deal — and then the two ways the last
of them can end without changing anything.

| | Scenario | What it adds |
|---:|---|---|
| 12 | [A rotary encoder detent changes the colour scheme](a-rotary-encoder-detent-changes-the-colour-scheme.md) | The only control a sealed box has that needs no second device, and how contact bounce is rejected by construction rather than by filtering |
| 13 | [A keypress updates the render configuration](a-keypress-updates-the-render-configuration.md) | The shortest route in, and the discipline that keeps it short: every branch builds a delta, none assigns a setting |
| 14 | [A render configuration change is refused](a-render-configuration-change-is-refused.md) | What happens when a change is not allowed, in the same words whoever asked — and the one check the configuration is not in a position to make |
| 15 | [Text typed on a phone reaches the render loop over the LAN](text-typed-on-a-phone-reaches-the-render-loop-over-the-lan.md) | A second process, sharing no memory with the camera, reaching it down the socket a shell would use |
| 16 | [A spoken phrase is answered from the shortcut table, with no model call](a-spoken-phrase-is-answered-from-the-shortcut-table-with-no-model-call.md) | Words becoming a setting with no key, no network and no model — and why the table declines rather than guesses |
| 17 | [A spoken phrase is turned into a config delta by the language model](a-spoken-phrase-is-turned-into-a-config-delta-by-the-language-model.md) | What the phrases the table declines cost instead, and the only path here that can be switched off entirely |
| 18 | [A model parse fails and the panel says which kind of failure it was](a-model-parse-fails-and-the-panel-says-which-kind-of-failure-it-was.md) | The first ending document 17 can have that is not a change, and how a failure becomes a sentence that fits |
| 19 | [The language model declines a request it cannot satisfy](the-language-model-declines-a-request-it-cannot-satisfy.md) | The second, and the harder one: a refusal is an answer, and must not be filed with the failures |

### When it is not simply running

In the order a run meets them: before the first frame, during, on the way out —
and last, the one thing the app keeps after the process is gone.

| | Scenario | What it adds |
|---:|---|---|
| 20 | [The SPI panel shows a start-up screen before the first camera frame](the-spi-panel-shows-a-start-up-screen-before-the-first-camera-frame.md) | The twenty seconds before there is anything to show, and why unlit glass is the one thing the panel must not do |
| 21 | [A camera that stopped delivering frames is detected and announced](a-camera-that-stopped-delivering-frames-is-detected-and-announced.md) | Why a working camera and a frozen picture look identical, and what a sealed box can do about it |
| 22 | [A failure notice is painted over the picture on the SPI panel](a-failure-notice-is-painted-over-the-picture-on-the-spi-panel.md) | The mechanism the two above both depend on: a band pushed with or without a frame to carry it |
| 23 | [A frozen picture is held without redrawing or SPI traffic](a-frozen-picture-is-held-without-redrawing-or-spi-traffic.md) | The deliberate still picture, and what a loop with nothing to draw ought to cost |
| 24 | [The camera, panel, encoder and socket are released on shutdown](the-camera-panel-encoder-and-socket-are-released-on-shutdown.md) | Four claims given back in a fixed order, because a leak on the way out breaks the *next* start rather than this one |
| 25 | [Every ask is recorded with its source, its cost and its elapsed time](every-ask-is-recorded-with-its-source-its-cost-and-its-elapsed-time.md) | What outlives the run, and the field that decides whether a record is evidence of anything |

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
- `LOW` · [A failure notice is painted over the picture on the SPI panel](a-failure-notice-is-painted-over-the-picture-on-the-spi-panel.md)
  — 36 pixels of the 240, in fixed ink over whatever is underneath, pushed
  with or without a frame to carry it.

## Getting a change in

Every route by which a setting changes — a typed line, a key, the knob, a
phone, or words — and the one validator they all meet. This is the largest
category, because it is where the app has the most ways in and therefore the
most that has to agree.

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
- `LOW` · [A model parse fails and the panel says which kind of failure it was](a-model-parse-fails-and-the-panel-says-which-kind-of-failure-it-was.md)
  — four infrastructure failures told apart because they call for different
  actions, and three answer failures deliberately not.
- `LOW` · [The language model declines a request it cannot satisfy](the-language-model-declines-a-request-it-cannot-satisfy.md)
  — a refusal is an answer with its own tool, and the one string on the panel
  this codebase did not write.

## Lifecycle

Starting, stalling, freezing and stopping — the states the machine is in when
it is not simply running.

- `MEDIUM` · [A camera that stopped delivering frames is detected and announced](a-camera-that-stopped-delivering-frames-is-detected-and-announced.md)
  — a frozen picture and a working camera are indistinguishable by eye, so the
  only output a sealed box has must be able to admit it has nothing new.
- `LOW` · [A frozen picture is held without redrawing or SPI traffic](a-frozen-picture-is-held-without-redrawing-or-spi-traffic.md)
  — the loop stops making frames rather than making repeats, and the camera is
  left running because restarting it costs 15-20 seconds.
- `MEDIUM` · [The camera, panel, encoder and socket are released on shutdown](the-camera-panel-encoder-and-socket-are-released-on-shutdown.md)
  — four claims given back in a fixed order, because a leak on the way out
  breaks the next start rather than this one.
- `LOW` · [Every ask is recorded with its source, its cost and its elapsed time](every-ask-is-recorded-with-its-source-its-cost-and-its-elapsed-time.md)
  — the only part of the app whose behaviour cannot be asserted in a test, so
  what really happened is kept instead.

---

One scenario is missing from every category above on purpose: window planning
happens in `run_ascii_camera.sh` calling `window_plan.plan()` before any object
exists, so it cannot be drawn as a collaboration between classes. Draw it with
the module named as a module, or leave it to [using it](../using-it.md).

The last two scenarios under *Getting a change in* are the outcomes the language
model scenario deliberately does not draw: one document per outcome, rather
than one diagram with a branch in it. They inherit its `LOW`, since a failure
of an optional path is not more urgent than the path.
