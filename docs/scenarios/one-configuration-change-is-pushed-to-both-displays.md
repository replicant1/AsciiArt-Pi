# One configuration change is pushed to both displays

**Priority: `HIGH`** — every accepted change of any kind ends here, whichever route asked for it. [What the priorities mean](../how-to-write-scenario-docs.md).

A setting has been validated and a replacement config exists. Something now has
to *happen* — and what has to happen is different for every setting. `contrast`
is an assignment the next frame picks up. `invert` means rebuilding the ASCII
generator. `fill` invalidates the cached grid **and** needs the terminal
cleared, because letterboxing leaves cells the picture no longer writes to and
they would keep the previous frame's characters for good.

The value is that this knowledge lives in **one place**. Before
[`_adopt`](../../ascii_camera.py#L282), "invert also has to rebuild the ASCII
generator" and "fill also has to invalidate the grid" were spread across the
key handler, and every new setting had to remember them all — a list nobody
holds completely, which is the kind of thing that is wrong for months before
anyone notices.

The title is half true, and the half that is false is the interesting one. The
terminal really is **pushed** to: cleared, re-schemed, its grid invalidated,
synchronously and here. The panel is not. It reads its settings out of the
`RenderConfig` it is handed **with the next frame**, so there is nothing to push
— the change reaches it by the ordinary route a moment later, on its own thread.
Which leaves exactly one gap, and the code closes it: if the picture is frozen
there is no next frame, so `_redraw` is set to make one happen.

Nothing here is conditional on which route asked. A key, the knob, a typed line,
a phone and a language model all arrive as a plain dict at
[`apply`](../../ascii_camera.py#L235), and by the time this runs there is
nothing left that could tell them apart.

| Class | What it represents, and its part in this scenario |
|---|---|
| [`MainRenderLooper`](../../ascii_camera.py#L98) | The one object the process is hung off, and the only thread a setting may change on. Here it is the **distributor**: [`_adopt`](../../ascii_camera.py#L282) is the single place that knows what each setting costs to change, and it works from a **set of changed names** rather than from the values |
| [`RenderConfig`](../../src/control/render_config.py#L118) | The complete live render state, frozen and replaced rather than mutated. Here it is the **diff**: `changes_from` says which fields actually moved, so a delta that asks for what is already set costs nothing at all |
| [`NcursesDisplay`](../../src/hdmi/ncurses_display.py#L34) | The HDMI terminal. Here it is the **pushed** one: it is told about a scheme, cleared when the picture's shape changes, and does so synchronously on this thread |
| [`LcdWorker`](../../src/lcd/lcd_worker.py#L61) | The panel's thread. Here it is the **not pushed** one, and deliberately: it reads the whole config out of the next frame it is handed, so the only thing this code does for it is make sure a next frame exists |

## One accepted change, and everything that must be told

```mermaid
sequenceDiagram
    autonumber
    participant App as MainRenderLooper<br/>the render loop's thread
    participant Cfg as RenderConfig<br/>frozen, replaced not mutated
    participant Proc as ImageProcessor
    participant Art as AsciiArt
    participant Term as NcursesDisplay<br/>told synchronously
    participant W as LcdWorker<br/>told by the next frame

    App->>Cfg: changes_from(previous)
    Cfg-->>App: the set of field names that actually moved
    App->>Proc: contrast, auto_levels, rotation, fill, mirror assigned outright
    App->>Art: rebuilt, but only for ramp, invert or colour_levels
    App->>App: grid_key cleared, but only for rotation or fill
    App->>Term: clear, for fill or for a target change
    App->>Term: set_scheme, for a scheme change
    App->>App: _redraw set, so a frozen picture still gets one more frame
    App->>W: nothing - it reads the config it is handed with the next frame
    App->>App: describe_changes logged, one line whoever asked
```

| Step | Message | What is going on |
|---:|---|---|
| 1 | `changes_from(previous)` | The diff, not the config. Everything below keys off names rather than values, which is what makes "did `invert` move" a question with a cheap answer |
| 2 | the set of field names that actually moved | Empty is the common case and returns immediately. A delta asking for what is already set is not an error and not a no-op that still repaints — it costs nothing, which is why `a bit more contrast` at the ceiling is safe to repeat |
| 3 | contrast, auto_levels, rotation, fill, mirror assigned outright | The cheap ones: plain attributes the processor reads on its next frame. Assigned unconditionally because testing whether each moved would cost more than the assignment |
| 4 | rebuilt, but only for ramp, invert or colour_levels | Three settings and one rebuild, because all three change the same object: the ramp string, its reversal, and the quantisation. Rebuilding on `contrast` would throw away a 256-entry table for nothing |
| 5 | grid_key cleared, but only for rotation or fill | The grid is fitted from the frame's shape and the window, so only the settings that change a *shape* invalidate it. `scheme` does not — which is why switching scheme with the knob never resizes the picture |
| 6 | clear, for fill or for a target change | `fill` off leaves letterboxed cells the picture no longer writes to, which would keep the previous frame's characters for ever. A `target` change needs it in **both** directions: switching the terminal off leaves the picture on screen, and switching it back on leaves the off-message under a picture that no longer covers every cell |
| 7 | set_scheme, for a scheme change | The expensive one, and the reason the knob banks its detents: this ends in a full repaint of every cell — some 27,000 in a full-screen terminal — so a five-detent spin applied one at a time was five repaints of pictures nobody could see |
| 8 | _redraw set, so a frozen picture still gets one more frame | The gap in "the panel finds out with the next frame": while frozen there is no next frame. Without this a setting changed on a frozen picture would sit invisible until it was unfrozen |
| 9 | nothing - it reads the config it is handed with the next frame | The panel is handed the whole `RenderConfig` with every frame, so a change reaches it without anything being pushed. There used to be an `LcdConfig` naming eight fields the panel cared about, which meant adding a setting required remembering to add it in two places — and the field it was missing was never going to announce itself |
| 10 | describe_changes logged, one line whoever asked | The one output of the whole exchange, and it names the fields and their old and new values rather than dumping the config. It is also the check that the knob's banking still works: a two-detent move must write **one** line |

No thread bands, and the reason is the substance of the document rather than an
absence of one. Everything here happens on the render loop's thread because
that is the only thread a setting may change on. The panel's thread is a
participant that is deliberately never spoken to — the arrow to it carries
nothing, which is exactly the design.

## Related scenarios

- [A typed command updates the render configuration](a-typed-command-updates-the-render-configuration.md)
  — the route in, and where `apply` calls this.
- [A render configuration change is refused](a-render-configuration-change-is-refused.md)
  — what happens instead when the replacement config is never built, so none of
  this runs and nothing is half-applied.
- [A rotary encoder detent changes the colour scheme](a-rotary-encoder-detent-changes-the-colour-scheme.md)
  — why a banked move is applied as one change, given what a scheme change
  costs here.
- [A frame reaches the SPI panel without stalling the render loop](a-frame-reaches-the-spi-panel-without-stalling-the-render-loop.md)
  — the next frame, which is how the panel actually learns about all of this.
- [A keypress updates the render configuration](a-keypress-updates-the-render-configuration.md) — the shortest route to
  `apply`, and the one that passes `note=True`.
