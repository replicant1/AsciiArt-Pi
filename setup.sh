#!/bin/bash
# Setup / verification for ASCII Art Live Camera on Raspberry Pi Zero 2.
#
# Everything needed is in Raspberry Pi OS Bookworm already, so this script
# mostly *checks* rather than installs.  Installs use the low-memory apt
# incantation: the Zero 2 has ~416 MB and apt-listchanges has been seen getting
# OOM-killed mid-install, which leaves the package database wedged.

set -u

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
missing=()

echo "================================"
echo "ASCII Art Camera - Setup Check"
echo "================================"
echo

if ! grep -qa "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    echo "Warning: this does not look like a Raspberry Pi."
fi

check_module() {
    if python3 -c "import $1" 2>/dev/null; then
        echo "  OK      $1"
    else
        echo "  MISSING $1"
        missing+=("$2")
    fi
}

echo "Python modules:"
check_module numpy      python3-numpy
check_module PIL        python3-pil
check_module picamera2  python3-picamera2
check_module curses     libncurses-dev
echo

if [ ${#missing[@]} -gt 0 ]; then
    echo "Installing: ${missing[*]}"
    sudo APT_LISTCHANGES_FRONTEND=none DEBIAN_FRONTEND=noninteractive \
        apt-get install -y -o Dpkg::Use-Pty=0 "${missing[@]}"
else
    echo "All Python dependencies present."
fi
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

echo "(An 'Unable to set controls: Device or resource busy' line above just"
echo " means ascii_camera.py is already running and holding the camera.)"
echo
echo "================================"
echo "To run:"
echo "  bash $PROJECT_DIR/run_ascii_camera.sh fit    # fills the screen, no letterboxing"
echo "  bash $PROJECT_DIR/run_ascii_camera.sh 80x80  # exactly 80x80 characters"
echo "  python3 $PROJECT_DIR/ascii_camera.py         # in the current terminal"
echo
echo "In the window: q quit, r rotate, f fill, i invert, c chars, +/- contrast,"
echo "a auto-levels.  Click the window first so it has keyboard focus."
echo "================================"
