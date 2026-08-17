#!/usr/bin/env python3
"""
Check the typed-command front end.

    python3 tests/commands_test.py

The interesting property is a *boundary*, not a parser. commands.py turns text
into typed values and stops; RenderConfig decides what is allowed. So "rotation
45" must parse cleanly and be refused one layer down, with the same wording
anything else gets - because when the language model arrives it will produce
deltas the same way, and an eval comparing the two is only meaningful if they
are judged by the same code.

The trap this guards against is the front end quietly becoming more permissive
than the validated path: accepting a near-miss spelling, or clamping a value
itself, or inventing a default for a word it did not understand. Any of those
would let a phrase work by hand and fail through the parser, which is exactly
the discrepancy Stage 3 is supposed to be able to measure.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import commands                                    # noqa: E402
import render_config                               # noqa: E402
from commands import CommandError                  # noqa: E402
from render_config import ConfigError, RenderConfig  # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def parses_to(line):
    kind, payload = commands.parse(line)
    return payload if kind == "delta" else (kind, payload)


def rejects(line):
    """(was it rejected, what it said)."""
    try:
        commands.parse(line)
    except CommandError as e:
        return True, str(e)
    return False, ""


def test_typing_a_setting():
    print("\n1. A setting and a value become a delta")
    check("a string choice", parses_to("scheme green") == {"scheme": "green"},
          str(parses_to("scheme green")))
    check("a float", parses_to("contrast 2.4") == {"contrast": 2.4},
          str(parses_to("contrast 2.4")))
    check("an int choice, as an int not a string",
          parses_to("rotation 90") == {"rotation": 90},
          repr(parses_to("rotation 90")))
    check("an int range", parses_to("lcd_font_size 9")
          == {"lcd_font_size": 9})

    print("\n2. Bools take the words a person would type")
    for word in ("on", "true", "yes", "y", "1"):
        check(f"invert {word} is True",
              parses_to(f"invert {word}") == {"invert": True})
    for word in ("off", "false", "no", "n", "0"):
        check(f"invert {word} is False",
              parses_to(f"invert {word}") == {"invert": False})
    # The one that would be a nasty surprise: 0 must not be truthy.
    check("invert 0 is False, not 'a non-empty string'",
          parses_to("invert 0") == {"invert": False})

    print("\n3. Several settings on one line")
    check("three at once",
          parses_to("contrast 2.4 invert on freeze off")
          == {"contrast": 2.4, "invert": True, "freeze": False},
          str(parses_to("contrast 2.4 invert on freeze off")))
    # This is the shape a model's delta takes, so it has to work by hand too.
    check("equals signs work as well as spaces",
          parses_to("scheme=green contrast=2") == {"scheme": "green",
                                                   "contrast": 2.0})
    check("case does not matter for names or choices",
          parses_to("SCHEME Green") == {"scheme": "green"},
          str(parses_to("SCHEME Green")))

    print("\n4. The words that are not settings")
    check("help", commands.parse("help") == ("help", None))
    check("help for one setting",
          commands.parse("help contrast") == ("help", "contrast"))
    check("show", commands.parse("show") == ("show", None))
    check("reset", commands.parse("reset") == ("reset", None))
    check("an empty line does nothing",
          commands.parse("   ") == ("none", None))


def test_what_it_refuses():
    print("\n5. Names and values are not guessed at")
    rejected, said = rejects("schmee green")
    check("an unknown setting is refused", rejected, said)
    check("...and the message lists the real ones", "scheme" in said, said)

    rejected, said = rejects("sch green")
    check("a prefix is NOT accepted", rejected, said)

    rejected, said = rejects("invert maybe")
    check("a bool that is neither is refused", rejected, said)
    rejected, said = rejects("contrast loads")
    check("a number that is not one is refused", rejected, said)
    # Note what is NOT here: "scheme purple" and "rotation 45". Both are the
    # right *type* for their field, so they parse, and section 7 checks that
    # RenderConfig is what turns them down. Refusing them here would put the
    # "must be one of" wording in two modules and let the front end reject
    # things the model's deltas would be judged on separately.
    rejected, said = rejects("rotation ninety")
    check("a choice needing a number, given a word, is refused", rejected,
          said)
    check("...and the message still lists the values", "90" in said, said)

    print("\n6. Malformed lines say what was wrong")
    rejected, said = rejects("scheme")
    check("a setting with no value is refused", rejected, said)
    rejected, said = rejects("scheme green contrast")
    check("a trailing setting with no value is refused", rejected, said)
    rejected, said = rejects("scheme green scheme amber")
    check("the same setting twice is refused", rejected, said)
    rejected, said = rejects("help nonsense")
    check("help for a setting that does not exist is refused", rejected, said)
    rejected, said = rejects("show me everything")
    check("a word command with arguments is refused", rejected, said)


def test_the_boundary():
    print("\n7. Type here, permission one layer down")
    # The whole design in four checks. A value of the right *type* but the
    # wrong magnitude must sail through parsing and be stopped by RenderConfig,
    # so there is one place that decides what is legal and one wording for
    # saying no - the same one the model's deltas will meet.
    for line, field in [("rotation 45", "rotation"),
                        ("scheme purple", "scheme"),
                        ("colour_levels 9", "colour_levels")]:
        try:
            parsed = parses_to(line)
            check(f"{line!r} parses fine", isinstance(parsed, dict),
                  str(parsed))
        except CommandError as e:
            check(f"{line!r} parses fine", False, f"front end refused: {e}")
            continue
        try:
            RenderConfig().with_changes(parsed)
            check(f"...and {field} is refused by RenderConfig", False)
        except ConfigError as e:
            check(f"...and {field} is refused by RenderConfig", True, str(e))

    print("\n7b. Only RenderConfig words a refusal, so there is one wording")
    # If the front end also said "must be one of", two modules would have to be
    # kept in step - and the model's deltas, which never pass through the front
    # end at all, would get a different message for the same mistake.
    #
    # Asserted against what the front end actually *says*, not against its
    # source text. The first version of this check read the module with
    # inspect.getsource and matched the comment explaining why the phrase had
    # been removed - a source-text check wearing a behaviour check's clothes,
    # and it failed on correct code.
    said = []
    for line in ("rotation ninety", "scheme purple", "invert maybe",
                 "contrast loads", "colour_levels lots", "target nowhere",
                 "lcd_font_size big", "ramp fancy", "freeze sometimes"):
        try:
            commands.parse(line)
        except CommandError as e:
            said.append(str(e))
    check("the front end refuses only on type, never on permission",
          not any("must be one of" in message for message in said),
          "; ".join(m for m in said if "must be one of" in m))

    # And the phrase does live somewhere - otherwise the check above would
    # pass on a build where nothing validated anything at all.
    try:
        RenderConfig().with_changes({"rotation": 45})
        check("RenderConfig is the one that says it", False)
    except ConfigError as e:
        check("RenderConfig is the one that says it",
              "must be one of" in str(e), str(e))

    check("contrast 9 parses fine", parses_to("contrast 9")
          == {"contrast": 9.0})
    check("...and is clamped by RenderConfig, not here",
          RenderConfig().with_changes(parses_to("contrast 9")).contrast == 4.0)

    print("\n8. The front end never clamps or corrects on its own")
    # If it did, a value would be silently altered before the layer that is
    # supposed to decide about it ever saw it.
    check("contrast 9 is not pre-clamped", parses_to("contrast 9")["contrast"]
          == 9.0, str(parses_to("contrast 9")))
    check("lcd_font_size 40 is not pre-clamped",
          parses_to("lcd_font_size 40")["lcd_font_size"] == 40)


def test_help_comes_from_specs():
    print("\n9. help is generated, so it cannot fall behind the settings")
    text = commands.help_text()
    for spec in render_config.SPECS:
        check(f"help mentions {spec.name}", spec.name in text)

    # Not just the names: the values too, or "what can I type" is unanswered.
    check("help lists the scheme names",
          all(name in text for name in ("grey", "green", "paper")))
    check("help lists the rotations",
          all(str(r) in text for r in (0, 90, 180, 270)))
    check("help gives the contrast range",
          "0.1" in text and "4.0" in text)
    check("help says a range is clamped", "clamped" in text)
    check("help mentions the other commands",
          all(word in text for word in ("show", "reset", "help")))

    print("\n10. help shows current values when it is given a config")
    plain = commands.help_text()
    live = commands.help_text(config=RenderConfig(scheme="amber"))
    check("without a config there are no current values",
          "[now" not in plain)
    check("with one, the value is shown", "'amber'" in live)

    print("\n11. help for a single setting is just that one")
    one = commands.help_text("contrast")
    check("it describes contrast", "contrast" in one)
    check("and not everything else", "lcd_font_size" not in one, one)


def test_show_and_reset():
    print("\n12. show lists every setting")
    text = commands.show_text(RenderConfig())
    for spec in render_config.SPECS:
        check(f"show includes {spec.name}", spec.name in text)

    print("\n13. reset is expressed as a delta, not a fresh config")
    # So that it goes down the same validated path as everything else, and the
    # app sees a normal change with a normal before and after.
    changed = RenderConfig(scheme="amber", contrast=3.0, invert=True)
    delta = commands.defaults_delta(changed)
    check("it names only what differs",
          set(delta) == {"scheme", "contrast", "invert"}, str(delta))
    check("and applying it returns the defaults",
          changed.with_changes(delta) == RenderConfig())
    check("resetting an untouched config is empty",
          commands.defaults_delta(RenderConfig()) == {})



def test_an_idle_client_does_not_starve_the_rest():
    """
    The bug a user hit: an interactive prompt sitting open blocked everyone.

    The server used to serve one connection at a time, on the reasoning that
    two people typing settings at one camera was not worth supporting. What
    that missed is that a single person's prompt holds its connection for as
    long as it is on screen - so every later client, including one-shot
    commands, sat unaccepted until it timed out. The only symptom was
    "lost the app: timed out", which looks exactly like a crashed camera.

    Uses a real socket and real threads; nothing here stands in for anything.
    """
    print("\n14. An open connection does not block other clients")
    import socket
    import tempfile
    import threading
    import time
    from pathlib import Path as _Path

    sys.path.insert(0, str(ROOT / "src"))
    from command_server import CommandServer

    sock_path = str(_Path(tempfile.mkdtemp()) / "test.sock")
    server = CommandServer(sock_path).start()

    # Stand in for the render loop: answer whatever is queued.
    draining = threading.Event()

    def drain():
        while not draining.is_set():
            for line, answer in server.take():
                answer.put(f"ok: {line}")
            time.sleep(0.02)

    loop = threading.Thread(target=drain, daemon=True)
    loop.start()

    def talk(sock, line):
        sock.sendall((line + "\n").encode())
        buf = b""
        while b"\x00" not in buf:
            buf += sock.recv(4096)
        return buf.split(b"\x00", 1)[0].decode().strip()

    try:
        # An interactive client connects and then just sits there, exactly as
        # a prompt waiting for typing does.
        idle = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        idle.settimeout(5)
        idle.connect(sock_path)
        check("the first client is served", talk(idle, "hello") == "ok: hello")

        # It stays connected and says nothing more. A second client must still
        # be served promptly.
        second = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        second.settimeout(5)
        started = time.monotonic()
        second.connect(sock_path)
        reply = talk(second, "second")
        took = time.monotonic() - started

        check("a second client is served while the first sits open",
              reply == "ok: second", reply)
        check("...and promptly, not after a timeout", took < 2.0,
              f"{took:.2f}s")

        # And the idle one still works afterwards.
        check("the first client still works", talk(idle, "again")
              == "ok: again")

        second.close()
        idle.close()
    finally:
        draining.set()
        server.stop()


def main():
    print("=" * 66)
    print("Typed commands: text in, validated delta out")
    print("=" * 66)

    test_typing_a_setting()
    test_what_it_refuses()
    test_the_boundary()
    test_help_comes_from_specs()
    test_show_and_reset()
    test_an_idle_client_does_not_starve_the_rest()

    print("\n" + "=" * 66)
    if failures:
        print(f"RESULT: {len(failures)} CHECK(S) FAILED")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("RESULT: the command front end behaves as documented.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
