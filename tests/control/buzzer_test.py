#!/usr/bin/env python3
"""
Check the tunes, without a buzzer, without a Pi and without making a sound.

    python3 tests/control/buzzer_test.py

Nothing in software can hear a piezo, so what is checkable here is everything
up to the air: which notes, in which order, at what duty, that the two notes
run into each other rather than being separate events, and that the channel is
always left silent. The last line of the run says what a human should hear,
because that half cannot be automated and should not be claimed.

The double is a **fake, not a stub**: it enforces the two rules the PWM driver
enforces - a duty may not exceed the period, and a period may not be shrunk
below the current duty. Both matter. `play` writes duty to zero before every
period change precisely to stay inside the second one, and against a stub that
accepted anything, a version with that line deleted would pass and then refuse
the second note of any tune that more than doubles in pitch.
"""

import logging
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from control import buzzer                            # noqa: E402

failures = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"           got  {got!r}\n           want {want!r}")
        failures.append(label)


class FakeChannel:
    """
    The PWM driver's observable behaviour, recorded rather than performed.

    Honest about the two rules that actually bite, both of which are refusals
    the real driver makes with EINVAL. Everything written lands in `events` in
    order, which is the contract - the sound itself is not reachable from here.
    """

    def __init__(self, fail_on_note=None):
        self.events = []
        self.period = 0
        self.duty = 0
        self.periods_written = 0
        self.fail_on_note = fail_on_note

    def write(self, chip, channel, name, value):
        value = int(value)
        if name == "period":
            if value < self.duty:
                raise OSError(22, "Invalid argument")   # what the driver does
            self.period = value
            self.periods_written += 1
            if self.periods_written == self.fail_on_note:
                raise RuntimeError("the panel fell off")
        elif name == "duty_cycle":
            if value > self.period:
                raise OSError(22, "Invalid argument")   # and the other way
            self.duty = value
        self.events.append((name, value))

    # -- readers the checks are written in terms of ------------------------
    def periods(self):
        return [v for n, v in self.events if n == "period"]

    def names(self):
        return [n for n, _ in self.events]


def period_for(hz):
    """What a frequency should become in the driver's nanoseconds."""
    return round(1_000_000_000 / hz)


# -- the tunes themselves ----------------------------------------------------

def test_the_tune_is_two_notes_an_octave_apart():
    print("\nthe greeting is two notes, an octave apart")
    check("the greeting", buzzer.HELLO, ((440, 0.25), (880, 0.25)))
    check("an octave apart", buzzer.HELLO[1][0], buzzer.HELLO[0][0] * 2)
    check("half a second in total", buzzer.duration(buzzer.HELLO), 0.5)


def test_goodbye_is_hello_backwards():
    """
    Derived, not written out, so the pair cannot drift apart.

    Checked against a reversal of HELLO rather than against a literal, so that
    changing the greeting changes this expectation too - a literal here would
    turn the derivation into a coincidence that a later edit could break.
    """
    print("\nthe farewell is the greeting reversed")
    check("reversed", buzzer.GOODBYE, tuple(reversed(buzzer.HELLO)))
    check("same length", buzzer.duration(buzzer.GOODBYE),
          buzzer.duration(buzzer.HELLO))


# -- what reaches the driver -------------------------------------------------

def test_the_notes_become_the_right_periods():
    print("\nthe notes reach the driver as the right periods")
    fake = FakeChannel()
    buzzer.hello(write=fake.write)
    check("440 Hz then 880 Hz, in nanoseconds",
          fake.periods(), [period_for(440), period_for(880)])


def test_the_duty_is_half_the_period():
    """
    50% is as loud as a square wave gets - above it the fundamental shrinks.

    Checked as a ratio of whatever period was written rather than as a
    constant, so it stays a statement about duty and not about 440 Hz.
    """
    print("\nthe duty is half of each period")
    fake = FakeChannel()
    buzzer.hello(write=fake.write)
    duties = [v for n, v in fake.events if n == "duty_cycle" and v]
    check("one non-zero duty per note", len(duties), 2)
    check("each is half its period",
          duties, [period_for(440) // 2, period_for(880) // 2])


def test_the_duty_is_zeroed_before_every_period_change():
    """
    The ordering the driver insists on, and the reason `play` looks odd.

    A period may not be shrunk below the current duty. The greeting escapes
    that by one nanosecond, so this check is written against the ordering
    itself rather than against a tune that happens to expose it.
    """
    print("\nduty goes to zero before each period")
    fake = FakeChannel()
    buzzer.hello(write=fake.write)
    names = fake.names()
    for i, name in enumerate(names):
        if name == "period":
            before = names[i - 1] if i else None
            check(f"the write before period #{i} is a duty",
                  before, "duty_cycle")
    zeroed_before = [fake.events[i - 1][1] for i, n in enumerate(names)
                     if n == "period"]
    check("and every one of those duties was zero", zeroed_before, [0, 0])


def test_a_tune_that_doubles_in_pitch_still_plays():
    """
    The check that makes the zeroing matter, using a tune that really needs it.

    440 Hz to 1760 Hz shrinks the period below the old duty. Without the
    zeroing the driver refuses the second note - so delete that line and this
    is the check that fails, where the greeting's own notes would not notice.
    """
    print("\na tune that more than doubles in pitch still plays")
    fake = FakeChannel()
    raised = None
    try:
        buzzer.play(((440, 0.01), (1760, 0.01)), write=fake.write)
    except Exception as e:                          # noqa: BLE001
        raised = f"{type(e).__name__}: {e}"
    check("nothing was refused", raised, None)
    check("both notes reached the driver",
          fake.periods(), [period_for(440), period_for(1760)])


def test_the_notes_run_into_each_other():
    """
    One gesture, not two events: `enable` is never turned off mid-tune.

    This is the audible difference the child process bought, kept honest here:
    a version that disabled between notes would put a gap back in by
    construction rather than by bad luck.
    """
    print("\nthe two notes are one continuous sound")
    fake = FakeChannel()
    buzzer.hello(write=fake.write)
    enables = [v for n, v in fake.events if n == "enable"]
    check("on, on, then off at the end", enables, [1, 1, 0])
    # the last enable is the only zero
    check("nothing was silenced mid-tune", enables[:-1], [1, 1])


def test_the_channel_is_left_silent():
    print("\nthe channel is left silent")
    fake = FakeChannel()
    buzzer.hello(write=fake.write)
    check("the last two writes are duty 0 then enable 0",
          fake.events[-2:], [("duty_cycle", 0), ("enable", 0)])


def test_a_note_that_fails_still_silences_the_channel():
    """
    The `finally`, with a driver that dies in the middle of the tune.

    A buzzer stuck on is worse than a buzzer that never sounded, because it
    does not stop when the app does.
    """
    print("\na note that fails still leaves the channel silent")
    fake = FakeChannel(fail_on_note=2)
    raised = None
    try:
        buzzer.hello(write=fake.write)
    except Exception as e:                          # noqa: BLE001
        raised = type(e).__name__
    check("the failure reached the caller", raised, "RuntimeError")
    check("and the channel was silenced anyway",
          fake.events[-2:], [("duty_cycle", 0), ("enable", 0)])


def test_play_takes_any_tune():
    print("\nplay takes any tune, not just the two named ones")
    fake = FakeChannel()
    buzzer.play(((262, 0.01), (330, 0.01), (392, 0.01)), write=fake.write)
    check("three notes", fake.periods(),
          [period_for(262), period_for(330), period_for(392)])


def test_the_pin_and_channel_are_the_wired_ones():
    """
    GPIO 13 is PWM1, and that mapping is made in config.txt.

    A silent repin would leave the buzzer dead with every other check green,
    because they all read the channel from the module they are testing.
    """
    print("\nthe pin and channel are the wired ones")
    check("PIN", buzzer.PIN, 13)
    check("CHANNEL", buzzer.CHANNEL, 1)
    check("chip path", buzzer.PWMCHIP, "/sys/class/pwm/pwmchip0")


# -- how start-up plays it ---------------------------------------------------

class FakePopen:
    """
    subprocess.Popen's observable behaviour, recorded rather than performed.

    Honest about the one thing that matters to the caller: the child is not
    finished when the call returns. `wait` blocks until `finish` is called, so
    a test can prove start-up carried on while the tune was still playing -
    which a fake returning instantly could not distinguish from the blocking
    version it replaced.
    """

    spawned = []

    def __init__(self, argv, stdout=None, stderr=None):
        self.argv = argv
        self.code = None
        self.done = threading.Event()
        FakePopen.spawned.append(self)

    def wait(self):
        self.done.wait(5)
        return self.code

    def finish(self, code=0):
        self.code = code
        self.done.set()


def test_the_tune_is_played_by_a_child_not_a_thread():
    """
    The greeting is spawned as its own interpreter running buzzer.py.

    A child has its own GIL, so the half second in which the app is bringing up
    libcamera and the panel cannot pull the two notes apart. On a thread it
    did, audibly.
    """
    print("\nthe greeting is played by a child process")
    FakePopen.spawned = []
    child = buzzer.in_process(name="Start-up tune", python="/usr/bin/python3",
                              popen=FakePopen)
    check("one child spawned", len(FakePopen.spawned), 1)
    check("the interpreter is the one asked for", child.argv[0], "/usr/bin/python3")
    check("it runs buzzer.py itself", Path(child.argv[1]).name, "buzzer.py")
    check("the script it names exists", Path(child.argv[1]).is_file(), True)
    child.finish()


def test_start_up_does_not_wait_for_the_child():
    """
    in_process returns while the tune is still sounding.

    The fake's `wait` blocks until told to finish, so a version that waited for
    the child would hang here rather than fail quietly - and the elapsed time
    is checked too, so a fake that stopped blocking could not hide it.
    """
    print("\nstart-up does not wait for the child")
    FakePopen.spawned = []
    started = time.time()
    child = buzzer.in_process(name="Start-up tune", popen=FakePopen)
    elapsed = time.time() - started
    check("returned while the child was still running", elapsed < 0.5, True)
    check("the child had not finished", child.done.is_set(), False)
    print(f"           returned in {elapsed:.3f} s, tune still playing")
    child.finish()


def test_a_child_that_fails_is_logged_not_raised():
    """
    A non-zero exit is noticed, and noticed somewhere - the reaping thread.

    Without the reaper the child stays a zombie and its exit code is seen by
    nobody, which is how a buzzer that stopped working would look exactly like
    one that never had.
    """
    print("\na child that fails is reaped and logged")
    FakePopen.spawned = []
    records = []

    class Catch(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Catch()
    buzzer.logger.addHandler(handler)
    try:
        child = buzzer.in_process(name="Start-up tune", popen=FakePopen)
        child.finish(code=3)
        deadline = time.time() + 5
        while not any("exited with 3" in r for r in records) and time.time() < deadline:
            time.sleep(0.01)
    finally:
        buzzer.logger.removeHandler(handler)

    check("the non-zero exit was logged",
          any("exited with 3" in r for r in records), True)


def test_a_failure_on_the_thread_stays_on_the_thread():
    """
    in_background is kept for callers not fighting the GIL, and still must not
    take the app down when the buzzer is missing.
    """
    print("\na failure inside in_background stays there")
    fake = FakeChannel(fail_on_note=1)
    raised = None
    thread = None
    try:
        thread = buzzer.in_background(write=fake.write, name="Test tune")
    except Exception as e:                          # noqa: BLE001
        raised = type(e).__name__
    check("nothing reached the caller", raised, None)
    if thread is not None:
        thread.join(5)
        check("the thread finished rather than hanging", thread.is_alive(), False)
        check("and the channel was still silenced",
              fake.events[-2:], [("duty_cycle", 0), ("enable", 0)])


def main():
    print("=" * 66)
    print("Buzzer - the tunes, with no Pi and no sound")
    print("=" * 66)

    test_the_tune_is_two_notes_an_octave_apart()
    test_goodbye_is_hello_backwards()
    test_the_notes_become_the_right_periods()
    test_the_duty_is_half_the_period()
    test_the_duty_is_zeroed_before_every_period_change()
    test_a_tune_that_doubles_in_pitch_still_plays()
    test_the_notes_run_into_each_other()
    test_the_channel_is_left_silent()
    test_a_note_that_fails_still_silences_the_channel()
    test_play_takes_any_tune()
    test_the_pin_and_channel_are_the_wired_ones()
    test_the_tune_is_played_by_a_child_not_a_thread()
    test_start_up_does_not_wait_for_the_child()
    test_a_child_that_fails_is_logged_not_raised()
    test_a_failure_on_the_thread_stays_on_the_thread()

    print("\n" + "=" * 66)
    if failures:
        print(f"RESULT: {len(failures)} CHECK(S) FAILED")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("RESULT: the right notes reach the driver as the right periods, at "
          "half duty, running")
    print("        into each other, and the channel is always left silent.")
    print("        Nothing here can hear it. On the real buzzer it should be "
          "two short notes,")
    print("        the second an octave above the first, with no gap - "
          "`python3 src/control/buzzer.py`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
