#!/bin/bash
# One-time install of the goodbye tune, which cannot live in the app.
#
# systemd runs every executable in /usr/lib/systemd/system-shutdown/ after all
# services are stopped and all filesystems unmounted, immediately before the
# kernel halts.  That is the only place a farewell can be the *last* thing the
# machine does - played from the app it is followed by every other service
# stopping, by the LED flashing, and by the halt itself.
#
# Root, hence its own script rather than a step in setup.sh, which deliberately
# only checks.  Same shape as setup_uinput.sh.
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET=/usr/lib/systemd/system-shutdown/asciiart.shutdown

sudo mkdir -p "$(dirname "$TARGET")"
sudo install -m 755 "$HERE/asciiart.shutdown" "$TARGET"

ls -l "$TARGET"
echo
echo "Installed. It plays only on poweroff and halt, not on reboot."
echo "To hear it without powering down:  sudo $TARGET poweroff"
echo "That also puts the panel and the activity LED out, so restore them with:"
echo "  sudo pinctrl set 18 op dh   # backlight back on"
echo "  echo actpwr | sudo tee /sys/class/leds/ACT/trigger"
