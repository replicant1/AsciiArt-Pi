"""
Which colour scheme is showing, and the two ways of changing it.

The `s` key steps forwards. A KY-040 knob steps both ways and, pressed, jumps
straight home to greyscale. Both end at `RenderConfig` through the same
`apply`, so neither can reach a scheme the other could not.

The knob is optional and the key is not, which is why this is not part of
src/control/encoder.py: that module is the hardware - two pins, a quadrature
table and a switch - and this is the policy about what turning it means. A run
without `--encoder` still cycles schemes; it just has one way in rather than
two.

Two behaviours here were paid for in visible glitches rather than reasoned out
in advance, and both are load-bearing:

  * **A move is applied whole, not one detent at a time.** `set_scheme` repaints
    every cell - it has to, since a light-screen scheme needs a different
    background on each one - so a five-detent spin applied one scheme at a time
    is five full repaints of pictures never on screen long enough to see. That
    is a hard strobe, and it feeds back on itself: a slower frame gives the
    knob longer to bank detents before anything is drawn.
  * **A press beats rotation banked in the same gap.** Only counts survive
    between frames, not the order the events happened in, so "turn then press"
    cannot be told from "press then turn". Going home is the answer that can be
    checked by looking, since it is the same wherever the knob had got to, and
    it costs one repaint rather than two.
"""

import logging

from art import palettes

logger = logging.getLogger(__name__)


class SchemeCycle:
    """Steps the colour scheme, from a key or a knob."""

    # Set only when --encoder brought one up. A class attribute so that
    # anything holding a cycle built without one still finds the name.
    encoder = None

    def __init__(self, settings, apply, colour_ok):
        """
        Args:
            settings: callable returning the live `RenderConfig`. A callable
                rather than the value because the scheme moves underneath this
                - by key, by knob, by socket - and the walk has to start from
                wherever it actually is.
            apply: callable taking a delta and returning whether anything
                changed. The single way settings change; this class never
                touches one directly.
            colour_ok: callable saying whether this terminal can show colour.
                Schemes it cannot show are skipped rather than offered, so the
                knob never lands on a picture nobody can see.
        """
        self._settings = settings
        self._apply = apply
        self._colour_ok = colour_ok

    # --- the knob, if there is one -----------------------------------------

    def start_encoder(self, clk, dt, sw, reverse=False):
        """
        Bring the rotary encoder up, or carry on without it.

        Not fatal on failure, for the same reason the LCD is not: the knob is a
        convenience over a key that still works, so an unplugged or
        misconfigured encoder should cost a log line rather than the whole app.
        lgpio is imported inside RotaryEncoder so this stays runnable off the
        Pi.
        """
        try:
            from control.encoder import RotaryEncoder

            self.encoder = RotaryEncoder(clk=clk, dt=dt, sw=sw,
                                         reverse=reverse).start()
        except Exception as e:
            logger.error("Rotary encoder unavailable, continuing without "
                         "it: %s", e, exc_info=True)
            self.encoder = None
        return self.encoder

    def poll(self):
        """Turn accumulated knob movement and presses into scheme changes."""
        if self.encoder is None:
            return
        steps = self.encoder.take()
        pressed = self.encoder.take_presses()

        # A press wins over rotation banked in the same frame, and the rotation
        # is dropped rather than applied on top - see the module docstring.
        if pressed:
            self.home()
            return

        # Handed over as one move, not one call per detent: everything banked
        # since the last frame lands on a single repaint. See step().
        if steps:
            self.step(steps)

    def stop(self):
        """
        Release the pins, if any were claimed.

        Matters as much as it does for the panel: a claim left behind makes the
        next run's start() fail.
        """
        if self.encoder is not None:
            self.encoder.stop()

    # --- the policy, whichever drove it ------------------------------------

    def home(self):
        """
        Jump straight back to greyscale, however far the knob has wandered.

        Found by kind rather than by name, so renaming the scheme cannot turn
        this into a lookup that raises. The greyscale scheme is also the one
        scheme every terminal can show, so this is the one jump that is always
        available - see the colour_ok test in step().
        """
        home = next(scheme for scheme in palettes.SCHEMES
                    if scheme.kind == "grey")
        # apply() is a no-op when the value is already there, so being home
        # already costs nothing and no repaint flashes.
        if self._apply({"scheme": home.name}):
            logger.info("Scheme: %s (%s) - knob pressed", home.name, home.note)

    def step(self, step=1):
        """
        Step to the next scheme, skipping any this terminal cannot show.

        Args:
            step: +1 for the next scheme, -1 for the previous one.  The
                keyboard only ever goes forwards, but a knob that could not go
                back would be a poor knob.
        """
        count = len(palettes.SCHEMES)
        direction = 1 if step >= 0 else -1
        start = palettes.SCHEME_NAMES.index(self._settings().scheme)

        # Walk to the destination first and change the display once, rather
        # than changing it at every scheme on the way - see the module
        # docstring for what that looked like when it did not.
        #
        # A whole lap is the identity, so the count reduces modulo the list
        # length; clamping to it instead lands a lap off.
        index = start
        for _ in range(abs(step) % count):
            for offset in range(1, count + 1):
                candidate = (index + direction * offset) % count
                if (palettes.SCHEMES[candidate].kind == "grey"
                        or self._colour_ok()):
                    index = candidate
                    break
            else:
                return

        if index == start:
            return
        # No grid invalidation on purpose: the grid does not depend on the
        # scheme any more, so recomputing it would only produce the same answer
        # and log a line claiming a change that did not happen. _adopt knows
        # this - the scheme is not in the set that clears grid_key.
        scheme = palettes.SCHEMES[index]
        if self._apply({"scheme": scheme.name}):
            logger.info("Scheme: %s (%s)", scheme.name, scheme.note)


__all__ = ["SchemeCycle"]
