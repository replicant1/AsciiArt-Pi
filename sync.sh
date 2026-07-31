#!/bin/bash
#
# Move files between this git repo and the Raspberry Pi's SSHFS mount.
#
#   bash sync.sh              # or "pull": Pi mount -> repo, ready to commit
#   bash sync.sh push         # repo -> Pi mount, e.g. after a git pull
#   bash sync.sh status       # report differences, copy nothing
#
# Why the repo is not simply kept inside the mount: git does a great deal of
# read-after-write against its own object store, and reads back through this
# SSHFS mount can return stale cached data when the Pi has written out of band
# (see CLAUDE.md). Keeping .git on local disk avoids handing git a filesystem
# that can lie to it. The cost is this script.
#
# Layout assumed (override with ASCIIART_PI / ASCIIART_LOCAL):
#
#   PiProjects/AsciiArt/
#   |-- remote/        the Pi, over SSHFS   <- deployed code runs here
#   |-- local/         Mac-only working notes, holds the unredacted CLAUDE.md
#   `-- AsciiArt-Pi/   this repo

set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
PARENT="$(cd "$REPO/.." && pwd)"
PI="${ASCIIART_PI:-$PARENT/remote}"
LOCAL="${ASCIIART_LOCAL:-$PARENT/local}"

MODE="${1:-pull}"

ROOT_FILES=(ascii_camera.py run_ascii_camera.sh setup.sh requirements.txt
            README.md piinput.py setup_uinput.sh)
SRC_FILES=(ascii_art.py camera.py display.py image_processor.py window_plan.py
           lcd.py lcd_display.py lcd_worker.py palettes.py)
TEST_FILES=(bench_pipeline.py capture_reference.py
            lcd_selftest.py lcd_render_bench.py lcd_concurrency.py
            palette_test.py keymap_test.py)
# README.md links to these, so they are kept alongside rather than repo-only:
# otherwise the two copies of the README would reference files that exist on one
# side and not the other.
DOC_FILES=(screenshot.png screenshot-colour.png display-selection-guide.html)

changed=0

# --- safety: is the Pi actually mounted? ------------------------------------
#
# This matters most for "push". If the mount has dropped, $PI is just an empty
# directory on the Mac, and copying into it would silently write to local disk
# while appearing to succeed - the code would never reach the Pi.
require_mount() {
    if ! mount | grep -q " on $PI "; then
        echo "ERROR: $PI is not a live mount." >&2
        echo "       Run ~/mountpi.sh first, or set ASCIIART_PI." >&2
        exit 1
    fi
}

# --- CLAUDE.md: regenerate from the unredacted original ---------------------
#
# The repo's copy has the Pi's address partly masked. Redaction is re-applied
# on every sync rather than done once, so a later edit to the original cannot
# quietly reintroduce the full address into a public commit.
#
# The pattern is deliberately generic - matching any dotted quad rather than
# one specific address - because this script is itself published, and hardcoding
# the address here would defeat the point of masking it in CLAUDE.md.
redact_claude_md() {
    local src="$LOCAL/CLAUDE.md" dst="$REPO/CLAUDE.md" tmp
    if [ ! -f "$src" ]; then
        echo "  skip  CLAUDE.md (no $src)"
        return
    fi

    tmp="$(mktemp)"
    sed -E 's/([0-9]{1,3}\.[0-9]{1,3})\.[0-9]{1,3}\.[0-9]{1,3}/\1.x.x/g' \
        "$src" > "$tmp"

    if grep -Eq '([0-9]{1,3}\.){3}[0-9]{1,3}' "$tmp"; then
        rm -f "$tmp"
        echo "ERROR: an unmasked IP address survived redaction; refusing." >&2
        exit 1
    fi

    if [ "$MODE" = status ]; then
        cmp -s "$tmp" "$dst" || { echo "  DIFF  CLAUDE.md"; changed=1; }
        rm -f "$tmp"
        return
    fi

    if cmp -s "$tmp" "$dst"; then
        rm -f "$tmp"
    else
        mv "$tmp" "$dst"
        chmod 644 "$dst"
        echo "  copy  CLAUDE.md (IP redacted)"
        changed=1
    fi
}

# --- copy one file, reporting only real changes -----------------------------
transfer() {
    local from="$1" to="$2" label="$3"
    if [ ! -f "$from" ]; then
        echo "  MISS  $label (not at $from)"
        return
    fi
    if cmp -s "$from" "$to"; then
        return
    fi
    changed=1
    if [ "$MODE" = status ]; then
        echo "  DIFF  $label"
    else
        cp "$from" "$to"
        echo "  copy  $label"
    fi
}

sweep() {
    local direction="$1"          # "pull" or "push"
    local name
    for name in "${ROOT_FILES[@]}"; do
        if [ "$direction" = pull ]; then
            transfer "$PI/$name" "$REPO/$name" "$name"
        else
            transfer "$REPO/$name" "$PI/$name" "$name"
        fi
    done
    for name in "${SRC_FILES[@]}"; do
        if [ "$direction" = pull ]; then
            transfer "$PI/src/$name" "$REPO/src/$name" "src/$name"
        else
            transfer "$REPO/src/$name" "$PI/src/$name" "src/$name"
        fi
    done
    for name in "${TEST_FILES[@]}"; do
        if [ "$direction" = pull ]; then
            transfer "$PI/tests/$name" "$REPO/tests/$name" "tests/$name"
        else
            transfer "$REPO/tests/$name" "$PI/tests/$name" "tests/$name"
        fi
    done
    for name in "${DOC_FILES[@]}"; do
        if [ "$direction" = pull ]; then
            transfer "$PI/docs/$name" "$REPO/docs/$name" "docs/$name"
        else
            transfer "$REPO/docs/$name" "$PI/docs/$name" "docs/$name"
        fi
    done
}

case "$MODE" in
    pull|status)
        require_mount
        [ "$MODE" = status ] && echo "Differences (Pi -> repo):" \
                             || echo "Pi -> repo:"
        sweep pull
        redact_claude_md
        ;;
    push)
        require_mount
        mkdir -p "$PI/src" "$PI/tests" "$PI/docs"
        echo "repo -> Pi:"
        sweep push
        # CLAUDE.md is deliberately never pushed: the repo's copy is redacted,
        # and writing it back would destroy the original's real address.
        ;;
    *)
        echo "usage: bash sync.sh [pull|push|status]" >&2
        exit 2
        ;;
esac

if [ "$changed" -eq 0 ]; then
    echo "  (nothing to do - already in sync)"
elif [ "$MODE" = pull ]; then
    echo
    echo "Now: git -C '$REPO' add -A && git -C '$REPO' commit && git -C '$REPO' push"
fi
