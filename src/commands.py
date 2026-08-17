"""
Typed commands to RenderConfig deltas.

    scheme green                -> {"scheme": "green"}
    contrast 2.4 invert on      -> {"contrast": 2.4, "invert": True}
    help                        -> the whole settings surface, from SPECS
    show                        -> what everything is set to now

This is a *front end*, and the split matters more than the parsing does. Turning
text into typed values is this module's whole job; deciding whether those values
are allowed is RenderConfig's, and nothing here duplicates that. So "rotation
45" is parsed happily into {"rotation": 45} and refused one layer down, with the
same message anything else would get.

That is the shape the language model will slot into: it also turns fuzzy input
into a typed delta, and it also gets no say in whether the delta is legal. When
it arrives, this module does not move - it becomes the deterministic path beside
it, and the thing an eval can compare against.

Type conversion is driven by SPECS rather than a table of its own, so a new
setting becomes typeable, documented and listed by `help` without anything here
being edited.
"""

import render_config
from render_config import SPECS, RenderConfig

# What counts as true and false when a bool is being typed by hand. Deliberately
# not "anything non-empty is true": `invert 0` meaning true would be a nasty
# surprise, and RenderConfig will not take a string anyway.
TRUE_WORDS = ("on", "true", "yes", "y", "1")
FALSE_WORDS = ("off", "false", "no", "n", "0")

# Commands that are not settings changes.
WORDS = ("help", "show", "reset")

# Resolved before a line ever reaches this module - the app's command socket
# hands "ask ..." to the language model on its own thread, because a parse
# crosses a network and the render loop cannot wait for it. Named here only so
# that `help` can list it, and so a line that arrives with the parser switched
# off gets an explanation instead of "there is no setting called 'ask'".
ASK = "ask"


class CommandError(ValueError):
    """A line that could not be turned into a delta, with a reason to print."""


def parse(line):
    """
    Turn one typed line into ("delta", {...}) or ("help"/"show"/"reset", arg).

    Args:
        line: what the user typed, without the newline.

    Returns:
        (kind, payload). kind is "delta", "help", "show", "reset" or "none".
        For "help" the payload is a field name or None.

    Raises:
        CommandError: with a message meant to be read by whoever typed it.
    """
    # `scheme=green` and `scheme green` both work. Syntax is forgiving; names
    # and values are not, which is the distinction that keeps this front end
    # from being able to accept anything the validated path would refuse.
    tokens = line.replace("=", " ").split()
    if not tokens:
        return "none", None

    head = tokens[0].lower()
    if head == ASK:
        raise CommandError(
            "natural language is not available on this run - either the app "
            "was started without its command socket resolver, or there is no "
            "API key. Every setting can still be set by name; try \"help\".")
    if head in WORDS:
        if head == "help":
            target = tokens[1].lower() if len(tokens) > 1 else None
            if target is not None and target not in render_config.BY_NAME:
                raise CommandError(unknown_setting(target))
            return "help", target
        if len(tokens) > 1:
            raise CommandError(f"{head} takes no arguments")
        return head, None

    if len(tokens) % 2:
        raise CommandError(
            "every setting needs a value - got an odd number of words. "
            f"Try \"{tokens[0]} <value>\", or \"help\" for the list.")

    delta = {}
    for name, text in zip(tokens[0::2], tokens[1::2]):
        name = name.lower()
        spec = render_config.BY_NAME.get(name)
        if spec is None:
            raise CommandError(unknown_setting(name))
        if name in delta:
            raise CommandError(f"{name} given twice in one line")
        delta[name] = _value(spec, text)
    return "delta", delta


def unknown_setting(name):
    """The message for a setting nobody has heard of, listing the real ones."""
    return (f"there is no setting called {name!r}; the settings are "
            + ", ".join(render_config.BY_NAME))


def _value(spec, text):
    """
    Turn one word into the type its field expects.

    Only the *type* is settled here. A value of the right type but the wrong
    magnitude - rotation 45, colour_levels 9 - is passed through untouched and
    refused by RenderConfig, so there is exactly one place that decides what is
    allowed and exactly one wording for saying no.
    """
    if spec.kind == "bool":
        lowered = text.lower()
        if lowered in TRUE_WORDS:
            return True
        if lowered in FALSE_WORDS:
            return False
        raise CommandError(
            f"{spec.name} takes {'/'.join(TRUE_WORDS[:3])} or "
            f"{'/'.join(FALSE_WORDS[:3])}, not {text!r}")

    if spec.kind == "choice":
        # Choices are ints for some fields and strings for others, so a match
        # is tried first - which settles the type *and* canonicalises the case,
        # so "Green" becomes "green".
        for choice in spec.choices:
            if isinstance(choice, str):
                if choice.lower() == text.lower():
                    return choice
            elif str(choice) == text:
                return choice

        # No match, and refusing here would be this layer overstepping. The
        # value's *type* still follows from the choices, so hand it on with
        # that type and let RenderConfig be the one place that says no - in the
        # one wording every other route gets, including the model's.
        #
        # The first version of this did refuse, which put "must be one of" in
        # two modules and meant `rotation 45` never reached the validator at
        # all. tests/commands_test.py caught it.
        if all(isinstance(choice, str) for choice in spec.choices):
            return text
        try:
            return int(text)
        except ValueError:
            allowed = ", ".join(str(choice) for choice in spec.choices)
            raise CommandError(
                f"{spec.name} takes a number - one of {allowed} - "
                f"not {text!r}") from None

    try:
        return int(text) if spec.kind == "int" else float(text)
    except ValueError:
        raise CommandError(f"{spec.name} takes a number, not {text!r}") from None


def describe(spec):
    """The one-line "what may I type here" for a single setting."""
    if spec.kind == "bool":
        return "on or off"
    if spec.kind == "choice":
        return "one of: " + ", ".join(str(c) for c in spec.choices)
    return f"a number from {spec.low} to {spec.high} (outside that is clamped)"


def help_text(name=None, config=None):
    """
    What can be typed, generated from SPECS rather than written out again.

    A setting added to RenderConfig is documented here the moment it exists,
    and cannot be forgotten - which is the same reason SPECS exists at all.

    Args:
        name: a single setting to describe, or None for all of them.
        config: the live config, so current values can be shown alongside.
    """
    chosen = [render_config.BY_NAME[name]] if name else list(SPECS)
    width = max(len(spec.name) for spec in chosen)

    lines = []
    if not name:
        lines += [
            "Type a setting and a value, then RETURN. Several at once is fine:",
            "",
            "    scheme green",
            "    contrast 2.4 invert on freeze off",
            "",
            "Or say it in your own words, and a language model works out the",
            "settings. The change it proposes is validated exactly as a typed",
            "one is, so it can be refused the same way:",
            "",
            "    ask make it warmer and blockier",
            "    ask undo that",
            "",
            "Settings:",
            "",
        ]

    for spec in chosen:
        now = ""
        if config is not None:
            now = f"   [now {getattr(config, spec.name)!r}]"
        lines.append(f"  {spec.name:<{width}}  {describe(spec)}{now}")
        lines.append(f"  {'':<{width}}  {spec.note}")
        lines.append("")

    if not name:
        lines += [
            "Also:",
            "",
            "  ask <words>      say it in your own words",
            "  help <setting>   just that one",
            "  show             every current value",
            "  reset            back to the start-up defaults",
            "",
            "Values outside a range are clamped; anything else is refused and",
            "nothing changes. The single-key controls still work as before.",
        ]
    return "\n".join(lines).rstrip()


def show_text(config):
    """Every current value, in the order SPECS declares them."""
    width = max(len(spec.name) for spec in SPECS)
    return "\n".join(f"  {spec.name:<{width}}  {getattr(config, spec.name)!r}"
                     for spec in SPECS)


def defaults_delta(config):
    """
    The delta that puts every setting back to its start-up default.

    Expressed as a delta rather than by swapping in a fresh RenderConfig, so
    that `reset` goes down the same validated path as everything else and the
    app's _adopt sees a normal change with a normal before and after.
    """
    fresh = RenderConfig()
    return {name: getattr(fresh, name) for name in fresh.changes_from(config)}
