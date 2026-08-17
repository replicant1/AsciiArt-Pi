"""
Every setting that can change while the camera is running, in one typed object.

Before this, the live settings were scattered: some on the ImageProcessor, some
as plain attributes of the app, the colour scheme as an index into a tuple, and
a hand-maintained second copy of eight of them in `LcdConfig` so the panel could
be told what the terminal was doing. Nothing named the full set, so nothing
could validate a change, log one, or hand one to anything else.

Here the set is named once, immutably, and every change is a *delta* - a dict of
field names to values - applied through `with_changes`, which either returns a
new config or raises listing everything wrong with the delta. Deltas are also
what the encoder and the keyboard produce, so there is exactly one path in.

Two rules, and the difference between them is deliberate:

  * A value outside a **range** is clamped. Ranges are limits of the hardware
    and the arithmetic, not category errors: contrast 9 is a coherent wish that
    the renderer cannot go all the way to, so it becomes 4.0. The keyboard's
    +/- keys already clamped this way.
  * A value outside an **enumeration** is refused, and so is an unknown field
    name or a value of the wrong type. There is no nearest sensible rotation to
    45 degrees and no scheme next door to "purple", so guessing would be worse
    than saying no.

`SPECS` carries the type, the permitted values and a one-line description of
every field. It exists so that the schema is derived rather than restated: a
new setting is added in exactly two places, the dataclass and SPECS, and
`_check_specs_match_fields` below fails at import if only one of them was
touched. (That failure mode is not hypothetical - sync.sh has the same shape of
trap, where a module missing from its file list is silently never copied.)
"""

import logging
from dataclasses import dataclass, fields, replace
from typing import NamedTuple

import palettes
from ascii_art import RAMPS

logger = logging.getLogger(__name__)

# Which output shows the picture. Not a capability - whether a panel or a
# terminal exists at all is a separate question the app answers at start-up -
# but a choice made on top of whatever exists.
TARGETS = ("both", "terminal", "lcd")


class ConfigError(ValueError):
    """
    A delta that could not be applied, carrying every reason rather than one.

    All the problems, not just the first: a caller correcting a delta a fault at
    a time learns nothing about how many are left, and a scoreboard counting
    refusals wants the whole list.
    """

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


class Spec(NamedTuple):
    """What one setting accepts, and what it is for."""

    name: str
    kind: str               # "bool", "choice", "int" or "float"
    note: str               # one line, for --help, logs and the schema
    choices: tuple = ()     # for "choice"
    low: float = None       # for "int" and "float"
    high: float = None


SPECS = (
    Spec("scheme", "choice",
         "Colour scheme the picture is drawn in.",
         choices=palettes.SCHEME_NAMES),
    Spec("ramp", "choice",
         "Character set, ordered light to dark.",
         choices=tuple(RAMPS)),
    Spec("invert", "bool",
         "Reverse the ramp, for a light background."),
    Spec("colour_levels", "choice",
         "Steps per channel in the live-colour scheme, on both displays; "
         "fewer means heavier banding. 6 means as many as the display can "
         "manage.",
         choices=(2, 3, 4, 5, 6)),
    Spec("contrast", "float",
         "Contrast multiplier about mid-grey; 1.0 leaves the frame alone.",
         low=0.1, high=4.0),
    Spec("auto_levels", "bool",
         "Stretch each frame's own brightness range to fill 0-255."),
    Spec("rotation", "choice",
         "Camera rotation in degrees, applied before any mirroring.",
         choices=(0, 90, 180, 270)),
    Spec("mirror", "bool",
         "Flip the picture left to right, after any rotation."),
    Spec("fill", "bool",
         "Crop the picture to fill the whole window instead of letterboxing "
         "it. The panel always fills and ignores this."),
    Spec("lcd_font_size", "int",
         "Glyph size on the SPI panel, which sets its character grid. 6, 8 "
         "and 9 tile the panel exactly; other sizes leave a black margin.",
         low=4, high=16),
    Spec("target", "choice",
         "Which display shows the picture.",
         choices=TARGETS),
    Spec("freeze", "bool",
         "Hold the last frame instead of taking new ones. Settings still "
         "apply, so a frozen picture can be adjusted and watched."),
)

BY_NAME = {spec.name: spec for spec in SPECS}


@dataclass(frozen=True)
class RenderConfig:
    """
    The complete live render state.

    Frozen on purpose. A setting that can be assigned in place is a setting
    that can be changed without anyone being told, which is how the panel's
    copy came to be maintained by hand; `with_changes` returns a new object, so
    every change has a before and an after to compare.
    """

    scheme: str = "grey"
    ramp: str = "coarse"
    invert: bool = False
    colour_levels: int = 6
    contrast: float = 1.0
    auto_levels: bool = True
    rotation: int = 0
    mirror: bool = False
    fill: bool = False
    lcd_font_size: int = 8
    target: str = "both"
    freeze: bool = False

    def with_changes(self, delta):
        """
        A new config with `delta` applied.

        Args:
            delta: {field name: value}. An empty delta is legal and returns an
                equal config, which is what "the user asked for nothing" should
                cost.

        Returns:
            A new RenderConfig. This one is unchanged.

        Raises:
            ConfigError: naming every unknown field, wrong type and value
                outside an enumeration. Values outside a range are clamped
                instead and are not errors.
        """
        problems = []
        changes = {}

        for name, value in delta.items():
            spec = BY_NAME.get(name)
            if spec is None:
                problems.append(
                    f"there is no setting called {name!r}; the settings are "
                    + ", ".join(BY_NAME))
                continue
            accepted, problem = _coerce(spec, value)
            if problem is not None:
                problems.append(problem)
            else:
                changes[name] = accepted

        if problems:
            raise ConfigError(problems)
        return replace(self, **changes)

    def changes_from(self, other):
        """
        Field names where this config and `other` disagree, in SPECS order.

        `other` may be None, meaning "nothing has been applied yet", in which
        case every field counts as changed - which is what start-up wants, since
        every subsystem still has to be told once.
        """
        if other is None:
            return tuple(spec.name for spec in SPECS)
        return tuple(spec.name for spec in SPECS
                     if getattr(self, spec.name) != getattr(other, spec.name))

    def describe_changes(self, other):
        """
        A one-line "field old->new" summary, for the log and the status line.

        Empty string when nothing changed, so a caller can use it as the test
        for whether a change was real. `other` of None describes the whole
        config, since that is the start-up case where there is no "before".
        """
        if other is None:
            return ", ".join(f"{name}={value!r}"
                             for name, value in self.as_delta().items())
        return ", ".join(f"{name} {getattr(other, name)!r}->"
                         f"{getattr(self, name)!r}"
                         for name in self.changes_from(other))

    def as_delta(self):
        """The whole config as a delta, so it can be replayed or diffed."""
        return {spec.name: getattr(self, spec.name) for spec in SPECS}


def _coerce(spec, value):
    """
    Check one field's value.

    Returns:
        (accepted value, None) or (None, problem). The accepted value is
        normalised to the spec's own type, so a rotation given as 90.0 is
        stored as the int 90 and compares equal to the default.
    """
    if spec.kind == "bool":
        # Exactly bool, not "anything truthy". 1 and "yes" are the shapes a
        # sloppy caller produces, and silently accepting them would leave the
        # config holding a value nothing else in the app expects to see.
        if not isinstance(value, bool):
            return None, f"{spec.name} takes true or false, not {value!r}"
        return value, None

    if spec.kind == "choice":
        # bool first: bool is a subclass of int, so False == 0 and `False in
        # (0, 90, 180, 270)` is True. Without this, freeze=False sent to
        # rotation by mistake would be accepted as "no rotation".
        if not isinstance(value, bool):
            for choice in spec.choices:
                if choice == value:
                    return choice, None
        allowed = ", ".join(repr(c) for c in spec.choices)
        return None, f"{spec.name} must be one of {allowed}, not {value!r}"

    # A range. Same bool exclusion, for the same reason.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, f"{spec.name} takes a number, not {value!r}"

    number = round(value) if spec.kind == "int" else float(value)
    clamped = min(spec.high, max(spec.low, number))
    if clamped != number:
        logger.info("%s clamped from %r to %r", spec.name, value, clamped)
    return (int(clamped) if spec.kind == "int" else float(clamped)), None


def from_args(args):
    """
    The starting config, from a parsed command line.

    The two pieces of history that live here rather than in the dataclass:
    `--colour` is the old way of asking for the live scheme and `--scheme` wins
    over it, and `--no-terminal` is a target choice expressed as a flag.
    """
    return RenderConfig(
        scheme=args.scheme or ("live" if args.colour else "grey"),
        ramp=args.ramp,
        invert=args.invert,
        colour_levels=args.colour_levels,
        contrast=args.contrast,
        auto_levels=not args.no_auto_levels,
        rotation=args.rotation,
        mirror=args.mirror,
        fill=args.fill,
        lcd_font_size=args.lcd_font_size,
        target="lcd" if args.no_terminal else "both",
        freeze=False,
    )


def _check_specs_match_fields():
    """
    Fail at import if SPECS and the dataclass have drifted apart.

    A field with no spec cannot be validated or described, and a spec with no
    field would be advertised and then rejected as unknown. Either way the
    symptom appears far from the omission, so it is caught here instead.
    """
    declared = tuple(f.name for f in fields(RenderConfig))
    specified = tuple(spec.name for spec in SPECS)
    if declared != specified:
        raise RuntimeError(
            "render_config: SPECS and RenderConfig disagree - "
            f"fields {declared}, specs {specified}")

    # Every default must survive its own validation *unchanged*. Comparing the
    # value back rather than only checking for an error is what catches a
    # default outside a range, which clamping would otherwise absorb in
    # silence - the config would then not equal the one it was built from.
    defaults = RenderConfig()
    for spec in SPECS:
        value = getattr(defaults, spec.name)
        accepted, problem = _coerce(spec, value)
        if problem is not None:
            raise RuntimeError(f"render_config: default {spec.name}={value!r} "
                               f"is not valid: {problem}")
        if accepted != value:
            raise RuntimeError(f"render_config: default {spec.name}={value!r} "
                               f"is not what validation returns ({accepted!r})")


_check_specs_match_fields()
