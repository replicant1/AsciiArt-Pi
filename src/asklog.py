"""
A record of every natural-language request, so real use becomes evidence.

Not every record is evidence about the *model*: `source` says whether a parse
answered or src/shortcuts.py did. Filter on it before counting anything about
the prompt.

The eval in tests/parser_eval.py scores the prompt against 41 utterances, all
of which were invented by the same person who wrote the prompt. That is the
measurement's real limit and no amount of re-running fixes it: a case file can
only test the failure modes its author thought of, and 41 cases put the true
pass rate somewhere north of 93% rather than at the 100% the scoreboard prints.

The way out is to stop inventing utterances. This module writes one JSON object
per ask to a file, so the things actually said to this camera - by someone
standing in front of it, phrasing it however they phrase it - accumulate
somewhere they can be read, counted, and promoted into cases.

Two decisions make that promotion cheap rather than a translation job:

  * `now` and `before` are stored as sparse deltas from the defaults, which is
    exactly the shape eval_cases.json uses for those keys. A logged record is
    most of a case already.
  * `outcome` uses the eval's own vocabulary - answered, declined, error - so
    the log and the scoreboard describe the same events in the same words.

It records what the *parser* did, not what the app finally did with it. The two
run on different threads by design (a parse crosses a network; the render loop
cannot wait), and the delta is validated again on the loop's thread before
anything moves. So a record saying `answered` means the model produced that
delta, not that the camera adopted it - `apply` may still have refused it, and
the app log is where that shows up.

Nothing here is allowed to break an ask. Every failure is swallowed and logged:
a camera that stops taking requests because it could not write a log file would
be a worse camera than one that quietly loses a line of history.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path

from render_config import SPECS, RenderConfig

logger = logging.getLogger(__name__)

# Beside runs/, which holds the eval's own output, and gitignored for the same
# reason: this is a record of what happened on one camera, not a fact about the
# code. It is deliberately inside the project directory rather than off in
# ~/.local/state - the whole point is that somebody goes and reads it.
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "logs" / "asks.jsonl"

# About 5,000 asks at roughly 400 bytes each. One old file is kept. This is not
# really about disk - it is that an append-only file nobody ever rotates is a
# thing that eventually surprises someone on a small card.
MAX_BYTES = 2_000_000


def _sparse(config):
    """A config as a delta from the defaults - eval_cases.json's `now` shape."""
    if config is None:
        return None
    return {name: getattr(config, name)
            for name in config.changes_from(RenderConfig())}


class AskLog:
    """
    Append-only record of asks, one JSON object per line.

    Safe to call from several threads: each client connection gets its own
    thread, so two people at two terminals can ask at once.
    """

    def __init__(self, path=None, max_bytes=MAX_BYTES):
        self.path = Path(path) if path else DEFAULT_PATH
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self.written = 0
        self.failed = 0

    def record(self, utterance, config, previous=None, delta=None,
               declined=None, unmet=None, error=None, seconds=None, usage=None,
               source="model"):
        """
        Write one ask. Returns the record written, or None if it could not be.

        Never raises. The caller is in the middle of answering somebody.

        `source` is who answered: "model" for a parse, "table" for a phrase
        src/shortcuts.py knew already. It is always written, including on the
        default, because a record that omits it is ambiguous rather than
        obviously a model answer - and this file is read months later.

        It also decides what a record is evidence *of*. A "table" record says
        nothing about the prompt: the model was never asked. Anything counting
        hit rate, or promoting real utterances into eval cases, has to filter
        on this or it will score the model on answers it never gave.
        """
        if error is not None:
            outcome = "error"
        elif declined is not None:
            outcome = "declined"
        else:
            outcome = "answered"

        record = {
            "when": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "utterance": utterance,
            "outcome": outcome,
            "source": source,
            "now": _sparse(config),
        }
        # Only the keys that mean something for this outcome, so the file stays
        # readable by eye and a case can be lifted out of it without pruning.
        for key, value in (("before", _sparse(previous)), ("delta", delta),
                           ("unmet", unmet), ("declined", declined),
                           ("error", error), ("seconds", seconds),
                           ("usage", usage)):
            if value:
                record[key] = value
        if seconds is not None:
            record["seconds"] = round(seconds, 2)

        try:
            with self._lock:
                self._rotate_if_needed()
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record) + "\n")
                self.written += 1
            return record
        except Exception as e:
            # A full disk, a read-only mount, a path that is a directory. Worth
            # a line in the app log and nothing more.
            self.failed += 1
            logger.error("Could not write the ask log at %s: %s", self.path, e)
            return None

    def _rotate_if_needed(self):
        """Keep one old file. Caller holds the lock."""
        try:
            if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
                os.replace(self.path, self.path.with_suffix(".jsonl.1"))
        except OSError as e:
            logger.warning("Could not rotate %s: %s", self.path, e)


def load(path=None):
    """
    Every record in the log, oldest first. Bad lines are skipped, not fatal.

    A truncated last line is the normal way this file ends if the power went
    out mid-write, and one unreadable line is not a reason to refuse the other
    four thousand.
    """
    path = Path(path) if path else DEFAULT_PATH
    if not path.exists():
        return []
    records, bad = [], 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            bad += 1
    if bad:
        logger.warning("Skipped %d unreadable line(s) in %s", bad, path)
    return records


def as_case(record, case_id=None):
    """
    Turn one logged ask into a candidate eval case.

    Candidate, not case: `expect` is filled in with what the model actually
    said, which is the thing under test. A human has to look at it and decide
    whether that was the right answer before it is worth anything. Promoting
    these unread would be writing the answer key from the model's own output -
    the exact circularity tests/eval_cases.json exists to avoid.
    """
    case = {"id": case_id or "from-log",
            "utterance": record.get("utterance", "")}
    if record.get("now"):
        case["now"] = record["now"]
    if record.get("before"):
        case["before"] = record["before"]
    if record.get("outcome") == "declined":
        case["expect"] = "decline"
    else:
        case["expect"] = record.get("delta", {})
    if record.get("unmet"):
        case["unmet"] = True
    case["note"] = "CANDIDATE from the ask log - check the expectation by hand."
    return case


def _check_sparse_covers_specs():
    """
    A field added to RenderConfig must reach the log without anyone remembering.

    `_sparse` walks changes_from, which walks SPECS, so this holds by
    construction - but it holds by construction only until somebody rewrites
    _sparse, and a log silently missing a field would be discovered much later
    by whoever wondered why their eval cases were wrong.
    """
    everything = RenderConfig().with_changes(
        {spec.name: _other_value(spec) for spec in SPECS})
    missing = {spec.name for spec in SPECS} - set(_sparse(everything))
    if missing:
        raise RuntimeError(f"asklog._sparse would not record: {sorted(missing)}")


def _other_value(spec):
    """Any legal value for this spec that is not the default."""
    default = getattr(RenderConfig(), spec.name)
    if spec.kind == "bool":
        return not default
    if spec.kind == "choice":
        return next(c for c in spec.choices if c != default)
    return spec.high if default != spec.high else spec.low


_check_sparse_covers_specs()
