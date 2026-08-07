"""
The one place the app's version is written down.

Deliberately a module of its own with no imports at all, so anything can read it
without dragging in numpy, PIL, curses or the camera.  Two callers need exactly
that: argparse wants it before the heavy modules are loaded, and the LCD worker
wants it on a thread that has none of them.

Bump `__version__` by hand.  It is not derived from git on purpose: the copy
that actually runs lives on the Pi at /home/rod/Projects/AsciiArt, which is not
a git checkout - the repository is kept off the SSHFS mount (see CLAUDE.md) - so
asking git would report nothing on the one machine where the number is visible
to a user.
"""

__version__ = "1.0.0"

# The name the app calls itself, on the start-up screen and in --version.
APP_NAME = "ascii_camera"
