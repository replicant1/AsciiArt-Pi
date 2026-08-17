#!/usr/bin/env python3
"""
Put an utterance to the parser and show exactly what came back.

    python3 tools/ask_parser.py "warmer, and blockier characters"
    python3 tools/ask_parser.py --schema
    python3 tools/ask_parser.py --batch tools/utterances.txt

Nothing here touches the camera. It parses, validates against RenderConfig,
and prints the delta, the refusal, the tokens and the wall time - which is the
information Stage 3's scoreboard will be built out of, and the information
needed right now to tell a good prompt from a bad one.

The exit code is the answer, so this composes: 0 when the utterance produced a
delta RenderConfig accepted, 1 otherwise. A declined utterance is a *correct*
outcome for "asdfgh" and a wrong one for "make it green", so the caller
decides - this only reports.
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import parser as nl_parser                          # noqa: E402
from render_config import RenderConfig              # noqa: E402


def show(utterance, config, previous, verbose):
    """Parse one utterance and print the outcome. Returns True on a delta."""
    print(f"\n\033[1m{utterance}\033[0m")
    try:
        parsed, after, problems = nl_parser.apply_to(
            utterance, config, previous=previous)
    except nl_parser.ParseError as e:
        print(f"  error    {e}")
        return False, config

    cost = (f"{parsed.usage.get('input', 0)} in / "
            f"{parsed.usage.get('output', 0)} out")
    cached = parsed.usage.get("cache_read", 0)
    if cached:
        cost += f", {cached} cached"
    print(f"  {parsed.seconds:.1f}s, {cost}")

    if parsed.declined is not None:
        print(f"  declined {parsed.declined}")
        return False, config

    print(f"  delta    {json.dumps(parsed.delta)}")
    if parsed.unmet:
        print(f"  unmet    {parsed.unmet}")
    if problems:
        # The boundary doing its job: a well-formed tool call whose values the
        # config refuses. Worth showing loudly - it is the failure mode the
        # whole two-layer design exists to make visible rather than silent.
        for problem in problems:
            print(f"  REFUSED  {problem}")
        return False, config

    print(f"  applied  {after.describe_changes(config) or 'nothing changed'}")
    if verbose:
        print(f"  after    {json.dumps(after.as_delta())}")
    return True, after


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("utterance", nargs="*", help="what to say to the camera")
    ap.add_argument("--batch", metavar="FILE",
                    help="a file of utterances, one per line, run in sequence "
                         "against a config that carries forward - so relative "
                         "requests and 'undo that' have something to refer to")
    ap.add_argument("--schema", action="store_true",
                    help="print the generated tool schema and exit")
    ap.add_argument("--verbose", action="store_true",
                    help="print the whole config after each change")
    args = ap.parse_args(argv)

    if args.schema:
        print(nl_parser.schema_json())
        return 0

    lines = []
    if args.batch:
        lines = [line.strip() for line in Path(args.batch).read_text().splitlines()
                 if line.strip() and not line.startswith("#")]
    if args.utterance:
        lines.append(" ".join(args.utterance))
    if not lines:
        ap.error("give an utterance, --batch FILE, or --schema")

    if nl_parser.api_key() is None:
        print(f"No API key. Set ANTHROPIC_API_KEY, or write one to\n"
              f"  {nl_parser.KEY_FILE}", file=sys.stderr)
        return 2

    print(f"model {nl_parser.MODEL}, effort {nl_parser.EFFORT}")
    config, previous = RenderConfig(), None
    started = time.monotonic()
    good = 0
    for line in lines:
        ok, after = show(line, config, previous, args.verbose)
        good += ok
        if after != config:
            config, previous = after, config

    if len(lines) > 1:
        print(f"\n{good}/{len(lines)} produced a delta the config accepted, "
              f"in {time.monotonic() - started:.0f}s")
    return 0 if good == len(lines) else 1


if __name__ == "__main__":
    sys.exit(main())
