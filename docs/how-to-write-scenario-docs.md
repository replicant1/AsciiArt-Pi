# How to write a scenario document

Everything needed to add a document to `docs/scenarios/` that matches the ones
already there. Read this first; the two existing scenarios are the worked
examples:

- [A typed command updates the render configuration](scenarios/a-typed-command-updates-the-render-configuration.md)
- [A render configuration change is refused](scenarios/a-render-configuration-change-is-refused.md)

## What a scenario is

The rest of `docs/` is organised by **subject** — a subsystem per file, the
machine described part by part. A scenario is the same machine described by
what its parts **do together**.

One scenario is a mind-sized chunk of behaviour:

- an interaction between **two and about five classes**
- achieving one outcome or sub-outcome that has **discrete value**
- **not necessarily end to end**. Scenarios are meant to compose: several of
  them chained describe a whole journey, but each stands alone
- the units of interaction are **classes**, not files

The granularity to aim for, in the shape of the pipeline: "the camera fills a
frame buffer", "brightness is mapped to ramp characters", "a typed command
updates the render configuration". Not "the app starts up", which is too big,
and not "`_coerce` checks one field", which is too small.

**Not everything is a class.** `src/language/shortcuts.py` has no class at all;
`src/control/commands.py` has only its exception. Where a collaborator is a
module of functions, name the module as the participant and say so plainly in
the cast table — "a module of functions rather than a class". Do not smuggle it
in as though it were a class, and do not avoid the scenario because of it.

## The headline

**Clarity beats brevity.** Before settling on a headline, check that every
important concept is called out by name. A short headline that leaves the
reader guessing what "the change" or "one place" refers to has failed.

| Too vague | Better |
|---|---|
| A refused change is refused in one place | A render configuration change is refused |
| A typed line becomes a config change | A typed command updates the render configuration |
| Brightness becomes characters | Pixel brightness is mapped to ramp characters |
| A knob turn becomes a scheme change | A rotary encoder detent changes the colour scheme |

The same test applies to **section headings inside the document**, where it
matters just as much. "Being refused" and "The one thing RenderConfig cannot
decide" gave no way to tell which of two gates you were about to read about;
"A value `RenderConfig` does not allow" and "A value `RenderConfig` allows, but
this run cannot honour" say it exactly.

The filename is the headline in kebab-case:
`a-render-configuration-change-is-refused.md`.

## The shape of the document

In this order, with no heading before the first diagram section:

1. `# Headline`
2. **Priority line** — one line, ``**Priority: `HIGH`** — why``, linking to the
   criteria. The reason is this scenario's own, not the category's
3. **Description** — two or three paragraphs
4. **Cast table** — one row per class, no heading above it
5. `## A heading naming what this diagram shows`
6. **The diagram**
7. **The step table**
8. Any closing prose about the diagram
9. Repeat 5–8 if the scenario has a second diagram
10. `## Related scenarios`

### 3. The description

What happens, in whose words, and **why it is worth having**. Say what the
value is — "this works against a process with no terminal of its own, where no
key can be pressed" — not merely what the code does.

Then the design tension the collaboration turns on: which layer is allowed to
decide what, and what would go wrong otherwise. Historical facts belong here
when they explain a decision: *"The first version of the parser did refuse bad
choices itself, which put 'must be one of' in two modules and meant
`rotation 45` never reached the validator at all."*

### 4. The cast table

Two columns. No lead-in line and no heading — the header row already says what
the table is.

```markdown
| Class | What it represents, and its part in this scenario |
|---|---|
| [`RenderConfig`](../../src/control/render_config.py#L118) | The complete live render state, frozen so that it is replaced rather than mutated. Here it is the **judge**: [`with_changes`](../../src/control/render_config.py#L141) is the only code in the app that decides whether a value is allowed |
```

- Column one: the class name, linked to **its own `class` line**.
- Column two: what the class represents in general, then its **role in this
  scenario**, with the role word in bold — the *judge*, the *courier*, the
  *translator*, the *applier*.
- Link method names in column two to their definitions.

The role is what keeps this from duplicating the generated
[class map](class-map.md). `MainRenderLooper` is the *applier* in one
scenario and the *caller* in another. **If a cast row would read the same in
every scenario, it is not pulling its weight.**

### 6. The diagram

Mermaid, in a ` ```mermaid ` fence. GitHub renders it natively and
`tools/docs/render_region.js` already depends on mermaid-cli, so it is the
house diagram language — `docs/architecture.md` has five blocks.

```
sequenceDiagram
    autonumber
    participant Asker as whoever asked<br/>key, knob, socket or model
    participant App as MainRenderLooper
    participant Cfg as RenderConfig<br/>frozen, replaced not mutated
```

- **Always `autonumber`.** It matches the existing diagrams and lets the step
  table below be keyed by number.
- **Participant labels carry a second line** via `<br/>` when the thread, the
  role or a key property is worth stating: `one thread per client`,
  `frozen, replaced not mutated`, `module of functions`.
- Prefer a sequence diagram. A collaboration diagram has no native Mermaid
  type; if one is genuinely terser, draw it as a `flowchart` with numbered edge
  labels and say that is what it is.

**Thread bands.** Where a diagram crosses a thread boundary, wrap each side in
a `rect` and put a `note` in it saying which thread and what its constraint is:

```
    rect rgba(128, 128, 128, 0.12)
        note over CS: client's own thread — may block
        ...
    end
    rect rgba(80, 140, 220, 0.12)
        note over App, Cfg: render loop thread — must never block
        ...
    end
```

Band a **boundary**, not every diagram. A single-threaded diagram gets no
bands, and should say so in a line of prose so the absence reads as a decision.

**No `alt`/`else`.** One outcome per scenario. Same cast with a different
outcome is a different collaboration and gets its own document — that is why
the refusal path was split out of the typed-command scenario. Two *sequential*
gates are not alternatives, and may be two diagrams in one document.

#### Mermaid traps, all found the hard way

| Trap | What happens | Fix |
|---|---|---|
| `;` inside a message | Mermaid treats it as a statement separator, truncates the message, loses the arrow, and the whole diagram fails to parse | Use a dash or a comma |
| `rect rgb(245, 245, 245)` | Opaque light grey puts light text on a light ground in GitHub's dark theme | `rect rgba(…, 0.12)` tints instead of painting, and works in both |
| `\|` in a table cell | Ends the cell | Reword |
| A participant aliased `Loop` | `note over Loop:` is read as the `loop` keyword - `Expecting 'ACTOR', got 'loop'` - and the whole diagram fails to parse | Alias it anything else. `Looper` |

**Render before committing.** `mermaid-cli` is installed on the Mac:

```bash
python3 - <<'PY'
import re, pathlib
doc = pathlib.Path("docs/scenarios/NAME.md")
for i, b in enumerate(re.findall(r"```mermaid\n(.*?)```", doc.read_text(), re.S)):
    pathlib.Path(f"/tmp/d{i}.mmd").write_text(b)
PY
mmdc -i /tmp/d0.mmd -o /tmp/d0.png -w 1400 -b white          # light
mmdc -i /tmp/d0.mmd -o /tmp/d0.png -t dark -b '#0d1117'      # dark
```

Then look at both. A diagram that parses is not the same as a diagram that
reads.

### 7. The step table

Three columns, directly under its diagram, one row per message.

```markdown
| Step | Message | What is going on |
|---:|---|---|
| 4 | [`_coerce`](../../src/control/render_config.py#L211)`(rotation spec, 45)`<br>`"rotation must be one of 0, 90, 180, 270, not 45"` | `rotation` is a `choice` spec, so 45 is compared against `(0, 90, 180, 270)` and misses… |
```

- **Step** is the `autonumber` value, right-aligned.
- **Message** reproduces the diagram's message **verbatim**, including its
  second line where it has one (`<br/>` in the diagram becomes `<br>` in the
  table). This is checked — see below.
- **What is going on** is elaboration, never a restatement of the call.

The third column is where the format earns its place. Put in it the facts that
live **between** methods, which a per-class glossary has nowhere to put:

- why a check happens *before* another one — `bool` is excluded before the
  choice comparison because `bool` subclasses `int`
- why a step exists at all — the second field is checked after the first
  already failed, so a caller can fix a whole delta in one pass
- what a constant is defending against — five seconds bounds a *wedged* app,
  not normal work
- the history — `_adopt` exists because "invert also has to rebuild the ASCII
  generator" was once spread across the key handler

A row with nothing to say beyond the message text is a sign the diagram has a
step it does not need.

## Linking

Links are relative paths, never `https://github.com/…` URLs: relative links
work when reading the repo locally, and `docs_links_test.py` checks them, while
external URLs are skipped because resolving them would need a network.

From `docs/scenarios/`, that is `../../ascii_camera.py`,
`../../src/control/render_config.py`, `../../tests/language/parser_eval.py`.

**Use `#L` line anchors.** A bare link to a 310-line file is useless for a
method-level reference. They go stale — which is why the test checks them.

| Link text | Rule |
|---|---|
| Backticked identifier — `` [`with_changes`](…#L141) `` | The line **must define that name**. Checked |
| Prose — `[four KB](…#L47)`, `[the knob](…#L711)` | Only has to land on a definition. Checked |
| A module with no class — `` [`commands`](../../src/control/commands.py) `` | Link the file, with no line |

Link the **name only** and leave call syntax outside:
`` [`take`](…#L258)`()` ``, not `` [`take()`](…#L258) ``.

Finding the line numbers:

```bash
grep -n "^class RenderConfig\|^    def with_changes\|^SPECS" src/control/render_config.py
```

Link freely in all three places — the cast table, the Message column and the
description column — wherever a name, a constant or a number in the prose has a
definition behind it. `[four KB](…#L47)` pointing at `MAX_LINE = 4096` lets a
reader check the document still tells the truth.

## Cross-references

**Name the message, never the step number.** `autonumber` values shift the
moment a message is inserted above them, and nothing outside the step table
checks them.

> …what happens in place of the `_adopt` and `describe_changes` exchange

not "instead of steps 11 to 14". This rule caught a live error the first time
it was applied: a reference to "the resolver at step 3" was already pointing at
step 4.

`grep -n "[Ss]tep[s]\? [0-9]" docs/scenarios/*.md` should find nothing.

## The related scenarios section

A bullet per related scenario, each **naming the relationship** — not just a
link:

```markdown
- [A typed command updates the render configuration](a-typed-command-updates-the-render-configuration.md)
  — the accepted path through the same `apply`, and where a typed line's type
  gets settled before it arrives here.
- **A keypress updates the render configuration** — the route that passes
  `note=True`, so the refusal is drawn on the picture rather than returned.
```

Scenarios not yet written are **bold, not linked** — a link to a missing file
fails the test — with a closing italic line: *"(The unlinked entries above are
documents not written yet.)"*. When the document appears, turn the bold into a
link in the same change, and use the title it actually ended up with.

## Getting the facts right

**Run the code rather than paraphrasing it.** Every refusal message in the
refusal scenario came from executing the path:

```bash
python3 -c "
import sys; sys.path.insert(0, 'src')
from control import render_config, commands
kind, delta = commands.parse('rotation 45 target speaker')
try: render_config.RenderConfig().with_changes(delta)
except render_config.ConfigError as e: print(*e.problems, sep='\n')
"
```

That produced the exact two lines the diagram quotes. It also settles claims
worth checking before writing them down — `SPECS` really is twelve entries;
`contrast 99` clamps to `4.0` rather than being refused.

Other sources of truth: [`docs/class-map.md`](class-map.md) is generated from
each class's own first docstring line, so cast descriptions can lean on it
without drifting; `SPECS` in `render_config.py` is the single source the
validator, the `help` text, the command-line arguments and the model's tool
schema are all built from.

Prefer picking an example that **exercises the point**. `rotation 45 target
speaker` was chosen over a simpler line because it is one of the few typed
commands that reaches the validator carrying *two* problems, which is what
makes "every reason, not the first" demonstrable rather than asserted.

## Before committing

```bash
python3 tests/docs/docs_links_test.py     # 20 checks
```

Its second half exists for these documents and covers what reading cannot see:

- every diagram message has a step table row saying the same thing, numbered
  in order
- every `#L` anchor lands on a definition
- a backticked label names the definition it lands on

It has already caught a real inconsistency — `` [`take()`] `` with the
parentheses wrongly inside the link text — and a stale anchor two lines off its
`def`.

**Add the file to `sync.sh`.** `DOC_FILES` names every document explicitly, and
one that is not in the list is silently never synced to the Pi. No error, it
simply never appears.

```
           scenarios/a-render-configuration-change-is-refused.md
```

## When the code moves under a scenario

Refactoring `src/` breaks these documents in two different ways, and only the
first is loud.

**Line anchors shift.** `docs_links_test.py` catches every one, which is what
the check is for - moving the ask path out of `MainRenderLooper` broke ten
anchors across three scenarios and the suite failed on it. Do not repoint them
by hand from a list of new line numbers; resolve each one by the symbol it used
to name:

```bash
git show HEAD:ascii_camera.py > /tmp/old.py
```

Then, for each stale `#L` anchor: read the `def`/`class` name at that line in
the *old* file, find where that name lives now, and rewrite the anchor. A
symbol that left the file entirely needs an explicit new target - `_poll_encoder`
became `SchemeCycle.poll` in another module, and no amount of line arithmetic
finds that.

**The cast may be wrong, and nothing checks it.** This is the quiet half. When
`_resolve_ask` became `AskResolver.resolve`, the shortcut-table scenario's cast
table still named `MainRenderLooper` as the triage and its diagram still had
a participant labelled `_resolve_ask, on that thread`. Both were now false, and
both passed every check - the anchors resolved, the step table matched the
diagram. Only reading it catches that.

So after any refactor that touches a class named in a scenario, re-read the
cast table and the participant labels. The mechanical checks protect the links,
not the claims.

## Priority

Every scenario carries a priority — `HIGH`, `MEDIUM` or `LOW` — recorded
against it in the [index](scenarios/SCENARIO_INDEX.md) and stated in a line
under the document's own headline. A new document gets its priority in the same change that adds it.

Priority is not "how interesting". It is **what breaks, and how often, if this
collaboration is wrong**. Two facts decide almost every call, and both are
properties of the *deployed* app rather than of the source:

- The boot service runs `ascii_camera.py --lcd --encoder --no-terminal`. In the
  sealed enclosure the SPI panel is the only output and the knob is the only
  input needing no second device. The HDMI terminal, and every key pressed on
  it, are switched off in the shipped product — real code on a real path, but
  not the one the appliance takes.
- The default scheme is `grey`, so the colour path is opt-in rather than
  ordinary.

| Priority | What earns it |
|---|---|
| `HIGH` | On the path **every frame** takes, or the only route by which the shipped device can be seen or driven at all. If it is wrong there is no picture, or no way to change one |
| `MEDIUM` | Runs whenever a person interacts, or once per run, or every frame but only in a configuration the appliance does not boot into. The picture survives without it; the product is diminished |
| `LOW` | Exceptional or optional: failure handling, record-keeping, and the paths that need an API key and a network to run at all |

**Where the `HIGH`/`MEDIUM` line is drawn is the whole of the design.** Drawn at
*per-frame* — the obvious reading — the HDMI terminal renderer outranks the
knob, which is backwards for a box with no monitor attached, and nearly
everything lands in one bucket. A ranking that puts most of its entries at one
level has measured nothing. Drawing it at *the deployed configuration* instead
gives 9 `HIGH`, 10 `MEDIUM`, 6 `LOW`, and each level then answers a different
question: what must never break, what a person notices, and what only matters
on a bad day.

So when a new scenario resists classification, the question to ask is not "is
this important" — everything in the app is — but "does the appliance execute
this on every frame, only when somebody acts, or only when something has gone
wrong or been switched on".

## Scenarios not yet written

Headlines already worked out, at the right granularity:

| Headline | Cast |
|---|---|
| `CameraCapture` hands the render loop a frame through a one-slot queue | `CameraCapture`, `YuvFrame`, `MainRenderLooper` |
| One YUV420 capture carries greyscale and colour without converting either | `YuvFrame`, `CameraCapture` |
| `ImageProcessor` rotates, crops and resizes a frame to the character grid | `MainRenderLooper`, `ImageProcessor` |
| Pixel brightness is mapped to ramp characters | `ImageProcessor`, `AsciiArt` |
| The chroma planes give each character cell its colour | `YuvFrame`, `ImageProcessor`, `AsciiArt` |
| A colour scheme is compiled into a per-cell lookup table | `Scheme`, `palettes`, `NcursesDisplay`, `LcdDisplay` |
| The character grid is drawn on the HDMI terminal by `NcursesDisplay` | `MainRenderLooper`, `NcursesDisplay` |
| `LcdWorker` renders to the SPI panel without stalling the render loop | `MainRenderLooper`, `LcdWorker`, `LcdDisplay` |
| The character grid is packed into RGB565 pixels for the ILI9341 | `LcdDisplay`, `GlyphAtlas`, `ILI9341` |
| The SPI panel shows a start-up screen before the first camera frame | `LcdWorker`, `SplashScreen`, `ILI9341` |
| A failure notice is painted over the picture on the SPI panel | `LcdWorker`, `LcdDisplay`, `ILI9341` |
| Text typed on a phone reaches the render loop over the LAN | `Handler`, `AskLimit`, `Forwarder`, `CommandServer` |
| A keypress updates the render configuration | `NcursesDisplay`, `MainRenderLooper`, `RenderConfig` |
| A rotary encoder detent changes the colour scheme | `RotaryEncoder`, `QuadratureDecoder`, `MainRenderLooper` |
| One configuration change is pushed to both displays | `MainRenderLooper`, `NcursesDisplay`, `LcdWorker` |
| A camera that stopped delivering frames is detected and announced | `MainRenderLooper`, `LcdWorker`, `LcdDisplay` |
| A frozen picture is held without redrawing or SPI traffic | `MainRenderLooper`, `RenderConfig` |
| The camera, panel, encoder and socket are released on shutdown | `CameraCapture`, `LcdWorker`, `RotaryEncoder`, `CommandServer` |

The no-`alt` rule splits some of these further once drawn: a camera that
returns a frame and one that times out are two outcomes, not one diagram with
a branch.

One of them cannot be drawn from classes at all — window planning happens in
`run_ascii_camera.sh` calling `window_plan.plan()` before any object exists.
Draw it with the module named as a module, or leave it to `docs/using-it.md`.
