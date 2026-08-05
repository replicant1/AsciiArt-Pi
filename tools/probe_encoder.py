#!/usr/bin/env python3
"""
Find which GPIO pins a rotary encoder is wired to, by watching them move.

A static pin dump cannot do this.  A KY-040 fits pull-up resistors to CLK and
DT but usually not to SW, so the switch is indistinguishable from an unconnected
pin until someone presses it.  Reading levels once also cannot tell CLK from DT,
and getting those two the wrong way round silently reverses the knob.

So this records edges on every free pin while a human works the control, and
identifies each pin by what it did:

  CLK and DT  the two busiest pins, and - the part that matters - pins whose
              edges interleave.  Quadrature means neither ever changes twice in
              a row without the other changing in between.  Two pins that were
              merely noisy do not do that.
  SW          isolated edges, far apart, with no partner pin moving with them.

Every pin is claimed with an internal pull-up so that an unconnected pin sits
high and stays quiet, rather than floating and inventing edges.

Deliberately claims no pin the LCD uses (8, 9, 10, 11, 18, 25, 27) - the panel
may still be lit - nor 0/1 (HAT EEPROM), 2/3 (I2C, hardware pull-ups) or 14/15
(the serial console).

    python3 tools/probe_encoder.py [seconds]
"""

import json
import sys
import time
from collections import defaultdict

import lgpio

# Free on this Pi: everything not spoken for by the panel, the EEPROM, I2C or
# the console.  Probing a pin already driven as an output would fight it.
CANDIDATES = [4, 5, 6, 12, 13, 16, 17, 19, 20, 21, 22, 23, 24, 26]

# A KY-040's mechanical contacts bounce for a few hundred microseconds.  Edges
# closer together than this on one pin are the same physical transition.
DEBOUNCE_NS = 1_000_000          # 1 ms

# Two edges this close on different pins came from one movement, not two.
PAIR_WINDOW_NS = 30_000_000      # 30 ms

# Enough edges to decode a direction from, and how long the knob must sit still
# before the recording is taken to be finished.
MIN_EDGES = 12
# Generous, because the natural way to work a knob is to turn it, pause, and
# then press - and stopping during that pause would miss the switch entirely.
QUIET_SECONDS = 8


def record(seconds):
    """Claim every candidate and collect timestamped edges for `seconds`."""
    handle = lgpio.gpiochip_open(0)
    events = []
    callbacks = []

    def on_edge(_chip, gpio, level, tick):
        # level 2 is a watchdog tick, not a real edge.
        if level in (0, 1):
            events.append((tick, gpio, level))

    claimed = []
    for pin in CANDIDATES:
        try:
            lgpio.gpio_claim_alert(handle, pin, lgpio.BOTH_EDGES,
                                   lgpio.SET_PULL_UP)
            callbacks.append(lgpio.callback(handle, pin, lgpio.BOTH_EDGES,
                                            on_edge))
            claimed.append(pin)
        except Exception as e:
            print(f"  skipped GPIO {pin}: {e}", file=sys.stderr)

    print(f"Watching GPIO {', '.join(str(p) for p in claimed)} "
          f"for up to {seconds} seconds.", flush=True)
    print("Turn the knob slowly clockwise about ten clicks, then "
          "anticlockwise ten clicks.  No hurry - this waits.", flush=True)

    # Waiting out the whole window wastes a minute of someone's time, and
    # cutting it short loses the data, so end on the knob going quiet rather
    # than on the clock: once enough edges have arrived, stop when they stop.
    # The clock is only the backstop for a knob that never moves at all.
    deadline = time.time() + seconds
    seen = 0
    while time.time() < deadline:
        time.sleep(0.2)
        if len(events) > seen:
            seen = len(events)
            quiet_since = time.time()
        elif seen >= MIN_EDGES and time.time() - quiet_since > QUIET_SECONDS:
            print(f"  {seen} edges, and the knob has been still for "
                  f"{QUIET_SECONDS}s - stopping.", flush=True)
            break

    for cb in callbacks:
        cb.cancel()
    lgpio.gpiochip_close(handle)
    return sorted(events)


def debounce(events):
    """Drop repeat edges on one pin inside the bounce window."""
    last = {}
    kept = []
    for tick, gpio, level in events:
        if gpio in last and tick - last[gpio] < DEBOUNCE_NS:
            continue
        last[gpio] = tick
        kept.append((tick, gpio, level))
    return kept


def interleaving(events, a, b):
    """
    How often pins `a` and `b` alternate rather than repeat.

    Genuine quadrature alternates almost every time: A, B, A, B.  Two
    independent noisy pins do not.  Returned as a fraction of the transitions
    between consecutive edges on this pair.
    """
    seq = [g for _, g, _ in events if g in (a, b)]
    if len(seq) < 4:
        return 0.0
    swaps = sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])
    return swaps / (len(seq) - 1)


def decode(events, clk, dt):
    """
    Follow the quadrature and report net movement.

    Reads the partner's level at each edge of one pin, which is the standard
    half-step decode: the partner's state says which way round the cycle the
    shaft is going.  Counts are in edges, not detents; a KY-040 gives two or
    four edges per click depending on where the detent sits.
    """
    level = {clk: 1, dt: 1}
    forward = back = 0
    for _, gpio, lev in events:
        if gpio not in (clk, dt):
            continue
        level[gpio] = lev
        if gpio == clk:
            if level[clk] == level[dt]:
                back += 1
            else:
                forward += 1
    return forward, back


def main():
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 45
    raw = record(seconds)
    events = debounce(raw)

    counts = defaultdict(int)
    for _, gpio, _ in events:
        counts[gpio] += 1

    print(f"\n{len(raw)} edges recorded, {len(events)} after debounce.")
    if not counts:
        print("\nNOTHING MOVED.  Either the knob was not turned during the "
              "window, or the module's ground is not connected.")
        return 1

    print("\nEdges per pin:")
    for gpio, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  GPIO {gpio:2d}  {n:5d}")

    busy = [g for g, _ in sorted(counts.items(), key=lambda kv: -kv[1])]

    result = {"edges": dict(counts)}

    if len(busy) >= 2:
        a, b = busy[0], busy[1]
        share = interleaving(events, a, b)
        forward, back = decode(events, a, b)
        print(f"\nRotation pair: GPIO {a} and GPIO {b}")
        print(f"  interleaving   {share:.2f}   "
              f"({'quadrature' if share > 0.8 else 'NOT a clean pair'})")
        print(f"  net movement   {forward} one way, {back} the other")
        result.update(clk=a, dt=b, interleaving=round(share, 3),
                      forward=forward, back=back)

    # The switch moves in isolation: no other pin changes near it.
    for gpio in busy[2:]:
        times = [t for t, g, _ in events if g == gpio]
        others = [t for t, g, _ in events if g != gpio]
        lonely = sum(1 for t in times
                     if not any(abs(t - o) < PAIR_WINDOW_NS for o in others))
        if lonely >= 2:
            print(f"\nSwitch candidate: GPIO {gpio} "
                  f"({lonely} of {len(times)} edges moved alone)")
            result.setdefault("sw", gpio)

    print("\n" + json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
