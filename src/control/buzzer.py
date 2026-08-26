#!/usr/bin/env python3
"""
Tones on the PS1240 piezo, driven straight off one GPIO pin.

    python3 src/control/buzzer.py             # play the start-up tune
    python3 src/control/buzzer.py --goodbye   # play the shutdown tune

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
import os
import sys
import threading
import time

logger = logging.getLogger(__name__)

# This file is also the child process `in_process` starts, so it needs to be
# able to name itself.
SCRIPT = os.path.abspath(__file__)

PIN = 13                 # the only free pin that reaches hardware PWM
CHIP = 0
DUTY = 50                # loudest a square wave gets; see the module docstring

# 440 Hz then 880 Hz, a quarter second each: an octave apart, so the two notes
# are unmistakably different even on a disc driven far below its resonance.
HELLO = ((440, 0.25), (880, 0.25))

# The same two notes the other way up.  Derived rather than written out, so the
# pair cannot drift apart: changing the greeting changes the farewell to match,
# and "the opposite order" stays true by construction rather than by anyone
# remembering to edit both.
GOODBYE = tuple(reversed(HELLO))


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
            time.sleep(seconds)
            # Each note is waited out for its own length, measured from the
            # moment it started - not to a deadline set at the top of the tune.
            # Deadlines were tried and were wrong: when the thread wakes late,
            # the time already spent is subtracted from the *next* note's wait,
            # the wait becomes zero, and the pin is driven low the instant the
            # note begins. The tune came out as one note, twice, at boot and
            # under load. Nothing in python needs to end a note - the cycle
            # count does that - so the only thing a wait has to guarantee is
            # that the note is not cut short. Waking late now costs a gap
            # before the next note, which is audible but honest.
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


def duration(notes):
    """How long a tune runs, before anything plays it."""
    return sum(seconds for _, seconds in notes)


def goodbye(pin=PIN, chip=CHIP, duty=DUTY, gpio=None):
    """
    The farewell: the greeting backwards, as the last thing the app does.

    Blocking, and that is the point rather than an oversight.  The greeting is
    a courtesy nobody waits for; this one is the signal that the box has
    finished with the camera and the panel and is safe to unplug, which is
    worth nothing at all if the process exits while it is still sounding.

    The caller still wants a bound on the wait - see MainRenderLooper._say_goodbye,
    which plays it on a thread and joins with a timeout, so a buzzer that
    somehow never returns cannot hold a shutdown open.
    """
    play(GOODBYE, pin=pin, chip=chip, duty=duty, gpio=gpio)


def in_background(notes=HELLO, pin=PIN, chip=CHIP, duty=DUTY, gpio=None,
                  name="Tune"):
    """
    Start a tune on a thread of its own and return it, without waiting.

    NOT what start-up calls any more - `in_process` is, and the reason is
    written up there. A thread keeps the tune off the critical path but leaves
    it sharing this process's GIL, which is audible: the notes come apart. This
    is kept because it is the right answer when the caller is not fighting the
    GIL, and because `play` on a thread is a smaller thing to reason about than
    a child process.

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

    `name` is what the log calls this tune.  It exists because the first
    version said "Start-up tune" whatever it was playing, so the farewell
    announced itself as a greeting - which is the sort of small lie that costs
    an hour when a log is the only witness left.
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
    logger.info("%s: %s on GPIO %d", name,
                ", ".join(f"{hz} Hz for {s}s" for hz, s in notes), pin)
    return thread


def in_process(name="Tune", python=None, script=None, popen=None):
    """
    Play the start-up tune in a child process, and return without waiting.

    A thread was not enough, and the reason is the GIL rather than anything to
    do with sound. `play` ends each note in C on a cycle count, so a note
    cannot be stretched - but the *next* note cannot begin until python wakes
    up, and during start-up the main thread is holding the GIL while libcamera
    and the panel come up. A late wake-up is a silence between two notes that
    are meant to be one gesture. That silence is what this removes.

    A child has its own interpreter and its own GIL, so nothing this process
    does can delay it.

    The cost is one interpreter start-up, measured at about 130 ms on this Pi -
    not the ~400 ms the whole child takes, because the in-process version
    already paid for importing lgpio (~104 ms) and opening the chip (~100 ms)
    before its own first note. So the greeting arrives about an eighth of a
    second later than it used to, and arrives whole.

    subprocess is imported here rather than at the top of the file because this
    module IS the child: a module-level import would be paid again by every
    child, on the one path where start-up latency is the thing being bought.

    `popen` is the spawner, and exists so a test can pass one that records
    instead of one that makes a noise - the same reason `play` takes `gpio`.

    The child is reaped on a daemon thread, which costs nothing: waitpid
    releases the GIL, so the thread is asleep in the kernel rather than
    competing with anything. Without it the finished child stays a zombie for
    the life of the app, which is untidy rather than harmful, but the thread is
    also the only place a non-zero exit can be noticed at all.
    """
    import subprocess                    # see the docstring: the child pays it

    if popen is None:
        popen = subprocess.Popen
    if python is None:
        python = sys.executable
    if script is None:
        script = SCRIPT

    child = popen([python, script],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def reap():
        code = child.wait()
        if code:
            logger.warning("%s: the buzzer process exited with %s", name, code)

    threading.Thread(target=reap, name="buzzer-reap", daemon=True).start()
    # Said out loud, because otherwise a tune that played and a tune that never
    # started look identical in the log - and on a board with no buzzer fitted
    # they sound identical too.
    logger.info("%s: %s on GPIO %d, in a child process", name,
                ", ".join(f"{hz} Hz for {s}s" for hz, s in HELLO), PIN)
    return child


def main():
    logging.basicConfig(level=logging.INFO)
    tune = GOODBYE if "--goodbye" in sys.argv else HELLO
    play(tune)       # blocking here: a script with nothing else to do
    print(f"played {len(tune)} notes on GPIO {PIN}: "
          + ", ".join(f"{hz} Hz for {s}s" for hz, s in tune))


if __name__ == "__main__":
    main()
