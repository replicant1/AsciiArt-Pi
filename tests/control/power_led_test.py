#!/usr/bin/env python3
"""
Check the power LED's pin handling, without a Pi and without an LED.

    python3 tests/control/power_led_test.py

Nothing in software can see this LED - grim photographs the HDMI output and a
discrete LED on a breadboard is not in it - so what is checkable here is
everything up to the light: which pin, which level, in which order, and that
the line is handed back and the chip closed however the call turns out. The
last line of the run says what a human should look for, because that half
cannot be automated and should not be claimed.

The double is a **fake, not a stub**: it refuses to free a pin that was never
claimed, exactly as lgpio does. That is the whole reason it exists. The
tempting spelling of set_level puts gpio_free in the `finally` next to
gpio_close, and against a stub that shrugs at anything, that version passes.
Against this fake it does what it would do on the Pi - throws on the way out of
a failed claim and replaces the real error with a meaningless one.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from control import power_led                        # noqa: E402

failures = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"           got  {got!r}\n           want {want!r}")
        failures.append(label)


class FakeGpio:
    """
    lgpio's observable behaviour, recorded rather than performed.

    Honest about the things that actually matter here: a pin must be claimed
    before it can be freed, a handle must be open to be used, and closing a
    chip releases whatever it still holds. Everything the module does lands in
    `events` in order, which is the contract - the light itself is not
    reachable from here.
    """

    def __init__(self, fail_on_claim=False):
        self.events = []
        self.claimed = set()
        self.open_handles = set()
        self.fail_on_claim = fail_on_claim

    def gpiochip_open(self, chip):
        self.events.append(("open", chip))
        self.open_handles.add(77)
        return 77                       # an arbitrary handle, as lgpio returns

    def gpio_claim_output(self, handle, pin, level):
        self._require_open(handle)
        if self.fail_on_claim:
            raise RuntimeError("GPIO busy")     # what a pin held elsewhere does
        self.claimed.add(pin)
        self.events.append(("claim", pin, level))

    def gpio_free(self, handle, pin):
        self._require_open(handle)
        if pin not in self.claimed:
            raise ValueError(f"GPIO {pin} was never claimed")   # lgpio's rule
        self.claimed.discard(pin)
        self.events.append(("free", pin))

    def gpiochip_close(self, handle):
        self._require_open(handle)
        self.open_handles.discard(handle)
        self.claimed.clear()            # closing releases what it still holds
        self.events.append(("close",))

    def _require_open(self, handle):
        if handle not in self.open_handles:
            raise ValueError("bad handle")


# -- the checks ---------------------------------------------------------------

def test_on_drives_the_pin_high():
    """Lighting it claims GPIO 4 as an output already at level 1."""
    print("\non() drives GPIO 4 high")
    gpio = FakeGpio()
    power_led.on(gpio=gpio)
    check("the exact sequence, in order",
          gpio.events, [("open", 0), ("claim", 4, 1), ("free", 4), ("close",)])


def test_off_drives_the_pin_low():
    """Putting it out is the same sequence at level 0, not a different path."""
    print("\noff() drives GPIO 4 low")
    gpio = FakeGpio()
    power_led.off(gpio=gpio)
    check("the exact sequence, in order",
          gpio.events, [("open", 0), ("claim", 4, 0), ("free", 4), ("close",)])


def test_the_two_differ_only_in_the_level():
    """
    The guard against on and off quietly becoming the same call.

    Worth its own check because both of the above would still pass if `off`
    were written to call `on` - each asserts its own sequence and neither
    looks at the other.
    """
    print("\non() and off() are opposites")
    lit, dark = FakeGpio(), FakeGpio()
    power_led.on(gpio=lit)
    power_led.off(gpio=dark)
    levels = [e[2] for e in lit.events + dark.events if e[0] == "claim"]
    check("one claims high, the other low", levels, [1, 0])


def test_the_pin_is_handed_back():
    """
    Nothing is left claimed, so the next caller can have the pin.

    The level surviving the free is the fact the module is built on, and it is
    a property of the hardware, not of this code - it is measured on the Pi,
    recorded in the module docstring, and cannot be asserted here.
    """
    print("\nthe line is not left claimed")
    gpio = FakeGpio()
    power_led.on(gpio=gpio)
    check("nothing still claimed", sorted(gpio.claimed), [])
    check("no handle left open", sorted(gpio.open_handles), [])


def test_a_failed_claim_still_closes_the_chip():
    """
    The failure path, and the reason gpio_free is not in the `finally`.

    A pin held by something else makes the claim raise. What must happen then
    is that the chip is closed and the *original* error reaches the caller. Put
    gpio_free in the `finally` instead and this check fails twice over: the
    error becomes lgpio's "never claimed" complaint, which says nothing about
    what went wrong.
    """
    print("\na claim that fails is reported honestly")
    gpio = FakeGpio(fail_on_claim=True)
    try:
        power_led.on(gpio=gpio)
    except Exception as e:                          # noqa: BLE001
        raised = f"{type(e).__name__}: {e}"
    else:
        raised = "nothing raised"
    check("the real error reaches the caller", raised, "RuntimeError: GPIO busy")
    check("the chip was closed anyway", gpio.events[-1], ("close",))
    check("no handle left open", sorted(gpio.open_handles), [])


def test_the_pin_is_the_documented_one():
    """
    GPIO 4 is wired to a real LED and written down in CLAUDE.md.

    A silent repin would leave the light dead and every other check green,
    because they all read the pin from the module they are testing.
    """
    print("\nthe pin and chip are the wired ones")
    check("PIN", power_led.PIN, 4)
    check("CHIP", power_led.CHIP, 0)


def main():
    print("=" * 66)
    print("Power LED (GPIO 4) - pin handling, with no Pi and no LED")
    print("=" * 66)

    test_on_drives_the_pin_high()
    test_off_drives_the_pin_low()
    test_the_two_differ_only_in_the_level()
    test_the_pin_is_handed_back()
    test_a_failed_claim_still_closes_the_chip()
    test_the_pin_is_the_documented_one()

    print("\n" + "=" * 66)
    if failures:
        print(f"RESULT: {len(failures)} CHECK(S) FAILED")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("RESULT: on() drives GPIO 4 high and off() drives it low, the line "
          "is handed back")
    print("        both times, and a claim that fails still closes the chip "
          "and says why.")
    print("        Nothing here can see the LED. On the real board it should "
          "light at start-up")
    print("        and stay lit - `python3 src/control/power_led.py --off` to "
          "put it out by hand.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
