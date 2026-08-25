#!/usr/bin/env python3
"""
Tones on the PS1240 piezo, driven straight off one GPIO pin.

    python3 src/control/buzzer.py          # play the start-up tune

Functions rather than a class, because there is nothing to remember between
one tune and the next.  Each call opens the chip, claims the pin, plays, and
frees it again, so no run holds GPIO 13 for the sake of half a second of
sound - and a claim left behind is what makes the *next* run fail to start.

The part is a bare transducer with no oscillator in it, so the pitch is
whatever it is driven at.  That is the whole reason for choosing it over the
KY-006 that came first, and it is checkable before anything drives it: a piezo
reads open at DC and a coil reads short.  docs/guides/enclosure-build-guide.html
has the pull-up test and why it goes first.

Timing is lgpio's, which is software PWM done in C, and each note's *length*
is lgpio's too - handed over as a cycle count so that python being slow to wake
cannot stretch a note.  Good enough for a tune nobody is tapping their foot to;
the shutdown tune, if it is ever written, wants the hardware PWM that GPIO 13
was chosen for - and that needs `dtoverlay=pwm-2chan` in config.txt and a
reboot, neither of which is here yet.

Two things learned the hard way and encoded below.  lgpio rejects a zero
frequency with "bad PWM micros", so a tone is stopped by writing the pin low
rather than by asking for 0 Hz - the obvious spelling raises, and raises again
inside the `finally` that was meant to clean up.  And 50% duty is as loud as a
square wave gets: above it the fundamental shrinks again, so 90% sounds like
10% rather than louder.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)

PIN = 13                 # the only free pin that reaches hardware PWM
CHIP = 0
DUTY = 50                # loudest a square wave gets; see the module docstring

# 440 Hz then 880 Hz, a quarter second each: an octave apart, so the two notes
# are unmistakably different even on a disc driven far below its resonance.
HELLO = ((440, 0.25), (880, 0.25))


def play(notes, pin=PIN, chip=CHIP, duty=DUTY, gpio=None):
    """
    Play (frequency_hz, seconds) pairs in order, then release the pin.

    `gpio` is the lgpio module, and exists so a test can pass one that records
    instead of one that makes a noise.  It is imported late by default because
    lgpio only exists on the Pi, exactly as encoder.py imports it.

    Blocking.  `in_background` is the one that does not block, and is what
    start-up calls; this is the primitive underneath it, and the one to use
    from a script or a test where waiting is the point.
    """
    if gpio is None:
        import lgpio as gpio            # imported late: only exists on the Pi

    handle = gpio.gpiochip_open(chip)
    try:
        gpio.gpio_claim_output(handle, pin, 0)
        started = time.perf_counter()
        elapsed = 0.0
        for frequency, seconds in notes:
            # The note's length is handed to lgpio as a cycle count, not kept
            # in python. Measured in the app: a thread that asks for 250 ms and
            # sleeps for it sounded for 431 ms, because sleep returns on time
            # and then waits for the GIL, which the main thread is holding
            # while it starts the panel and the camera. The tune plays during
            # the busiest half second of the process, so this is the normal
            # case rather than bad luck. Counted in C, the note ends on time
            # whatever python is doing; the worst a late wake-up can now do is
            # leave a gap before the next note, which is far kinder to the ear
            # than a first note two thirds longer than the second.
            gpio.tx_pwm(handle, pin, frequency, duty, 0,
                        max(1, round(frequency * seconds)))
            # Deadlines from the start of the tune rather than one sleep after
            # another, so a late wake-up costs that note alone and does not
            # push everything after it further out.
            elapsed += seconds
            remaining = started + elapsed - time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)
            # NOT tx_pwm(..., 0, 0): lgpio raises "bad PWM micros" on a zero
            # frequency, which would abandon the pin mid-tune and then raise a
            # second time on the way out. The cycle count has almost certainly
            # ended the note already; this is what makes "almost" not matter.
            gpio.gpio_write(handle, pin, 0)
    finally:
        gpio.gpio_write(handle, pin, 0)
        gpio.gpio_free(handle, pin)
        gpio.gpiochip_close(handle)


def hello(pin=PIN, chip=CHIP, duty=DUTY, gpio=None):
    """
    The start-up tune: the box saying it is alive before it can show anything.

    Worth having for the same reason the panel's splash screen is: the camera
    takes about twenty seconds to produce its first frame, and in a sealed box
    twenty seconds of silence and blank glass is indistinguishable from broken
    hardware.  This one arrives in the first half second, before the panel has
    anything at all.

    Blocking.  Start-up wants `in_background`.
    """
    play(HELLO, pin=pin, chip=chip, duty=duty, gpio=gpio)


def in_background(notes=HELLO, pin=PIN, chip=CHIP, duty=DUTY, gpio=None):
    """
    Start a tune on a thread of its own and return it, without waiting.

    Start-up must not stand still for half a second of sound.  Nothing later
    depends on the tune having finished, and nothing about the tune depends on
    what start-up does next, so the two have no reason to be in step.

    A daemon thread, so a tune still playing cannot hold the process open at
    shutdown.  Losing the pin claim that way is safe: the kernel drops the
    chip handle when the process goes, which is the same guarantee that makes
    a crash mid-tune survivable.

    Failures are logged here rather than raised, because by the time one
    happens there is no longer a caller to raise to.  The returned thread is
    for tests and for anyone who does want to wait; ignoring it is the normal
    case.
    """
    def run():
        try:
            play(notes, pin=pin, chip=chip, duty=duty, gpio=gpio)
        except Exception as e:                      # noqa: BLE001
            logger.warning("Buzzer fell silent: %s: %s", type(e).__name__, e)

    thread = threading.Thread(target=run, name="buzzer", daemon=True)
    thread.start()
    # Said out loud, because otherwise a tune that played and a tune that never
    # started look identical in the log - and on a board with no buzzer fitted
    # they sound identical too.
    logger.info("Start-up tune: %s on GPIO %d",
                ", ".join(f"{hz} Hz for {s}s" for hz, s in notes), pin)
    return thread


def main():
    logging.basicConfig(level=logging.INFO)
    hello()          # blocking here: a script with nothing else to do
    print(f"played {len(HELLO)} notes on GPIO {PIN}: "
          + ", ".join(f"{hz} Hz for {s}s" for hz, s in HELLO))


if __name__ == "__main__":
    main()
