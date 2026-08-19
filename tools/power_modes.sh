#!/bin/bash
# CPU cost of the terminal render, which is the biggest lever on battery life.
#
# In an enclosure there is no HDMI screen, so --no-terminal is the correct mode
# anyway - and it skips building the 267x100 terminal picture entirely, leaving
# only the 64x24 the panel actually shows. This measures what that is worth.
#
# CPU% is a proxy for dynamic power, not a wattage. It is the honest thing to
# measure from here; converting to watts needs a meter inline with the supply.

cd /home/rod/Projects/AsciiArt || exit 1
SETTLE=35
SAMPLE=15

measure() {
    label="$1"; shift
    pid=$(pgrep -f '[a]scii_camera.py'); [ -n "$pid" ] && kill $pid; sleep 5

    # Backgrounded explicitly. run_ascii_camera.sh returns on its own because it
    # backgrounds lxterminal internally, but a bare python3 does not - and
    # launching it in the foreground here hangs the whole script, which is
    # exactly what the first version of this did.
    "$@" >/dev/null 2>&1 &
    sleep "$SETTLE"
    pid=$(pgrep -f '[a]scii_camera.py' | head -1)
    if [ -z "$pid" ]; then echo "$label: FAILED TO START"; return; fi

    # Whole-process CPU over the sample window, from /proc jiffies.
    t0=$(awk '{print $14+$15}' /proc/$pid/stat)
    w0=$(date +%s)
    sleep "$SAMPLE"
    t1=$(awk '{print $14+$15}' /proc/$pid/stat 2>/dev/null)
    w1=$(date +%s)
    hz=$(getconf CLK_TCK)
    printf '%-28s %5.1f%% CPU   (of one core)\n' "$label" \
        "$(echo "scale=2; ($t1-$t0)/$hz/($w1-$w0)*100" | bc)"
    grep -a 'Rendered\|fps' ascii_camera.log >/dev/null 2>&1
}

echo "=== settle ${SETTLE}s, sample ${SAMPLE}s per mode ==="
measure "HDMI terminal + LCD" bash run_ascii_camera.sh fit --lcd
measure "LCD only (--no-terminal)" nohup python3 -u ascii_camera.py --lcd --no-terminal

pid=$(pgrep -f '[a]scii_camera.py'); [ -n "$pid" ] && kill $pid
echo "done"
