# A failure notice is painted over the picture on the SPI panel

**Priority: `LOW`** — it runs only when something has already gone wrong, but it is the only way a sealed box can tell anyone that it has. [What the priorities mean](../how-to-write-scenario-docs.md).

In the enclosure there is no terminal, no status line[^statusline] and nobody
watching a log. The panel[^panel] is the entire output of the machine, and it
is showing a picture. When the API key[^apikey] is refused or the camera stops
delivering, the picture carries on looking exactly as it did — which is the
failure mode this scenario exists to prevent.

The answer is a band along the bottom of the panel: [36 pixels of
240](../../src/lcd/lcd_display.py#L37), a seventh of the glass, painted over
whatever is already there and taken away four seconds later. It is drawn in
[fixed ink](../../src/lcd/lcd_display.py#L39) on a [near-black
ground](../../src/lcd/lcd_display.py#L40) rather than in the scheme[^scheme]'s
colours, and that is deliberate twice over. The glyph atlas[^atlas] holds only
the ramp[^ramp] characters, so the character grid[^grid] **cannot spell
anything at all** — a message has to be rasterised[^coverage] separately or it
cannot exist. And a message tinted by whatever cell colours happen to sit
under it would be least legible exactly when it matters most, which under the
`live` scheme is most of the time.

**The band is pushed whether or not there is a frame to push it with.** That
is the case the whole mechanism is built for: when the camera stops, the
render loop has nothing to draw, so a notice[^notice] that could only travel
attached to a frame would never arrive.
[`show_notice`](../../src/lcd/lcd_display.py#L259) paints into the persistent
frame buffer and sends it on its own.

![The SPI panel showing an ASCII picture with a two-line message painted across
the bottom 36 of its 240 rows in warm white on near-black, marked with a bracket.
Beside it, the same band arriving with a frame to carry it and arriving with no
frame at all, painted into the buffer that persists between renders. At the right,
the picture region that repaints itself and the margin outside it that does
not](../images/notice-band.svg)

*A seventh of the glass, in fixed ink over whatever is underneath. The two
smaller pairs are the distinction the whole mechanism turns on: a notice that
could only travel attached to a frame would never arrive in the case it exists
for, which is the camera having stopped. The dashed rectangle at the right is
why taking the band away means writing zeros — the picture repaints itself, and
the margin around it never does.*

Kept by hand: edit [`notice-band.svg`](../images/notice-band.svg) directly, since
nothing regenerates it.

| Class | What it represents, and its part in this scenario |
|---|---|
| [`LcdWorker`](../../src/lcd/lcd_worker.py#L61) | The thread that owns the panel. Here it is the **clock**: it holds the text and its expiry, notices when either the message or its absence differs from what is on the glass, and acts only on that difference |
| [`LcdDisplay`](../../src/lcd/lcd_display.py#L98) | The ASCII grid turned into pixels. Here it is the **painter**: it rasterises the message once, blends it into the frame buffer, and knows that taking a band away means writing zeros rather than simply not writing |
| [`ILI9341`](../../src/lcd/lcd.py#L47) | The panel itself, over SPI. Here it is **indifferent**: it is handed a whole 153,600-byte buffer either way, so a notice costs one full transfer and not a partial update |

## A message appears, and four seconds later it does not

```mermaid
sequenceDiagram
    autonumber
    participant Looper as MainRenderLooper<br/>the render loop's thread
    box rgba(120,140,200,0.10) the lcd thread
    participant W as LcdWorker<br/>owns the panel
    participant D as LcdDisplay<br/>grid to pixels
    end
    participant P as ILI9341<br/>240x320 over SPI

    Looper->>W: notice("the API key was refused", 4.0)
    W->>W: store the text and monotonic now plus four seconds
    W->>W: run wakes after IDLE_TICK with no frame waiting
    W->>W: _tick_notice asks what should be shown, and what is
    W->>D: show_notice(text)
    D->>D: notice_mask wraps to two lines of 44 and caches the result
    D->>D: _paint_notice blends warm white over the bottom 36 rows
    D->>P: show_packed sends the whole frame buffer
    W->>W: four seconds on, _live_notice returns None
    W->>D: clear_notice()
    D->>P: the band zeroed, pushed the same way
```

| Step | Message | What is going on |
|---:|---|---|
| 1 | [`notice`](../../src/lcd/lcd_worker.py#L143)`("the API key was refused", 4.0)` | Called from [`_note`](../../ascii_camera.py#L337), which says the same sentence on every display the run actually has. The terminal gets a status line; the panel gets this. In the enclosure only the second one exists |
| 2 | store the text and monotonic now plus four seconds | Under a [lock](../../src/lcd/lcd_worker.py#L143), because the caller is the render loop's thread and everything below is the panel's. The expiry is stored, not a timer — nothing has to be cancelled if a second notice arrives |
| 3 | `run` wakes after [`IDLE_TICK`](../../src/lcd/lcd_worker.py#L43) with no frame waiting | A fifth of a second. This is the path that matters: no frame is coming, because the thing being reported is often the reason no frame is coming |
| 4 | [`_tick_notice`](../../src/lcd/lcd_worker.py#L297) asks what should be shown, and what is | The comparison is against `_notice_shown`, which records what was last **put on the glass** rather than what was last asked for. Those differ the moment a notice expires, and the difference is the whole trigger |
| 5 | [`show_notice`](../../src/lcd/lcd_display.py#L259)`(text)` | The no-frame path. The frame buffer persists between renders, so the band can be painted over the last good picture and sent without one |
| 6 | [`notice_mask`](../../src/lcd/lcd_display.py#L213) wraps to two lines of 44 and caches the result | A notice stands for four seconds and the panel redraws 27 times a second, so rasterising per frame would put a PIL[^pil] text call back on the hot path — the one thing `lcd_display.py` exists to keep off it. [Two lines](../../src/lcd/lcd_display.py#L37) is the whole budget; a third would start eating the picture |
| 7 | [`_paint_notice`](../../src/lcd/lcd_display.py#L246) blends warm white over the bottom 36 rows | Straight into the RGB565[^rgb565] buffer, arithmetic rather than drawing. It writes to the full frame rather than the picture region, so the band lands on the panel edge whatever margin the grid fit leaves |
| 8 | `show_packed` sends the whole frame buffer | 153,600 bytes, 38 writes of 4,096, about 33 ms. There is no partial update: a notice costs a full transfer, which is affordable precisely because it happens when nothing else is using the bus |
| 9 | four seconds on, [`_live_notice`](../../src/lcd/lcd_worker.py#L162) returns None | Expiry is checked on read rather than swept, so no timer thread exists and a notice cannot outlive the run |
| 10 | [`clear_notice`](../../src/lcd/lcd_display.py#L272)`()` | Reached only because `_band_painted` distinguishes *nothing to clean up* from *a message just expired*. Without that flag the two are the same state and the band would never come off |
| 11 | the band zeroed, pushed the same way | **Zeroed, not skipped.** The picture region repaints itself on the next frame, but the margin strip outside it is never written again — so the band's last row would survive for good. It is the same trap the font-size rebuild has, and the same fix |

The band is drawn on the panel's own thread throughout. The render loop's only
part is the first message: it says the sentence and goes back to work, and
whether the panel is mid-transfer at that moment is not its problem.

## What the band can hold

| Message | Lines |
|---|---|
| `the API key was refused` | 1 |
| `no network - words need one, settings do not` | 1 |
| `asking too fast - wait a moment` | 1 |
| `no picture from the camera for 47s` | 1 |
| `cannot do that: I can change how the picture looks, not where the camera points` | 2 |

Forty-four characters a line, eighty-eight in total, and anything longer is cut
with an ellipsis by [`_wrap`](../../src/lcd/lcd_display.py#L236). Every message
the app generates for a *failure* fits on one line, which is not luck — the
[failure summaries](../../src/language/resolver.py#L180) were written to that
width. Declines are the ones that need two, because their text comes from the
model rather than from this codebase.

## Related scenarios

- [A camera that stopped delivering frames is detected and announced](a-camera-that-stopped-delivering-frames-is-detected-and-announced.md)
  — the biggest customer of this path, and the one where no frame is arriving
  to carry the message.
- [A model parse fails and the panel says which kind of failure it was](a-model-parse-fails-and-the-panel-says-which-kind-of-failure-it-was.md)
  — where the sentences in the table above are chosen, and why they are short.
- [A frame reaches the SPI panel without stalling the render loop](a-frame-reaches-the-spi-panel-without-stalling-the-render-loop.md)
  — the ordinary path this one interrupts, and the thread it shares.

### Footnotes

[^statusline]: The **status line** is the single line of readouts under the
    picture — scheme, ramp, frame rate, grid size — built by
    [`status_line`](../../src/hdmi/status_line.py#L76). It is also where a
    refusal or a notice is shown on the terminal, since there is nowhere else
    to put one.

[^panel]: The **SPI panel** is a 2.4 inch ILI9341 LCD, 240x320, wired to the
    Pi's SPI bus — a four-wire serial bus for talking to peripherals — and
    driven from userspace by [`ILI9341`](../../src/lcd/lcd.py#L47) with no
    kernel driver behind it. In the sealed enclosure it is the only display
    there is. One full frame is 153,600 bytes, sent in
    [`SPI_CHUNK`](../../src/lcd/lcd.py#L44) pieces of 4 KB because that is what
    the driver's buffer holds.

[^apikey]: The key that authenticates a call to the model's API, read from
    [`KEY_FILE`](../../src/language/parser.py#L101) by
    [`api_key`](../../src/language/parser.py#L301). Without one the whole model
    path is switched off rather than failing at the call, which is why every
    path that needs it is `LOW` priority: the appliance runs without it.

[^scheme]: A **colour scheme** is one of the nine named looks in
    [`SCHEMES`](../../src/art/palettes.py#L79), and which one is live is part
    of the render configuration. `grey` is the default, and is what "greyscale
    mode" means: characters only, drawn from the luma plane and nothing else.
    `live` is the only scheme that reads the chroma planes, through
    [`colour_grid`](../../src/capture/image_processor.py#L187). The other seven
    are **tints** — green phosphor, amber CRT, e-ink on paper — which recolour
    the same greyscale picture from two fixed colours.

[^atlas]: A **glyph atlas** is every character of the *ramp* — ten of them for
    the default ramp, not the whole font — drawn once, in advance, into one
    array: [`GlyphAtlas`](../../src/lcd/lcd_display.py#L46). A frame is then
    assembled by copying the right rectangles out of it rather than by drawing
    text, which at 64 by 24 is one array operation instead of 1,536 calls into
    the font renderer. That it holds the ramp and not the font is why changing
    the ramp rebuilds it.

[^ramp]: A **ramp** is the string of characters the picture is drawn with,
    ordered from lightest to darkest — ` .:-=+*#%@` is one. Brightness picks a
    position along it, so the ramp is what decides how the picture looks before
    any colour is involved. The named ones are in
    [`RAMPS`](../../src/art/ascii_art.py#L17) and the setting chooses between
    them.

[^grid]: The **character grid** is the picture as this app holds it: `rows` by
    `cols` character **cells** rather than pixels, each cell one character
    chosen from the brightness of the patch of camera frame it covers.
    [`to_grid`](../../src/capture/image_processor.py#L172) is what resizes a
    plane to it. How big it is depends on where the picture is going — 64 by 24
    on the SPI panel at the default font size, and whatever the window holds on
    the HDMI terminal.

[^coverage]: **Rasterising** a glyph turns its outline into pixels, and what
    comes out is **coverage**: how much of each pixel the shape actually fills,
    0 to 255. Edge pixels land in between, which is what antialiasing is. It
    matters here that coverage is a fade and not a mask — the panel blends the
    cell's colour towards the unlit screen colour by it, so `@` peaking at 239
    rather than 255 is visible rather than academic.

[^notice]: A **notice** is a short message painted over the bottom of the
    picture on the panel — two lines in fixed ink over whatever is underneath,
    sized by [`NOTICE_LINES`](../../src/lcd/lcd_display.py#L37). It is how a
    box with no keyboard and no terminal says something went wrong, and it
    covers 36 of the panel's 240 rows.

[^pil]: The Python Imaging Library, as maintained in Pillow. It is what
    rasterises the glyphs and what the panel's slower path uses to convert an
    image. Its per-call cost is the thing this app organises itself to avoid:
    one call that does a whole frame is fine, 1,536 calls that each do a cell
    are not.

[^rgb565]: **RGB565** is how the panel wants a pixel: two bytes, five bits of
    red, six of green, five of blue — green gets the spare bit because the eye
    is most sensitive to it. [`rgb565`](../../src/lcd/lcd.py#L271) packs one
    colour and [`pack_rgb565`](../../src/lcd/lcd.py#L254) a whole image.
