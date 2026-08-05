"""
Rotary encoder input: a KY-040 knob on two GPIO pins.

Wiring as fitted (BCM numbering):

    CLK -> GPIO 19       + -> 3.3V
    DT  -> GPIO 26     GND -> GND
    SW  -> not connected

The module carries its own pull-up resistors on CLK and DT, which is why those
two pins read high at rest even though this chip defaults GPIO 9-27 to pull-down.
An internal pull-up is enabled anyway so the decoder still behaves if the
module's 3.3V line is ever disturbed - an unconnected pin would otherwise float
and invent transitions.

Two decisions here are worth stating, because both were measured on this
hardware rather than assumed (tools/probe_encoder.py):

Bounce is heavy.  Turning the knob about twenty clicks produced 453 edges that
reduced to 88 once repeats inside a millisecond were dropped - roughly a 5:1
ratio.  Any decoder that simply counts edges, or that reads the partner pin at
each edge, will therefore report bursts of phantom movement.  So this uses a
transition table instead of edge counting: it tracks where the shaft is within
the quadrature cycle and emits a step only on a *complete* cycle.  A contact
rattling between two adjacent states drives the table back and forth over
transitions that emit nothing, so bounce costs CPU and nothing else.  This is
the property being relied on, and encoder_test.py holds it to it by feeding in
recorded-style bounce and demanding an exact step count.

One detent is one full cycle.  Those 88 edges spanned about twenty clicks, so
roughly 4.4 edges per click - a full four-state cycle per detent.  Emitting per
cycle therefore gives one scheme change per click, which is what a knob should
feel like.  An encoder wired for half-step detents would want R_HALF instead.
"""

import logging
import threading

logger = logging.getLogger(__name__)

# Decoder states.  The name says how far round a cycle the shaft has got and
# in which direction, so an unexpected transition can always fall back to START
# without the caller ever seeing a step.
_START = 0x0
_CW_FINAL = 0x1
_CW_BEGIN = 0x2
_CW_NEXT = 0x3
_CCW_BEGIN = 0x4
_CCW_FINAL = 0x5
_CCW_NEXT = 0x6

# Flags OR-ed into the next state when a full cycle completes.
_DIR_CW = 0x10
_DIR_CCW = 0x20
_STATE_MASK = 0x07
_DIR_MASK = 0x30

# Row = current state, column = the new (clk, dt) pin pair as (clk << 1) | dt.
# Every row covers all four pin combinations, so no input can fall through:
# a transition that does not belong to the direction being tracked routes back
# to _START and emits nothing.  That total coverage is what makes the table
# bounce-proof rather than merely bounce-tolerant.
_TABLE = (
    # _START: sitting at rest with both pins high; one pin dropping starts a
    # cycle and which one it is decides the direction.
    (_START,     _CW_BEGIN,  _CCW_BEGIN, _START),
    # _CW_FINAL: three quarters round clockwise; both pins high again completes
    # it and is the only transition in the whole table that emits a CW step.
    (_CW_NEXT,   _START,     _CW_FINAL,  _START | _DIR_CW),
    # _CW_BEGIN
    (_CW_NEXT,   _CW_BEGIN,  _START,     _START),
    # _CW_NEXT
    (_CW_NEXT,   _CW_BEGIN,  _CW_FINAL,  _START),
    # _CCW_BEGIN
    (_CCW_NEXT,  _START,     _CCW_BEGIN, _START),
    # _CCW_FINAL: the mirror of _CW_FINAL, and the only CCW step in the table.
    (_CCW_NEXT,  _CCW_FINAL, _START,     _START | _DIR_CCW),
    # _CCW_NEXT
    (_CCW_NEXT,  _CCW_FINAL, _CCW_BEGIN, _START),
)


class QuadratureDecoder:
    """
    Pin levels in, detents out.  No GPIO, no threads, no clock.

    Kept free of hardware on purpose: this is the part that can be wrong in a
    way nobody notices until the knob feels bad, so it has to be testable on a
    machine with no encoder attached.
    """

    def __init__(self):
        self._state = _START

    def feed(self, clk, dt):
        """
        Advance the state machine.

        Args:
            clk: Current CLK level, 0 or 1.
            dt: Current DT level, 0 or 1.

        Returns:
            +1 for one detent clockwise, -1 for one anticlockwise, 0 for a
            transition that does not complete a cycle - which is most of them,
            and all of the ones bounce produces.
        """
        entry = _TABLE[self._state & _STATE_MASK][(clk << 1) | dt]
        self._state = entry & _STATE_MASK
        direction = entry & _DIR_MASK
        if direction == _DIR_CW:
            return 1
        if direction == _DIR_CCW:
            return -1
        return 0


class RotaryEncoder:
    """
    A KY-040 on two GPIO pins, read through lgpio's edge callbacks.

    Callbacks arrive on lgpio's own thread, so steps are accumulated under a
    lock and the render loop collects them with take().  Nothing here blocks
    that loop, and a knob nobody touches costs it nothing at all.
    """

    def __init__(self, clk=19, dt=26, reverse=False, chip=0):
        """
        Args:
            clk: BCM pin for CLK.
            dt: BCM pin for DT.
            reverse: Swap which way is positive.  Whether clockwise counts as
                forward depends on which of the two pins the user called CLK
                when wiring, and that is a coin toss no amount of code can
                settle - so it is a flag rather than a guess.
            chip: gpiochip number.
        """
        self.clk = clk
        self.dt = dt
        self.reverse = reverse
        self.chip = chip

        self._decoder = QuadratureDecoder()
        self._lock = threading.Lock()
        self._steps = 0
        self._levels = {}
        self._handle = None
        self._callbacks = []

        self.detents = 0        # total movement seen, for the log

    def start(self):
        """
        Claim the pins and begin watching.  Raises if the pins are unavailable.

        Deliberately allowed to raise: the caller decides whether a missing
        knob is fatal, exactly as it does for the LCD.
        """
        import lgpio                     # imported late: only exists on the Pi

        self._lgpio = lgpio
        self._handle = lgpio.gpiochip_open(self.chip)
        for pin in (self.clk, self.dt):
            lgpio.gpio_claim_alert(self._handle, pin, lgpio.BOTH_EDGES,
                                   lgpio.SET_PULL_UP)
            # A short hardware debounce spares this 1GHz core most of the 5:1
            # bounce measured on these contacts.  It is an optimisation only -
            # correctness rests on the transition table, which is why the value
            # is small enough that a fast turn still gets through intact.
            try:
                lgpio.gpio_set_debounce_micros(self._handle, pin, 200)
            except AttributeError:
                pass                     # older lgpio; the table copes anyway
            self._levels[pin] = lgpio.gpio_read(self._handle, pin)

        for pin in (self.clk, self.dt):
            self._callbacks.append(
                lgpio.callback(self._handle, pin, lgpio.BOTH_EDGES,
                               self._on_edge))

        logger.info("Rotary encoder on CLK=GPIO%d DT=GPIO%d%s",
                    self.clk, self.dt, " (reversed)" if self.reverse else "")
        return self

    def _on_edge(self, _chip, gpio, level, _tick):
        # Level 2 is lgpio's watchdog tick rather than a real edge.
        if level not in (0, 1):
            return
        self._levels[gpio] = level
        step = self._decoder.feed(self._levels[self.clk],
                                  self._levels[self.dt])
        if not step:
            return
        if self.reverse:
            step = -step
        with self._lock:
            self._steps += step
            self.detents += 1

    def take(self):
        """
        Net detents since the last call, and reset.

        Net rather than a list of events: two clicks one way and two back is
        no change, and the picture should not flicker through four schemes to
        say so.  Returns 0 when the knob has not moved, which is the usual case
        and costs the render loop only a lock.
        """
        with self._lock:
            steps, self._steps = self._steps, 0
        return steps

    def stop(self):
        """Release the pins.  Safe to call twice, and never raises."""
        for callback in self._callbacks:
            try:
                callback.cancel()
            except Exception:
                pass
        self._callbacks = []
        if self._handle is not None:
            try:
                for pin in (self.clk, self.dt):
                    self._lgpio.gpio_free(self._handle, pin)
                self._lgpio.gpiochip_close(self._handle)
            except Exception as e:
                logger.error("Releasing the encoder failed: %s", e)
            self._handle = None
        logger.info("Rotary encoder stopped: %d detents", self.detents)
