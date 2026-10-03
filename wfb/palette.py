"""Colour parsing and the palette rules.

On a 64-colour panel each channel must be one of ``0x00``, ``0x55``, ``0xAA`` or
``0xFF``; anything else is dithered by the firmware and looks grainy
(ADR 0006 4, lint check 3).  The check is exact arithmetic against the device's
documented palette size -- it is a warning, not an error, because a deliberate
dithered colour is a legitimate choice.

On a 2-colour panel (the Instinct family) only black and white are safe: the
device files' own `compiler.json` palette is exactly those two, and whatever
the firmware does with any other colour is unverified (research 16 §5).  The
nearest safe colour is the one with the lower contrast ratio against it --
the same luminance measure the contrast lint uses.  8- and 14-colour panels
have no known rule, and 65,536 colours need none.

Both rules are tables here (`MIP64_SNAP`, `MONO_LUMINANCE`), which
`Color.nearest_legal` and `wfb.preview`'s per-pixel snap both read, so a
warning's "nearest" colour is exactly what the preview draws.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")
_SHORT_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3})$")

#: The four legal channel values on a 64-colour device.
MIP64_LEVELS = (0x00, 0x55, 0xAA, 0xFF)

#: The 64-colour rule as a table: each channel value's nearest legal level.
#: The rule is per channel, so this one table is the whole rule, for
#: `Color.nearest_legal(64)` and for the preview's per-pixel snap alike.
MIP64_SNAP = bytes(min(MIP64_LEVELS, key=lambda level: abs(level - value))
                   for value in range(256))

#: Rec. 709 luminance weights, red, green, blue (`Color.relative_luminance`).
LUMINANCE_WEIGHTS = (0.2126, 0.7152, 0.0722)


#: The 64 colours a MIP panel shows, named: ``(name, "#RRGGBB", label)``.
#: The names are apps.bliemel.net/colors' (both of its "Green"s are kept,
#: the darker as `dark_green`), in that page's order: white to black, one
#: channel stepping at a time.  `wfb new -t palette` and
#: `docs/guide/mip-palette.md` list the same rows (`tests/test_palette.py`),
#: and the editor offers them by name (`wfb.studio.inspect.vocabulary`).
MIP64_NAMED: tuple[tuple[str, str, str], ...] = (
    ("white", "#FFFFFF", "White"),
    ("shalimar", "#FFFFAA", "Shalimar"),
    ("laser_lemon", "#FFFF55", "Laser Lemon"),
    ("yellow", "#FFFF00", "Yellow"),
    ("lavender_rose", "#FFAAFF", "Lavender Rose"),
    ("sundown", "#FFAAAA", "Sundown"),
    ("texas_rose", "#FFAA55", "Texas Rose"),
    ("web_orange", "#FFAA00", "Web Orange"),
    ("pink_flamingo", "#FF55FF", "Pink Flamingo"),
    ("brilliant_rose", "#FF55AA", "Brilliant Rose"),
    ("sunset_orange", "#FF5555", "Sunset Orange"),
    ("international_orange", "#FF5500", "International Orange"),
    ("magenta_fuchsia", "#FF00FF", "Magenta Fuchsia"),
    ("hollywood_cerise", "#FF00AA", "Hollywood Cerise"),
    ("razzmatazz", "#FF0055", "Razzmatazz"),
    ("red", "#FF0000", "Red"),
    ("pale_turquoise", "#AAFFFF", "Pale Turquoise"),
    ("mint_green", "#AAFFAA", "Mint Green"),
    ("conifer", "#AAFF55", "Conifer"),
    ("spring_bud", "#AAFF00", "Spring Bud"),
    ("perano", "#AAAAFF", "Perano"),
    ("silver_chalice", "#AAAAAA", "Silver Chalice"),
    ("olive_green", "#AAAA55", "Olive Green"),
    ("citrus", "#AAAA00", "Citrus"),
    ("medium_purple", "#AA55FF", "Medium Purple"),
    ("violet_blue", "#AA55AA", "Violet Blue"),
    ("apple_blossom", "#AA5555", "Apple Blossom"),
    ("rust", "#AA5500", "Rust"),
    ("electric_violet", "#AA00FF", "Electric Violet"),
    ("dark_magenta", "#AA00AA", "Dark Magenta"),
    ("jazzberry_jam", "#AA0055", "Jazzberry Jam"),
    ("bright_red", "#AA0000", "Bright Red"),
    ("baby_blue", "#55FFFF", "Baby Blue"),
    ("medium_aquamarine", "#55FFAA", "Medium Aquamarine"),
    ("screamin_green", "#55FF55", "Screamin' Green"),
    ("bright_green", "#55FF00", "Bright Green"),
    ("cornflower_blue", "#55AAFF", "Cornflower Blue"),
    ("cadet_blue", "#55AAAA", "Cadet Blue"),
    ("fruit_salad", "#55AA55", "Fruit Salad"),
    ("kelly_green", "#55AA00", "Kelly Green"),
    ("neon_blue", "#5555FF", "Neon Blue"),
    ("rich_blue", "#5555AA", "Rich Blue"),
    ("emperor", "#555555", "Emperor"),
    ("verdun_green", "#555500", "Verdun Green"),
    ("electric_indigo", "#5500FF", "Electric Indigo"),
    ("indigo", "#5500AA", "Indigo"),
    ("tyrian_purple", "#550055", "Tyrian Purple"),
    ("maroon", "#550000", "Maroon"),
    ("aqua", "#00FFFF", "Aqua"),
    ("medium_green", "#00FFAA", "Medium Green"),
    ("malachite", "#00FF55", "Malachite"),
    ("green", "#00FF00", "Green"),
    ("azure_radiance", "#00AAFF", "Azure Radiance"),
    ("persian_green", "#00AAAA", "Persian Green"),
    ("pigment_green", "#00AA55", "Pigment Green"),
    ("japanese_laurel", "#00AA00", "Japanese Laurel"),
    ("navy_blue", "#0055FF", "Navy Blue"),
    ("cobalt", "#0055AA", "Cobalt"),
    ("mosque", "#005555", "Mosque"),
    ("dark_green", "#005500", "Dark Green"),
    ("blue", "#0000FF", "Blue"),
    ("midnight_blue", "#0000AA", "Midnight Blue"),
    ("navy", "#000055", "Navy"),
    ("black", "#000000", "Black"),
)


def mip64_name(value: str) -> str | None:
    """The MIP name of a ``#RRGGBB`` value, or ``None`` when the colour is
    not one of the 64."""
    return _MIP64_BY_VALUE.get(value.upper())


_MIP64_BY_VALUE = {hex_: name for name, hex_, _ in MIP64_NAMED}

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
        """``True`` when the panel is known to show this colour as written:
        the 64-colour MIP rule, or black/white on a 2-colour panel.  No rule
        is guessed for any other size (:func:`has_palette_rule`)."""
        if display_colors == 64:
            return all(c in MIP64_LEVELS for c in (self.r, self.g, self.b))
        if display_colors == 2:
            return self in (BLACK, WHITE)
        return True

    def nearest_legal(self, display_colors: int | None) -> "Color":
        if display_colors == 64:
            return Color(MIP64_SNAP[self.r], MIP64_SNAP[self.g], MIP64_SNAP[self.b])
        if display_colors == 2:
            units = sum(table[c] for table, c in zip(MONO_LUMINANCE, (self.r, self.g, self.b)))
            return WHITE if units > MONO_THRESHOLD else BLACK
        return self

    def relative_luminance(self) -> float:
        """WCAG relative luminance -- Rec. 709 primaries over sRGB-degamma'd
        channels -- used by the contrast lint and, since it is the same
        "fraction of full white" figure Garmin's unpublished AOD rule wants
        (research 11 §1.2), by the AOD burn-in lint too
        (`wfb.lint.check_aod_burn_in`)."""
        red, green, blue = LUMINANCE_WEIGHTS
        return (red * srgb_channel_to_linear(self.r)
                + green * srgb_channel_to_linear(self.g)
                + blue * srgb_channel_to_linear(self.b))

    def contrast_ratio(self, other: "Color") -> float:
        a, b = self.relative_luminance(), other.relative_luminance()
        lo, hi = min(a, b), max(a, b)
        return (hi + 0.05) / (lo + 0.05)

    def __str__(self) -> str:
        return f"#{self.value:06X}"

    def dim(self, num: int, den: int) -> "Color":
        """Scale this colour's luminance by ``num/den`` (`aod: {dim: ...}`):
        each channel times ``num/den``, rounded to the
        nearest integer with :func:`dim_channel`'s own plain integer
        arithmetic, never a float -- see that function's docstring for why.
        """
        return Color(dim_channel(self.r, num, den), dim_channel(self.g, num, den),
                     dim_channel(self.b, num, den))


BLACK = Color(0x00, 0x00, 0x00)
WHITE = Color(0xFF, 0xFF, 0xFF)

#: The relative luminance at which a colour's contrast ratio against black
#: equals its ratio against white, (Y + 0.05) / 0.05 = 1.05 / (Y + 0.05):
#: above it the colour is nearer white on a 2-colour panel, at or below it
#: nearer black.  About 0.179.  Applied as :data:`MONO_THRESHOLD`.
MONO_CROSSOVER = math.sqrt(1.05 * 0.05) - 0.05


def has_palette_rule(display_colors: int | None) -> bool:
    """Whether :meth:`Color.is_palette_legal` can answer for this palette
    size: 2 and 64 have a rule, 65,536 needs none.  8, 14 and an unknown
    size have none, and are reported "not checked"."""
    return display_colors in (2, 64) or (display_colors is not None and display_colors >= 65536)


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


#: Relative luminance 1.0 in the integer units of :data:`MONO_LUMINANCE`.
MONO_SCALE = 65535

#: The 2-colour rule as tables: each channel value's share of relative
#: luminance, in 1/:data:`MONO_SCALE` units, one table per channel.  A
#: colour is nearer white when its three shares sum above
#: :data:`MONO_THRESHOLD`.  Integers, so `Color.nearest_legal(2)` and the
#: preview, which sums the same tables over a whole image, give the same
#: answer for every colour, the ones at the crossover included.
MONO_LUMINANCE: tuple[tuple[int, ...], ...] = tuple(
    tuple(round(weight * srgb_channel_to_linear(value) * MONO_SCALE) for value in range(256))
    for weight in LUMINANCE_WEIGHTS)

#: :data:`MONO_CROSSOVER` in :data:`MONO_LUMINANCE`'s units.
MONO_THRESHOLD = round(MONO_CROSSOVER * MONO_SCALE)


def dim_channel(value: int, num: int, den: int) -> int:
    """Scale one 0-255 channel by ``num/den``, rounded to the nearest integer
    (ties up), with only integer arithmetic (`aod: {dim: ...}`).

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
