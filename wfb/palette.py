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
        # Only the 64-colour MIP rule is known; no rule for any other palette
        # size (or an unknown one, `Device.display_colors`) is guessed at.
        if display_colors != 64:
            return True
        return all(c in MIP64_LEVELS for c in (self.r, self.g, self.b))

    def nearest_legal(self, display_colors: int | None) -> "Color":
        if display_colors != 64:
            return self
        def snap(c: int) -> int:
            return min(MIP64_LEVELS, key=lambda level: abs(level - c))

        return Color(snap(self.r), snap(self.g), snap(self.b))

    def relative_luminance(self) -> float:
        """WCAG relative luminance -- Rec. 709 primaries over sRGB-degamma'd
        channels -- used by the contrast lint and, since it is the same
        "fraction of full white" figure Garmin's unpublished AOD rule wants
        (research 11 §1.2, §5), by the AOD burn-in lint too
        (`wfb.lint.check_aod_burn_in`)."""
        return (0.2126 * srgb_channel_to_linear(self.r)
                + 0.7152 * srgb_channel_to_linear(self.g)
                + 0.0722 * srgb_channel_to_linear(self.b))

    def contrast_ratio(self, other: "Color") -> float:
        a, b = self.relative_luminance(), other.relative_luminance()
        lo, hi = min(a, b), max(a, b)
        return (hi + 0.05) / (lo + 0.05)

    def __str__(self) -> str:
        return f"#{self.value:06X}"

    def dim(self, num: int, den: int) -> "Color":
        """Scale this colour's luminance by ``num/den`` (`aod: {dim: ...}`,
        plan 14 slice 3): each channel times ``num/den``, rounded to the
        nearest integer with :func:`dim_channel`'s own plain integer
        arithmetic, never a float -- see that function's docstring for why.
        """
        return Color(dim_channel(self.r, num, den), dim_channel(self.g, num, den),
                     dim_channel(self.b, num, den))


def srgb_channel_to_linear(value: int) -> float:
    """One 0-255 sRGB-encoded channel -> linear 0-1, the sRGB EOTF (the
    piecewise curve WCAG's own relative-luminance formula specifies).
    Factored out of :meth:`Color.relative_luminance` so the contrast lint
    and the AOD burn-in lint (`wfb.lint.check_aod_burn_in`, which builds a
    256-entry lookup table from this same function to score a whole
    rendered frame without a per-pixel gamma call) can never disagree about
    what "linear" means for a channel value.
    """
    s = value / 255.0
    return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4


def dim_channel(value: int, num: int, den: int) -> int:
    """Scale one 0-255 channel by ``num/den``, rounded to the nearest integer
    (ties up), with only integer arithmetic (plan 14 slice 3, `aod: {dim:
    ...}`).

    This exact formula is computed in three places that must agree bit for
    bit: here, in Python, for a build-time-constant colour (a bare hex
    literal or a `palette.<name>` reference -- `Expression.is_constant`,
    pre-dimmed into a second literal at build time, `wfb.emit.monkeyc.
    common._dim_color_code`); in the generated `WfbColor.dim`
    (`runtime-lib/WfbColor.mc`), for a colour whose value is not known until
    the device resolves it (`config.colors.<role>`, or a conditional between
    several colours); and in `wfb.preview`, rendering the same frame on the
    host.  A float would let a channel landing near a `.5` boundary round
    differently across those three -- Python's banker's rounding, this
    platform's own `Math.round`, and 32-bit vs. 64-bit precision could each
    disagree -- so every one of them does this same integer division
    instead, which Monkey C's `/` on two non-negative `Number`s and Python's
    `//` compute identically.
    """
    return max(0, min(255, (value * num + den // 2) // den))


def dim_fraction(dim: float) -> tuple[int, int]:
    """One face's `aod: {dim: ...}` factor (0-1, exclusive of 0), as the
    ``(num, den)`` integer ratio :func:`dim_channel`, the codegen ternary and
    the generated `WfbColor.dim` all share -- a fixed denominator of 1000
    (three decimal digits) is precise enough for a value the schema already
    restricts to 0-1, and, being an integer itself, is exactly representable
    on both sides with no floating-point drift to keep in sync.
    """
    return round(dim * 1000), 1000
