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

    def rounded(self) -> "IntBox":
        left, top = round(self.x), round(self.y)
        return IntBox(left, top, round(self.right) - left, round(self.bottom) - top)


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
