#!/usr/bin/env python3
"""
Check the start-up tune, without a buzzer and without making a sound.

    python3 tests/control/buzzer_test.py

Nothing in software can hear a piezo, so what is checkable here is everything
up to the air: which notes, in which order, for how long, at what duty, and
that the pin is released afterwards. The last line of the run says what a human
should hear, because that half cannot be automated and should not be claimed.

The double is a **fake, not a stub**: it refuses a zero frequency exactly as
lgpio does, raising "bad PWM micros". That is not decoration. The first version
of this tune stopped a note with `tx_pwm(..., 0, 0)`, which threw mid-tune and
threw again inside the `finally` meant to clean up, leaving GPIO 13 claimed and
driving. A fake that accepted 0 Hz would have been perfectly happy with the
code that did that.
"""

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from control import buzzer                            # noqa: E402

failures = []
skipped = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"           got  {got!r}\n           want {want!r}")
        failures.append(label)


class FakeGpio:
    """
    lgpio's observable behaviour, recorded rather than performed.

    Honest about the two things that actually bit: a zero frequency raises, and
    a pin has to be claimed before it can be written. Everything the module
    does to it lands in `events` in order, which is the contract - the sound
    itself is not reachable from here.
    """

    def __init__(self, fail_on_note=None):
        self.events = []
        self.slept = []
        self.fail_on_note = fail_on_note
        self.claimed = set()
        self.notes_played = 0

    # -- the lgpio surface this module uses -------------------------------
    def gpiochip_open(self, chip):
        self.events.append(("open", chip))
        return 99                       # an arbitrary handle, as lgpio returns

    def gpio_claim_output(self, handle, pin, level):
        self.claimed.add(pin)
        self.events.append(("claim", pin, level))

    def tx_pwm(self, handle, pin, frequency, duty, offset=0, cycles=0):
        if frequency == 0:
            raise ValueError("bad PWM micros")        # what lgpio really does
        if pin not in self.claimed:
            raise ValueError(f"GPIO {pin} was never claimed as an output")
        self.notes_played += 1
        if self.notes_played == self.fail_on_note:
            raise RuntimeError("the panel fell off")
        self.events.append(("tone", pin, frequency, duty, cycles))

    def gpio_write(self, handle, pin, level):
        self.events.append(("write", pin, level))

    def gpio_free(self, handle, pin):
        self.claimed.discard(pin)
        self.events.append(("free", pin))

    def gpiochip_close(self, handle):
        self.events.append(("close",))


def without_sleeping(fn):
    """Run `fn` with buzzer's sleep recording its argument instead of waiting."""
    slept = []
    real = buzzer.time.sleep
    buzzer.time.sleep = slept.append
    try:
        fn()
    finally:
        buzzer.time.sleep = real
    return slept


def test_the_tune_is_two_notes_an_octave_apart():
    """The tune itself, as data, before anything plays it."""
    check("HELLO is 440 Hz then 880 Hz, a quarter second each",
          buzzer.HELLO, ((440, 0.25), (880, 0.25)))
    check("the second note is exactly an octave above the first",
          buzzer.HELLO[1][0] / buzzer.HELLO[0][0], 2.0)
    check("the duty is 50%, the loudest a square wave gets", buzzer.DUTY, 50)
    check("and it plays on GPIO 13, the pin that reaches hardware PWM",
          buzzer.PIN, 13)


def test_goodbye_is_hello_backwards():
    """
    Derived, not written out twice, so the pair cannot drift apart.

    Checked as a relationship rather than as a literal: asserting
    `((880, 0.25), (440, 0.25))` would pass just as happily if someone changed
    the greeting and left the farewell behind, which is the one way these two
    can go wrong.
    """
    check("GOODBYE is HELLO reversed", buzzer.GOODBYE,
          tuple(reversed(buzzer.HELLO)))
    check("so it rises on the way in and falls on the way out",
          (buzzer.HELLO[0][0] < buzzer.HELLO[1][0],
           buzzer.GOODBYE[0][0] > buzzer.GOODBYE[1][0]), (True, True))
    check("and both take the same half second",
          (buzzer.duration(buzzer.HELLO), buzzer.duration(buzzer.GOODBYE)),
          (0.5, 0.5))


def test_goodbye_plays_the_notes_the_other_way_up():
    """The farewell on the wire, cycle counts and all."""
    fake = FakeGpio()
    without_sleeping(lambda: buzzer.goodbye(gpio=fake))
    check("880 Hz first, then 440, each still a quarter second",
          [(e[2], e[4]) for e in fake.events if e[0] == "tone"],
          [(880, 220), (440, 110)])
    check("and the pin is handed back", fake.claimed, set())


def test_hello_drives_the_pin_in_the_right_order():
    """
    The whole sequence, which is the only contract software can see.

    Written out in full rather than checked a property at a time: the order is
    the part that matters - a tone before the claim, or a free before the last
    note, is exactly the kind of fault that still makes a noise on the bench
    and leaves the pin unusable for the next run.
    """
    fake = FakeGpio()
    slept = without_sleeping(lambda: buzzer.hello(gpio=fake))
    check("it opens the chip, claims 13, plays both notes, and hands it back",
          fake.events,
          [("open", 0),
           ("claim", 13, 0),
           ("tone", 13, 440, 50, 110), ("write", 13, 0),
           ("tone", 13, 880, 50, 220), ("write", 13, 0),
           ("write", 13, 0), ("free", 13), ("close",)])
    # Deadlines from the start of the tune, not one sleep after another, so a
    # note that woke late does not push every note after it further out. With a
    # sleep that returns instantly the second wait is the whole 0.5 s, which is
    # exactly what "wait until 0.5 s after the tune began" means.
    check("and waits to a deadline rather than by adding up sleeps",
          [round(x, 2) for x in slept], [0.25, 0.5])


def test_the_note_length_is_lgpios_job_not_pythons():
    """
    The bug the user heard: a note stretched by 181 ms in the real app.

    A note timed by `sleep` ends when the thread next runs, and the tune plays
    during the busiest half second of start-up - the panel and the camera both
    coming up on the main thread. Measured in the app, the first note was asked
    for 250 ms and sounded for 431. Handing lgpio a cycle count moves the note's
    end into C, where the GIL cannot reach it.

    Checked as arithmetic rather than by timing anything: 440 Hz for a quarter
    second is 110 cycles, and if that number is wrong the note is the wrong
    length no matter how good the scheduler is.
    """
    fake = FakeGpio()
    without_sleeping(lambda: buzzer.hello(gpio=fake))
    cycles = [(e[2], e[4]) for e in fake.events if e[0] == "tone"]
    check("each note is handed over as its own cycle count",
          cycles, [(440, 110), (880, 220)])
    for frequency, count in cycles:
        check(f"and {count} cycles at {frequency} Hz really is a quarter second",
              round(count / frequency, 4), 0.25)


def test_a_note_that_fails_still_hands_the_pin_back():
    """
    The failure that actually happened, and the reason the finally is there.

    A tone raising mid-tune must not leave GPIO 13 claimed and driving: the
    next run would fail to start, which is a worse fault than a missing beep
    and a far more confusing one.
    """
    fake = FakeGpio(fail_on_note=2)
    try:
        buzzer.hello(gpio=fake)
    except RuntimeError:
        pass
    else:
        check("the second note raised", "no exception", "RuntimeError")
    check("the pin is freed even when a note raises", fake.claimed, set())
    check("and the chip is closed", fake.events[-1], ("close",))
    check("and it was driven low on the way out", fake.events[-3], ("write", 13, 0))


def test_a_zero_frequency_is_never_asked_for():
    """
    lgpio raises on 0 Hz, so silence has to be a write rather than a frequency.

    The fake enforces this by raising, so the check is that the tune completes
    at all - but assert it explicitly too, because a future edit could stop a
    note some other way and this names what is wrong with 0.
    """
    fake = FakeGpio()
    without_sleeping(lambda: buzzer.hello(gpio=fake))
    frequencies = [e[2] for e in fake.events if e[0] == "tone"]
    check("every frequency handed to tx_pwm is a real one", frequencies,
          [440, 880])
    check("and silence is a write, not a zero-frequency tone",
          [e for e in fake.events if e[0] == "write"],
          [("write", 13, 0)] * 3)


def test_play_takes_any_tune():
    """`hello` is one tune, not the only one the module can play."""
    fake = FakeGpio()
    slept = without_sleeping(
        lambda: buzzer.play(((100, 0.1), (200, 0.2), (300, 0.3)), gpio=fake))
    check("three notes go out in the order given",
          [(e[2], e[3]) for e in fake.events if e[0] == "tone"],
          [(100, 50), (200, 50), (300, 50)])
    check("each with its own cycle count",
          [e[4] for e in fake.events if e[0] == "tone"], [10, 40, 90])
    check("and its own deadline", [round(x, 2) for x in slept],
          [0.1, 0.3, 0.6])


def test_start_up_does_not_wait_for_the_tune():
    """
    The point of the thread: start-up carries on while the tune is playing.

    Gated rather than timed. A fake that blocks inside the first note lets this
    assert that `in_background` had already returned *while the note was still
    sounding*, which is the actual claim - where "it returned in under 50 ms"
    would pass on a machine that was merely fast, and flake on one that was
    busy.
    """
    sounding = threading.Event()
    release = threading.Event()

    class GatedGpio(FakeGpio):
        def tx_pwm(self, handle, pin, frequency, duty, offset=0, cycles=0):
            super().tx_pwm(handle, pin, frequency, duty, offset, cycles)
            sounding.set()
            release.wait(5)

    fake = GatedGpio()
    thread = buzzer.in_background(gpio=fake)
    check("the first note is sounding", sounding.wait(5), True)
    check("and the caller already has control back while it sounds",
          thread.is_alive(), True)
    check("on a thread that cannot hold the process open", thread.daemon, True)
    release.set()
    thread.join(5)
    check("the tune finishes on its own", thread.is_alive(), False)
    check("and the pin is handed back without the caller doing anything",
          fake.claimed, set())


def test_a_failure_on_the_thread_stays_on_the_thread():
    """
    Nothing is left to raise to once the caller has moved on.

    A tune that dies must log and stop, not kill a thread with an unhandled
    traceback in a process whose whole job is to keep drawing.
    """
    fake = FakeGpio(fail_on_note=1)
    thread = buzzer.in_background(gpio=fake)
    thread.join(5)
    check("the thread ends rather than hanging", thread.is_alive(), False)
    check("and the pin is still handed back", fake.claimed, set())


def test_the_shutdown_waits_for_its_tune():
    """
    The farewell is waited for, where the greeting is not.

    Gated the same way round as the start-up check, and asserting the opposite:
    there, the caller had control back while the note was sounding; here it must
    still be inside `_say_goodbye` until the tune is done. Timing would not
    settle this - a fast machine finishes the tune before anyone can look.
    """
    sounding = threading.Event()
    release = threading.Event()

    class GatedGpio(FakeGpio):
        def tx_pwm(self, handle, pin, frequency, duty, offset=0, cycles=0):
            super().tx_pwm(handle, pin, frequency, duty, offset, cycles)
            sounding.set()
            release.wait(5)

    fake = GatedGpio()
    returned = threading.Event()

    def farewell():
        buzzer.goodbye(gpio=fake)
        returned.set()

    caller = threading.Thread(target=farewell, daemon=True)
    caller.start()
    check("the first note is sounding", sounding.wait(5), True)
    check("and the caller has NOT returned while it sounds",
          returned.is_set(), False)
    release.set()
    check("it returns once the tune is done", returned.wait(5), True)


def test_a_shutdown_is_never_held_up_by_the_buzzer():
    """
    The bound on the wait, which is what stops a farewell becoming a hang.

    `_say_goodbye` joins with a timeout. A tune that never ends must cost the
    shutdown that timeout and no more, because the alternative is systemd's
    SIGKILL at fifteen seconds - and that leaves claimed exactly the camera and
    GPIO pins that the rest of _shut_down exists to release, which is the worse
    failure by a distance.
    """
    sys.path.insert(0, str(ROOT))
    try:
        import ascii_camera                            # noqa: E402
    except ModuleNotFoundError as e:
        print(f"  [SKIP] a tune that never ends does not hold up the shutdown "
              f"-- needs the Pi ({e.name} is not installed here)")
        skipped.append("a tune that never ends does not hold up the shutdown")
        return

    never_ends = threading.Event()

    class Sticky:
        """A buzzer whose tune never finishes, which is the case that matters."""
        GOODBYE = buzzer.GOODBYE
        duration = staticmethod(buzzer.duration)

        @staticmethod
        def in_background(notes=None, **kw):
            # **kw rather than a fixed signature: the app passes `name=` now,
            # and the first version of this fake did not take it. The call
            # raised, _say_goodbye swallowed it, and the wait this test exists
            # to measure was never entered - it reported 0.00 s and went red,
            # which is the only reason the mismatch was noticed at all.
            thread = threading.Thread(target=lambda: never_ends.wait(30),
                                      daemon=True)
            thread.start()
            return thread

    real = ascii_camera.buzzer
    ascii_camera.buzzer = Sticky
    began = time.perf_counter()
    try:
        ascii_camera.MainRenderLooper._say_goodbye(object())
    finally:
        ascii_camera.buzzer = real
        never_ends.set()
    waited = time.perf_counter() - began

    # The bound is the tune's own length plus a second. Checked as a range so
    # this measures the timeout being honoured rather than restating it: too
    # short and it never waited, too long and the join is unbounded.
    check("it gives up on the tune rather than hanging the shutdown",
          1.4 < waited < 3.0, True)
    print(f"        (waited {waited:.2f} s for a tune that never ends)")


def test_the_app_survives_a_buzzer_that_is_not_there():
    """
    A missing buzzer must not stop the picture.

    This is the consequence that matters at the enclosure: the tune is a
    courtesy, the picture is the point. `_say_hello` is called with a bare
    object because it touches nothing on self - if that stops being true, this
    fails loudly and the test needs rewriting rather than deleting.
    """
    sys.path.insert(0, str(ROOT))
    try:
        import ascii_camera                            # noqa: E402
    except ModuleNotFoundError as e:
        # ascii_camera pulls in PIL, which lives only on the Pi. Announced
        # rather than passed: a check that quietly skips reads exactly like a
        # check that ran, and this is the one that covers the app itself.
        print(f"  [SKIP] a buzzer that raises is logged, not propagated  -- "
              f"needs the Pi ({e.name} is not installed here)")
        skipped.append("a buzzer that raises is logged, not propagated")
        return

    real = ascii_camera.buzzer

    class Broken:
        @staticmethod
        def in_background(*a, **kw):
            raise OSError("no such device")

    ascii_camera.buzzer = Broken
    try:
        ascii_camera.MainRenderLooper._say_hello(object())
        survived = True
    except Exception as e:                             # noqa: BLE001
        survived = f"{type(e).__name__}: {e}"
    finally:
        ascii_camera.buzzer = real
    check("a buzzer that raises is logged, not propagated", survived, True)


def main():
    print("the start-up tune")
    print("=" * 66)
    test_the_tune_is_two_notes_an_octave_apart()
    test_goodbye_is_hello_backwards()
    test_goodbye_plays_the_notes_the_other_way_up()
    test_hello_drives_the_pin_in_the_right_order()
    test_the_note_length_is_lgpios_job_not_pythons()
    test_a_note_that_fails_still_hands_the_pin_back()
    test_a_zero_frequency_is_never_asked_for()
    test_play_takes_any_tune()
    test_start_up_does_not_wait_for_the_tune()
    test_the_shutdown_waits_for_its_tune()
    test_a_shutdown_is_never_held_up_by_the_buzzer()
    test_a_failure_on_the_thread_stays_on_the_thread()
    test_the_app_survives_a_buzzer_that_is_not_there()

    print("\n" + "=" * 66)
    if skipped:
        print(f"{len(skipped)} check(s) skipped, needing the Pi: "
              + ", ".join(skipped))
    if failures:
        print(f"RESULT: {len(failures)} CHECK(S) FAILED")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("RESULT: the tune is the right notes, in the right order, it does "
          "not hold up start-up,")
    print("        and the pin is always handed back.")
    print("        Nothing here can hear it. On the real buzzer it should be "
          "two short notes,")
    print("        the second an octave above the first - "
          "`python3 src/control/buzzer.py` to listen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
