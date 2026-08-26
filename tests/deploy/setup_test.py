#!/usr/bin/env python3
"""
Check that setup.sh notices a config.txt this project cannot run on.

    python3 tests/deploy/setup_test.py

config.txt is not in git and nothing syncs it, so after a reimage its four
load-bearing lines are the one thing that does not come back on its own. The
whole value of the check is that it fails when they are absent - so these
checks are written against config.txt files that are deliberately wrong, and
each asserts on the *reported* state of a specific line rather than on the exit
code alone.

Nothing here touches the real /boot/firmware/config.txt or the real user.
setup.sh reads CONFIG_TXT and APP_USER from the environment for exactly this
reason, and escalates with sudo only when the file it was given needs it - so
--fix is exercised here for real, against a throwaway file, with no root.

The near-miss case is the one worth having. "dtoverlay=pwm-2chan" without its
pins is not a weaker version of the required line: it takes GPIO 18 and 19,
which on this board are the panel backlight and the encoder's CLK. A check that
accepted it would be worse than no check.
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETUP = ROOT / "deploy" / "setup.sh"

GOOD = """\
# a config.txt with everything this project needs
dtparam=spi=on
dtparam=audio=on
camera_auto_detect=1
[all]
gpio=18=op,dl
dtoverlay=gpio-shutdown
dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4
"""

failures = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"           got  {got!r}\n           want {want!r}")
        failures.append(label)


def run(config_text, *args, path=None):
    """Run setup.sh --boot-only against a throwaway config.txt."""
    tmp = Path(tempfile.mkdtemp())
    config = path or (tmp / "config.txt")
    config.write_text(config_text)
    result = subprocess.run(
        ["bash", str(SETUP), "--boot-only", *args],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
             "CONFIG_TXT": str(config),
             # A user that cannot exist, so the group check is a known quantity
             # and never accidentally passes on whatever machine this runs on.
             "APP_USER": "no-such-user-for-tests"},
    )
    return result, config


def boot_states(output):
    """{config line: 'OK' | 'MISSING'} for the boot-configuration block only."""
    states = {}
    inside = False
    for line in output.splitlines():
        if line.startswith("Boot configuration"):
            inside = True
            continue
        if inside and line.startswith("Group membership"):
            break
        if inside:
            m = re.match(r"\s+(OK|MISSING|ADDED)\s+(\S.*)$", line)
            if m:
                states[m.group(2)] = m.group(1)
    return states


SPI = "dtparam=spi=on"
BACKLIGHT = "gpio=18=op,dl"
BUTTON = "dtoverlay=gpio-shutdown"
BUZZER = "dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4"


def test_a_good_config_passes():
    print("\na config.txt with all four lines")
    result, _ = run(GOOD)
    states = boot_states(result.stdout)
    for line in (SPI, BACKLIGHT, BUTTON, BUZZER):
        check(f"{line}", states.get(line), "OK")


def test_a_missing_line_is_reported():
    print("\nthe buzzer overlay removed")
    result, _ = run(GOOD.replace(BUZZER + "\n", ""))
    states = boot_states(result.stdout)
    check("the buzzer line is MISSING", states.get(BUZZER), "MISSING")
    check("the others are still OK",
          [states.get(x) for x in (SPI, BACKLIGHT, BUTTON)], ["OK"] * 3)
    check("it says what the line is for",
          "the buzzer on GPIO 13" in result.stdout, True)
    check("and exits non-zero", result.returncode != 0, True)


def test_a_commented_out_line_does_not_count():
    """
    A line someone disabled is absent, not present.

    Worth its own check because the obvious implementation - a plain grep for
    the text - passes here and would tell you SPI was enabled when it is not.
    """
    print("\nthe SPI line commented out")
    result, _ = run(GOOD.replace(SPI, "# " + SPI))
    states = boot_states(result.stdout)
    check("commented is MISSING, not OK", states.get(SPI), "MISSING")


def test_the_overlay_without_its_pins_is_rejected():
    """
    The near-miss that matters: a bare pwm-2chan takes GPIO 18 and 19.
    """
    print("\nthe buzzer overlay with its pins left off")
    result, _ = run(GOOD.replace(BUZZER, "dtoverlay=pwm-2chan"))
    states = boot_states(result.stdout)
    check("the required line is still MISSING", states.get(BUZZER), "MISSING")
    check("and exits non-zero", result.returncode != 0, True)


def test_indented_lines_still_count():
    """Leading whitespace is legal in config.txt and must not fail the check."""
    print("\na line with leading whitespace")
    result, _ = run(GOOD.replace(BUTTON, "    " + BUTTON))
    states = boot_states(result.stdout)
    check("indentation is tolerated", states.get(BUTTON), "OK")


def test_fix_appends_what_is_missing():
    """
    --fix writes the missing lines, backs the file up first, and then passes.

    Run for real against a throwaway file, so this exercises the append path
    rather than asserting about it.
    """
    print("\n--fix repairs a config.txt with two lines missing")
    broken = GOOD.replace(BUZZER + "\n", "").replace(BACKLIGHT + "\n", "")
    result, config = run(broken, "--fix")
    states = boot_states(result.stdout)
    check("the buzzer line was added", states.get(BUZZER), "ADDED")
    check("the backlight line was added", states.get(BACKLIGHT), "ADDED")

    backups = list(config.parent.glob("config.txt.bak-*"))
    check("a backup was made", len(backups), 1)
    if backups:
        check("and the backup is the file as it was",
              backups[0].read_text(), broken)

    check("it says a reboot is needed",
          "reboot is needed" in result.stdout, True)

    # The real proof: run again against the repaired file and it now passes.
    again, _ = run(config.read_text())
    check("a re-run finds nothing missing",
          [boot_states(again.stdout).get(x)
           for x in (SPI, BACKLIGHT, BUTTON, BUZZER)], ["OK"] * 4)


def test_a_user_that_does_not_exist_is_reported():
    print("\nthe group check against a user that does not exist")
    result, _ = run(GOOD)
    check("says so rather than passing quietly",
          "does not exist" in result.stdout, True)


def main():
    print("=" * 66)
    print("setup.sh - does it notice a config.txt this project cannot run on?")
    print("=" * 66)

    if not SETUP.is_file():
        print(f"  setup.sh not found at {SETUP}")
        return 1

    test_a_good_config_passes()
    test_a_missing_line_is_reported()
    test_a_commented_out_line_does_not_count()
    test_the_overlay_without_its_pins_is_rejected()
    test_indented_lines_still_count()
    test_fix_appends_what_is_missing()
    test_a_user_that_does_not_exist_is_reported()

    print("\n" + "=" * 66)
    if failures:
        print(f"RESULT: {len(failures)} CHECK(S) FAILED")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("RESULT: the four config.txt lines are each checked for exactly, a")
    print("        commented-out or pin-less near-miss counts as missing, and")
    print("        --fix repairs a broken file and backs it up first.")
    print("        Nothing here touched the real config.txt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
