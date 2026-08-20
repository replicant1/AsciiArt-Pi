"""
"ask <words>" in, a delta out - on the caller's thread, never the render loop.

This is the piece of the app that is allowed to be slow. `CommandServer` runs
it on the client's own thread precisely so that it can be: a parse crosses a
network and takes two to four seconds, and the render loop cannot stop for that
without stopping both displays with it. By the time the loop sees the result it
is a dict, indistinguishable from a line somebody typed.

The order of the two answers below is the design, not an optimisation:

  1. `src/language/shortcuts.py` is tried first, **before the API key is even
     looked for**. A hit needs no key and no network, so "green" and "freeze
     it" still work with the WiFi down and `ask` stops being all or nothing.
     A hit is also instant, which on a panel with no spinner is the difference
     you feel.
  2. Everything else goes to `src/language/parser.py` and the model.

What comes back is a delta and nothing more. This module never touches a
setting: `RenderConfig` judges whatever it produces, in the same words a typed
line earns, and that is the only reason comparing the two routes means
anything.
"""

import logging
import threading

from language import shortcuts

logger = logging.getLogger(__name__)


class AskResolver:
    """Turns "ask <words>" into a delta, on whatever thread called it."""

    def __init__(self, settings, note, log=None):
        """
        Args:
            settings: callable returning (config, previous_config). A callable
                rather than the values themselves because an ask arrives
                whenever somebody types one, and the settings it is being said
                about are whatever they are at that moment. `RenderConfig` is
                frozen and replaced wholesale on the loop's thread, so reading
                it from here either sees a change or does not - never a
                half-applied one, and never worth a lock.
            note: callable(text, seconds=...) that says something on every
                display this run has. A message that reaches only the socket
                reply has been delivered to whoever is holding a phone, not to
                the person standing in front of the camera.
            log: an AskLog, or None to keep no record. Silent when absent: an
                ask that works is worth more than a record of it.
        """
        self._settings = settings
        self._note = note
        self.log = log

    # --- start-up ----------------------------------------------------------

    def warm(self):
        """
        Import the model SDK in the background, so the first ask is not slow.

        Measured on this Pi: `import anthropic` alone costs 11 seconds, which
        is longer than the CLI used to wait for any reply at all. Left lazy,
        the first "ask" after every restart timed out on the client while
        quietly succeeding on the app - the worst of both, a reported failure
        and a changed setting.

        A daemon thread, started once, and only when there is a key to make it
        worth paying for: without one, ask is off and an 11-second import buys
        nothing but resident memory on a 416 MB machine.
        """
        try:
            from language import parser as nl_parser
        except Exception as e:
            logger.info("Natural language unavailable: %s", e)
            return
        if nl_parser.api_key() is None:
            logger.info("No API key found, so \"ask\" is off; every other "
                        "command still works")
            return

        def warm():
            import time
            started = time.monotonic()
            try:
                import anthropic                            # noqa: F401
            except Exception as e:
                logger.error("Could not load the model SDK: %s", e)
                return
            logger.info("Model SDK ready in %.1f s; \"ask\" is available",
                        time.monotonic() - started)

        threading.Thread(target=warm, name="warm-parser", daemon=True).start()

    # --- the resolver hook -------------------------------------------------

    def resolve(self, line):
        """
        One line off the socket, and what the render loop should be given.

        Returns:
            None if the line is not an ask, so it passes through untouched as
            an ordinary typed command; an `Ask` carrying a delta already worked
            out; or a `Reply` to send straight back without troubling the loop.
        """
        from control.command_server import Ask, Reply

        head, _, rest = line.partition(" ")
        if head.lower() != "ask":
            return None

        utterance = rest.strip()
        if not utterance:
            return Reply('say what you want changed, e.g. ask make it warmer')

        config, previous = self._settings()

        # The table first, and deliberately before the key check.
        delta = shortcuts.look_up(utterance, config, previous)
        if delta is not None:
            logger.info("Ask %r -> %s (table)", utterance, delta)
            self.record(utterance, config, previous, delta=delta,
                        source="table", seconds=0.0)
            return Ask(utterance=utterance, delta=delta, note="instant")

        try:
            from language import parser as nl_parser
        except Exception as e:
            return Reply(f"the language model parser is unavailable: {e}")
        if nl_parser.api_key() is None:
            self._note("no API key, so words are off")
            return Reply("no API key, so ask is off. Put one in "
                         f"{nl_parser.KEY_FILE} to switch it on; every other "
                         "command works without it.")

        # A parse takes two to four seconds, and on a panel with no spinner
        # that is indistinguishable from a camera that ignored you. Say so - and
        # for longer than the parser's own timeout, since the point is that the
        # message cannot expire while the request is still out. The default four
        # seconds was wrong for exactly this: a request may run for twenty, and
        # the panel would go quiet two-thirds of the way through it.
        self._note(f"asking: {utterance[:40]}",
                   seconds=nl_parser.TIMEOUT_SECONDS + 2)

        # A parse that raced a keypress resolves against settings one change
        # stale, which for "a bit warmer" is not worth a lock.
        try:
            parsed = nl_parser.parse(utterance, config, previous=previous)
        except nl_parser.ParseError as e:
            # Network down, key rejected, timeout. The panel and the terminal
            # both have to survive this, so it is a sentence, not a traceback.
            logger.warning("Ask failed for %r: %s", utterance, e)
            self.record(utterance, config, previous, error=str(e))
            # Said on the panel as well as returned to whoever asked. This is
            # the whole of "honest failure": the camera did not do what it was
            # told, and the only display in the box has to admit it rather than
            # carry on showing a picture as though nothing was asked.
            self._note(self.short_failure(e))
            return Reply(f"could not reach the model: {e}")

        if parsed.declined is not None:
            logger.info("Ask declined %r: %s", utterance, parsed.declined)
            self.record(utterance, config, previous, parsed=parsed)
            # A decline is an answer, not a failure - but it is still an answer
            # nobody sees if it only goes back down the socket.
            self._note("cannot do that: " + parsed.declined)
            return Reply(f"  {parsed.declined}")

        note = f"{parsed.seconds:.1f}s"
        if parsed.unmet:
            note += f" - {parsed.unmet}"
        logger.info("Ask %r -> %s (%s)", utterance, parsed.delta, note)
        self.record(utterance, config, previous, parsed=parsed)
        return Ask(utterance=utterance, delta=parsed.delta, note=note)

    # --- saying it, and writing it down ------------------------------------

    @staticmethod
    def short_failure(error):
        """
        Turn a ParseError into something that fits a 320-pixel band.

        The socket reply keeps the full text - whoever typed it can read a
        sentence. The panel gets the kind of failure, because "the network is
        down" and "the key was refused" call for different actions and the
        difference between them is worth the two words it costs.

        The split is by what to do next, not by exception class. Two answer
        failures - the model calling neither tool, and the model asking to
        change nothing - are deliberately left in the fallback, because the
        only move for either is to try again and neither is the asker's
        doing. A safety refusal is not like them: the request itself is what
        was rejected, so retrying it verbatim cannot work, and saying so is
        the difference between somebody rewording the request and somebody
        deciding the camera is broken.
        """
        text = str(error).lower()
        # First, and matching a phrase this codebase writes rather than one
        # the SDK does - src/language/parser.py raises "the model declined
        # this request (category)". Matching the bare word "declined" would
        # be shorter and would also catch a declined card, which is a billing
        # problem wearing the same word and calls for the opposite advice.
        if "declined this request" in text:
            return "the model would not answer - rephrase it"
        if "timeout" in text or "timed out" in text:
            return "the model took too long - try again"
        if "connection" in text or "network" in text or "resolve" in text:
            return "no network - words need one, settings do not"
        if "authentication" in text or "api key" in text or "401" in text:
            return "the API key was refused"
        if "rate" in text and "limit" in text:
            return "asking too fast - wait a moment"
        return "could not ask the model"

    def record(self, utterance, config, previous, parsed=None, error=None,
               delta=None, seconds=None, source="model"):
        """
        Write one ask down, if there is anywhere to write it.

        Runs on the caller's thread with the parse, never the render loop.
        Silent when there is no log: an ask that works is worth more than a
        record of it, so this is the one place in the path allowed to do
        nothing at all.
        """
        if self.log is None:
            return
        self.log.record(
            utterance, config, previous=previous, error=error, source=source,
            delta=delta if parsed is None else parsed.delta or None,
            declined=None if parsed is None else parsed.declined,
            unmet=None if parsed is None else parsed.unmet,
            seconds=seconds if parsed is None else parsed.seconds,
            usage=None if parsed is None else parsed.usage)


__all__ = ["AskResolver"]
