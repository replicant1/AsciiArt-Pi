"""
The bottom line of the terminal: every setting's state, and what fits.

Two jobs, and the second is the awkward one. Every toggle reads out its current
state on the left, so nothing about the app is hidden - if you cannot remember
what is on, the answer is on that line. On the right are the key hints, and a
narrow window cannot hold both.

**Sections are dropped whole rather than the string being cut.** A fixed line
truncated to width ends mid-word, and "s:sche" is worse than no hint at all. So
the hints come in four progressively shorter forms and the first that fits is
used; the readouts on the left are never dropped, because they are the half
that cannot be guessed.

A refused change takes the hints' place for a few seconds. The hints are the
same every frame and the message is the answer to what was just pressed, so
while there is something to say the hints are what gives way.

This is a function of its arguments and nothing else - no app, no display, no
clock. The caller works out the frame rate, decides whether a notice has
expired, and asks the display how wide it is; all of those need state that
changes every frame, and none of them is formatting.
"""

# The four hint sets, longest first. Each is a prefix of the situation above it
# in usefulness rather than in text: what survives a narrower window is the key
# somebody reaching for the keyboard is most likely to want, not the first few
# characters of the full list.
HINTS = (
    " | q:quit r:rotate f:fill i:invert c:chars +/-:contrast"
    " a:auto s:scheme SPC:freeze t:target l:lcdfont",
    " | q:quit r:rotate f:fill i:invert c:chars s:scheme"
    " SPC:freeze t:target",
    " | q:quit r:rotate f:fill s:scheme SPC:freeze",
    " | q:quit",
    "",
)


def on_off(flag):
    """"on" or "off", for a line where "True" would read oddly."""
    return "on" if flag else "off"


def readouts(config, rate, geometry, lcd_grid=None):
    """
    The left-hand half: frame rate, grid, and the state of every toggle.

    Args:
        config: the live RenderConfig.
        rate: already-formatted, because a frozen picture reports "frozen"
            rather than a number and only the caller knows it is frozen for
            long enough to have stopped collecting frame times.
        geometry: the character grid as text, or "headless" where there is no
            window to have one.
        lcd_grid: the panel's own (cols, rows), or None if no panel is running.
    """
    stats = (f" {rate} {geometry} rot{config.rotation}"
             f" con{config.contrast:.1f}"
             f" sch:{config.scheme}"
             f" chr:{config.ramp}"
             f" auto:{on_off(config.auto_levels)}"
             f" fill:{on_off(config.fill)}"
             f" inv:{on_off(config.invert)}"
             f" tgt:{config.target}")

    if lcd_grid is not None:
        # Showing the panel's own grid makes its independence from the
        # terminal's visible: resizing the window moves one and not the other,
        # and changing the panel font moves the panel's alone.
        stats += " lcd:%dx%d@%d" % (tuple(lcd_grid)
                                    + (config.lcd_font_size,))
    return stats


def status_line(config, rate, geometry, lcd_grid=None, notice=None, width=80):
    """
    The whole line, trimmed to what the window can show.

    Args:
        notice: something to say in place of the key hints, or None. The caller
            owns its lifetime - whether it has expired is a question about a
            clock, not about formatting.
        width: how many columns there are to fill.
    """
    stats = readouts(config, rate, geometry, lcd_grid)

    # A refusal or a clamp beats the key list.
    if notice is not None:
        return f"{stats} | {notice}"[:width]

    for hints in HINTS:
        if len(stats) + len(hints) <= width:
            return stats + hints

    # Narrower than the readouts themselves. Nothing left to drop whole, so
    # this is the one place a cut is the only answer. NcursesDisplay clips to
    # the same width when it writes, so this changes no pixel - it just makes
    # the width argument mean what it says, which is what lets a test hold the
    # promise to it.
    return stats[:width]


__all__ = ["HINTS", "on_off", "readouts", "status_line"]
