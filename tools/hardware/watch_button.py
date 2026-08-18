#!/usr/bin/env python3
"""Watch GPIO 3, 4 and 5 with internal pull-ups and report every transition.

Used to find out which header pin a newly wired push button actually reaches:
run it, press the button, and see which line goes low. A pin that never moves
is not carrying the switch contacts.
"""
import sys
import time

import lgpio

PINS = (3, 4, 5)
DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 25.0

h = lgpio.gpiochip_open(0)
try:
    for p in PINS:
        lgpio.gpio_claim_input(h, p, lgpio.SET_PULL_UP)
    time.sleep(0.05)

    state = {p: lgpio.gpio_read(h, p) for p in PINS}
    print("idle: " + "  ".join(f"GPIO{p}={'hi' if state[p] else 'LO'}" for p in PINS))
    print(f"press the button now - watching for {DURATION:.0f}s", flush=True)

    edges = {p: 0 for p in PINS}
    t0 = time.monotonic()
    while time.monotonic() - t0 < DURATION:
        for p in PINS:
            v = lgpio.gpio_read(h, p)
            if v != state[p]:
                state[p] = v
                edges[p] += 1
                print(f"{time.monotonic() - t0:6.2f}s  GPIO{p} -> {'hi' if v else 'LO'}",
                      flush=True)
        time.sleep(0.002)

    print("\nedge counts: " + "  ".join(f"GPIO{p}={edges[p]}" for p in PINS))
    moved = [p for p in PINS if edges[p]]
    if not moved:
        print("VERDICT: nothing moved - no switch contact on 3, 4 or 5")
        sys.exit(1)
    print("VERDICT: switch contact is on GPIO " + ", ".join(str(p) for p in moved))
finally:
    lgpio.gpiochip_close(h)
