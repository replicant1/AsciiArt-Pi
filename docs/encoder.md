## The rotary encoder

A KY-040 rotary encoder on two GPIO pins, which steps through the colour
schemes. Off unless `--encoder` is given.

```bash
bash run_ascii_camera.sh fit --lcd --encoder
```

### Wiring

BCM numbering, and chosen to avoid every pin the SPI panel uses:

```
CLK -> GPIO 19        + -> 3.3V
DT  -> GPIO 26      GND -> GND
SW  -> GPIO 6
```

**GPIO 6 for `SW` is not an arbitrary free pin.** The module fits pull-ups to
CLK and DT but not to SW, so the switch depends entirely on an internal one —
and this chip defaults GPIO 0–8 to pull-*up* and GPIO 9–27 to pull-*down*. On a
pull-down pin the switch would read as held down from power-on until the app
configured it; on GPIO 6 it idles high throughout. Nothing else was using it,
and it sits two rows from the rotation pins on the header.

The module carries its own pull-up resistors on CLK and DT. That is worth
knowing because it makes the encoder findable: those two pins read high at rest
even though this chip defaults GPIO 9–27 to pull-*down*, so they stand out in a
`pinctrl get 0-27` dump before anything has been configured. `tools/probe_encoder.py`
turns that into a positive identification by watching every free pin while the
knob is turned, and reporting which two interleave.

### Why a state machine and not an edge count

The contacts bounce hard. Measured on this encoder, about twenty clicks produced
453 edges that reduced to 88 once repeats inside a millisecond were dropped —
roughly 5:1. Anything that counts edges, or that samples the partner pin at each
edge, reads that as movement that never happened.

So `src/encoder.py` tracks position within the quadrature cycle using a
transition table, and emits a step only on a complete cycle. Bounce drives the
table back and forth across transitions that emit nothing, so it costs CPU and
nothing else. `tests/encoder_test.py` holds it to that by feeding in modelled
bounce at the measured ratio and demanding an exact step count — it needs no
encoder attached, and it is the only part of this that can be checked without
turning a knob by hand.

One detent is one full cycle on this module (88 edges over ~20 clicks, so ~4.4
each), which is why one click is one scheme.

### One repaint per move, not one per scheme

The knob banks detents between frames, and a fast spin in a slow scheme can bank
several. Applying them one at a time looks harmless and is not: every scheme
change calls `set_scheme()`, which repaints the whole window, so a five-detent
move became five full repaints of pictures that were never on screen long enough
to be seen. It reads as a hard strobe, and it feeds back on itself — a slower
frame gives the knob longer to bank, so the burst grows exactly when it hurts
most.

`_cycle_scheme` therefore takes the whole move at once, walks to the destination
internally, and tells the display once. The intermediate schemes are invisible by
definition, so nothing is lost. The log makes this visible: a two-detent move
writes one `Scheme:` line, not two.

### The button, and what wins when both happen at once

Pressing the knob returns to `grey` in one step, rather than winding back
through the schemes. Pressing again when already there does nothing at all — not
even a repaint, since a repaint you did not need is still a visible flash.

Turning and pressing between the same two frames is resolved in favour of the
press, and the rotation is discarded rather than applied first. Only the *counts*
survive the wait between frames, not the order they happened in, so "turn then
press" and "press then turn" are indistinguishable by the time the render loop
looks at them. Of the two answers available, going home is the one that can be
verified by looking, because it is the same wherever the knob had got to — and
it costs one repaint instead of two.

The switch is debounced at 5 ms against CLK and DT's 200 µs. The rotation pins
have the transition table as a safety net and want a short window so a fast turn
survives intact; the switch has no such net, and nothing about a button needs
sub-millisecond resolution. Only the falling edge is counted, so one press is one
event however long it is held, and releasing does nothing.

### Direction

Which way is "forwards" depends on which of the two pins was called CLK when
wiring, and no amount of code can settle that — it is a coin toss that has to be
resolved by turning the real knob. As wired here, clockwise is forwards, which
is why `--encoder-reverse` exists and is off. If the knob is rewired and runs
backwards, that flag is the whole fix.
