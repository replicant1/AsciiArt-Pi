"""
Natural language in, a validated RenderConfig delta out.

    "warmer, and blockier characters"
        -> {"scheme": "amber", "ramp": "coarse"}

The model is a *parser*, not an executor. It turns a fuzzy utterance into a
typed delta and stops there; whether that delta is allowed is RenderConfig's
decision, exactly as it is for a line typed at the CLI. Nothing the model emits
reaches the hardware without going through `with_changes` first, and from the
app's point of view a parsed delta and a typed one are indistinguishable.

That boundary is the whole design. It is also what makes the two comparable:
src/control/commands.py is the deterministic path, this is the fuzzy one, and both are
judged by the same validator with the same wording. An eval that scored them
against different validators would be measuring the validators.

The tool schema is generated from render_config.SPECS rather than written out
again. A setting added to RenderConfig becomes describable to the model the
moment it exists - the same reason `help` is generated, and the reason SPECS
carries a note per field instead of only a type.

Two tools rather than one, because refusing is an answer:

    set_render   a delta, holding only the fields that should change
    decline      the utterance does not describe a settings change

"asdfgh" and "make me a sandwich" are not failures to be papered over with a
best guess - a parser that always answers cannot be scored on the cases where
the right answer is no. Forcing a tool call means the reply is always one of
those two and never a paragraph of prose.
"""

import contextlib
import json
import logging
import os
import threading
from pathlib import Path

from control import render_config
from control.render_config import SPECS, ConfigError, RenderConfig

logger = logging.getLogger(__name__)

# Claude Sonnet 5, chosen on measurement rather than instinct. Opus was the
# starting point on the principle that you measure against the best before
# trading capability away; tests/language/parser_eval.py is what did the trading.
#
# Three runs each of the 41 cases, after the prompt gained the defaults and the
# schema disallowed empty deltas:
#
#     opus 5      100% 100% 98%    0.33p an ask    2.9s
#     sonnet 5     95%  95% 95%    0.20p an ask    2.3s
#     haiku 4.5    95%  90% 93%    0.18p an ask    1.8s
#
# Sonnet at 40% less per ask and half a second quicker, for about four points.
# Haiku saves almost nothing beyond that and drops another two, and it never
# fills in `unmet` - "make it green and email this to my sister" silently loses
# half the request, which is worse at the camera than the score suggests.
#
# Where the four points go, so a future reader can judge whether the trade
# still holds: vocab-panel-glyphs fails every run - "bigger characters on the
# little screen" also switches target to lcd - and look-calmer, the vaguest
# case in the set, does not change the scheme. Both look like prompt problems
# rather than ceilings. Fixing either is a 13p experiment.
#
# Switching back is this one string. Run the eval before believing any change
# to it, and more than once: the noise floor is about +/-2-3%.
MODEL = "claude-sonnet-5"

# Small, scoped work - one short utterance, one tool call - so the cheapest
# effort level is the right starting point. Thinking is deliberately left at
# its default (on) rather than disabled: with thinking off, this model can
# occasionally write a tool call into its visible text instead of emitting a
# tool_use block, which completes the turn, runs nothing, and reports no error.
# A parser cannot afford a failure mode that looks like success. Effort is the
# lever for cost here, not the thinking switch.
#
# Not every model takes it. Haiku 4.5 rejects the request outright with "This
# model does not support the effort parameter", a 400 that arrives before any
# token is billed and reads like a broken key rather than a model that predates
# the feature. Set this to None for those, and the parameter is left out
# entirely rather than sent and refused.
EFFORT = "low"

# Enough headroom for a short think plus one tool call. max_tokens caps
# thinking and output together, so sizing this to the tool call alone would
# truncate mid-parse.
MAX_TOKENS = 4096

# The camera is on a domestic WiFi link and the app is a render loop: a parse
# that has not come back in this long is more useful as an error than as a
# pause. The SDK's own default is ten minutes, which would freeze the picture.
TIMEOUT_SECONDS = 20.0
MAX_RETRIES = 1

# Where the key lives when it is not in the environment. Outside the project
# directory on purpose: sync.sh copies an explicit file list, and a key inside
# the tree is one careless addition away from a public commit.
KEY_FILE = Path.home() / ".config" / "asciicam" / "api_key"

def _defaults_sentence():
    """
    The defaults, read from RenderConfig rather than written out again.

    Stating them in prose would be a second copy, and the copy is the one that
    goes stale: change a default in the dataclass and the model would go on
    confidently restoring the old one, in the one situation - "put everything
    back" - where being wrong is least visible.

    Worth having at all because a weaker model noticed it was missing. Asked to
    put everything back to normal, Haiku 4.5 declined with "you haven't told me
    what the normal defaults are", which was correct; Opus and Sonnet inferred
    them and hid the gap.
    """
    default = RenderConfig()
    parts = []
    for spec in SPECS:
        value = getattr(default, spec.name)
        if isinstance(value, bool):
            value = "true" if value else "false"
        parts.append(f"{spec.name} {value}")
    return ", ".join(parts)


SYSTEM_PROMPT = """\
You turn spoken or typed requests into settings changes for an ASCII art \
camera - a Raspberry Pi that renders its camera feed as characters, on two \
displays at once: a terminal window on an HDMI monitor, and a 2.4 inch LCD \
panel of 320x240 pixels.

Call set_render with only the settings that should change. Leave everything \
else out; omitted settings keep their current values. Call decline when the \
request does not describe a change to these settings.

What the vocabulary means on this device:

- Warmer means the amber or lime schemes; cooler means cyan, navy or azure. \
Green is the classic phosphor terminal look, paper is e-ink on white.
- Blockier, chunkier or simpler characters means the coarse ramp; finer, more \
detailed or more shades means the fine ramp.
- Bigger or chunkier *on the panel* means a larger lcd_font_size, which gives \
fewer, larger characters. This is separate from the character ramp.
- The little screen, the panel and the LCD all mean target lcd. The big \
screen, the monitor and the terminal mean target terminal.
- Posterised, banded, or fewer colours means lowering colour_levels. This only \
affects the live-colour scheme.
- Punchier or more contrast means raising contrast; flatter means lowering it.
- Freeze, hold and pause mean freeze on. The picture stops but settings keep \
working, so a frozen picture can still be adjusted.

Requests are often relative - warmer, a bit less, back to normal. You are told \
the current settings and the ones before the last change, so resolve them \
against those and emit absolute values. Undo means returning the settings that \
last changed to what they were before.

Normal, standard and default mean these values: __DEFAULTS__. A request to put \
things back to normal is asking for those, and counts as naming them.

A request can ask for several things at once, and can ask for something you \
can only partly do. Do the part that maps to a setting rather than declining \
the whole thing, and say what you could not do in the `unmet` field.

Change only what the request mentions. Do not change a second setting in order \
to make the first one take effect: the person may have chosen the current \
settings deliberately, and a change they did not ask for is worse than one \
that is not yet visible. Say so in `unmet` instead.\
""".replace("__DEFAULTS__", _defaults_sentence())


def _json_type(value):
    """The JSON Schema type name for one of a spec's choice values."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    return "string"


def _property(spec):
    """One field of the tool's input schema, derived from its Spec."""
    note = spec.note
    if spec.kind == "bool":
        return {"type": "boolean", "description": note}
    if spec.kind == "choice":
        return {
            "type": _json_type(spec.choices[0]),
            "enum": list(spec.choices),
            "description": note,
        }
    # A range. The bounds go in the description as well as the schema: the
    # model reads the description reliably, and a value outside the range is
    # clamped rather than refused anyway, so this is guidance and not a gate.
    kind = "integer" if spec.kind == "int" else "number"
    return {
        "type": kind,
        "minimum": spec.low,
        "maximum": spec.high,
        "description": f"{note} From {spec.low} to {spec.high}.",
    }


def tools():
    """
    The tool definitions, generated from SPECS.

    Not `strict`, deliberately. Strict tool use would require every field to be
    present on every call - a delta is sparse by nature, and "unchanged" would
    have to be spelled as an explicit null twelve times. More to the point,
    RenderConfig is already the validator, and an eval that could never observe
    a malformed delta could not measure how often the model produces one.
    Letting a bad value through to the validator is the measurement.
    """
    properties = {spec.name: _property(spec) for spec in SPECS}
    return [
        {
            "name": "set_render",
            "description": (
                "Change one or more of the camera's render settings. Include "
                "only the settings that should change."
            ),
            "input_schema": {
                "type": "object",
                # An empty call is not an answer: it reports success while
                # changing nothing and saying nothing, which is a worse reply
                # than an honest refusal. Tools here are not strict, so this is
                # guidance rather than a gate - parse() still has to cope when
                # it arrives anyway.
                "minProperties": 1,
                "properties": {
                    **properties,
                    "unmet": {
                        "type": "string",
                        "description": (
                            "Anything the request asked for that these "
                            "settings cannot express. Omit when the request "
                            "was fully satisfied."
                        ),
                    },
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "decline",
            "description": (
                "The request does not describe a change to the camera's "
                "settings - it is unintelligible, or asks for something this "
                "device does not do."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": (
                            "One short sentence a person would find useful, "
                            "addressed to them."
                        ),
                    },
                },
                "required": ["reason"],
                "additionalProperties": False,
            },
        },
    ]


class ParseError(RuntimeError):
    """The parse could not be completed - network, key, or a refusal."""


class Parsed:
    """
    What one utterance came back as.

    Exactly one of `delta` and `declined` is set. `unmet` carries the part of
    the request the settings cannot express, which is not the same as a
    refusal: "warmer and play some music" changes the scheme and says so.
    """

    def __init__(self, delta=None, declined=None, unmet=None, usage=None,
                 seconds=None):
        self.delta = delta
        self.declined = declined
        self.unmet = unmet
        self.usage = usage or {}
        self.seconds = seconds

    @property
    def ok(self):
        return self.delta is not None

    def __repr__(self):
        if self.declined is not None:
            return f"Parsed(declined={self.declined!r})"
        return f"Parsed(delta={self.delta!r}, unmet={self.unmet!r})"


def api_key():
    """
    The key, from the environment or from a file outside the project.

    Returns None rather than raising, so a caller can decide whether a missing
    key is fatal - the app treats it as "no natural language today" and carries
    on with the knob and the keyboard.
    """
    from_env = os.environ.get("ANTHROPIC_API_KEY")
    if from_env:
        return from_env.strip()
    try:
        key = KEY_FILE.read_text().strip()
    except OSError:
        return None
    return key or None


# One client, built once and shared. Two reasons, and the second is the one
# that bit: building a client costs about 0.4 s on this Pi, and building
# several *at the same time* fails outright - pydantic's lazy model building is
# not thread-safe on first construction, so two threads racing into their first
# anthropic.Anthropic() can surface as "BaseModel cannot be instantiated
# directly". A serial caller never sees it; the eval runs four at a time and
# hit it on roughly one case in forty. The client itself is fine to share -
# it is requests that are concurrent, not construction.
_client_lock = threading.Lock()
_shared_client = None


# Let exactly one request in this process run on its own, then get out of the
# way. Sharing the client fixed half of a problem: building several at once is
# not thread-safe, but neither is *parsing the first response*, because the SDK
# builds its response models lazily and the first reply is what triggers it.
# Four threads arriving with the first four replies at once has surfaced as
# "BaseModel cannot be instantiated directly", which reads as a flaky model
# rather than a race in our own process.
#
# Measured before assuming: the error appeared about once in every 123 parses,
# both before and after the client was shared - three clean runs of a 1-in-123
# event is what luck looks like 37% of the time, and it was over-read as a fix.
#
# The cost of this is one serialised request per process, at startup, on a path
# that already waits seconds for the network. The app warms the import at boot
# for the same reason.
_first_call_lock = threading.Lock()
_first_call_done = False


@contextlib.contextmanager
def _first_call_alone():
    """Serialise the first successful request; a no-op after that."""
    global _first_call_done
    if _first_call_done:
        yield
        return
    with _first_call_lock:
        if _first_call_done:            # somebody got there while we waited
            yield
            return
        yield
        # Only on success. A call that raised never parsed a response, so
        # nothing was warmed and the next one should still go alone - otherwise
        # a camera that starts up with the network down loses the protection
        # exactly when it finally reconnects and everything retries at once.
        _first_call_done = True


def _client(key=None):
    """
    The shared SDK client, built on first use.

    An explicit key bypasses the cache and builds its own, which is what tests
    and any future multi-key caller want; the common path shares one.
    """
    global _shared_client
    import anthropic

    if key:
        return anthropic.Anthropic(api_key=key, timeout=TIMEOUT_SECONDS,
                                   max_retries=MAX_RETRIES)

    with _client_lock:
        if _shared_client is None:
            resolved = api_key()
            if not resolved:
                raise ParseError(
                    "no API key: set ANTHROPIC_API_KEY or write one to "
                    f"{KEY_FILE}")
            _shared_client = anthropic.Anthropic(
                api_key=resolved, timeout=TIMEOUT_SECONDS,
                max_retries=MAX_RETRIES)
        return _shared_client


def _describe(config):
    """The config as compact JSON, for the model to resolve relative asks."""
    return json.dumps(config.as_delta(), separators=(",", ":"))


def parse(utterance, config, previous=None, client=None):
    """
    Turn one utterance into a delta, or into a refusal.

    Args:
        utterance: what the person said or typed.
        config: the live RenderConfig, so relative requests resolve.
        previous: the config before the last change, so "undo" has a target.
            None on the first change of a run, which is honest - there is
            nothing to undo yet.
        client: an Anthropic client, for tests. Built from the key if omitted.

    Returns:
        Parsed.

    Raises:
        ParseError: no key, the network failed, the reply was refused by the
            model's own safety classifiers, or it came back in a shape this
            code cannot read. Every one of these is a thing the panel has to
            be able to say something useful about.
    """
    import time

    client = client or _client()
    state = {"now": json.loads(_describe(config))}
    if previous is not None:
        state["before"] = json.loads(_describe(previous))

    started = time.monotonic()
    try:
        # Built rather than written out, so an unsupported parameter can be
        # left out instead of sent and refused.
        options = {"output_config": {"effort": EFFORT}} if EFFORT else {}
        with _first_call_alone():
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                **options,
                # The system prompt and the tool schema are identical on every
                # call, so they are the cache prefix; the settings and the
                # utterance vary and therefore come after it, in the user turn.
                # Putting the current settings in the system prompt would change
                # the prefix on every request and cache nothing.
                system=[{
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                tools=tools(),
                # One of the two tools, never prose. A parser that can reply with a
                # paragraph has a third output shape nothing downstream handles.
                tool_choice={"type": "any"},
                messages=[{
                    "role": "user",
                    "content": (f"Settings: {json.dumps(state)}\n"
                                f"Request: {utterance}"),
                }],
            )
    except Exception as e:
        # Anything from the SDK - connection, timeout, rate limit, bad key.
        # Deliberately widened: the caller's job is to put something on a
        # 240x320 panel, not to tell an APIConnectionError from a
        # RateLimitError, and the class name is in the log either way.
        logger.error("Parse failed for %r: %s", utterance, e, exc_info=True)
        raise ParseError(str(e)) from e

    seconds = time.monotonic() - started

    # Checked before reading content, not after. A declined request returns a
    # perfectly good HTTP 200 whose content is empty or partial, so anything
    # that indexes content[0] first breaks here rather than reporting a
    # refusal. It is vanishingly unlikely for camera settings - but the cost
    # of the check is one comparison and the cost of missing it is a crash.
    if response.stop_reason == "refusal":
        detail = getattr(response, "stop_details", None)
        category = getattr(detail, "category", None)
        logger.warning("Model declined the request (%s)", category)
        raise ParseError(f"the model declined this request ({category})")

    usage = {
        "input": response.usage.input_tokens,
        "output": response.usage.output_tokens,
        "cache_read": getattr(response.usage, "cache_read_input_tokens", 0),
        "cache_write": getattr(response.usage,
                               "cache_creation_input_tokens", 0),
    }

    for block in response.content:
        if block.type != "tool_use":
            continue
        if block.name == "decline":
            return Parsed(declined=block.input.get("reason", "no reason given"),
                          usage=usage, seconds=seconds)
        if block.name == "set_render":
            fields = dict(block.input)
            unmet = fields.pop("unmet", None)
            if not fields:
                # set_render with nothing to set. Two different things wearing
                # the same shape, and they deserve different answers.
                if unmet:
                    # "zoom in a bit" on its own: nothing here maps to a
                    # setting, and it said so. That is a refusal with a reason,
                    # which is exactly what decline is for, so report it as one
                    # rather than as an empty change nobody can see.
                    return Parsed(declined=unmet, usage=usage, seconds=seconds)
                # Nothing changed and no reason given. Deliberately an error
                # rather than a quiet decline: dressing it up as a refusal
                # would hide a malformed answer from the eval, and hiding it
                # is how a scoreboard stops measuring.
                raise ParseError(
                    "the model asked to change nothing, and gave no reason")
            return Parsed(delta=fields, unmet=unmet or None, usage=usage,
                          seconds=seconds)

    raise ParseError("the model replied without calling either tool")


def apply_to(utterance, config, previous=None, client=None):
    """
    Parse and validate, without touching anything.

    The last step before the hardware, and the one that makes the model's
    output ordinary: the delta goes through the same `with_changes` a typed
    command uses, and is refused in the same words. Returns the new config so
    the caller can decide what to do with it.

    Returns:
        (Parsed, RenderConfig or None, problems). `problems` is the list
        RenderConfig raised, empty when the delta was accepted.
    """
    parsed = parse(utterance, config, previous=previous, client=client)
    if not parsed.ok:
        return parsed, None, []
    try:
        return parsed, config.with_changes(parsed.delta), []
    except ConfigError as e:
        logger.warning("Model produced an invalid delta %r: %s",
                       parsed.delta, e)
        return parsed, None, e.problems


def schema_json():
    """The generated tool schema, for eyeballing and for the eval's records."""
    return json.dumps(tools(), indent=2)


__all__ = ["MODEL", "ParseError", "Parsed", "RenderConfig", "api_key",
           "apply_to", "parse", "render_config", "schema_json", "tools"]
