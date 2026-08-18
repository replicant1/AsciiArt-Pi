# Telling it what to do

### Typing settings by name

The single-key controls are quick but fixed: one key per setting, and no way to
say *how much*. Alongside them the app opens a local command socket, so any
setting can be set by name from a shell:

```bash
python3 tools/app/asciicam_cli.py            # a prompt
python3 tools/app/asciicam_cli.py show       # or one command and out
```

```
ascii> scheme green
  scheme 'grey'->'green'
ascii> contrast 2.4 invert on freeze off
  contrast 1.0->2.4, invert False->True
ascii> rotation 45
  rotation must be one of 0, 90, 180, 270, not 45
```

`help` lists every setting with its permitted values and current value, `show`
prints the values alone, and `reset` returns to the start-up defaults. **The
help text is generated from `SPECS`**, so a setting added to `RenderConfig` is
documented the moment it exists and cannot be forgotten.

This works against the systemd service, which has no terminal of its own and
cannot otherwise be typed at — that is most of the reason it exists.

### Saying it in your own words

`ask` sends the line to a language model, which works out which settings the
words mean:

```
ascii> ask make it warmer and blockier
  scheme 'grey'->'amber'
  (3.9s)
ascii> ask undo that
  scheme 'amber'->'grey'
  (3.7s)
ascii> ask green and turn the volume up
  scheme 'grey'->'green'
  (3.9s - There's no audio, so no volume to turn up.)
ascii> ask make me a sandwich
  I can only adjust the camera's display settings - no sandwiches here.
```

**The model proposes; `RenderConfig` disposes.** What comes back is a delta,
and it goes through the same `apply()` a typed command uses and is refused in
the same words — so a model that asks for `rotation 45` gets
`rotation must be one of 0, 90, 180, 270`, exactly as you would. There is no
path from the model to the hardware that skips the validator.

Two things make it work at all on a Zero 2:

- **The parse happens on the command socket's own thread, never the render
  loop.** It crosses a network and takes about four seconds; the loop cannot
  stop for that without stopping both displays. By the time the loop sees the
  request it is a dict, indistinguishable from a typed one.
- **The SDK is imported at start-up, in the background.** `import anthropic`
  alone costs 11 seconds on this hardware — longer than the CLI used to wait
  for any reply. Left lazy, the first `ask` after every restart timed out on
  the client while quietly succeeding on the app: a reported failure *and* a
  changed setting, which is the worst of both.

`ask` needs an API key at `~/.config/asciicam/api_key` (or `ANTHROPIC_API_KEY`
in the environment). Without one it says so and points at the fix; every other
command works exactly as before. The key lives outside the project tree on
purpose — `sync.sh` copies an explicit file list, and a key inside the tree is
one careless `git add -A` from a public commit.

The tool schema the model is given is **generated from `SPECS`**, the same
source as the `help` text and the validator's own rules. Add a setting and it
becomes typeable, documented, and askable at once — see
[One config, one way in](../architecture.md#one-config-one-way-in). `tools/app/ask_parser.py` runs
utterances against the parser without involving the camera, which is where the
prompt gets tuned; it costs roughly 0.35p a sentence. It is a
Unix socket with mode 0600, so it is not reachable from the network and only
the user running the app can connect; `--no-commands` switches it off.

**The split is the point, not the parsing.** `src/control/commands.py` turns text into
typed values and stops there; `RenderConfig` decides what is allowed. So
`rotation 45` parses cleanly and is refused one layer down, in the same wording
every other route gets. When a language model is added it will produce deltas
the same way and be judged by the same code — which is the only thing that
makes comparing them meaningful. A front end that quietly accepted more than
the validated path would let a phrase work by hand and fail through the parser.

With `--encoder`, a KY-040 rotary encoder cycles the colour schemes too:

| Knob | Effect |
|------|--------|
| Turn clockwise | Next colour scheme — what `s` does |
| Turn anticlockwise | Previous colour scheme — what `s` cannot do |
| Press | Jump straight back to `grey`, however far the knob has wandered |

It needs no window focus, and it works under `--no-terminal`, where there is no
keyboard to press `s` on. See [The rotary encoder](encoder.md#the-rotary-encoder).

Every toggle reads out its current state on the left of the status bar, so
nothing is hidden:

```
 15.0fps 267x100 rot180 con1.0 sch:grey chr:coarse auto:on fill:off inv:off tgt:both lcd:64x24@8 | q:quit ...
```

The key hints on the right are dropped in whole groups when the window is too
narrow to hold them; the readouts on the left always stay. A refused change —
an impossible target, say — takes the hints' place for four seconds, since the
hints are the same every frame and the message is the answer to what was just
pressed.

`--ramp` takes a name and nothing else — there is no way to supply the ramp
characters yourself. It used to accept an arbitrary string, which meant a
mistyped name was silently taken as a literal ramp: `--ramp standard` drew the
picture out of the eight letters of the word rather than complaining. It is now
rejected, listing the names that do work.

### The phrases that skip the model

`ask make it green` used to cross a network, wait 2.6 seconds and cost a third
of a US cent to work out `{"scheme": "green"}` — which is the scheme's own name,
said out loud. `src/language/shortcuts.py` answers that class of phrase from a table
before any model call or key check happens. (Not "before the parser is
imported" — `_warm_parser()` imports it at start-up when a key is present,
so the first ask of a run does not pay an 11-second import.)

Measured end to end through the phone page, against the running service:

| Utterance | Answered by | Wall clock | Tokens |
|---|---|---|---|
| `green` | table | 0.24 s | none |
| `a bit more contrast` | table | 0.10 s | none |
| `undo that` | table | 0.13 s | none |
| `freeze it` | table | 0.10 s | none |
| `something calmer` | model | 2.6 s | 2,562 |

**The table is exact and the model is fuzzy, and that split is the whole
design.** It matches a normalised string — case, spacing, trailing punctuation
and politeness removed, nothing else — and returns nothing the moment it is not
certain. A table that guessed would be competing with the model at the thing the
model is for, and losing quietly: a near-miss becomes a wrong setting with no
round trip to blame it on. Normalisation is deliberately shallow for the same
reason; stemming would let two different requests collapse into one string, and
"a bit more contrast" is not "way more contrast".

Four kinds of entry earn a place:

- **A setting's own value, said out loud** — `green`, `make it amber`,
  `fine characters`. Generated from `SPECS`, so a scheme added to `palettes.py`
  is speakable the same day without editing the table, for the same reason
  `help` and the tool schema are generated from it.
- **A boolean said as a verb** — `freeze it`, `invert it`.
- **A step along a range** — `a bit more contrast` is ×1.3 from wherever
  contrast is now, clamped to its own spec, so a step at the ceiling is a no-op
  rather than a refusal. These are functions of the live config, not constants.
- **`undo that`**, which is not a guess at all: the app knows the previous
  config exactly, so the restoring delta is arithmetic. The model can only
  approximate this from a sparse description in its prompt.

Left to the model on purpose: anything with a mood in it (`something calmer`),
anything compound (`green, high contrast, and the fine ramp`), the target
phrasings, and every phrase that should be declined. **A table cannot decline
well** — it can only fail to match, which is not the same thing.

Two properties fall out of putting the lookup before the key check, and both are
worth more than the money:

- A hit needs **no API key and no network**. With the WiFi down, `green` and
  `freeze it` still work, so `ask` stops being all-or-nothing.
- A hit is **instant**, which on a 240×320 panel with no spinner is the
  difference you actually feel.

`tests/language/shortcuts_test.py` guards the two things that are not obvious by
inspection. Every decline case in `eval_cases.json` must **miss** the table. And
where the table and the model answer the same phrase — 7 of the 41 eval cases —
the table's delta is scored by `parser_eval.py`'s own scorer against the same
expectations, bands included, so the two cannot drift apart unnoticed. A third
guard runs at import: every delta the table can produce must survive
`RenderConfig`, so a renamed scheme fails at start-up rather than in front of
somebody using the camera.

Every ask is recorded in `logs/asks.jsonl` with a `source` of `model` or
`table`. That distinction decides what a record is evidence *of* — a table hit
says nothing about the prompt, because the model was never asked — so anything
counting hit rate or promoting real utterances into eval cases has to filter on
it.

### When something goes wrong, the panel says so

In the enclosure the panel is the only output there is. A failure that reaches
only the status line, or only the socket reply, has been reported to whoever
happened to be holding a phone — not to the person standing in front of the
camera watching nothing happen. So `_note()` now says it on every display this
run actually has, and the failures all go through it:

| What happened | What the panel says |
|---|---|
| The parse is in flight (2–4 s) | `asking: make it warmer and blockier` |
| Network down | `no network - words need one, settings do not` |
| Timeout | `the model took too long - try again` |
| Key refused | `the API key was refused` |
| Rate limited | `asking too fast - wait a moment` |
| The model declined | `cannot do that:` and its own wording |
| No key at all | `no API key, so words are off` |
| **The camera stopped** | `no picture from the camera for 95s` |

The in-flight message is not politeness. A parse takes two to four seconds, and
on a panel with no spinner that is indistinguishable from a camera that ignored
you — which is the same failure as any other, just quieter.

**The notice is a band drawn into the RGB565 buffer after the picture is
packed**, not part of the character grid. The glyph atlas holds only the ramp,
so the grid literally cannot spell anything; and text tinted by whatever cell
colours happened to sit under it would be unreadable exactly when it mattered.
Fixed ink on a fixed band is legible over every scheme including `live`, and
`tests/panel/notice_test.py` asserts the band comes out byte-identical over a bright
picture and a blank one.

**The stalled camera is the case that shaped the design.** On 18 August an OOM
storm killed the desktop session, capture stopped at 09:20, and the app kept
redrawing its last frame for ninety-five minutes. Every check said healthy — the
render loop answered the command socket in 1.4 s — and the panel showed a
picture. A frozen picture and a working camera are indistinguishable by eye.
Now, ten seconds after frames stop, the panel says so, and repeats every thirty
seconds while it is still true.

That message is the one a frame-driven display cannot deliver: there are no
frames for it to ride on. The frame buffer is persistent, so it is painted over
whatever picture is already up there and pushed on its own.

**Verification is split, because it has to be.** `tests/panel/notice_test.py` (36
checks) covers the geometry, the caching, the wrapping, the frameless path and
the stall thresholds, and was checked by breaking the implementation four ways —
each mutant failed exactly the tests meant to catch it. What no test on this
machine can answer is whether the result is *readable*: nothing here can see the
SPI panel. `tools/hardware/notice_demo.py` holds a message still on the real panel for as
long as you like, over a bright gradient — the hardest case for legibility —
so a person can judge it:

```bash
sudo systemctl stop ascii-camera            # it owns the panel
python3 tools/hardware/notice_demo.py --message decline --seconds 120
sudo systemctl start ascii-camera
```

Confirmed by eye on the real panel: two lines, wrapped on a word boundary, the
overflow ending in an ellipsis. Long declines are truncated there; the full text
still goes back to whoever asked and into `logs/asks.jsonl`.

### Saying it from a phone

The enclosure seals the box. Its east wall carries mini-HDMI and USB-C power and
nothing else, so once it is shut the input inventory is the encoder, the
shutdown button, the camera and WiFi — and everything on that list except WiFi
carries a few bits per second. Natural language needs a keyboard, and the best
keyboard available is the one already in a pocket.

`src/control/web_server.py` serves one page to a phone on the LAN and forwards whatever
is typed into it to the command socket, verbatim:

    phone -> HTTP -> web_server.py -> Unix socket -> resolver -> render loop

Start it by hand, or install `deploy/ascii-camera-web.service` to have it come up at
boot:

```bash
python3 src/control/web_server.py                    # 0.0.0.0:8080, LAN only
sudo cp deploy/ascii-camera-web.service /etc/systemd/system/ && \
  sudo systemctl enable --now ascii-camera-web
```

Then open `http://<the Pi's address>:8080/` on the phone. The page is one text
box with a **say it in your own words** toggle (on by default, and all it does
is prefix `ask `), chips for `show`, `help` and `reset`, and a transcript of
what came back. It is a single self-contained document — no fonts, scripts or
styles from anywhere else, because the phone may well be able to reach the Pi
and not the internet.

**It is a client of the socket, not a part of the app.** Nothing new reaches the
render loop; a web request becomes a typed line one step in and is then
indistinguishable from one typed at `tools/app/asciicam_cli.py` — same validation,
same wording, same single entry point. That is worth more than it sounds:

- The render loop cannot be hurt by a bug in here. The worst this can do is not
  answer.
- It is startable, stoppable and testable with the camera running. The service
  owns the camera and `/dev/spidev0.0`; this owns a TCP port, and the two never
  contend — `tests/control/web_server_test.py` runs against the live app without
  disturbing it.
- The money switches off separately. `systemctl stop ascii-camera-web` ends
  asking from the network; the picture carries on.

Three things guard it, because this is the only part of the build reachable from
the network at all:

- **IPv4 only.** This Pi has a globally routable IPv6 address, and a listener on
  it would be reachable from outside the house the moment the router allowed it.
  Binding `AF_INET` means there is no such address to reach — a stronger
  guarantee than a firewall rule nobody will re-check.
- **Private source addresses only.** Anything that is not RFC1918, loopback or
  link-local is refused before the body is read. A second fence, and the one
  that still stands if the box is ever port-forwarded by accident.
- **A rate limit on the requests that cost money.** `ask` spends an API call;
  every other line is free, so only asks are counted — 20 a minute, across all
  clients, because the hazard being guarded is a bill and a bill does not care
  which phone ran it up. Being capped never stops you typing a setting by name.

`GET /health` says whether the app is listening without sending it anything: a
health check that cost an API call, or woke the render loop, would be a worse
problem than the one it diagnoses. The page uses it to light the dot beside the
title.

Measured end to end from a laptop on the same WiFi, against the running
service: `ask warmer, and finer characters` took 5.1 s round trip, 3.9 s of
which was the model. `show` came back in well under a second. The utterance
landed in `logs/asks.jsonl` in exactly the shape a typed one does, which is the
check that the two paths really are one path.
