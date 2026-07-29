"""Synthetic mouse/keyboard input for testing GUI programs on the Pi.

Creates a virtual input device via /dev/uinput, so events are delivered by the
kernel exactly like real hardware. This works for both Wayland-native and
Xwayland clients, unlike xdotool which only reaches X11 clients.

Requires: python3-evdev, the uinput module loaded, and write access to
/dev/uinput (see the udev rule in CLAUDE.md).

Usage:
    import piinput
    m = piinput.Mouse()
    m.move_to(500, 300)
    m.click()

    k = piinput.Keyboard()
    k.type("hello")
    k.key("ENTER")
"""
import time

from evdev import AbsInfo, UInput
from evdev import ecodes as e

# Screen size of the Pi's display. ABS values are scaled to this.
SCREEN_W = 2048
SCREEN_H = 1080

# Time for udev/the compositor to notice a newly created virtual device.
SETTLE = 1.0


class Mouse:
    """An absolute-positioning virtual pointer."""

    def __init__(self, width=SCREEN_W, height=SCREEN_H):
        self.width = width
        self.height = height
        cap = {
            e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE],
            e.EV_ABS: [
                (e.ABS_X, AbsInfo(value=0, min=0, max=width - 1, fuzz=0, flat=0, resolution=0)),
                (e.ABS_Y, AbsInfo(value=0, min=0, max=height - 1, fuzz=0, flat=0, resolution=0)),
            ],
        }
        self.ui = UInput(cap, name="pi-test-mouse", version=0x3)
        time.sleep(SETTLE)

    def move_to(self, x, y):
        self.ui.write(e.EV_ABS, e.ABS_X, max(0, min(self.width - 1, int(x))))
        self.ui.write(e.EV_ABS, e.ABS_Y, max(0, min(self.height - 1, int(y))))
        self.ui.syn()
        time.sleep(0.2)

    def click(self, button=e.BTN_LEFT):
        self.ui.write(e.EV_KEY, button, 1)
        self.ui.syn()
        time.sleep(0.05)
        self.ui.write(e.EV_KEY, button, 0)
        self.ui.syn()
        time.sleep(0.2)

    def click_at(self, x, y, button=e.BTN_LEFT):
        self.move_to(x, y)
        self.click(button)

    def close(self):
        self.ui.close()


# Characters that need Shift held down.
_SHIFTED = {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6",
    "&": "7", "*": "8", "(": "9", ")": "0", "_": "MINUS", "+": "EQUAL",
    "{": "LEFTBRACE", "}": "RIGHTBRACE", ":": "SEMICOLON", '"': "APOSTROPHE",
    "<": "COMMA", ">": "DOT", "?": "SLASH", "~": "GRAVE", "|": "BACKSLASH",
}
_PLAIN = {
    " ": "SPACE", "-": "MINUS", "=": "EQUAL", "[": "LEFTBRACE", "]": "RIGHTBRACE",
    ";": "SEMICOLON", "'": "APOSTROPHE", ",": "COMMA", ".": "DOT", "/": "SLASH",
    "`": "GRAVE", "\\": "BACKSLASH", "\n": "ENTER", "\t": "TAB",
}


class Keyboard:
    """A virtual keyboard covering the whole standard key set."""

    def __init__(self):
        # Only real key codes. dir(ecodes) also yields sentinels like KEY_MAX
        # and KEY_CNT, and enabling those makes UInput fail with EINVAL.
        keys = sorted(c for c in e.keys if isinstance(c, int) and c < e.KEY_MAX)
        self.ui = UInput({e.EV_KEY: keys}, name="pi-test-keyboard", version=0x3)
        time.sleep(SETTLE)

    def _tap(self, code, shift=False):
        if shift:
            self.ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 1)
        self.ui.write(e.EV_KEY, code, 1)
        self.ui.syn()
        self.ui.write(e.EV_KEY, code, 0)
        if shift:
            self.ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 0)
        self.ui.syn()
        time.sleep(0.02)

    def key(self, name):
        """Press a named key, e.g. "ENTER", "ESC", "F5", "LEFT"."""
        self._tap(getattr(e, "KEY_" + name.upper()))

    def type(self, text):
        for ch in text:
            if ch.isalpha():
                self._tap(getattr(e, "KEY_" + ch.upper()), shift=ch.isupper())
            elif ch.isdigit():
                self._tap(getattr(e, "KEY_" + ch))
            elif ch in _SHIFTED:
                self._tap(getattr(e, "KEY_" + _SHIFTED[ch]), shift=True)
            elif ch in _PLAIN:
                self._tap(getattr(e, "KEY_" + _PLAIN[ch]))
            else:
                raise ValueError("no key mapping for %r" % ch)

    def close(self):
        self.ui.close()
