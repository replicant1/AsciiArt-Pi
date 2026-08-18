#!/bin/bash
# Launch the ASCII camera in its own terminal window on the Pi's HDMI screen.
#
# Usage: bash run_ascii_camera.sh [GEOMETRY] [extra ascii_camera.py args...]
#
#   GEOMETRY is one of:
#     fit        Largest window that the picture fills exactly (default)
#     COLS       That many columns; rows chosen so the picture fills the window
#     COLSxROWS  Exactly this, letterboxing the picture if the shape disagrees
#
#   bash run_ascii_camera.sh fit
#   bash run_ascii_camera.sh 120
#   bash run_ascii_camera.sh 80x80
#   bash run_ascii_camera.sh fit --colour   # start in the live colour scheme
#   bash run_ascii_camera.sh 120 --fps 10 --rotation 0
#
# Environment:
#   ASCII_FONT=7   Force a font point size instead of the computed one.
#
# Why this script exists rather than a bare lxterminal call:
#
#  * An SSH session does not inherit the desktop's Wayland environment, so
#    XDG_RUNTIME_DIR and WAYLAND_DISPLAY must be set or no window appears.
#  * lxterminal takes its font size from a config file, not the command line,
#    and at the default "Monospace 10" an 80-row window does not fit on a
#    1080px-tall screen - lxterminal silently clamps it to ~57 rows.  So we
#    generate a dedicated profile, leaving the user's own settings alone.
#  * Whether the picture fills the window depends on the character cell's
#    height/width ratio, which changes with font size.  src/art/window_plan.py
#    reads the real cell metrics from Pango and sizes the window to match.

set -u

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
GEOMETRY="${1:-fit}"
[ $# -gt 0 ] && shift

export XDG_RUNTIME_DIR=/run/user/1000
export WAYLAND_DISPLAY=wayland-0

# --- screen size ------------------------------------------------------------
# Parse with sed rather than ${MODE%x*}: the mode string ends in " px", so a
# shortest-suffix strip on "x" chops at the x in "px" and yields "2048x1080 p".
read -r SCREEN_W SCREEN_H <<< "$(wlr-randr 2>/dev/null \
    | grep -oE '[0-9]+x[0-9]+ px' | head -1 \
    | sed -E 's/([0-9]+)x([0-9]+) px/\1 \2/')"
SCREEN_W="${SCREEN_W:-2048}"
SCREEN_H="${SCREEN_H:-1080}"

# --- camera aspect, which a 90/270 degree rotation transposes ---------------
ASPECT=1.3333
case " $* " in
    *" --rotation 90 "*|*" --rotation 270 "*) ASPECT=0.75 ;;
esac

# --- plan the window --------------------------------------------------------
PLAN=$(python3 "$PROJECT_DIR/src/art/window_plan.py" \
       "$GEOMETRY" "$SCREEN_W" "$SCREEN_H" "$ASPECT" 2>/dev/null)
if [ -z "$PLAN" ]; then
    echo "window_plan.py failed; falling back to 80x33 Monospace 7" >&2
    PLAN="80 33 7 1.833"
fi
read -r COLS ROWS FONT_SIZE CELL_ASPECT <<< "$PLAN"

# Colour gets no special treatment here. The app used to coarsen the grid when
# the live scheme was on, and this script used to halve the planned window to
# match, so the picture still filled it. Both are gone: the grid now follows the
# window and the camera alone, whatever the scheme, and colour simply costs
# frame rate. One geometry, one grid, whichever scheme you land on.

[ -n "${ASCII_FONT:-}" ] && FONT_SIZE="$ASCII_FONT"

# --- dedicated lxterminal profile -------------------------------------------
# lxterminal 0.4.1 builds the profile path as "lxterminal-<NAME>.conf" (see the
# "lxterminal%s%s.conf" format string in the binary), NOT "<NAME>.conf" - get
# this wrong and it silently falls back to the default profile.
PROFILE=asciicam
PROFILE_DIR="$HOME/.config/lxterminal"
mkdir -p "$PROFILE_DIR"
cat > "$PROFILE_DIR/lxterminal-$PROFILE.conf" <<EOF
[general]
fontname=Monospace $FONT_SIZE
scrollback=0
bgcolor=rgb(0,0,0)
fgcolor=rgb(220,220,220)
disallowbold=false
cursorblinks=false
audiblebell=false
geometry_columns=$COLS
geometry_rows=$ROWS
hidescrollbar=true
hidemenubar=true
hideclosebutton=false
disablef10=false
disableconfirm=true
EOF

# --no-remote stops lxterminal handing the request to an already-running
# instance, which would ignore this profile entirely.
# Redirecting output matters too: if lxterminal keeps the SSH session's stdout
# open, run_on_pi.sh never returns and the launch looks like a hang.
lxterminal --no-remote \
           --profile="$PROFILE" \
           --geometry="${COLS}x${ROWS}" \
           --title="ASCII Art Camera" \
           -e "python3 $PROJECT_DIR/ascii_camera.py --cell-aspect $CELL_ASPECT $*" \
           >/dev/null 2>&1 &

echo "Launched ASCII camera"
echo "  window   ${COLS}x${ROWS} characters, Monospace $FONT_SIZE"
echo "  cell     aspect $CELL_ASPECT (height/width)"
echo "  screen   ${SCREEN_W}x${SCREEN_H} px"
echo "  args     ${*:-none}"
echo "  log      $PROJECT_DIR/ascii_camera.log"
