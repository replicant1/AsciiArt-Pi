# A keypress updates the render configuration

**Priority: `MEDIUM`** — the fastest route into the settings, and the one the enclosure never uses: `--no-terminal`[^headless] means there is no keyboard to press. [What the priorities mean](../how-to-write-scenario-docs.md).

Somebody presses `i` and the picture inverts. It is the shortest path in the
app — no socket[^socket], no parse, no network — and its value is that it is
*only* short, not different. A key builds the same kind of delta[^delta] a
typed line does and hands it to the same `apply`, so a key cannot reach a
setting the socket cannot, or set a value the validator would refuse.

That was not always so, and the history is the reason the code looks as it
does. Each key used to assign its setting directly, which meant every branch
had to remember the consequences of its own change — that `invert`[^invert]
also rebuilds the ASCII generator, that `fill`[^fill] also invalidates the
cached grid[^grid]. A new setting had to remember all of them. **Every branch
now builds a delta and none assigns anything**, so the knowledge lives in one
place.

Two details in the reading are worth having. Keys are **drained**, not sampled:
a single read per frame would fall behind a burst of keypresses at fifteen
frames a second, so the loop consumes everything buffered before fetching the
next frame. And contrast is *nudged* rather than set — `+` adds 0.1 and lets
`apply` clamp it — so the end stops need no arithmetic in the key handler.

| Class | What it represents, and its part in this scenario |
|---|---|
| [`NcursesDisplay`](../../src/hdmi/ncurses_display.py#L34) | The HDMI terminal. Here it is the **keyboard**, and a non-blocking one: [`get_key`](../../src/hdmi/ncurses_display.py#L265) returns a character or `None` and never waits, because the render loop cannot afford to |
| [`MainRenderLooper`](../../ascii_camera.py#L98) | The one object the process is hung off. Here it is the **translator**: [`_handle_key`](../../ascii_camera.py#L608) turns a character into a delta and hands it on, and is the only code in the app that knows which key means what |
| [`RenderConfig`](../../src/control/render_config.py#L118) | The complete live render state, frozen and replaced rather than changed. Here it is the **judge and the reference**: a key that toggles reads the current value from it, and the delta it produces is checked by it |

## One keypress, between two frames

```mermaid
sequenceDiagram
    autonumber
    actor User as somebody at the keyboard
    participant Term as NcursesDisplay<br/>never blocks
    participant App as MainRenderLooper<br/>the render loop's thread
    participant Cfg as RenderConfig<br/>frozen, replaced not mutated

    User->>Term: presses i
    App->>App: _drain_input runs once per frame, after the knob and the socket
    App->>Term: get_key()
    Term-->>App: the character, or None when nothing is waiting
    App->>Cfg: the current value of invert, to toggle it
    Cfg-->>App: False
    App->>App: _handle_key builds a delta and assigns nothing
    App->>App: apply({invert: True}), the same call every other route makes
    App->>Term: get_key() again, until the buffer is empty
```

| Step | Message | What is going on |
|---:|---|---|
| 1 | presses i | One of about a dozen live keys. `q` is the only one that does not produce a delta — it returns `False` and stops the loop, which is the same mechanism a signal[^signals] uses rather than a second way to quit |
| 2 | [`_drain_input`](../../ascii_camera.py#L833) runs once per frame, after the knob and the socket | All three input routes are read at the same point in the loop, so a key, a detent[^detent] and a typed line land in the same place and in a defined order. The knob is read here rather than on a timer of its own for exactly that reason |
| 3 | [`get_key`](../../src/hdmi/ncurses_display.py#L265)`()` | Non-blocking, always. A blocking read would stop the picture whenever nobody was typing, which is most of the time |
| 4 | the character, or None when nothing is waiting | `None` ends the drain. A window resize arrives here too, as the pseudo-key `RESIZE`, which is why a resize and a keypress cannot race — they are the same queue |
| 5 | the current value of invert, to toggle it | A toggle has to read before it can flip. Reading from the config[^config] rather than from a local copy is what stops the key and the socket disagreeing about what `invert` currently is |
| 6 | False | The config is frozen, so this value cannot change underneath the handler between reading it and building the delta |
| 7 | [`_handle_key`](../../ascii_camera.py#L608) builds a delta and assigns nothing | The rule the whole method is written to. A branch that assigned `self.config.invert` directly would work and would silently skip the ASCII rebuild, which is the class of bug this shape makes impossible |
| 8 | [`apply`](../../ascii_camera.py#L235)`({invert: True})`, the same call every other route makes | The convergence point. By the time this is called, nothing distinguishes the keypress from a typed line, a knob detent or a phrase a language model turned into a delta — and `note=True` is the default here, so a refusal is drawn on the picture rather than returned to a caller |
| 9 | [`get_key`](../../src/hdmi/ncurses_display.py#L265)`()` again, until the buffer is empty | The drain. At fifteen frames a second a single read per frame would lag behind anyone typing quickly, and the lag would grow rather than settle |

No thread bands: everything here is the render loop's own thread, which is the
only thread a setting may be changed on. The keyboard is read from it, the
delta is built on it and the change is applied on it — the shortest route in
the app precisely because it never leaves the thread that draws.

`s` is the exception worth noting: it does not build a delta but calls
[`step`](../../src/control/scheme_cycle.py#L133) on the scheme[^scheme] cycle,
so that the key and the knob walk the schemes by one piece of code rather than
two that have to agree.

## Related scenarios

- [A typed command updates the render configuration](a-typed-command-updates-the-render-configuration.md)
  — the same `apply`, reached the long way round, and where a line's types get
  settled first.
- [A render configuration change is refused](a-render-configuration-change-is-refused.md)
  — what a key gets when it asks for something impossible, and why it appears
  on the picture rather than in a reply.
- [One configuration change is pushed to both displays](one-configuration-change-is-pushed-to-both-displays.md)
  — what happens after `apply` accepts, and the consequences a key no longer
  has to remember.
- [A rotary encoder detent changes the colour scheme](a-rotary-encoder-detent-changes-the-colour-scheme.md)
  — the `s` key's other driver, walking the schemes through the same code.
- [The character grid is drawn on the HDMI terminal](the-character-grid-is-drawn-on-the-hdmi-terminal.md)
  — the display this keyboard belongs to, and the one the enclosure does not
  have.

### Footnotes

[^headless]: `--no-terminal` runs the app with no terminal picture at all — a
    stand-in object with the same methods as the display, which does nothing.
    The enclosure boots that way, because there is no monitor attached, so the
    terminal's cost is not wasted so much as never paid.

[^socket]: A **Unix domain socket** is a file-backed pipe between processes on
    one machine — the same read-and-write as a network socket, with no network.
    [`CommandServer`](../../src/control/command_server.py#L80) listens on one,
    which is how a shell, a phone or a script reaches a running camera without
    the app ever opening a port.

[^delta]: A **delta** is a plain dict of the settings a change means to alter —
    `{"scheme": "amber"}` — and nothing else. Every route in builds one and
    hands it to the configuration; none of them assigns a setting directly.
    That is what keeps validation in one place no matter who asked.

[^invert]: The **invert** setting reverses the ramp, so bright pixels get the
    dark end of it — white-on-black becomes black-on-white in effect. It
    reverses the characters and deliberately leaves the position table alone,
    which is how both displays stay in agreement about which glyph a brightness
    deserves.

[^fill]: **fill** and **fit** are the two ways a 4:3 frame can be put into a
    grid of another shape. `fit` keeps all of the picture and leaves blank
    margins — letterboxing. `fill` crops the frame to the grid's on-screen
    shape so no margin remains, at the price of the edges. It is a setting like
    any other, and one of the two that change the grid's shape rather than its
    appearance.

[^grid]: The **character grid** is the picture as this app holds it: `rows` by
    `cols` character **cells** rather than pixels, each cell one character
    chosen from the brightness of the patch of camera frame it covers.
    [`to_grid`](../../src/capture/image_processor.py#L172) is what resizes a
    plane to it. How big it is depends on where the picture is going — 64 by 24
    on the SPI panel at the default font size, and whatever the window holds on
    the HDMI terminal.

[^signals]: `SIGTERM` is how one process politely asks another to stop —
    `systemctl stop` sends it, and `SIGINT` is what ctrl-c sends. Python's
    default for `SIGTERM` exits without unwinding, so no `finally` block runs:
    that is why this app installs a handler that does nothing but set a flag
    and let the ordinary path do the releasing.

[^detent]: A **detent** is one click of the knob — the position it settles
    into, felt as a notch. Electrically it is one full cycle of the two
    switches, which is what [`QuadratureDecoder`](../../src/control/encoder.py#L88)
    counts. **Quadrature** is the arrangement: two switches a quarter-cycle
    apart, so which one changes first says which way the knob turned, and
    contact bounce that does not complete a cycle emits nothing.

[^config]: The **render configuration** is the complete live state of how the
    picture is drawn — scheme, ramp, contrast, rotation and the rest. It is
    frozen: nothing assigns to it, and every change produces a whole new
    [`RenderConfig`](../../src/control/render_config.py#L118) through
    [`with_changes`](../../src/control/render_config.py#L141), which is also
    the only code that decides whether a value is allowed. What the settings
    are, and what each accepts, is
    [`SPECS`](../../src/control/render_config.py#L74) — one table that the
    validator, the `help` text, the command-line arguments and the model's
    tool schema are all built from.

[^scheme]: A **colour scheme** is one of the nine named looks in
    [`SCHEMES`](../../src/art/palettes.py#L79), and which one is live is part
    of the render configuration. `grey` is the default, and is what "greyscale
    mode" means: characters only, drawn from the luma plane and nothing else.
    `live` is the only scheme that reads the chroma planes, through
    [`colour_grid`](../../src/capture/image_processor.py#L187). The other seven
    are **tints** — green phosphor, amber CRT, e-ink on paper — which recolour
    the same greyscale picture from two fixed colours.
