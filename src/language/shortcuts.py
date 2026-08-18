"""
The phrases that do not need a language model.

`ask make it green` crosses a network, waits 2.6 seconds and costs a third of a
US cent to work out `{"scheme": "green"}` - which is the scheme's own name, said
out loud. This module answers that class of phrase from a table, in microseconds
and for nothing, and hands everything else to src/language/parser.py unchanged.

**The table is exact and the model is fuzzy, and that split is the whole
design.** A lookup that guessed would be competing with the model at the thing
the model is for, and losing quietly: a near-miss here becomes a wrong setting
with no round trip to blame it on. So this matches a normalised string against a
list of phrasings and answers `None` the moment it is not certain. Every phrase
it does not know is somebody else's problem, and that somebody is better at it.

What earns a place, in the order the entries below are built:

  * **A setting's own value, said as a phrase.** "green", "make it amber",
    "fine characters". These are generated from `SPECS`, so a scheme added to
    palettes.py is speakable the same day without editing this file - the same
    reason `help`, the tool schema and the validator are all generated from the
    same source.
  * **A boolean, said as a verb.** "freeze it", "invert it".
  * **A step along a range.** "a bit more contrast", "bigger characters". These
    need the current config, which is why an entry is a function of it rather
    than a constant.
  * **"undo that"**, which is not a guess at all: the app knows the previous
    config exactly, so the delta that restores it is arithmetic. The model can
    only approximate this, and does, from a sparse description in its prompt.

What is deliberately left to the model: anything with a mood in it ("something
calmer"), anything compound ("green, high contrast, and the fine ramp"), the
target phrasings ("same but on the big screen"), and every phrase that should be
declined. A table cannot decline well - it can only fail to match, which is not
the same thing and must not be reported as if it were.

Two properties worth stating plainly, because they are the point:

  * A hit costs nothing and takes no time, so the panel changes while your
    thumb is still on the glass.
  * A hit needs no API key and no network. With the WiFi down or the key
    missing, "green" and "freeze it" still work, and `ask` stops being all or
    nothing.
"""

import logging

from control.render_config import BY_NAME, RenderConfig

logger = logging.getLogger(__name__)

# One step along a range. 1.3 was not tuned - it is the smallest move that is
# unmistakable on the panel, and tests/language/parser_eval.py's own band for "a bit more
# contrast" (1.05 to 2.0 from a default of 1.0) contains it comfortably.
CONTRAST_STEP = 1.3
FONT_STEP = 1

# Politeness, stripped before matching so it does not have to appear in every
# phrasing below. Nothing semantic is removed - "a bit" survives, because "a bit
# more contrast" and "way more contrast" are different requests.
COURTESIES = ("please", "can you", "could you", "i'd like", "id like")


def normalise(utterance):
    """
    Lower case, one space between words, no trailing punctuation, no manners.

    Deliberately shallow. Stemming or stopword removal would let two different
    requests normalise to the same string, which is the one failure this table
    cannot afford - it would answer confidently and never reach the model.
    """
    text = " ".join(utterance.lower().split()).strip(" .!?,")
    changed = True
    while changed:
        changed = False
        for word in COURTESIES:
            if text.startswith(word + " "):
                text, changed = text[len(word) + 1:].strip(), True
            if text.endswith(" " + word):
                text, changed = text[:-len(word) - 1].strip(), True
    return text


def _clamp(name, value):
    """Hold a stepped value inside its own spec, so a step at the end is a no-op."""
    spec = BY_NAME[name]
    return max(spec.low, min(spec.high, value))


def _step_contrast(factor):
    def resolve(config, previous):
        return {"contrast": round(_clamp("contrast", config.contrast * factor), 2)}
    return resolve


def _step_font(delta):
    def resolve(config, previous):
        return {"lcd_font_size": int(_clamp("lcd_font_size",
                                            config.lcd_font_size + delta))}
    return resolve


def _undo(config, previous):
    """
    Put back exactly what the last change moved.

    Returns None rather than an empty delta when there is nothing to undo, so
    the phrase falls through to the model instead of being answered with a
    shrug. That costs an API call in a case nobody can satisfy, which is the
    cheaper mistake: the alternative is this module inventing a reply.
    """
    if previous is None:
        return None
    changed = config.changes_from(previous)
    if not changed:
        return None
    return {name: getattr(previous, name) for name in changed}


def _fixed(delta):
    def resolve(config, previous):
        return dict(delta)
    return resolve


def _build():
    """
    The table, generated where it can be and written out where it cannot.

    Returns {normalised phrase: resolver}. A resolver takes (config, previous)
    and returns a delta, or None to fall through.
    """
    table = {}

    def add(phrases, resolver):
        for phrase in phrases:
            key = normalise(phrase)
            if key in table:
                # Two entries claiming one phrase means one of them silently
                # never runs, and which one depends on dict order. Fail at
                # import, where it is a typo, rather than in a month, where it
                # is a bug report about one word behaving oddly.
                raise RuntimeError(f"two shortcuts claim {key!r}")
            table[key] = resolver

    # --- a setting's own value, said out loud -------------------------------
    #
    # Generated from SPECS, so this stays true as values are added. `live` gets
    # "live colour" free, which is how it was actually asked for in the log.
    #
    # The two settings get their OWN phrasings rather than one shared template.
    # Sharing produced a cross product where "fine colour" set the ramp and
    # "coarse colour" did too - phrases that are about the other setting
    # entirely, answered confidently. "{value} characters" is the one form both
    # can honestly claim: "green characters" means characters drawn in green,
    # and "fine characters" means finer ones. Nothing else crosses.
    PHRASINGS = {
        "scheme": ("{v}", "{v} scheme", "the {v} scheme", "make it {v}",
                   "go {v}", "switch to {v}", "{v} characters",
                   "{v} colour", "{v} color"),
        "ramp": ("{v}", "{v} ramp", "the {v} ramp", "make it {v}",
                 "{v} characters", "{v} glyphs", "{v} detail"),
    }
    for name, forms in PHRASINGS.items():
        for value in BY_NAME[name].choices:
            add(tuple(form.format(v=value) for form in forms),
                _fixed({name: value}))

    # --- a boolean, said as a verb ------------------------------------------
    for phrases, delta in (
            (("freeze", "freeze it", "freeze the picture", "hold it there"),
             {"freeze": True}),
            (("unfreeze", "unfreeze it", "unfreeze the picture"),
             {"freeze": False}),
            (("invert", "invert it", "invert the picture"), {"invert": True}),
            (("uninvert", "uninvert it", "stop inverting"), {"invert": False}),
            (("mirror", "mirror it", "flip it left to right"),
             {"mirror": True}),
            (("unmirror", "unmirror it", "stop mirroring"), {"mirror": False})):
        add(phrases, _fixed(delta))

    # --- a step along a range ------------------------------------------------
    add(("more contrast", "a bit more contrast", "a little more contrast",
         "turn up the contrast", "turn the contrast up", "more punch"),
        _step_contrast(CONTRAST_STEP))
    add(("less contrast", "a bit less contrast", "a little less contrast",
         "turn down the contrast", "turn the contrast down", "flatten it out"),
        _step_contrast(1 / CONTRAST_STEP))
    add(("bigger characters", "larger characters", "bigger text",
         "bigger glyphs"), _step_font(FONT_STEP))
    add(("smaller characters", "smaller text", "smaller glyphs"),
        _step_font(-FONT_STEP))

    # --- arithmetic the model can only approximate ---------------------------
    add(("undo that", "undo", "undo it", "put that back"), _undo)

    return table


TABLE = _build()


def _check_table_is_answerable():
    """
    Every fixed entry must survive the validator, at import.

    A scheme renamed in palettes.py or a typo in a phrase's delta would
    otherwise show up as a refusal in front of somebody using the camera, long
    after the change that caused it. Stepped entries are checked from the
    defaults, which is enough to catch a wrong field name or a bad type.
    """
    base = RenderConfig()
    for phrase, resolver in TABLE.items():
        delta = resolver(base, None)
        if delta is None:
            continue                      # undo, with nothing to undo
        try:
            base.with_changes(delta)
        except Exception as e:
            raise RuntimeError(f"shortcut {phrase!r} produces {delta!r}, "
                               f"which the validator refuses: {e}") from e


_check_table_is_answerable()


def look_up(utterance, config, previous=None):
    """
    The delta for a phrase this table is certain about, or None.

    Args:
        utterance: what was said, without the leading "ask".
        config: the settings it is being said about.
        previous: the settings before the last change, for "undo that".

    Returns:
        A delta dict, or None to mean "not mine" - which is every phrase this
        table does not recognise, and every phrase it recognises but cannot
        answer from the state it was given.
    """
    resolver = TABLE.get(normalise(utterance))
    if resolver is None:
        return None
    delta = resolver(config, previous)
    if delta is None:
        return None
    logger.debug("Shortcut %r -> %s", utterance, delta)
    return delta


__all__ = ["TABLE", "look_up", "normalise"]
