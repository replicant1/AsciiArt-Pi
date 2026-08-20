# Scenarios, by category

One document per mind-sized chunk of behaviour: two to five classes, a sequence
diagram, a table explaining every message in it, and links into the source.
[How to write one](../how-to-write-scenario-docs.md).

The five categories below follow the shape of the machine — light in at the top,
pixels out, and the ways a person changes what happens last. They are the same
grouping the pipeline itself has, which is why an empty one is worth showing:
it says where the gaps are.

**Four written, twenty-one still to write.** Unwritten entries are in bold rather
than linked, because a link to a file that does not exist fails
`tests/docs/docs_links_test.py`.

## Capture

Frames off the camera, and into a shape the rest can use. *None written yet.*

- **`CameraCapture` hands the render loop a frame through a one-slot queue**
- **One YUV420 capture carries greyscale and colour without converting either**
- **`ImageProcessor` rotates, crops and resizes a frame to the character grid**

## Art

Turning brightness into characters, and characters into colour. *None written
yet.*

- **Pixel brightness is mapped to ramp characters**
- **The chroma planes give each character cell its colour**
- **A colour scheme is compiled into a per-cell lookup table**

## The two displays

The HDMI terminal and the ILI9341 panel, which run at the same time and at
different rates. *None written yet.*

- **The character grid is drawn on the HDMI terminal by `NcursesDisplay`**
- **`LcdWorker` renders to the SPI panel without stalling the render loop**
- **The character grid is packed into RGB565 pixels for the ILI9341**
- **The SPI panel shows a start-up screen before the first camera frame**
- **A failure notice is painted over the picture on the SPI panel**

## Getting a change in

Every route by which a setting changes — a typed line, a key, the knob, a
phone, or words — and the one validator they all meet. All four written
scenarios are here, because this is where the app has the most ways in and
therefore the most that has to agree.

- [A typed command updates the render configuration](a-typed-command-updates-the-render-configuration.md)
  — a line on the Unix socket crosses a thread boundary, is parsed into typed
  values, validated, and pushed to both displays.
- [A render configuration change is refused](a-render-configuration-change-is-refused.md)
  — why `rotation 45` is refused in the same words whoever asked, and the one
  check `RenderConfig` is not in a position to make.
- [A spoken phrase is answered from the shortcut table, with no model call](a-spoken-phrase-is-answered-from-the-shortcut-table-with-no-model-call.md)
  — how `a bit more contrast` becomes a delta in microseconds, with no API key,
  no network and no model.
- [A spoken phrase is turned into a config delta by the language model](a-spoken-phrase-is-turned-into-a-config-delta-by-the-language-model.md)
  — what `something calmer` costs instead: a key, a network, and two and a half
  seconds, for a delta nothing downstream can tell from a typed one.
- **Text typed on a phone reaches the render loop over the LAN**
- **A keypress updates the render configuration**
- **A rotary encoder detent changes the colour scheme**
- **One configuration change is pushed to both displays**
- **A model parse fails and the panel says which kind of failure it was**
- **The language model declines a request it cannot satisfy**

## Lifecycle

Starting, stalling, freezing and stopping — the states the machine is in when
it is not simply running. *None written yet.*

- **A camera that stopped delivering frames is detected and announced**
- **A frozen picture is held without redrawing or SPI traffic**
- **The camera, panel, encoder and socket are released on shutdown**
- **Every ask is recorded with its source, its cost and its elapsed time**

---

One scenario is missing from every category above on purpose: window planning
happens in `run_ascii_camera.sh` calling `window_plan.plan()` before any object
exists, so it cannot be drawn as a collaboration between classes. Draw it with
the module named as a module, or leave it to [using it](../using-it.md).

The last two entries under *Getting a change in* are the outcomes the language
model scenario deliberately does not draw: one document per outcome, rather
than one diagram with a branch in it.
