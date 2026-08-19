#!/usr/bin/env python3
"""
Check AskResolver: what "ask <words>" turns into, and on whose thread.

    python3 tests/language/resolver_test.py

No camera, no panel, no terminal, no network. These tests were written against
MainRenderLooper, because that is where the code used to live, and they had
to build a whole app to ask a question about a sentence. AskResolver takes a
callable for the settings, a callable for saying things, and an optional log,
so the fakes below are four lines each and the subject under test is the
subject being tested.

A stub parser stands in for src/language/parser.py. What needs pinning down is
the wiring - that the table is consulted before the key is even looked for,
that a decline is an answer rather than a failure, and that an unreachable
model is a sentence rather than a traceback. Whether the model picks good
settings is a different question, and tools/app/ask_parser.py is where it gets
asked.

The property that matters most is invisible in the output: this all happens on
the caller's thread. If it ever migrated into the render loop, every parse
would stop both displays for the seconds it takes.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from control.command_server import Ask, Reply          # noqa: E402
from control.render_config import RenderConfig         # noqa: E402
from language.resolver import AskResolver              # noqa: E402

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}" + (f"  ({detail})" if detail else ""))


class StubParser:
    """Stands in for src/language/parser.py, with no API key and no network."""

    KEY_FILE = "/nowhere/api_key"

    # The resolver reads this to size the "asking" notice, so the stub carries
    # it too: it is part of the parser's surface, not an implementation detail.
    TIMEOUT_SECONDS = 20.0

    class ParseError(RuntimeError):
        pass

    class _Parsed:
        def __init__(self, delta=None, declined=None, unmet=None):
            self.delta = delta
            self.declined = declined
            self.unmet = unmet
            self.seconds = 1.5
            self.usage = None

        @property
        def ok(self):
            return self.delta is not None

    def __init__(self, key="k", result=None, raises=None):
        self._key = key
        self._result = result
        self._raises = raises
        self.calls = []

    def api_key(self):
        return self._key

    def parse(self, utterance, config, previous=None):
        self.calls.append((utterance, config, previous))
        if self._raises is not None:
            raise self._raises
        return self._result


class Notices:
    """Collects what would have been drawn on the terminal and the panel."""

    def __init__(self):
        self.said = []

    def __call__(self, text, seconds=None):
        self.said.append((text, seconds))

    def last(self):
        return self.said[-1][0] if self.said else None


def make_resolver(stub, config=None, previous=None):
    """
    A resolver over fixed settings, with the stub where its import will find it.

    The name has to match what the resolver imports - `language.parser`.
    Patching anything else still "works" in the sense that nothing raises; it
    just stops intercepting, and these tests then go to the real model over the
    network and are scored against whatever it happens to answer. A stub that
    is not reached is worse than no stub, so `reaches_the_stub` below asserts
    the interception itself rather than trusting it.
    """
    sys.modules["language.parser"] = stub
    config = RenderConfig() if config is None else config
    notices = Notices()
    return AskResolver(settings=lambda: (config, previous),
                       note=notices), notices, config


def test_only_asks_are_touched():
    print("\n1. An ordinary typed line passes straight through")
    stub = StubParser(result=StubParser._Parsed(delta={"scheme": "green"}))
    resolver, _, _ = make_resolver(stub)

    check("a typed line is not the resolver's business",
          resolver.resolve("scheme green") is None)
    check("...and the model was never called", stub.calls == [])

    print("\n2. A bare 'ask' asks for words rather than failing")
    resolved = resolver.resolve("ask")
    check("bare ask is answered", isinstance(resolved, Reply))
    check("...with an example", "warmer" in resolved.text, resolved.text)
    check("...and still no model call", stub.calls == [])


def test_the_model_path():
    print("\n3. A phrase with a mood in it goes to the model")
    # Not "make it green" - shortcuts.py answers that from its table without a
    # model, which is the point of the table and would leave this asserting
    # things about a stub nobody called.
    stub = StubParser(result=StubParser._Parsed(delta={"scheme": "green"}))
    resolver, notices, config = make_resolver(stub)

    resolved = resolver.resolve("ask something calmer")
    check("the resolver returns an Ask", isinstance(resolved, Ask),
          type(resolved).__name__)
    check("carrying the delta", resolved.delta == {"scheme": "green"},
          str(resolved.delta))
    check("reaches_the_stub: the model was asked exactly once",
          len(stub.calls) == 1, str(len(stub.calls)))
    check("...and given the live config to resolve against",
          stub.calls[0][1] is config)
    check("the note carries how long it took", resolved.note, "1.5s")

    print("\n4. The wait is announced while it is still happening")
    said, seconds = notices.said[0]
    check("the panel is told an ask is in flight",
          said.startswith("asking:"), said)
    check("...for longer than the parser's own timeout",
          seconds > StubParser.TIMEOUT_SECONDS, str(seconds))


def test_the_table_path():
    print("\n5. A phrase the table knows never reaches the model")
    stub = StubParser(result=StubParser._Parsed(delta={"scheme": "green"}))
    resolver, notices, _ = make_resolver(stub)

    quick = resolver.resolve("ask make it green")
    check("the table answers it", isinstance(quick, Ask),
          type(quick).__name__)
    check("with the same delta the model would have produced",
          quick.delta == {"scheme": "green"}, str(quick.delta))
    check("...and the model was not called at all", stub.calls == [])
    check("the reply says it was instant", quick.note, "instant")
    check("...and nothing was said on the panel, there being no wait",
          notices.said == [], str(notices.said))

    print("\n6. A stepped phrase is resolved against the settings it was said about")
    warm, _, _ = make_resolver(StubParser(),
                               config=RenderConfig().with_changes(
                                   {"contrast": 2.0}))
    stepped = warm.resolve("ask a bit more contrast")
    check("the step is taken from the live value, not the default",
          stepped.delta == {"contrast": 2.6}, str(stepped.delta))


def test_the_table_needs_neither_key_nor_network():
    print("\n7. With the model unreachable, the table still answers")
    stub = StubParser(raises=StubParser.ParseError("connection refused"))
    resolver, notices, _ = make_resolver(stub)

    survives = resolver.resolve("ask make it green")
    check("a phrase the table knows works with the model unreachable",
          isinstance(survives, Ask), type(survives).__name__)
    check("...and gives the right delta anyway",
          survives.delta == {"scheme": "green"}, str(survives.delta))

    resolved = resolver.resolve("ask something calmer")
    check("the failure is caught", isinstance(resolved, Reply),
          type(resolved).__name__)
    check("and says what went wrong",
          "connection refused" in resolved.text, resolved.text)
    check("the panel is told which kind of failure it was",
          notices.last(), "no network - words need one, settings do not")

    print("\n8. With no key at all, the table still answers")
    resolver, notices, _ = make_resolver(StubParser(key=None))

    keyless = resolver.resolve("ask freeze it")
    check("a table phrase works with no key",
          isinstance(keyless, Ask), type(keyless).__name__)
    check("...and does the right thing", keyless.delta == {"freeze": True},
          str(keyless.delta))

    resolved = resolver.resolve("ask something calmer")
    check("the model path is refused politely", isinstance(resolved, Reply))
    check("...naming the key file", "api_key" in resolved.text, resolved.text)
    check("...and saying the rest still works",
          "other command" in resolved.text, resolved.text)
    check("...and the panel says so too",
          notices.last(), "no API key, so words are off")


def test_a_decline_is_an_answer():
    print("\n9. A refusal from the model comes back as words, not an error")
    stub = StubParser(result=StubParser._Parsed(
        declined="I only change display settings."))
    resolver, notices, _ = make_resolver(stub)

    resolved = resolver.resolve("ask make me a sandwich")
    check("a decline comes straight back", isinstance(resolved, Reply),
          type(resolved).__name__)
    check("with the model's own words",
          "display settings" in resolved.text, resolved.text)
    check("and the panel is told as well as the socket",
          notices.last().startswith("cannot do that:"), notices.last())


def test_failures_are_sorted_into_kinds():
    print("\n10. Each kind of failure gets its own short sentence")
    for message, expected in (
            ("Request timed out", "the model took too long - try again"),
            ("connection refused",
             "no network - words need one, settings do not"),
            ("401 authentication_error", "the API key was refused"),
            ("rate limit exceeded", "asking too fast - wait a moment"),
            ("something else entirely", "could not ask the model")):
        check(f"{message!r} -> {expected!r}",
              AskResolver.short_failure(RuntimeError(message)) == expected,
              AskResolver.short_failure(RuntimeError(message)))


def test_asks_are_written_down():
    print("\n11. The log records which of the two answered")
    written = []

    class FakeLog:
        def record(self, utterance, config, **kw):
            written.append((utterance, kw))

    stub = StubParser(result=StubParser._Parsed(delta={"scheme": "green"}))
    resolver, _, _ = make_resolver(stub)
    resolver.log = FakeLog()

    resolver.resolve("ask make it green")
    resolver.resolve("ask something calmer")
    check("both were written down", len(written) == 2, str(len(written)))
    check("the table hit says so", written[0][1]["source"], "table")
    check("...and cost no time", written[0][1]["seconds"] == 0.0)
    check("the model answer says so too", written[1][1]["source"], "model")

    print("\n12. With no log, an ask still works")
    resolver, _, _ = make_resolver(StubParser())
    check("no log is not an error",
          isinstance(resolver.resolve("ask freeze it"), Ask))


def main():
    print("=" * 68)
    print("AskResolver: words in, a delta out, off the render loop")
    print("=" * 68)

    test_only_asks_are_touched()
    test_the_model_path()
    test_the_table_path()
    test_the_table_needs_neither_key_nor_network()
    test_a_decline_is_an_answer()
    test_failures_are_sorted_into_kinds()
    test_asks_are_written_down()

    print("\n" + "=" * 68)
    if failures:
        print(f"{len(failures)} FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
