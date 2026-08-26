#!/usr/bin/env python3
"""
Check the shutdown hook's farewell, without shutting anything down.

    python3 tests/deploy/shutdown_hook_test.py

The hook is the last thing the machine runs, so almost nothing about it can be
observed in the ordinary way: it executes after every service has stopped and
every filesystem is unmounted, it cannot log because the root filesystem is
read only by then, and the tune is its only diagnostic. What IS checkable is
everything up to the air - which notes, as which periods, in which order, that
they run into each other, that the channel is left silent however the tune
ends, and that a reboot is left alone.

What no test can reach is the failure that has actually happened here once:
lgpio's tx_pwm reporting success at shutdown while the pin stayed silent. That
is why the tune is the diagnostic and why a real poweroff is the only proof.
Nothing in this file should be read as saying the farewell was heard.

The hook has no .py extension - systemd runs the directory, not an import - so
it is loaded by path.
"""

import importlib.util
import sys
import time
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "deploy" / "asciiart.shutdown"

failures = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"           got  {got!r}\n           want {want!r}")
        failures.append(label)


def load_hook():
    loader = SourceFileLoader("asciiart_shutdown", str(HOOK))
    spec = importlib.util.spec_from_loader("asciiart_shutdown", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)      # __name__ != "__main__", so main() is not run
    return module


hook = load_hook()


class Recorder:
    """Every attribute written to the PWM channel, in order."""

    def __init__(self, fail_on_note=None):
        self.events = []
        self.periods_written = 0
        self.fail_on_note = fail_on_note

    def write(self, name, value):
        value = int(value)
        if name == "period":
            self.periods_written += 1
            if self.periods_written == self.fail_on_note:
                raise OSError(22, "Invalid argument")
        self.events.append((name, value))

    def periods(self):
        return [v for n, v in self.events if n == "period"]


def period_for(hz):
    return round(1_000_000_000 / hz)


def test_the_farewell_is_the_greeting_reversed():
    print("\nthe farewell falls where the greeting rose")
    check("880 Hz then 440 Hz", hook.GOODBYE, ((880, 0.25), (440, 0.25)))


def test_the_notes_become_the_right_periods():
    print("\nthe notes reach the driver as the right periods")
    rec = Recorder()
    hook.play_goodbye(write=rec.write)
    check("880 Hz then 440 Hz, in nanoseconds",
          rec.periods(), [period_for(880), period_for(440)])


def test_the_duty_is_half_the_period():
    print("\nthe duty is half of each period")
    rec = Recorder()
    hook.play_goodbye(write=rec.write)
    duties = [v for n, v in rec.events if n == "duty_cycle" and v]
    check("one non-zero duty per note", len(duties), 2)
    check("each is half its period",
          duties, [period_for(880) // 2, period_for(440) // 2])


def test_the_duty_is_zeroed_before_every_period():
    print("\nduty goes to zero before each period")
    rec = Recorder()
    hook.play_goodbye(write=rec.write)
    names = [n for n, _ in rec.events]
    before = [rec.events[i - 1] for i, n in enumerate(names) if n == "period"]
    check("each period is preceded by a zero duty",
          before, [("duty_cycle", 0), ("duty_cycle", 0)])


def test_the_notes_run_into_each_other():
    print("\nthe two notes are one falling gesture")
    rec = Recorder()
    hook.play_goodbye(write=rec.write)
    enables = [v for n, v in rec.events if n == "enable"]
    check("on, on, then off at the end", enables, [1, 1, 0])


def test_the_channel_is_left_silent():
    print("\nthe channel is left silent")
    rec = Recorder()
    hook.play_goodbye(write=rec.write)
    check("the last two writes silence it",
          rec.events[-2:], [("duty_cycle", 0), ("enable", 0)])


def test_a_note_that_fails_still_silences_the_channel():
    """A buzzer left sounding does not stop when the machine does."""
    print("\na note that fails still leaves the channel silent")
    rec = Recorder(fail_on_note=2)
    raised = None
    try:
        hook.play_goodbye(write=rec.write)
    except Exception as e:                          # noqa: BLE001
        raised = type(e).__name__
    check("the failure was not swallowed here", raised, "OSError")
    check("and the channel was silenced anyway",
          rec.events[-2:], [("duty_cycle", 0), ("enable", 0)])


def test_the_fallback_is_used_when_there_is_no_pwm_channel():
    """
    A config.txt that lost its overlay falls back to bit-banging.

    Rough is better than silent, and this is the one branch where the old
    hand-written square wave still earns its keep.
    """
    print("\nno PWM channel falls back to bit-banging")
    called = []
    real_chip, real_bang = hook.PWMCHIP, hook.bit_bang_goodbye
    try:
        hook.PWMCHIP = "/nonexistent/pwm"
        hook.bit_bang_goodbye = lambda: called.append("bit-banged")
        hook.play_goodbye()
    finally:
        hook.PWMCHIP, hook.bit_bang_goodbye = real_chip, real_bang
    check("the fallback ran", called, ["bit-banged"])


def test_ensure_channel_gives_up_without_a_chip():
    print("\nensure_channel gives up rather than raising")
    real_chip = hook.PWMCHIP
    try:
        hook.PWMCHIP = "/nonexistent/pwm"
        check("returns False", hook.ensure_channel(), False)
    finally:
        hook.PWMCHIP = real_chip


STEPS = ("hush_the_panel", "put_out_the_activity_led",
         "douse_the_power_led", "play_goodbye")


def run_main(kind):
    """
    Run main() with every step replaced by a recorder, and return their names.

    The steps have to be observable for this to mean anything. main() swallows
    every exception a step raises - deliberately, since a panel that will not go
    dark is no reason to skip the tune or delay the halt - so off the Pi they all
    fail instantly and a version that ran them on a reboot would look exactly
    like one that did not. That is not hypothetical: the first version of this
    check watched only the return value and the clock, and a mutant that deleted
    the reboot guard passed it.
    """
    called = []
    originals = {name: getattr(hook, name) for name in STEPS}
    try:
        for name in STEPS:
            setattr(hook, name, (lambda n: lambda *a, **k: called.append(n))(name))
        rc = hook.main(["asciiart.shutdown", kind])
    finally:
        for name, fn in originals.items():
            setattr(hook, name, fn)
    return rc, called


def test_a_reboot_is_left_alone():
    """A farewell three seconds before a greeting is noise, not information."""
    print("\na reboot plays nothing")
    rc, called = run_main("reboot")
    check("returns 0", rc, 0)
    check("and did nothing at all", called, [])


def test_a_poweroff_runs_every_step_in_order():
    """
    Everything visible goes dark first, and the tune is last.

    The order is the point: by the time the farewell sounds there is nothing
    left to see, and nothing happens after the sound.
    """
    print("\na poweroff runs every step, in order")
    rc, called = run_main("poweroff")
    check("returns 0", rc, 0)
    check("panel, activity LED, power LED, then the tune",
          called, list(STEPS))


def test_a_halt_is_treated_like_a_poweroff():
    print("\na halt is treated like a poweroff")
    _, called = run_main("halt")
    check("all four steps ran", called, list(STEPS))


def test_the_pin_and_channel_are_the_wired_ones():
    print("\nthe pin and channel are the wired ones")
    check("BUZZER", hook.BUZZER, 13)
    check("PWM_CHANNEL", hook.PWM_CHANNEL, 1)
    check("backlight pin", hook.BACKLIGHT, 18)
    check("power LED pin", hook.POWER_LED, 4)


def main():
    print("=" * 66)
    print("Shutdown hook - the farewell, without shutting anything down")
    print("=" * 66)

    test_the_farewell_is_the_greeting_reversed()
    test_the_notes_become_the_right_periods()
    test_the_duty_is_half_the_period()
    test_the_duty_is_zeroed_before_every_period()
    test_the_notes_run_into_each_other()
    test_the_channel_is_left_silent()
    test_a_note_that_fails_still_silences_the_channel()
    test_the_fallback_is_used_when_there_is_no_pwm_channel()
    test_ensure_channel_gives_up_without_a_chip()
    test_a_reboot_is_left_alone()
    test_a_poweroff_runs_every_step_in_order()
    test_a_halt_is_treated_like_a_poweroff()
    test_the_pin_and_channel_are_the_wired_ones()

    print("\n" + "=" * 66)
    if failures:
        print(f"RESULT: {len(failures)} CHECK(S) FAILED")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("RESULT: the farewell reaches the driver as the right periods, at half")
    print("        duty, running into each other, and the channel is always left")
    print("        silent. A reboot plays nothing.")
    print("        This does NOT mean the farewell was heard. Only a real")
    print("        poweroff can tell you that - it has been silent before while")
    print("        every call reported success.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
