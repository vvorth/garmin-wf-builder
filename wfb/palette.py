"""Colour parsing and the 64-colour MIP palette rule.

On a 64-colour panel each channel must be one of ``0x00``, ``0x55``, ``0xAA`` or
``0xFF``; anything else is dithered by the firmware and looks grainy
(ADR 0006 4, lint check 3).  The check is exact arithmetic against the device's
documented palette size -- it is a warning, not an error, because a deliberate
dithered colour is a legitimate choice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")
_SHORT_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3})$")

#: The four legal channel values on a 64-colour device.
MIP64_LEVELS = (0x00, 0x55, 0xAA, 0xFF)


class ColorError(ValueError):
    pass


@dataclass(frozen=True)
class Color:
    r: int
    g: int
    b: int

    @classmethod
    def parse(cls, raw: object, *, what: str = "color") -> "Color":
        if isinstance(raw, Color):
            return raw
        if isinstance(raw, int) and not isinstance(raw, bool):
            return cls((raw >> 16) & 0xFF, (raw >> 8) & 0xFF, raw & 0xFF)
        if not isinstance(raw, str):
            raise ColorError(f"{what}: expected a colour such as '#FF8000', got {raw!r}")
        m = _HEX_RE.match(raw.strip())
        if m:
            v = int(m.group(1), 16)
            return cls((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF)
        m = _SHORT_HEX_RE.match(raw.strip())
        if m:
            d = m.group(1)
            return cls(int(d[0] * 2, 16), int(d[1] * 2, 16), int(d[2] * 2, 16))
        raise ColorError(f"{what}: {raw!r} is not a colour.  Use '#RRGGBB' or '#RGB'")

    @property
    def value(self) -> int:
        return (self.r << 16) | (self.g << 8) | self.b

    def as_monkeyc(self) -> str:
        return f"0x{self.value:06X}"

    def is_palette_legal(self, display_colors: int | None) -> bool:
        """``True`` when the panel can show this colour without dithering."""
        if display_colors is None:
            return True  # not checked -- see Device.display_colors
        if display_colors >= 65536:
            return True
        if display_colors == 64:
            return all(c in MIP64_LEVELS for c in (self.r, self.g, self.b))
        return True  # no rule known for this palette size; do not guess

    def nearest_legal(self, display_colors: int | None) -> "Color":
        if display_colors != 64:
            return self
        snap = lambda c: min(MIP64_LEVELS, key=lambda level: abs(level - c))  # noqa: E731
        return Color(snap(self.r), snap(self.g), snap(self.b))

    def relative_luminance(self) -> float:
        """WCAG relative luminance, for the contrast lint."""

        def channel(c: int) -> float:
            s = c / 255.0
            return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

        return 0.2126 * channel(self.r) + 0.7152 * channel(self.g) + 0.0722 * channel(self.b)

    def contrast_ratio(self, other: "Color") -> float:
        a, b = self.relative_luminance(), other.relative_luminance()
        lo, hi = min(a, b), max(a, b)
        return (hi + 0.05) / (lo + 0.05)

    def __str__(self) -> str:
        return f"#{self.value:06X}"
