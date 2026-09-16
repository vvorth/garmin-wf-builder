"""Lengths and angles, and the rules for resolving them to device pixels.

ADR 0004: absolute pixels are not the primary model.  A length is one of

    ``12px``   device pixels, verbatim
    ``30%``    of the parent box, along the axis being resolved
    ``38%r``   of the screen's *minor radius* -- what keeps a round design
               circular on a non-square screen
    ``1.5pt``  multiples of a reference font's real pixel height on this device

Angles are degrees with **12 o'clock = 0 and clockwise positive**, because that
is how a watch designer thinks.  Garmin's ``drawArc`` uses 3 o'clock = 0 and
counter-clockwise positive; :func:`to_garmin_degrees` performs the conversion so
the author never has to.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum


class UnitError(ValueError):
    pass


class Axis(str, Enum):
    X = "x"
    Y = "y"
    #: For radii, thicknesses and other quantities with no natural axis; ``%``
    #: then resolves against the parent box's smaller dimension.
    MINOR = "minor"


_LENGTH_RE = re.compile(r"^\s*(?P<num>[+-]?(?:\d+\.?\d*|\.\d+))\s*(?P<unit>%r|%|px|pt)?\s*$")
_ANGLE_RE = re.compile(r"^\s*(?P<num>[+-]?(?:\d+\.?\d*|\.\d+))\s*(?P<unit>deg|rad|turn)?\s*$")
_DURATION_RE = re.compile(r"^\s*(?P<num>\d+)\s*(?P<unit>m|h|d)\s*$")


@dataclass(frozen=True)
class Length:
    value: float
    unit: str  # "px" | "%" | "%r" | "pt"

    @classmethod
    def parse(cls, raw: object, *, what: str = "length") -> "Length":
        if isinstance(raw, Length):
            return raw
        if isinstance(raw, bool):
            raise UnitError(f"{what}: expected a length, got a boolean")
        if isinstance(raw, (int, float)):
            return cls(float(raw), "px")
        if not isinstance(raw, str):
            raise UnitError(f"{what}: expected a length such as '12px' or '30%', got {raw!r}")
        m = _LENGTH_RE.match(raw)
        if not m:
            raise UnitError(
                f"{what}: {raw!r} is not a length.  Use px, %, %r or pt, e.g. '12px', '-4%', '38%r'"
            )
        return cls(float(m.group("num")), m.group("unit") or "px")

    def resolve(self, *, box: "Box", axis: Axis, minor_radius: float, font_px: float | None = None) -> float:
        """Resolve to device pixels within ``box``."""
        if self.unit == "px":
            return self.value
        if self.unit == "%r":
            return self.value / 100.0 * minor_radius
        if self.unit == "%":
            if axis is Axis.X:
                extent = box.width
            elif axis is Axis.Y:
                extent = box.height
            else:
                extent = min(box.width, box.height)
            return self.value / 100.0 * extent
        if self.unit == "pt":
            if font_px is None:
                raise UnitError("pt units need a reference font; none is in scope here")
            return self.value * font_px
        raise UnitError(f"unknown unit {self.unit!r}")

    def __str__(self) -> str:
        num = f"{self.value:g}"
        return f"{num}{self.unit}"


def is_sub_pixel_length(length: "Length | None", value: float) -> bool:
    """True when ``length`` is a nonzero `%`/`%r` length whose resolved
    magnitude is under 1 px -- the exact condition :func:`at_least_one_px`
    clamps away when its switch is on, and the one `wfb.layout.Resolver`
    records a `wfb.layout.SubPixelLength` for when its switch is off (plan 08
    §3.3).  Pulled out as its own predicate, rather than folded into
    `at_least_one_px` alone, so both call sites -- "should this be clamped"
    and "would this have been clamped had the switch been on" -- share
    exactly one definition of "sub-pixel", and can never drift apart the way
    two independent `0 < abs(value) < 1` checks eventually would.

    ``length`` is the original :class:`Length` (``None`` for "no length was
    authored, a default applied" -- never sub-pixel, the default is not a
    relative unit at all); ``value`` is what :meth:`Length.resolve` returned
    for it, in device pixels, *before* rounding to a whole pixel.
    """
    return length is not None and length.unit in ("%", "%r") and 0 < abs(value) < 1


def at_least_one_px(length: "Length | None", value: float, enabled: bool) -> float:
    """A nonzero relative length never resolves to less than 1 px -- when
    `min_1px:` (plan 08) switches this on for the caller's element/part.

    A `%`/`%r` length scales per device: the same hairline (`thickness:
    0.5%r`, say) that draws as 1 px on one screen can round to 0 on another,
    so it draws on one target and silently vanishes on the next.  Rounding
    down to nothing is only a real answer when the author actually wrote a
    zero -- so, when `enabled`, this clamps a *nonzero* `%`/`%r` result's
    magnitude up to 1 px, sign preserved, and leaves everything else
    (`px`/`pt` lengths, which are already exactly what the author wrote, and
    an exact `0`) alone.

    ``enabled`` is **required, with no default**, deliberately: every call
    site states its own gate (the owning element's `resolved_min_1px`)
    explicitly, so the rule and its switch can never quietly drift apart --
    see `wfb.layout.Resolver._extent`/`._hand_extent`, the only callers. When
    `enabled` is false this returns `value` untouched -- today's pre-feature
    arithmetic, exactly -- even where :func:`is_sub_pixel_length` is true;
    the caller is the one that turns that case into a `SubPixelLength`
    record for the suppressible `sub-pixel-length` lint.

    ``length`` is the original :class:`Length` (``None`` for "no length was
    authored, a default applied" -- never clamped, the default is not a
    relative unit at all); ``value`` is what :meth:`Length.resolve` returned
    for it, in device pixels, *before* rounding to a whole pixel.
    """
    if enabled and is_sub_pixel_length(length, value):
        return math.copysign(1.0, value)
    return value


# --------------------------------------------------------------------------
# Sizes that are resolved *before* layout runs
#
# A bitmap font -- an author's own custom font, or one of the synthetic
# per-size icon fonts :mod:`wfb.icons` builds -- is rasterised at one nominal
# pixel size, and that size has to be known before any element is placed.
# That is the whole reason these two rules live here rather than in either
# caller: both the icon path (`wfb.layout`, `wfb.emit.resources.icon_font_specs`)
# and the custom-font path (`wfb.emit.resources.bake_fonts`) need exactly the
# same "declared size -> this device's pixels" answer, and having two of them
# is how a `12px` icon and a `12px` font would silently drift apart.


#: The units a size resolved before layout may use.  `%` (of the parent box)
#: and `pt` (of an element's own font) both depend on context that does not
#: exist yet at baking time; `%r` and `px` do not -- a fraction of the
#: screen's minor radius, or a device pixel count, mean the same thing
#: wherever the thing being sized ends up sitting.
SIZE_UNITS = ("px", "%r")


def pixel_size(length: "Length | None", minor_radius: float, default: float = 24.0) -> int:
    """Resolve a `px`/`%r` length to whole device pixels, with no box in scope.

    Deliberately independent of any parent box -- callable before layout, so a
    bitmap font can be baked once per distinct declared size before the
    elements that use it are placed.  This is why the sizes that reach it are
    restricted to :data:`SIZE_UNITS` (enforced in :mod:`wfb.ir`, which owns the
    author-facing diagnostic).

    For an icon this is the height the glyph should *visibly* draw at, not
    necessarily the nominal em size it gets baked at -- see
    `wfb.icons.bake_size`, which turns this target into the size handed to the
    rasteriser.  For a text font it is the nominal em size directly; see that
    function's docstring for why the two are deliberately not unified.
    """
    if length is None:
        return round(default)
    return max(1, round(length.resolve(box=_UNUSED_BOX, axis=Axis.MINOR,
                                       minor_radius=minor_radius)))


@dataclass(frozen=True)
class Angle:
    """Degrees, 12 o'clock = 0, clockwise positive."""

    degrees: float

    @classmethod
    def parse(cls, raw: object, *, what: str = "angle") -> "Angle":
        if isinstance(raw, Angle):
            return raw
        if isinstance(raw, bool):
            raise UnitError(f"{what}: expected an angle, got a boolean")
        if isinstance(raw, (int, float)):
            return cls(float(raw))
        if not isinstance(raw, str):
            raise UnitError(f"{what}: expected an angle such as '45deg', got {raw!r}")
        m = _ANGLE_RE.match(raw)
        if not m:
            raise UnitError(f"{what}: {raw!r} is not an angle.  Use deg, rad or turn, e.g. '45deg'")
        value, unit = float(m.group("num")), m.group("unit") or "deg"
        if unit == "rad":
            import math

            value = math.degrees(value)
        elif unit == "turn":
            value *= 360.0
        return cls(value)

    def to_garmin(self) -> float:
        """Convert to ``Dc.drawArc``'s convention: 3 o'clock = 0, CCW positive."""
        return (90.0 - self.degrees) % 360.0

    def __str__(self) -> str:
        return f"{self.degrees:g}deg"


def to_garmin_degrees(degrees: float) -> float:
    return (90.0 - degrees) % 360.0


@dataclass(frozen=True)
class Duration:
    """A plain span of time -- minutes, hours or days, whole numbers only.

    Distinct from :class:`Angle`/:class:`Length`: nothing here is resolved
    against a device.  A `graph` element's `range:` is the one place this
    project needs a duration rather than a screen-relative quantity -- "the
    last 4 hours" of heart-rate history means the same 14400 seconds on every
    target, so there is no per-device resolve step the way a `Length` has.
    """

    seconds: int

    @classmethod
    def parse(cls, raw: object, *, what: str = "duration") -> "Duration":
        if isinstance(raw, Duration):
            return raw
        if isinstance(raw, bool) or not isinstance(raw, str):
            raise UnitError(
                f"{what}: expected a duration such as '30m', '4h' or '7d', got {raw!r}"
            )
        m = _DURATION_RE.match(raw)
        if not m:
            raise UnitError(
                f"{what}: {raw!r} is not a duration.  Use m, h or d, e.g. '30m', '4h', '7d'"
            )
        factor = {"m": 60, "h": 3600, "d": 86400}[m.group("unit")]
        return cls(int(m.group("num")) * factor)

    def __str__(self) -> str:
        if self.seconds % 86400 == 0:
            return f"{self.seconds // 86400}d"
        if self.seconds % 3600 == 0:
            return f"{self.seconds // 3600}h"
        return f"{self.seconds // 60}m"


@dataclass(frozen=True)
class Box:
    """An axis-aligned rectangle in device pixels."""

    x: float
    y: float
    width: float
    height: float

    @property
    def left(self) -> float:
        return self.x

    @property
    def top(self) -> float:
        return self.y

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2.0

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2.0

    def anchor_point(self, anchor: str) -> tuple[float, float]:
        try:
            fx, fy = ANCHORS[anchor]
        except KeyError:
            raise UnitError(
                f"unknown anchor {anchor!r}.  Valid anchors: {', '.join(sorted(ANCHORS))}"
            ) from None
        return self.x + fx * self.width, self.y + fy * self.height

    def rounded(self, *, min_1px: bool = False) -> "IntBox":
        """Snap to whole pixels.

        Rounds each edge independently (round-half-to-even), then takes the
        width/height as the difference of the rounded edges -- which is
        usually what keeps a box's rounded corners consistent with its
        rounded centre, but has one degenerate case: a box whose float width
        is exactly ``1.0`` and centred on an integer coordinate has
        ``left = n - 0.5``, ``right = n + 0.5``, and round-half-to-even
        sends *both* to ``n`` when ``n`` is even -- width 0, even though a
        clamp upstream (:func:`at_least_one_px`) deliberately made this box
        1 px wide.

        That one case is corrected here, but only when ``min_1px`` is true --
        plan 08 §3.3 made the clamp itself opt-in, and this correction exists
        solely to protect *that* clamp's own work, so it must not fire on its
        own where the clamp never ran.  ``min_1px`` therefore defaults to
        `False`, today's pre-feature arithmetic exactly (this correction did
        not exist at all before the clamp was added), and a caller passes
        `True` only at the handful of call sites whose box width/height is
        itself a raw, unrounded extent that went through
        :meth:`wfb.layout.Resolver._extent` -- a `group`'s own `size:`, or a
        `shape`/`progress`/`graph`'s plain rectangular `size:` box.  Every
        other box here (a circle/arc/ellipse's doubled radius-plus-pad reach,
        a polygon's point-derived bounds, a hand or pattern's swept-disc or
        ink-bounds box) never hits this exact tie in the first place, so
        those call sites are left at the default and get exactly the
        arithmetic they always have.

        Any other width/height, rounded or not, is left exactly as the
        edge-rounding above produces it -- in particular the same rounding
        can still turn some other float extent (say 25 px at a half-integer
        left edge) into a different integer width; that is pre-existing
        behaviour, unchanged here.
        """
        left, top = round(self.x), round(self.y)
        width, height = round(self.right) - left, round(self.bottom) - top
        if min_1px:
            if self.width >= 1 and width < 1:
                width = 1
            if self.height >= 1 and height < 1:
                height = 1
        return IntBox(left, top, width, height)


#: A stand-in for :meth:`Length.resolve`'s ``box`` argument where there is no
#: box: :func:`pixel_size` only ever resolves `px`/`%r`, neither of which reads
#: it.  Never leaks anywhere -- a `%` length that reached it would resolve to
#: zero, which is why :data:`SIZE_UNITS` exists and is enforced upstream.
_UNUSED_BOX = Box(0.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True)
class IntBox:
    """A rectangle snapped to whole pixels -- what reaches generated code."""

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def union(self, other: "IntBox") -> "IntBox":
        x, y = min(self.x, other.x), min(self.y, other.y)
        return IntBox(x, y, max(self.right, other.right) - x, max(self.bottom, other.bottom) - y)

    def inflate(self, by: int) -> "IntBox":
        return IntBox(self.x - by, self.y - by, self.width + 2 * by, self.height + 2 * by)

    def clamp_to(self, width: int, height: int) -> "IntBox":
        x, y = max(0, self.x), max(0, self.y)
        return IntBox(x, y, min(self.right, width) - x, min(self.bottom, height) - y)

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)


#: The nine box positions, as (fraction of width, fraction of height).
ANCHORS: dict[str, tuple[float, float]] = {
    "top_left": (0.0, 0.0),
    "top": (0.5, 0.0),
    "top_right": (1.0, 0.0),
    "left": (0.0, 0.5),
    "center": (0.5, 0.5),
    "right": (1.0, 0.5),
    "bottom_left": (0.0, 1.0),
    "bottom": (0.5, 1.0),
    "bottom_right": (1.0, 1.0),
}
