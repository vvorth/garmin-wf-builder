"""The icon catalogue.

An icon is a single glyph from a vendored icon font
(``wfb/assets/icons/SymbolsNerdFont-Regular.ttf`` -- see the README there for
what it is and its licensing), baked into a BMFont sheet at build time by the
same pipeline that bakes an author's own custom text font
(:mod:`wfb.fonts.bmfont`).  Drawing an icon is therefore drawing text: one
``drawText`` call against a baked bitmap font, exactly like any other bound
text element.  Nothing is drawn from primitives (no ``fillCircle`` /
``fillPolygon`` calls hand-written per icon), which is what earlier versions of
this catalogue did -- see git history and CLAUDE.md for why that approach was
replaced: it capped the vocabulary at whatever anyone had hand-drawn, and nothing
stopped an icon meaning the wrong thing (a heart drawn for "do not disturb").

A name in :data:`CATALOG` is the documented, common-case way to reach a glyph.
It is not the only way: :func:`resolve_codepoint` also accepts a single literal
character, checked against the font's own character map -- the same relationship
``color:`` has between a named palette entry and a literal hex value.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .units import Axis, Box, Length

#: The vendored font every icon glyph comes from.
FONT_PATH = Path(__file__).resolve().parent / "assets" / "icons" / "SymbolsNerdFont-Regular.ttf"

#: Used only when an icon name failed to resolve, so baking has *something*
#: valid to measure.  Never reaches a real build: an unresolved icon is a build
#: error, and the pipeline stops before this element is baked or drawn.
FALLBACK_CODEPOINT = ""  # fa-question


@dataclass(frozen=True)
class Icon:
    name: str
    codepoint: str  # a single character
    description: str


CATALOG: dict[str, Icon] = {
    icon.name: icon
    for icon in [
        Icon("heart", "", "a heart, for heart rate (Font Awesome fa-heart)"),
        Icon("steps", "", "footprints, for step count (Font Awesome fa-shoe_prints)"),
        Icon("flame", "", "a flame, for calories (Codicons cod-flame)"),
        Icon("alarm", "", "a clock face, for an alarm indicator (Font Awesome fa-clock_o)"),
        Icon("dnd", "", "a bell with a slash, for do-not-disturb (Codicons cod-bell_slash)"),
        Icon("notification", "",
             "a speech bubble; draw a count on top of it (Font Awesome fa-comment)"),
    ]
}


def get(name: str) -> Icon | None:
    return CATALOG.get(name)


def names() -> list[str]:
    return sorted(CATALOG)


def resolve_codepoint(name: str) -> str | None:
    """A catalogue name's glyph, or a literal character the font itself contains.

    The second form is the escape hatch: the font has over ten thousand glyphs
    and the maintained catalogue only names the common ones, so an author who
    knows the codepoint they want (from
    https://www.nerdfonts.com/cheat-sheet, say) can paste the character
    directly rather than waiting for it to be added here.
    """
    icon = CATALOG.get(name)
    if icon is not None:
        return icon.codepoint
    if len(name) == 1 and ord(name) > 0x7F and name in _available_glyphs():
        return name
    return None


@lru_cache(maxsize=1)
def _available_glyphs() -> frozenset[str]:
    from fontTools.ttLib import TTFont

    with TTFont(str(FONT_PATH), lazy=True) as font:
        cmap = font.getBestCmap()
    # Codepoints above the Basic Multilingual Plane need a UTF-16 surrogate
    # pair to represent in some contexts and have not been exercised through
    # the Garmin toolchain; the catalogue itself only uses BMP codepoints; see
    # docs/limitations.md.
    return frozenset(chr(cp) for cp in cmap if cp < 0x10000)


#: Lengths an icon's `size:` may use.  `%` (of the parent box) and `pt`
#: (of an element's own font) both depend on context that is not yet known when
#: the icon font is baked, before layout runs -- see `pixel_size` below.  `%r`
#: and `px` do not: a fraction of the screen's minor radius, or a device pixel
#: count, mean the same thing regardless of where the icon sits.
SIZE_UNITS = ("px", "%r")


def pixel_size(length: Length | None, minor_radius: float, default: float = 24.0) -> int:
    """Resolve an icon's `size:` to device pixels.

    Deliberately independent of any parent box -- callable before layout, so
    the icon font can be baked once per distinct size before the elements that
    use it are placed.  This is why `size:` is restricted to `px`/`%r`
    (enforced in `wfb.ir`): both resolve from `minor_radius` alone.
    """
    if length is None:
        return round(default)
    return max(1, round(length.resolve(box=_UNUSED_BOX, axis=Axis.MINOR, minor_radius=minor_radius)))


_UNUSED_BOX = Box(0.0, 0.0, 0.0, 0.0)


#: Maps a Length's unit to a fragment safe inside a Monkey C identifier.
_UNIT_WORD = {"%r": "pctr", "%": "pct", "px": "px", "pt": "pt"}


def font_key(length: Length | None) -> str:
    """The synthetic font name for every icon declared at this `size:`.

    Keyed by the *declared* length, not the pixel size it resolves to --
    deliberately, because the generated view class is shared across every
    target device (one `drawXxx` method, one set of `Rez.Fonts.*` references)
    while the resolved pixel size differs per device (`8%r` is a different
    pixel count on a 260px and a 280px screen).  This is exactly the
    custom-font relationship: a stable name whose *baked content* varies per
    device.  Keying by the resolved pixel value instead would give two
    devices with different screens two different symbol names for what the
    generated code treats as one font field -- an ``Undefined symbol``
    compile error on every device but the one the view happened to be
    generated from.
    """
    if length is None:
        return "icon_default"
    unit = _UNIT_WORD[length.unit]
    value = f"{length.value:g}".replace(".", "p").replace("-", "neg")
    return f"icon_{value}{unit}"
