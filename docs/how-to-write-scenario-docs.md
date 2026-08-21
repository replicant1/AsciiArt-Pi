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
4. **An illustration**, if the scenario has geometry worth showing. Optional,
   and most scenarios do not
5. **Cast table** — one row per class, no heading above it
6. `## A heading naming what this diagram shows`
7. **The diagram**
8. **The step table**
9. Any closing prose about the diagram
10. Repeat 6–9 if the scenario has a second diagram
11. `## Related scenarios`
12. `### Footnotes`, then the **footnote definitions** — one block at the end
    of the file, below *Related scenarios*

### 3. The description

What happens, in whose words, and **why it is worth having**. Say what the
value is — "this works against a process with no terminal of its own, where no
key can be pressed" — not merely what the code does.

Then the design tension the collaboration turns on: which layer is allowed to
decide what, and what would go wrong otherwise. Historical facts belong here
when they explain a decision: *"The first version of the parser did refuse bad
choices itself, which put 'must be one of' in two modules and meant
`rotation 45` never reached the validator at all."*

### 4. The illustration, when there is geometry to show

Some scenarios are about *shape*: a frame that changes proportion, a plane that
is thrown away, a grid that is a hundredth of the size of what fed it. Prose can
only assert that, and a sequence diagram cannot say it at all — it is built to
show who calls whom, not what the data now looks like. Where the substance is
geometric, one drawing does the job of a paragraph and does it better.

`imageprocessor-rotates-crops-and-resizes-a-frame-to-the-character-grid.md` has
the worked example: five panels left to right, the picture as it stands at each
one.

**Draw the data, not the calls.** The sequence diagram already answers *who says
what to whom*. The illustration answers *what does the picture look like here* —
which is why they can sit in one document without repeating each other. If a
draft is turning into boxes with verbs in them, it is a diagram, not an
illustration, and it belongs in mermaid or nowhere.

**Put a motif in the data.** The single decision that made the ImageProcessor
figure work is the letter `F` sitting in the frame: asymmetric on both axes, so
a rotation, a transposition and a mirror are all visible at a glance. Without it
the panels are five blue rectangles and every claim is back in the caption.
Anything with no symmetry will do; a letter is easiest to draw.

**Show what is discarded**, not only what survives. The crop panel is hatched
where `fill` throws rows away, and that band is the whole point of the stage —
a picture of the surviving strip alone would say nothing about what the setting
costs.

**Every number in it is a claim.** Take the dimensions and counts from the
document's own prose, which has already been checked, rather than working them
out again beside it. A figure that disagrees with the paragraph above it is
worse than no figure, and nothing in the suite compares the two.

#### What is worth drawing, and what is not

| Suitable | Why |
|---|---|
| Shapes and proportions changing — rotate, crop, resize, letterbox | It is geometry; a picture *is* the explanation |
| Something being thrown away or kept — cropped bands, dropped frames, a margin never written to | The absence is invisible in prose and obvious in a drawing |
| Sizes collapsing — 76,800 pixels to 2,400 cells, 153,600 bytes to 38 writes | The ratio is the point, and a drawing carries it without arithmetic |
| Layout in memory — planes stacked in one buffer, tiles gathered from an atlas, bytes packed into RGB565 | It has a real shape, and the shape is the reason the code is fast |
| A grid and what fills a cell | The cell is this app's unit; showing one is worth a paragraph |
| The *shape* of a signal — two switches a quarter-cycle apart, and the bounce between them | It is a picture of what the pins do, not of how long they take. Duration is the thing that cannot be drawn honestly; a transition can |

| Not suitable | Why |
|---|---|
| Threads, and which of them may block | Nothing about a thread has a shape. The sequence diagram's bands already say it, and better |
| Timing and elapsed seconds | A duration drawn to scale is a gantt chart, which the mermaid traps table says lies about its own start |
| Control flow, branches, error paths | The no-`alt` rule applies here too: one outcome per document, and the step table carries the ordering |
| Class structure and who owns what | That is the cast table's job, and the [class overview](class-overview.md)'s |
| Anything the sequence diagram already shows | A second drawing of one thing is a second thing to keep true |

#### Drawing it

Hand-written **SVG** in `docs/images/`, referenced from the document like any
other figure. Mermaid stays the house language for the *collaboration* diagram —
but a mermaid flowchart can only name a transposed axis or a dropped band, and
this kind of figure exists to show them, so it is written by hand.

- **A white card, whatever the reader's theme.** GitHub renders markdown light
  or dark; an explicit light background with dark ink reads as a printed figure
  in both, and needs one file rather than a `<picture>` pair.
- **Self-contained.** System font stack, no external images, no script. It is
  served as an `<img>`, so nothing it references from elsewhere will load.
- **About 1180 units wide**, which is roughly the width GitHub gives a document
  before it scales the image down.
- **Panels in a row, captions under each**: what the stage is called above, what
  the data now is below, in two sizes so the dimension line reads as secondary.
- **Alt text describes the picture**, because it is all a screen reader gets —
  not "a diagram of the pipeline" but what is in each panel. The italic caption
  underneath is for everybody and says what to notice, which is a different job.
- **Say that it is hand-drawn**, so the next person does not go looking for the
  script that regenerates it.

**Render it and look at it before committing.** `mermaid-cli` brings a headless
browser with it, which will screenshot an SVG at its real size:

```bash
node -e '
const p = require("/opt/homebrew/lib/node_modules/@mermaid-js/mermaid-cli/node_modules/puppeteer");
(async () => {
  const b = await p.launch(), pg = await b.newPage();
  await pg.setViewport({width: 1200, height: 500, deviceScaleFactor: 2});
  await pg.goto("file:///ABSOLUTE/PATH/figure.svg");
  await pg.screenshot({path: "/tmp/figure.png", clip: {x: 0, y: 0, width: 1180, height: 470}});
  await b.close();
})();'
```

`qlmanage -t -s 1400 -o . figure.svg` is quicker and crops awkwardly; either
way, the point is to look. The first draft of the ImageProcessor figure had its
dashed outline overlapping its own heading, which is invisible in the markup and
obvious the moment it is drawn.

**Add the file to `sync.sh`.** `DOC_FILES` names every image explicitly, and one
that is not in the list is silently never synced to the Pi.

### 5. The cast table

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
[class overview](class-overview.md). `MainRenderLooper` is the *applier* in one
scenario and the *caller* in another. **If a cast row would read the same in
every scenario, it is not pulling its weight.**

### 7. The diagram

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
| `gantt` with `dateFormat X` | An absolute start date is ignored and the bar is drawn from zero, silently - a thread that starts at six seconds claims to start at boot | Position with `after <id>`, which is honoured, or draw the timeline as characters |
| A participant aliased with a keyword - `Loop`, `Box`, `Alt`, `Par`, `Opt`, `End`, `Rect`, `Note`, `Critical`, `Break` | The alias is read as the keyword, `Expecting 'ACTOR', got 'loop'`, and the whole diagram fails to parse. Matching is case-insensitive, so `Loop` and `Box` both collide | Alias it anything else. `Looper`, `Inbox` |

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

### 8. The step table

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

## Footnotes

A scenario is read by people who have not read the other twenty-four, and by
people who have never seen the domain. Both are lost by the same mechanism: a
word the writer no longer notices using. Footnotes are how a document stays
readable to them without the body turning into a tutorial — the sentence keeps
its pace, and the definition waits at the bottom for whoever needs it.

### Two kinds of term, and the second is the one that gets missed

**Domain vocabulary** is the easy half, because it looks unfamiliar on the
page: `ISP`, `YUV420`, stride, a daemon thread, a numpy view. Anyone can see
that those need explaining.

**The app's own vocabulary** is the half that gets past the writer, because it
is what they say every day: *greyscale mode*, *colour scheme*, *the character
grid*, *the ramp*, *the LCD worker*, *the Zero 2*. Each is a phrase in plain
English that means something exact here and nothing in particular anywhere
else. *Greyscale mode* is the one that started this rule: it means the `grey`
scheme, and a reader who does not yet know the app has nine schemes, one of
them the default, cannot get there from the words.

Two questions catch it:

- Is the term a **name in `src/`** — a class, a scheme, a setting, a mode? Then
  it is this app's word for this app's thing, however ordinary it sounds.
- Would understanding it need **another document to have been read first**?
  Scenarios are meant to be read out of order, so "it is explained in the
  colour-scheme one" is not an answer.

### What does not earn a footnote

- A term the sentence already explains. `Daemon, so a wedged capture cannot
  keep the process alive` has done the work — that one carries a note only
  because "daemon" also means something else in Unix, which the sentence does
  not say.
- **Design reasoning.** Why the collaboration is shaped this way belongs in the
  description or in the step table's third column. A footnote that argues is a
  paragraph that landed in the wrong place. Define the term, then give the one
  fact that makes it matter here: the `YUV420` note earns its length by ending
  at the 76,800 and 38,400 bytes the body is already quoting.

### Mechanics

GitHub Flavored Markdown: `[^label]` where the term is, `[^label]: …` at the
end of the file. GitHub collects the definitions into its own *Footnotes*
section wherever they sit in the source, renders each marker as a numbered
link, and gives every note a `↩` back to where it was referenced.

- **Label with a word, not a number** — `[^stride]`, `[^scheme]`. The rendered
  numbering is automatic and follows first use, so inserting a term never
  renumbers anything by hand.
- **Mark the first use only.** A second reference to the same note is fine
  where it genuinely helps — `[^scheme]` is used at *colour scheme* and again
  at *greyscale mode* — and GitHub gives both markers one number and the note
  two back-links, `↩` and `↩2`.
- **Order the definitions by first use**, which is the order they render in.
- **One term, one note, word for word.** `ISP`, the character grid and the
  colour schemes are explained in a dozen documents each. Copy the wording
  rather than writing it again: a reader who has met the note before should
  recognise it and move on, and two notes that drift apart are two claims to
  keep true. All 25 scenarios draw on one set of 56, and the commonest — the panel, the
  colour schemes, the character grid — carry half the documents each.
- **Head the block `### Footnotes`, at level three.** GitHub's own footnotes
  heading exists but is screen-reader-only, so without one the notes arrive
  on the page with nothing naming them — and the level matters, because
  `.markdown-body h2` carries a `border-bottom` and `.markdown-body
  .footnotes` a `border-top`. At level two that is two grey rules stacked
  under the word; at level three it is the section's own, which is the one
  that belongs there. The heading has to be the last thing before the
  definitions, since they render where they sit.

### Two placements that break things

**Never inside a diagram message or the step table's Message column.**
`docs_links_test.py` compares those two verbatim after stripping links,
backticks and bold — and a `[^x]` survives that stripping, so the check fails
with the row and the message differing by exactly the marker. Put the marker in
the third column instead, which sits beside the message anyway. This is the
only one of the two mistakes that is caught for you.

**Never immediately before a colon.** `the character grid[^grid]: the ISP does
the downscale` renders correctly, but `[^grid]:` is also what a *definition*
looks like, so it misleads a reader of the raw file and anything scanning for
one. Reword, or use a dash.

### Checking them

Nothing in the suite pairs markers with definitions, so do it directly — an
orphan marker renders as literal text on the page, which is easy to miss in a
document that has a dozen real ones:

```bash
python3 - <<'CHECK'
import re, pathlib
s = pathlib.Path("docs/scenarios/NAME.md").read_text()
defs = re.findall(r"(?m)^\[\^([\w-]+)\]:", s)
refs = re.findall(r"\[\^([\w-]+)\]", re.sub(r"(?m)^\[\^[\w-]+\]:.*$", "", s))
print("orphan refs:", set(refs) - set(defs), " unused defs:", set(defs) - set(refs))
CHECK
```

The harder question is not whether the notes are wired up but whether a term
was missed, and the answer is not to re-read looking for them — the terms a
writer misses are exactly the ones that look ordinary to them. Extract the
candidates from the prose instead, the way
[`check_glossary.py`](../tools/docs/check_glossary.py) does for the build
guides: take the terms already glossed anywhere in `docs/scenarios/`, and for
each document report the ones it uses without a note. That sweep is what added
the last 40-odd markers across the 25 documents, including every mention of the
character grid in the two documents named after it.

Everything else applies as it does in the body: `#L` anchors inside a footnote
are checked like any other, so link into `src/` freely, and **measure the
claims**. The stride note says the stride comes back equal to the width because
the running service logs `stride=320`, not because the code reads as though it
would.

### Where they are not links

On GitHub they are links, in both directions. In the raw file, and in VS Code's
built-in preview, `[^isp]` shows as literal text — that preview needs the
`bierner.markdown-footnotes` extension before it renders them at all. Worth
knowing before concluding a document is broken.

Thirteen notes is the most any document carries and four the least, against a
median of nine. One per term, at first use, and only for terms.

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

Other sources of truth: [`docs/class-overview.md`](class-overview.md) gives each
class a synopsis of what it is for, which is where a cast row's *role* should
differ from rather than repeat; `SPECS` in `render_config.py` is the single source the
validator, the `help` text, the command-line arguments and the model's tool
schema are all built from.

Prefer picking an example that **exercises the point**. `rotation 45 target
speaker` was chosen over a simpler line because it is one of the few typed
commands that reaches the validator carrying *two* problems, which is what
makes "every reason, not the first" demonstrable rather than asserted.

## Before committing

```bash
python3 tests/docs/docs_links_test.py     # 31 checks
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

They are listed in the **[index](scenarios/SCENARIO_INDEX.md)**, grouped by
category, each with its priority and the cast already worked out.

The list used to be a table here as well, which meant two inventories of one
thing: they drifted apart three times before this paragraph replaced the
second copy - fifteen entries here against eighteen there, and only one of
them carrying priorities. The index is the authority now, and adding a
document means striking it off exactly one list.

Two things about that list are worth knowing before picking from it. The
no-`alt` rule splits some of its entries further once drawn: a camera that
returns a frame and one that times out are two outcomes, not one diagram with
a branch. And one entry cannot be drawn from classes at all - window planning
happens in `run_ascii_camera.sh` calling `window_plan.plan()` before any
object exists. Draw that one with the module named as a module, or leave it to
`docs/using-it.md`.
