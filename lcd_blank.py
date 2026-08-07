#!/usr/bin/env python3
"""Blank the ILI9341 SPI panel and turn its backlight off.

Run this when the ASCII camera has been stopped: killing the app leaves whatever
frame it last pushed sitting in the panel's memory, lit, indefinitely.

Belt and braces, because each step protects against something different:

  backlight(0)  FIRST, before anything else.  ILI9341.__init__ starts the
                backlight PWM at 100%, and the panel's frame memory is undefined
                after a reset, so reset() and init() with the light on can flash
                garbage at whoever is sitting in front of it.
  fill(BLACK)   clears the panel's own frame memory, so there is nothing to come
                back if the display is ever switched on again.
  SLEEP_IN      the ILI9341's lowest-power state: internal oscillator, booster
                and DC/DC converters off.  The driver's init() sends its
                opposite, 0x11 sleep-out, but nothing in the driver sends this.
  pinctrl       the backlight pin left as an output driving LOW, and this is the
                step that actually matters.

Do NOT finish with ILI9341.close().  Its docstring says it blanks the panel, but
it drives the backlight pin low and then calls GPIO.cleanup() on it, which hands
the pin back as an input - and the module's pull-up promptly relights the
backlight.  Observed directly: after close() the panel showed a uniform glow, and
"pinctrl set 18 op dl" put it out.

So release the GPIO first and set the pin low afterwards, with pinctrl rather
than RPi.GPIO: pinctrl writes the pad register and exits, leaving the pin driven,
whereas anything holding a GPIO line loses it when the process ends.

None of this removes power.  The panel's VCC is wired straight to the Pi's 3.3V
rail with nothing in between, so cutting it needs a hardware change, not code.
"""
import subprocess
import sys

sys.path.insert(0, "/home/rod/Projects/AsciiArt/src")

from lcd import ILI9341

BLACK = 0x0000        # RGB565: all five red, six green and five blue bits clear
SLEEP_IN = 0x10       # ILI9341 sleep-in; init() sends 0x11, sleep-out
DISPLAY_OFF = 0x28

lcd = ILI9341(landscape=True)
lcd.backlight(0)      # belt and braces: the driver now starts the PWM at 0 for
lcd.reset()           # this very reason - frame memory is undefined after a
lcd.init()            # reset, and lighting it flashes garbage at whoever is
lcd.fill(BLACK)       # sitting in front of the panel
lcd._command(DISPLAY_OFF)
lcd._command(SLEEP_IN)

lcd._pwm.stop()
lcd.spi.close()
lcd.GPIO.cleanup([lcd.dc, lcd.rst, lcd.bl])
subprocess.run(["pinctrl", "set", str(lcd.bl), "op", "dl"], check=True)

state = subprocess.run(["pinctrl", "get", str(lcd.bl)],
                       capture_output=True, text=True).stdout.strip()
print(f"panel filled with 0x{BLACK:04X}, display-off 0x{DISPLAY_OFF:02X} and "
      f"sleep-in 0x{SLEEP_IN:02X} sent")
print(f"backlight pin: {state}")
