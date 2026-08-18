#!/usr/bin/env python3
"""
Score the natural-language parser against tests/eval_cases.json.

    python3 tests/parser_eval.py                 # the whole set
    python3 tests/parser_eval.py --only decline  # cases whose id contains this
    python3 tests/parser_eval.py --jobs 1        # serially, for clean logs
    python3 tests/parser_eval.py --save runs/    # keep the raw results

Costs money and needs the network, so it is deliberately not in the suite the
other tests run in. It is a test you choose to run.

Why it exists, rather than reading the output and nodding: a prompt cannot be
tuned without a scoreboard, and a stochastic component is exactly where the
temptation to substitute an impression for a measurement is strongest. This
project already argues this way about hardware - twenty encoder clicks gave 453
edges and 88 after debouncing, and nobody had to guess. This is that instinct
pointed at a model.

Three things it is careful about:

  * Field by field, not pass/fail per utterance. "green, high contrast and the
    fine ramp" getting two of three right is worth knowing about; a single
    boolean would throw that away.
  * Correctly refused is its own bucket. "asdfgh" should be declined, and a
    scorer that counted every decline as a failure would be measuring the
    wrong thing - and would reward a parser that always guesses.
  * Some cases have a band of right answers. "a bit more contrast" is correct
    anywhere above where it started and short of doubling it; scoring it
    against one number would be scoring a coin flip. The case file says so
    per case rather than the scorer guessing.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from language import parser as nl_parser                              # noqa: E402
from control.render_config import ConfigError, RenderConfig     # noqa: E402

CASES = Path(__file__).resolve().parent / "eval_cases.json"

# Input, cached-read and output dollars per million tokens, at list prices so
# the figure is an upper bound and does not quietly go stale against a discount
# nobody recorded here. Cached reads are a tenth of input. An unknown model is
# costed at the most expensive row rather than guessed at, and says so: a
# comparison that silently under-reports the price of the thing you are
# thinking of switching to would be worse than no figure.
PRICES = {
    "claude-opus-5": (5.0, 0.5, 25.0),
    "claude-opus-4-8": (5.0, 0.5, 25.0),
    "claude-sonnet-5": (3.0, 0.3, 15.0),
    "claude-sonnet-4-6": (3.0, 0.3, 15.0),
    "claude-haiku-4-5": (1.0, 0.1, 5.0),
}
DEAREST = max(PRICES.values())


def price_of(model):
    """(input, cache-read, output) per million tokens, and whether it is known."""
    if model in PRICES:
        return PRICES[model], True
    return DEAREST, False


# What counts as a pass overall. Deliberately not 100%: the component is
# stochastic, and a threshold it can only meet on a good day is a threshold
# that gets ignored. Raise it when the prompt earns it.
TARGET = 0.90

GREEN, RED, YELLOW, DIM, BOLD, OFF = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m")


def matches(expected, actual):
    """
    Is one field's value acceptable?

    Three shapes, because three kinds of question:
        "green"              exactly this
        ["amber", "lime"]    any of these - warm is not one colour
        {"min": .., "max":}  anywhere in this band - relative asks have no
                             single right answer
    """
    if isinstance(expected, dict):
        low, high = expected.get("min"), expected.get("max")
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            return False
        return (low is None or actual >= low) and (high is None or actual <= high)
    if isinstance(expected, list):
        return any(matches(one, actual) for one in expected)
    return expected == actual


def config_for(case):
    """The settings the utterance is resolved against, and the ones before."""
    now = RenderConfig().with_changes(case.get("now", {}))
    before = None
    if "before" in case:
        before = RenderConfig().with_changes(case["before"])
    return now, before


def score_delta(case, delta, expected):
    """
    Compare one delta to what was wanted, field by field.

    Returns (hits, misses, spurious, notes). A field is a hit when it is
    present and acceptable, a miss when it is absent or wrong, and spurious
    when it was not asked for and not allowed - a model that changes the ramp
    when you asked about the panel font has done something wrong even though
    it also did the right thing.
    """
    allowed = set(case.get("allow", []))
    forbidden = set(case.get("forbid", []))
    hits, misses, spurious, notes = 0, 0, 0, []

    for field, want in expected.items():
        if field not in delta:
            misses += 1
            notes.append(f"missing {field} (wanted {want!r})")
        elif matches(want, delta[field]):
            hits += 1
        else:
            misses += 1
            notes.append(f"{field}={delta[field]!r}, wanted {want!r}")

    for field, got in delta.items():
        if field in expected:
            continue
        if field in forbidden:
            spurious += 1
            notes.append(f"{field} must not be set (got {got!r})")
        elif field not in allowed:
            spurious += 1
            notes.append(f"unasked-for {field}={got!r}")

    return hits, misses, spurious, notes


def run_case(case):
    """Parse one utterance and judge it. Never raises; failures are results."""
    result = {"id": case["id"], "utterance": case["utterance"],
              "hits": 0, "misses": 0, "spurious": 0, "notes": [],
              "outcome": None, "ok": False, "seconds": 0.0, "usage": {}}
    now, before = config_for(case)
    expected = case.get("expect")
    wants_decline = expected == "decline"

    try:
        parsed = nl_parser.parse(case["utterance"], now, previous=before)
    except nl_parser.ParseError as e:
        result["outcome"] = "error"
        result["notes"] = [str(e)]
        return result

    result["seconds"] = parsed.seconds
    result["usage"] = parsed.usage

    if parsed.declined is not None:
        result["notes"] = [parsed.declined]
        # Declining is right when the case says so, and also when the case
        # allows it - "rotate 45 degrees" has no exact answer, so a refusal
        # and a sensible nearest are both good, and insisting on one would be
        # scoring taste rather than capability.
        if wants_decline or case.get("or_decline"):
            result["outcome"] = "refused-correctly"
            result["ok"] = True
        else:
            result["outcome"] = "refused-wrongly"
        return result

    # From here it answered. First: is the delta even legal? This is the two
    # layers meeting, and the answer nobody wants to see is "no".
    try:
        now.with_changes(parsed.delta)
    except ConfigError as e:
        result["outcome"] = "invalid"
        result["notes"] = e.problems
        return result

    if wants_decline:
        # It answered something it should have refused. Whether the delta was
        # otherwise sensible is beside the point.
        result["outcome"] = "answered-wrongly"
        result["notes"] = [f"should have declined; said {parsed.delta}"]
        if "or_delta" in case:
            hits, misses, spurious, notes = score_delta(
                case, parsed.delta, case["or_delta"])
            if misses == 0 and spurious == 0:
                result.update(outcome="answered-acceptably", ok=True,
                              hits=hits, notes=["a sensible alternative"])
        return result

    hits, misses, spurious, notes = score_delta(case, parsed.delta, expected)
    result.update(hits=hits, misses=misses, spurious=spurious, notes=notes)

    if case.get("unmet") and not parsed.unmet:
        result["misses"] += 1
        result["notes"].append("said nothing about the part it could not do")

    result["outcome"] = "answered"
    result["ok"] = result["misses"] == 0 and result["spurious"] == 0
    return result


def show(result):
    mark = f"{GREEN}PASS{OFF}" if result["ok"] else f"{RED}FAIL{OFF}"
    if result["outcome"] in ("error", "invalid"):
        mark = f"{YELLOW}{result['outcome'].upper()}{OFF}"
    print(f"  [{mark}] {result['id']:<28} {DIM}{result['utterance']}{OFF}")
    for note in result["notes"] if not result["ok"] else []:
        print(f"           {note}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="run cases whose id contains this")
    ap.add_argument("--jobs", type=int, default=4,
                    help="cases in parallel; each is independent, so this is "
                         "safe. 1 for readable logs")
    ap.add_argument("--save", metavar="DIR", help="write the raw results here")
    ap.add_argument("--target", type=float, default=TARGET,
                    help="pass rate needed to exit 0")
    ap.add_argument("--model", default=None,
                    help="model to score instead of the app's own. The point "
                         "of the exercise: a cheaper one is a one-string "
                         "change, and this says what it costs in accuracy")
    ap.add_argument("--effort", default=None,
                    help="reasoning effort to score instead of the app's "
                         "own; 'none' omits the parameter, which models older "
                         "than it require")
    args = ap.parse_args(argv)

    # Set before anything runs, so every case and the saved record agree on
    # what was actually scored.
    if args.model:
        nl_parser.MODEL = args.model
    if args.effort:
        # "none" so a model that has no effort parameter can be scored at all;
        # an empty string on a command line is easy to pass by accident.
        nl_parser.EFFORT = None if args.effort == "none" else args.effort

    if nl_parser.api_key() is None:
        print(f"No API key. Set ANTHROPIC_API_KEY or write one to\n"
              f"  {nl_parser.KEY_FILE}", file=sys.stderr)
        return 2

    cases = json.loads(CASES.read_text())["cases"]
    if args.only:
        cases = [c for c in cases if args.only in c["id"]]
    if not cases:
        print("no cases matched", file=sys.stderr)
        return 2

    print("=" * 72)
    print(f"Parser eval: {len(cases)} cases against {nl_parser.MODEL}, "
          f"effort {nl_parser.EFFORT}")
    print("=" * 72)

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        results = list(pool.map(run_case, cases))
    elapsed = time.monotonic() - started

    for result in results:
        show(result)

    passed = sum(r["ok"] for r in results)
    hits = sum(r["hits"] for r in results)
    misses = sum(r["misses"] for r in results)
    spurious = sum(r["spurious"] for r in results)
    buckets = {}
    for r in results:
        buckets[r["outcome"]] = buckets.get(r["outcome"], 0) + 1

    print("\n" + "-" * 72)
    print(f"{BOLD}Cases{OFF}   {passed}/{len(results)} "
          f"({passed / len(results):.0%})")
    print(f"{BOLD}Fields{OFF}  {hits} right, {misses} wrong or missing, "
          f"{spurious} unasked-for")
    if hits + misses:
        print(f"        recall {hits / (hits + misses):.0%}", end="")
    if hits + spurious:
        print(f", precision {hits / (hits + spurious):.0%}")
    else:
        print()

    print(f"\n{BOLD}Outcomes{OFF}")
    for name in ("answered", "refused-correctly", "answered-acceptably",
                 "refused-wrongly", "answered-wrongly", "invalid", "error"):
        if name in buckets:
            print(f"  {name:<22} {buckets[name]}")

    tokens_in = sum(r["usage"].get("input", 0) for r in results)
    tokens_out = sum(r["usage"].get("output", 0) for r in results)
    cached = sum(r["usage"].get("cache_read", 0) for r in results)
    (in_price, cache_price, out_price), known = price_of(nl_parser.MODEL)
    cost = (tokens_in * in_price + cached * cache_price
            + tokens_out * out_price) / 1_000_000
    unknown = "" if known else "  (unknown model, priced at the dearest row)"
    print(f"\n{BOLD}Cost{OFF}    {tokens_in} in, {cached} cached, "
          f"{tokens_out} out - about ${cost:.3f} ({cost * 79:.0f}p)"
          f"{unknown}")
    print(f"{BOLD}Time{OFF}    {elapsed:.0f}s at {args.jobs} in parallel")

    if args.save:
        out = Path(args.save)
        out.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = out / f"eval-{stamp}.json"
        path.write_text(json.dumps({
            "model": nl_parser.MODEL, "effort": nl_parser.EFFORT,
            "passed": passed, "of": len(results), "results": results,
            "cost_usd": round(cost, 4), "seconds": round(elapsed, 1),
        }, indent=2))
        print(f"\nsaved {path}")

    rate = passed / len(results)
    print()
    if rate >= args.target:
        print(f"{GREEN}RESULT: {rate:.0%}, at or above the {args.target:.0%} "
              f"target.{OFF}")
        return 0
    print(f"{RED}RESULT: {rate:.0%}, below the {args.target:.0%} target.{OFF}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
