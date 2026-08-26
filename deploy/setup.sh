#!/bin/bash
# Setup / verification for ASCII Art Live Camera on Raspberry Pi Zero 2.
#
#   bash deploy/setup.sh              # check everything; install missing packages
#   bash deploy/setup.sh --fix        # ...and add missing config.txt lines and groups
#   bash deploy/setup.sh --boot-only  # just config.txt and groups, no apt, no camera
#
# Most of what this project needs is in Raspberry Pi OS Bookworm already, so
# this mostly *checks*.  Installs use the low-memory apt incantation: the Zero 2
# has ~416 MB and apt-listchanges has been seen getting OOM-killed mid-install,
# which leaves the package database wedged.
#
# The reason this script exists in its present form is that /boot/firmware/config.txt
# is NOT in git and nothing syncs it, while four of its lines are load-bearing.
# After a reimage their absence shows up as four unrelated-looking faults: no
# /dev/spidev0.0, a panel lit from the moment of power-on, no way to switch the
# box on, and a silent buzzer.  Checking for them here is the difference between
# a script run and an archaeology exercise.  CLAUDE.md carries the same list.
#
# CONFIG_TXT and APP_USER are overridable so the checks can be run against a
# throwaway file - see tests/deploy/setup_test.py, which does exactly that.

set -u

CONFIG_TXT="${CONFIG_TXT:-/boot/firmware/config.txt}"
APP_USER="${APP_USER:-rod}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

FIX=0
BOOT_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --fix)       FIX=1 ;;
        --boot-only) BOOT_ONLY=1 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

problems=0
needs_reboot=0

ok()   { echo "  OK      $*"; }
bad()  { echo "  MISSING $*"; problems=$((problems + 1)); }
fixed(){ echo "  ADDED   $*"; }

# --- what config.txt must contain -------------------------------------------
#
# Exact lines, deliberately.  A near-miss is worth reporting rather than
# tolerating: "dtoverlay=pwm-2chan" without its pins is not a lesser version of
# the line below, it is the one that silently takes GPIO 18 and 19 - the panel
# backlight and the encoder's CLK.
BOOT_LINES=(
    "dtparam=spi=on|the ILI9341 SPI panel (/dev/spidev0.0)"
    "gpio=18=op,dl|the panel backlight, held off from the first instant of boot"
    "dtoverlay=gpio-shutdown|the power button on GPIO 3, this box's only switch"
    "dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4|the buzzer on GPIO 13, driven as hardware PWM"
)

REQUIRED_GROUPS=(spi i2c gpio input video)

# Escalate only when the file actually needs it. On the Pi config.txt is
# root-owned and these go through sudo; pointed at a writable file - which is
# what tests/deploy/setup_test.py does - they do not, so the checks and the
# --fix path can both be exercised without root.
copy_config() {
    if [ -w "$(dirname "$CONFIG_TXT")" ]; then cp "$CONFIG_TXT" "$1"
    else sudo cp "$CONFIG_TXT" "$1"; fi
}

append_config() {
    if [ -w "$CONFIG_TXT" ]; then cat >> "$CONFIG_TXT"
    else sudo tee -a "$CONFIG_TXT" > /dev/null; fi
}

config_has() {
    [ -f "$CONFIG_TXT" ] || return 1
    # -x is doing the work: the whole line must equal the required text, so a
    # commented-out line fails by construction and there is no need to filter
    # comments separately. Leading and trailing whitespace is stripped first,
    # because indentation is legal in config.txt and means nothing.
    # Do NOT relax this to a substring match. "dtparam=spi=on" would then be
    # satisfied by a commented-out copy of itself, and the whole point of the
    # check is to notice a config.txt this project cannot run on.
    sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//' "$CONFIG_TXT" | grep -qxF "$1"
}

check_boot_config() {
    echo "Boot configuration ($CONFIG_TXT):"
    if [ ! -f "$CONFIG_TXT" ]; then
        bad "$CONFIG_TXT does not exist"
        return
    fi
    local entry line why absent=()
    for entry in "${BOOT_LINES[@]}"; do
        line="${entry%%|*}"
        why="${entry#*|}"
        if config_has "$line"; then
            ok "$line"
        else
            bad "$line"
            echo "          ^ needed for $why"
            absent+=("$entry")
        fi
    done

    [ ${#absent[@]} -eq 0 ] && return

    if [ "$FIX" -eq 0 ]; then
        echo
        echo "  Re-run with --fix to append them, or add them by hand under [all]."
        return
    fi

    local backup="$CONFIG_TXT.bak-$(date +%Y%m%d-%H%M%S)"
    if ! copy_config "$backup"; then
        echo "  Could not back up $CONFIG_TXT; refusing to edit it." >&2
        return
    fi
    echo "  Backed up to $backup"
    # An explicit [all] header, so this is correct wherever the file happened to
    # end. Appending blind would land the lines in whatever the last section was.
    {
        echo ""
        echo "# Added by deploy/setup.sh --fix for ASCII Art Live Camera."
        echo "[all]"
        for entry in "${absent[@]}"; do
            echo "${entry%%|*}"
        done
    } | append_config
    for entry in "${absent[@]}"; do
        fixed "${entry%%|*}"
        problems=$((problems - 1))
    done
    needs_reboot=1
}

check_groups() {
    echo
    echo "Group membership for $APP_USER:"
    if ! id "$APP_USER" > /dev/null 2>&1; then
        bad "user $APP_USER does not exist"
        return
    fi
    local have absent=() group
    have=" $(id -nG "$APP_USER") "
    for group in "${REQUIRED_GROUPS[@]}"; do
        if [[ "$have" == *" $group "* ]]; then
            ok "$group"
        else
            bad "$group"
            absent+=("$group")
        fi
    done

    [ ${#absent[@]} -eq 0 ] && return

    if [ "$FIX" -eq 0 ]; then
        local joined
        joined="$(IFS=,; echo "${absent[*]}")"
        echo "  Re-run with --fix, or: sudo usermod -aG $joined $APP_USER"
        return
    fi
    local joined
    joined="$(IFS=,; echo "${absent[*]}")"
    if sudo usermod -aG "$joined" "$APP_USER"; then
        for group in "${absent[@]}"; do
            fixed "$group"
            problems=$((problems - 1))
        done
        echo "  Group changes need a fresh login (or a reboot) to take effect."
        needs_reboot=1
    fi
}

# --- python modules ----------------------------------------------------------
#
# Every module imported by anything under src/. The first four were here from
# the start; the rest were missing from this list for months while being
# imported by the panel, the encoder, the buzzer and the input simulation - so
# a fresh machine passed setup and then failed at run time.
missing_packages=()
check_module() {
    if python3 -c "import $1" 2>/dev/null; then
        ok "$1"
    else
        bad "$1"
        missing_packages+=("$2")
    fi
}

check_modules() {
    echo
    echo "Python modules:"
    check_module numpy      python3-numpy
    check_module PIL        python3-pil
    check_module picamera2  python3-picamera2
    check_module curses     libncurses-dev
    check_module lgpio      python3-lgpio
    check_module spidev     python3-spidev
    check_module evdev      python3-evdev
    check_module RPi.GPIO   python3-rpi.gpio
    check_module gpiozero   python3-gpiozero

    [ ${#missing_packages[@]} -eq 0 ] && return
    echo "  Installing: ${missing_packages[*]}"
    if sudo APT_LISTCHANGES_FRONTEND=none DEBIAN_FRONTEND=noninteractive \
            apt-get install -y -o Dpkg::Use-Pty=0 "${missing_packages[@]}"; then
        problems=$((problems - ${#missing_packages[@]}))
    fi
}

check_services() {
    echo
    echo "Services (unit files are in deploy/; whether they are enabled is not):"
    local unit
    for unit in ascii-camera.service ascii-camera-web.service; do
        local state
        state="$(systemctl is-enabled "$unit" 2>/dev/null || echo "not installed")"
        if [ "$state" = "enabled" ]; then
            ok "$unit enabled"
        else
            echo "  NOTE    $unit is '$state'"
            echo "          sudo cp $PROJECT_DIR/deploy/$unit /etc/systemd/system/"
            echo "          sudo systemctl daemon-reload && sudo systemctl enable --now ${unit%.service}"
        fi
    done
    echo "  NOTE    the shutdown hook is installed as a COPY; if deploy/asciiart.shutdown"
    echo "          has changed, run: bash $PROJECT_DIR/deploy/install_shutdown_hook.sh"
}

check_camera() {
    echo
    echo "Camera:"
    python3 - <<'PY'
import os
os.environ.setdefault("LIBCAMERA_LOG_LEVELS", "*:ERROR")
try:
    from picamera2 import Picamera2
    cameras = Picamera2.global_camera_info()
except Exception as exc:
    print(f"  Could not query libcamera: {exc}")
else:
    if not cameras:
        print("  No camera detected - check the CSI ribbon cable.")
    for cam in cameras:
        print(f"  Found {cam.get('Model')} "
              f"(mounted rotation {cam.get('Rotation')} degrees)")
PY
    echo
    echo "  (An 'Unable to set controls: Device or resource busy' line above just"
    echo "   means ascii_camera.py is already running and holding the camera.)"
}

# --- run ---------------------------------------------------------------------

echo "================================"
echo "ASCII Art Camera - Setup Check"
echo "================================"
echo

if [ "$BOOT_ONLY" -eq 0 ] && ! grep -qa "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    echo "Warning: this does not look like a Raspberry Pi."
    echo
fi

check_boot_config
check_groups

if [ "$BOOT_ONLY" -eq 0 ]; then
    check_modules
    check_services
    check_camera
fi

echo
echo "================================"
if [ "$problems" -gt 0 ]; then
    echo "RESULT: $problems thing(s) still need attention - see MISSING above."
else
    echo "RESULT: everything this project needs is present."
fi
if [ "$needs_reboot" -eq 1 ]; then
    echo "        A reboot is needed for the changes just made to take effect."
fi

if [ "$BOOT_ONLY" -eq 0 ]; then
    echo
    echo "To run:"
    echo "  bash $PROJECT_DIR/run_ascii_camera.sh fit    # fills the screen, no letterboxing"
    echo "  bash $PROJECT_DIR/run_ascii_camera.sh 80x80  # exactly 80x80 characters"
    echo "  python3 $PROJECT_DIR/ascii_camera.py         # in the current terminal"
    echo
    echo "In the window: q quit, r rotate, f fill, i invert, c chars, g colour,"
    echo "a auto-levels.  Click the window first so it has keyboard focus."
fi
echo "================================"

[ "$problems" -eq 0 ]
