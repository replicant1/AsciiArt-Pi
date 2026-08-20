## Architecture

```mermaid
flowchart TB
    subgraph camthread["camera.py — capture thread"]
        CAP["picam2.capture_array"]
        WRAP["_wrap to YuvFrame<br/>luma plane, stride padding sliced off"]
        CAP --> WRAP
    end

    Q(["frame_queue<br/>maxsize 1, drop oldest"])
    WRAP --> Q

    subgraph mainthread["ascii_camera.py — main thread"]
        GET["camera.get_frame"]
        PROC["ImageProcessor.process<br/>rotate, crop, resize BOX, auto-levels"]
        ART["AsciiArt.to_ascii_text<br/>256-entry LUT"]
        REND["NcursesDisplay.render<br/>xterm-256 colour pairs"]
        GET --> PROC --> ART --> REND
    end

    Q --> GET

    subgraph lcdthread["lcd_worker.py — LCD thread, only with --lcd"]
        INBOX(["_inbox<br/>maxsize 1, drop oldest"])
        LPROC["ImageProcessor, fill=True<br/>its own grid, from the panel font"]
        LART["AsciiArt.to_indices"]
        LREND["LcdDisplay.render<br/>GlyphAtlas gather, pack to RGB565"]
        LSPI["ILI9341.show_packed<br/>spidev, 153600 bytes a frame"]
        INBOX --> LPROC --> LART --> LREND --> LSPI
    end

    GET -->|"submit(frame, RenderConfig)"| INBOX

    REND --> TERM(["HDMI terminal window"])
    LSPI --> PANEL(["2.4 inch ILI9341 panel"])
```

**Both queues hold one frame and drop the older one.** The camera thread
overwrites the pending frame on every capture, so a slow render never
accumulates a backlog — the picture stays current rather than falling
progressively further behind. `LcdWorker.submit()` does the same thing for the
panel, and neither blocks nor raises, so a slow SPI write can never stall the
main loop.

**The LCD is a second pipeline, not a copy of the first.** It takes the same
`YuvFrame` and redoes the work: its own `ImageProcessor` with `fill=True`, its
own `AsciiArt`, and a grid it derives from its own font rather than the
terminal's. It has to. The panel is 64x24 where the window might be 267x100, it
always fills rather than letterboxing, and it can use full RGB where curses is
limited to the xterm-256 palette. What it copies instead is the *settings*: the app's whole
`RenderConfig` rides along with every frame, so pressing `s` or `c` changes both
displays together. It ignores the two fields that are not its business — `fill`,
because the panel always fills, and `target`, because whether it should be
drawing at all is the main loop's decision and shows up as frames simply not
arriving. `lcd_font_size` is the one field that is the panel's alone.

With `--no-terminal` the `NcursesDisplay` branch is replaced by
`HeadlessDisplay`, which renders nothing and only logs — the panel then carries
the picture alone.

### One config, one way in

Every setting that can change while the camera is running lives in a single
frozen `RenderConfig` (`src/control/render_config.py`), and every change to one is a
*delta* — a dict of field names to values — applied through
`MainRenderLooper.apply()`. The keyboard produces deltas. The knob produces
deltas. Nothing anywhere assigns a setting directly.

The settings used to be scattered: some on the `ImageProcessor`, some as plain
attributes of the app, the colour scheme as an index into a tuple, and a
hand-maintained second copy of eight of them in an `LcdConfig` so the panel
could be told what the terminal was doing. Nothing named the full set, so
nothing could validate a change, log one, or hand one to anything else — and
each key binding had to remember its own consequences. `f` had to know to
invalidate the grid *and* repaint; `i` had to know to rebuild the ASCII
generator. Adding a setting meant finding all of those places.

Now `_adopt()` is the one place that knows what each change costs, and it works
off a set of changed field names:

| Changed | What it costs |
|---------|---------------|
| `contrast`, `auto_levels`, `rotation`, `fill`, `mirror` | assignments the processor reads next frame |
| `ramp`, `invert`, `colour_levels` | rebuild `AsciiArt` — the ramp string and its length both move |
| `rotation`, `fill` | invalidate the fitted grid |
| `fill` | repaint, or letterboxed cells keep the old frame's characters |
| `scheme` | `display.set_scheme()`, which repaints every cell |
| `target` | blank the panel, or repaint the window, depending which way |
| `lcd_font_size` | nothing here — the panel reads it off the next frame's config |

Validation splits two ways on purpose. A value outside a **range** is clamped:
contrast 9 is a coherent wish the renderer cannot go all the way to, so it
becomes 4.0, which is what the `+` key always did. A value outside an
**enumeration** is refused, along with an unknown field name or a wrong type —
there is no nearest sensible rotation to 45 degrees and no scheme next door to
"purple", so guessing would be worse than saying no. A refusal names *every*
fault in the delta rather than the first, and changes nothing at all.

One trap worth naming, because it is silent: `bool` is a subclass of `int`, so
`False == 0` and `False in (0, 90, 180, 270)` is `True`. Without an explicit
bool check, a delta meant for `freeze` but addressed to `rotation` would be
accepted as "no rotation" — a wrong field taking a wrong value and reporting
success. `tests/control/render_config_test.py` pins that case down.

`SPECS` in the same module carries the type, the permitted values and a
one-line description of every field, so the schema is derived rather than
restated. A field with no spec, or a spec with no field, fails at import rather
than showing up later as a setting nothing can change — the same shape of trap
`sync.sh` has, where a module missing from its file list is silently never
copied.

### From a phrase to the panel

Two front ends, one path. This is what happens between saying "make it warmer"
and the panel being warmer, whichever way it was said:

```mermaid
sequenceDiagram
    autonumber
    actor Person
    participant CLI as tools/app/asciicam_cli.py
    participant WEB as src/control/web_server.py<br/>phone page, LAN only
    participant SOCK as CommandServer<br/>a thread per client
    participant RES as AskResolver.resolve<br/>same client thread
    participant API as parser.py<br/>and the Claude API
    participant MAIN as render loop<br/>main thread
    participant TERM as HDMI terminal
    participant LCD as LcdWorker<br/>its own thread
    participant PANEL as ILI9341 panel

    alt at a keyboard, over SSH
        Person->>CLI: ask make it warmer
        CLI->>SOCK: "ask make it warmer\n"
    else on a phone, over WiFi
        Person->>WEB: POST /ask, "make it warmer"
        Note right of WEB: the toggle prefixes "ask ",<br/>and that is the only thing<br/>this process changes
        WEB->>SOCK: "ask make it warmer\n"
    end

    SOCK->>RES: _prepare(line), before the loop hears anything
    Note over MAIN,PANEL: the loop never waits for any of this —<br/>the picture stays at 15 fps throughout
    RES->>API: parse(utterance, config, previous_config)
    API-->>RES: set_render {"scheme": "amber", "ramp": "coarse"}
    Note left of API: or decline, which is<br/>an answer, not a failure
    RES->>RES: asklog.record(...) → logs/asks.jsonl
    RES-->>SOCK: Ask(utterance, delta, note)

    SOCK->>MAIN: inbox.put — a delta with nothing left to wait for
    MAIN->>MAIN: take() once per frame, beside the keys and the knob
    MAIN->>MAIN: apply(delta) → RenderConfig.with_changes

    alt the delta validates
        MAIN->>TERM: _adopt: rebuild AsciiArt, repaint, set_scheme
        MAIN->>LCD: submit(frame, RenderConfig) with the next frame
        LCD->>PANEL: glyph atlas → RGB565 → 153,600 bytes over SPI
        MAIN-->>SOCK: "scheme 'grey'→'amber', ramp 'fine'→'coarse'"
    else refused
        MAIN-->>SOCK: every fault in the delta, and nothing changed
    end

    alt back to the CLI
        SOCK-->>CLI: the reply, NUL-terminated
        CLI-->>Person: printed at the prompt
    else back to the phone
        SOCK-->>WEB: the same reply, wrapped in JSON
        WEB-->>Person: appended to the transcript
    end
```

**Both front ends produce the same line.** `src/control/web_server.py` is a client of
the command socket exactly as `tools/app/asciicam_cli.py` is; it forwards what was
typed verbatim, and the app has no field anywhere recording which one sent it.
The single difference is the one the note calls out — the page's **say it in
your own words** toggle prefixes `ask `, which at the prompt you would type
yourself. Turn it off and
the two are byte-identical.

**The slow part runs on the client's thread, never the loop.** A parse crosses
a network and takes two to four seconds; on the render loop that would stop both
displays for the duration. So the resolver does its work before the loop hears
anything, and what reaches the inbox is a delta with nothing left to wait for.
That is why `CommandServer`'s own `REPLY_TIMEOUT` is five seconds while the
CLI's socket timeout is ninety: the loop is only ever asked to apply a dict, and
five seconds of not doing that means it has wedged.

**A parsed delta and a typed one are the same delta.** `commands.run_command`
unwraps the `Ask` and hands it to `apply()` — the same call `scheme amber`
makes, the same `RenderConfig.with_changes` validation, and literally the same
wording on refusal, since both answers come out of the same `_report`. The
model cannot reach anything a typed line could not, which is what makes
`tests/language/parser_eval.py` meaningful: it scores deltas against the validator that
will actually judge them.

**The panel is told last, and indirectly.** `_adopt` pushes the cheap changes
straight onto the processor and repaints the terminal, but nothing calls the
panel. The whole `RenderConfig` rides along with the next frame, so the panel
finds out when it next has something to draw — which is why a change made while
the picture is frozen sets `_redraw` rather than assuming a frame is coming.

**State lives on the app, not on the connection.** `previous_config` is what
`ask undo that` resolves against, and it belongs to the camera rather than to
whoever is connected. So an undo from a phone undoes a change typed at the CLI,
or made with the knob. One history, however many ways in.

### Classes

```mermaid
classDiagram
    direction TB

    class MainRenderLooper {
        +NcursesDisplay display
        +CameraCapture camera
        +ImageProcessor processor
        +AsciiArt ascii_art
        +LcdWorker lcd
        +SchemeCycle schemes
        +AskResolver asks
        +CommandServer commands
        +Namespace args
        +RenderConfig config
        +RenderConfig previous_config
        +bool terminal_on
        +bool lcd_on
        +tuple grid
        +float cell_aspect
        +deque frame_times
        +bool is_running
        +run()
        +apply(delta) tuple
        -_next_frame() YuvFrame
        -_build_picture(frame) tuple
        -_shut_down(started)
        -_adopt(config, previous)
        -_feasible_target(target) str
        -_grid_for(frame_shape) tuple
        -_status() str
        -_handle_key(key) bool
        -_drain_input() bool
    }

    class AskResolver {
        +AskLog log
        +warm()
        +resolve(line) Ask
        +short_failure(error) str$
    }

    class SchemeCycle {
        +RotaryEncoder encoder
        +start_encoder(clk, dt, sw)
        +poll()
        +step(step)
        +home()
        +stop()
    }

    class CameraCapture {
        +int width
        +int height
        +int frame_rate
        +Picamera2 picam2
        +int stride
        +Queue frame_queue
        +Thread capture_thread
        +bool is_running
        +start()
        +get_frame(timeout) YuvFrame
        +stop()
        -_capture_loop()
        -_wrap(frame) YuvFrame
    }

    class YuvFrame {
        +tuple shape
        +ndarray luma
        +ndarray chroma
    }

    class ImageProcessor {
        +float contrast
        +bool auto_levels
        +int rotation
        +bool fill
        +bool mirror
        +float cell_aspect
        +process(luma, cols, rows) ndarray
        +to_grid(plane, cols, rows) ndarray
        +colour_grid(frame, grey, cols, rows) ndarray
        +rotate(frame) ndarray
        +crop_to_aspect(frame, target_aspect) ndarray
        +resize(frame, cols, rows) ndarray
        +adjust_levels(frame) ndarray
        +source_size(width, height) tuple
    }

    class AsciiArt {
        +str chars
        +ndarray lut
        +int colour_levels
        +to_ascii_text(grayscale_frame) list
        +to_indices(grayscale_frame) ndarray
        +to_colour_indices(rgb) ndarray
        -_build_lut() ndarray
    }

    class NcursesDisplay {
        +bool draws
        +window stdscr
        +int rows
        +int cols
        +tuple canvas_size
        +cell_metrics() tuple
        +refresh_size() bool
        +set_scheme(scheme)
        +render(ascii_lines, status, colours)
        +get_key() str
        +message(text)
        +clear()
        +close()
        -_configure()
        -_start_colour()
        -_write_runs(row, col, line, colour_row)
    }

    class HeadlessDisplay {
        +bool draws
        +float status_interval
        +cell_metrics() tuple
        +refresh_size() bool
        +set_scheme(scheme)
        +render(ascii_lines, status, colours)
        +get_key() str
        +message(text)
        +clear()
        +close()
    }

    class Scheme {
        <<NamedTuple>>
        +str name
        +str kind
        +tuple ink
        +tuple screen
        +str note
    }

    class LcdWorker {
        <<threading.Thread>>
        +LcdDisplay display
        +ImageProcessor processor
        +int frames
        +int dropped
        +int errors
        +submit(frame, config)
        +blank()
        +run()
        +stop(timeout)
        -_draw(frame, config)
        -_apply(config)
    }

    class RenderConfig {
        <<frozen dataclass>>
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
        +with_changes(delta) RenderConfig
        +changes_from(other) tuple
        +describe_changes(other) str
        +as_delta() dict
    }

    class LcdDisplay {
        +ILI9341 lcd
        +GlyphAtlas atlas
        +int cols
        +int rows
        +tuple grid_size
        +float cell_aspect
        +set_ramp(ramp)
        +set_font_size(font_size)
        +render(indices, colours, screen)
        +clear()
        +close()
        -_blit(indices)
        -_pack_grey(coverage)
        -_pack_colour(coverage, colours, screen)
    }

    class GlyphAtlas {
        +str chars
        +FreeTypeFont font
        +int cell_w
        +int cell_h
        +ndarray tiles
        -_render() ndarray
    }

    class ILI9341 {
        +int width
        +int height
        +bool landscape
        +SpiDev spi
        +int dc
        +int rst
        +int bl
        +reset()
        +init()
        +set_window(x0, y0, x1, y1)
        +fill(colour)
        +show(image)
        +show_packed(packed)
        +backlight(percent)
        +close()
    }

    class Mouse {
        +int width
        +int height
        +UInput ui
        +move_to(x, y)
        +click(button)
        +click_at(x, y, button)
        +close()
    }

    class Keyboard {
        +UInput ui
        +key(name)
        +type(text)
        +close()
        -_tap(code, shift)
    }

    MainRenderLooper *-- CameraCapture : luma frames
    MainRenderLooper *-- ImageProcessor : rotate, crop, resize, levels
    MainRenderLooper *-- AsciiArt : brightness to characters
    MainRenderLooper o-- NcursesDisplay : render, keys
    MainRenderLooper o-- LcdWorker : only with --lcd
    MainRenderLooper *-- RenderConfig : every live setting
    MainRenderLooper *-- SchemeCycle : the s key and the knob
    MainRenderLooper *-- AskResolver : only with a command socket
    MainRenderLooper o-- CommandServer : typed lines, its own thread
    CommandServer ..> AskResolver : resolver hook, on the client's thread
    SchemeCycle o-- RotaryEncoder : only with --encoder
    LcdWorker ..> RenderConfig : arrives with each frame

    CameraCapture ..> YuvFrame : produces
    NcursesDisplay ..|> HeadlessDisplay : same duck type, draws=False
    NcursesDisplay ..> Scheme : colour pairs

    LcdWorker *-- LcdDisplay : owns once started
    LcdWorker *-- ImageProcessor : its own, fill=True
    LcdWorker *-- AsciiArt : its own, panel grid
    LcdWorker ..> RenderConfig : adopts settings
    LcdWorker ..> Scheme : live, tint or grey

    LcdDisplay *-- GlyphAtlas : pre-rendered glyph tiles
    LcdDisplay *-- ILI9341 : packed RGB565 over SPI

    Keyboard ..> NcursesDisplay : synthetic keys, via the kernel
```

The app core is `MainRenderLooper`, which constructs the camera, processor and
renderer, hence composition; `NcursesDisplay` is aggregation instead, because
`curses.wrapper()` owns the screen and hands the window in. `LcdWorker` is
aggregation for a different reason — it only exists when `--lcd` is passed, so
`self.lcd` is `None` on an ordinary run and every use of it is guarded.

**The LCD half of the diagram is deliberately a parallel of the top half.**
`LcdWorker` owns its *own* `ImageProcessor` and `AsciiArt`, which is why those
two classes appear on both sides of the picture. Nothing is shared but the
`YuvFrame` itself and the immutable `RenderConfig`, and that is what makes
the thread safe: once `start()` is called the worker owns its `LcdDisplay`
outright and the main loop never touches it again. The one channel between them
is `submit()`, which drops rather than blocks.

Underneath, `LcdDisplay` is where the ASCII grid becomes pixels — `GlyphAtlas`
pre-renders every character in the ramp once, so a frame is a single numpy
gather rather than 1,536 `draw.text()` calls — and `ILI9341` is the bare panel
driver, speaking RGB565 over `spidev` with no kernel framebuffer involved.

`Mouse` and `Keyboard` (`tools/hardware/piinput.py`) are **test tooling, not part of the
app** — they create a virtual input device under `/dev/uinput` so the running
application can be driven with synthetic events. The dashed line is deliberate:
nothing imports them. Events travel out to the kernel, through the compositor,
and arrive at `NcursesDisplay.get_key()` indistinguishable from a real
keypress, which is what makes them useful for testing the live controls.

Three parts of the codebase are mostly or entirely functions, so they barely
appear above: `fit_grid()` in `image_processor.py`; all of `window_plan.py`
(`cell_size()`, `plan()`), which `run_ascii_camera.sh` calls when sizing the
window and which the app never imports at runtime; and `palettes.py`, which is
the `Scheme` tuple above plus the lookup tables built from it — `rgb_table()`
for the panel's full RGB and `index_table()` for the terminal's xterm-256
approximation, which is the one place the two displays genuinely diverge.

### Startup

Most of the work before the first frame is done by the supplementary scripts,
not the app: sizing the window, choosing a font, and handing the desktop
session's environment to a process launched over SSH.

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant L as run_ascii_camera.sh
    participant W as window_plan.py
    participant X as lxterminal
    participant M as ascii_camera.py<br/>main()
    participant D as NcursesDisplay
    participant C as CameraCapture
    participant Pi as Picamera2<br/>libcamera

    opt first run only
        U->>U: bash deploy/setup.sh, checks numpy, PIL, picamera2, curses, camera
    end

    U->>L: bash run_ascii_camera.sh fit [args]

    L->>L: export XDG_RUNTIME_DIR and WAYLAND_DISPLAY
    Note right of L: an SSH session inherits neither,<br/>and without them no window appears
    L->>L: wlr-randr, parse the screen size with sed
    L->>L: camera aspect, transposed for a 90 or 270 rotation

    L->>W: plan(request, screen, aspect)
    loop font sizes 6 to 14
        W->>W: cell_size(), real cell metrics from Pango
        W->>W: discard sizes whose window overflows the screen
    end
    W-->>L: COLS ROWS FONT_SIZE CELL_ASPECT

    L->>L: write ~/.config/lxterminal/lxterminal-asciicam.conf
    Note right of L: a dedicated profile, so the user's<br/>own terminal settings are untouched

    L->>X: launch with that profile, geometry and title
    L-->>U: report window, cell aspect, screen and log path

    X->>X: read the profile, map the window
    X->>M: run python3 ascii_camera.py in a pty

    M->>M: set LIBCAMERA_LOG_LEVELS before picamera2 is imported
    M->>M: import picamera2, about 5.4 s on a Zero 2
    M->>M: parse_args()
    M->>M: setup_logging, basicConfig to file then dup2 stderr onto it
    Note right of M: nothing may reach the terminal<br/>once curses owns the screen

    M->>D: curses.wrapper, then NcursesDisplay(stdscr)
    D->>D: noecho, cbreak, nodelay, keypad, hide the cursor
    D->>D: getmaxyx, log the terminal size
    D-->>M: display

    M->>M: build CameraCapture, ImageProcessor, AsciiArt
    M->>D: cell_metrics()
    D-->>M: None on lxterminal, so the passed cell aspect stands

    M->>D: message, starting camera please wait
    M->>C: camera.start()
    C->>Pi: Picamera2, create_video_configuration, YUV420 and FrameDurationLimits
    C->>Pi: configure, then read back the real stride and size
    C->>Pi: start()
    C->>C: spawn the daemon capture thread
    C-->>M: running

    Note over M,Pi: about 8 s from process start to the first frame

    M->>M: enter the main render loop
```

Three ordering constraints in there are not free choices:

- **`LIBCAMERA_LOG_LEVELS` is set at module level**, above the import of
  `camera`. libcamera reads it when its C++ layer loads, so setting it inside
  `main()` would be too late.
- **`setup_logging()` runs before `curses.wrapper()`**, and redirects file
  descriptor 2 rather than just Python's logging. libcamera writes to stderr
  directly, never through `logging`, and a single stray line garbles the
  picture once curses owns the screen.
- **The stride is read back after `configure()`, not assumed.** The ISP may pad
  rows out to a hardware-friendly width, and slicing that padding off is what
  keeps the image from shearing.

The two scripts exist because neither problem can be solved from inside the
app: a process launched over SSH does not inherit the Wayland session, and
lxterminal takes its font size from a config file rather than the command line.
`deploy/setup.sh` is a one-time dependency and camera check, not part of startup.

### Main render loop

```mermaid
sequenceDiagram
    autonumber
    participant T as CameraCapture._capture_loop<br/>background thread
    participant Q as frame_queue<br/>maxsize 1
    participant App as MainRenderLooper.run<br/>main thread
    participant P as ImageProcessor
    participant A as AsciiArt
    participant D as NcursesDisplay
    participant L as LcdWorker<br/>background thread
    participant Pan as LcdDisplay<br/>ILI9341

    Note over T,Q: started by camera.start(), runs until stop()

    loop every sensor frame, rate capped by --fps
        T->>T: picam2.capture_array(main)
        T->>T: _wrap, YuvFrame with stride padding removed
        T->>Q: get_nowait, discard the previous frame
        T->>Q: put_nowait(frame)
    end

    Note over App,D: one pass per rendered frame

    loop while is_running
        App->>D: refresh_size()
        alt terminal size changed
            D-->>App: True
            App->>D: cell_metrics()
            D-->>App: cell pixels, or None on lxterminal
            App->>App: invalidate grid_key
        else unchanged
            D-->>App: False
        end

        alt frozen, and a frame is already held
            App->>App: reuse the held frame
            opt nothing changed since the last draw
                App->>App: poll the controls, sleep 50 ms, next pass
            end
        else running normally
            App->>Q: camera.get_frame(timeout=1.0)
        end

        alt no frame within 1 s
            Q-->>App: None
            App->>App: dropped += 1
            App->>D: message, waiting for camera
        else frame ready
            Q-->>App: YuvFrame, luma h x w uint8

            opt --lcd, and the target includes the panel
                App->>L: submit(frame, self.config)
                Note right of App: never blocks, never raises,<br/>replaces any frame still pending
            end

            Note right of App: with the target on the panel alone,<br/>everything below is skipped entirely

            App->>App: _grid_for(luma.shape), fit_grid unless cached

            App->>P: process(luma, cols, rows)
            P->>P: rotate()
            opt fill mode on
                P->>P: crop_to_aspect()
            end
            P->>P: resize(), PIL BOX area average
            P->>P: adjust_levels(), auto-levels then contrast
            P-->>App: rows x cols uint8

            App->>A: to_ascii_text(grid)
            A->>A: lut[grid], then tobytes().decode() per row
            A-->>App: list of strings

            App->>App: frame_count += 1, frame_times.append()
            App->>D: render(lines, _status())
            D->>D: addstr per row, then refresh()
        end

        loop _drain_input, until nothing is waiting
            App->>D: get_key()
            D-->>App: key, or None when drained
            opt a key was pressed
                App->>App: _handle_key() builds a delta
                App->>App: apply(delta), validated then _adopt()ed
            end
        end
    end

    Note over L,Pan: concurrently, at its own pace — spidev drops the GIL<br/>during the transfer, so this genuinely overlaps

    loop while frames keep arriving
        L->>L: _apply(config), rebuilding ramp and atlas only if changed
        L->>L: ImageProcessor.process to the panel's own grid
        L->>L: AsciiArt.to_indices
        L->>Pan: render(indices, colours, screen)
        Pan->>Pan: GlyphAtlas gather, then pack to RGB565
        Pan->>Pan: show_packed, 153600 bytes as 38 spidev writes
    end

    App->>T: camera.stop()
    App->>L: stop(), join then close the panel
    L->>Pan: clear() then close(), backlight left off
```

The two loops are independent, which is the point of the one-slot queue. The
capture thread never waits for the renderer: it overwrites the pending frame
on every capture, so `get_frame()` always yields the newest image rather than
the head of a growing backlog. A slow render therefore drops frames instead of
falling progressively further behind real time.

Four details the diagram makes explicit:

- **The terminal size is checked every pass**, not just at startup, which is
  what lets the picture refit when the window is resized under it.
- **`get_frame()` blocks for up to a second.** The camera caps its own rate, so
  the main loop needs no pacing of its own — it runs exactly as often as frames
  arrive. A timeout means the camera is still warming up or has stalled, not
  that the loop is spinning too fast.
- **Freezing is the one case that needs its own pacing.** Nothing is being
  waited for, so without a sleep the loop would spin a core redrawing an
  unchanging picture and pushing it down the SPI bus fifteen times a second.
  It draws when something has actually changed — a setting, a resize, a notice
  that has to appear or expire — and otherwise polls the controls every 50 ms.
  The camera is deliberately left running throughout, because stopping it would
  make unfreezing cost the 15–20 seconds libcamera takes to come back.
- **Keys are drained, not sampled.** A single `getch()` per frame would lag
  behind a keypress burst at 15 fps, so `_drain_input()` consumes everything
  buffered before the next frame is fetched.

```
AsciiArt-Pi/
├── ascii_camera.py        entry point, main loop, CLI, live controls
├── run_ascii_camera.sh    launches it in a sized window on the HDMI screen
├── src/                   six packages, one per subsystem
├── tests/                 mirrors src/, plus tests/docs/ for the documents
├── tools/                 app/ hardware/ docs/
├── deploy/                systemd units and the one-time setup scripts
└── docs/                  this, its neighbours, and the published guides
```

The files inside those directories are not listed here on purpose. That list
existed, drifted, and was still describing `src/camera.py` and a flat `tests/`
long after both had moved — a hand-copied inventory of something the code
already states. The **[module map](module-map.md)** and the **[class
overview](class-overview.md)** are generated from the source and guarded by tests that
fail when they go stale; they are where to look.

The three `lcd_*` modules are a deliberate stack rather than one file:
`lcd_worker.py` deals only in threading and settings, `lcd_display.py` only in
turning a character grid into pixels, and `lcd.py` only in what the ILI9341
wants to hear. Only the bottom one knows about SPI, which is what lets
`tests/lcd/lcd_render_bench.py` exercise the render path without a panel attached.
