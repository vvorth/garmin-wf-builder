r"""Icon sizing, resolution and the weather-condition lookup.

The catalogue *data* -- every name, its codepoint, its description -- lives in
:mod:`wfb.icon_catalog`, imported here as :data:`CATALOG`. This module is
everything you do *with* that data: resolving a name (or a raw pasted glyph)
to a codepoint, baking it at the right size, keying the generated font
resource, and mapping a `Toybox.Weather.CONDITION_*` value to a catalogue
name. See :mod:`wfb.icon_catalog`'s own docstring for why the two are split
and for the `\uXXXX` escape convention every codepoint in this project follows.

**Weather is an icon, not a special case, except for the one piece of logic
that has to be.** Turning a raw `Weather.CONDITION_*` value into a drawn glyph
is two independent steps, kept independent on both sides of the build:

1. **Which name?** :data:`GARMIN_WEATHER_CONDITION_ICON` maps the 54 raw
   values to a :data:`wfb.icon_catalog.CATALOG` name -- pure lookup, no font
   knowledge at all. Its on-device twin is `WfbWeather.mc`'s `chooseIcon()`,
   a hand-written barrel function (the mapping is fixed and shared across
   every design, the same reasoning that keeps `WfbArc.mc`/`WfbTime.mc`
   hand-written) that returns a *name*, never a glyph.
2. **Which glyph for that name?** :func:`weather_icon_for_condition` (here)
   and `source/IconGlyphs.mc`'s `glyph()` (generated per project by
   :mod:`wfb.emit.monkeyc` directly from :data:`wfb.icon_catalog.CATALOG`, not
   hand-written) both just index the one catalogue by name.

An earlier version collapsed both steps into `WfbWeather.mc` itself, which
meant a raw glyph character embedded directly in that hand-written switch --
a second, parallel table on the Monkey C side that only `wfb.icon_catalog`
was supposed to be the one copy of. Splitting "which name" from "which glyph"
on the device, the same way the Python side already split them, removed it:
`WfbWeather.mc` now only ever deals in ASCII catalogue *names*, and every
actual glyph character in the whole project -- static icon or weather
condition alike -- is written exactly once, in `wfb/icon_catalog.py`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from .icon_catalog import CATALOG, Icon
from .units import Axis, Box, Length

#: The vendored font every icon glyph comes from.
FONT_PATH = Path(__file__).resolve().parent / "assets" / "icons" / "SymbolsNerdFont-Regular.ttf"

#: Used only when an icon name failed to resolve, so baking has *something*
#: valid to measure.  Never reaches a real build: an unresolved icon is a build
#: error, and the pipeline stops before this element is baked or drawn.
FALLBACK_CODEPOINT = "\uf128"  # preview:  (fa-question)




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
    """Every character the vendored font can draw -- the raw-glyph escape hatch's
    universe, and what :func:`resolve_codepoint` checks a literal character against.

    Includes codepoints above the Basic Multilingual Plane (Material Design
    Icons, used by this catalogue, lives entirely above it). An earlier version
    of this function excluded them out of caution about how Monkey C would
    handle a UTF-16 surrogate pair. Checked since, against the real toolchain:
    `monkeyc` compiles such a character in a string literal without complaint,
    but the **resource compiler's `filter` attribute** on a `<font>` element --
    which is Java, and parses that attribute as UTF-16 code units -- splits the
    character into two surrogate halves that match no real glyph and fails the
    build with "does not have characters in the given filter". That is a real,
    reproduced compile error, not a guess. `wfb.emit.resources.build_bundle`
    works around it by omitting `filter` for any font that needs a glyph above
    U+FFFF; the `.fnt` itself, which this project's own baking already subsets
    correctly, is authoritative regardless. See that function for the detail.
    """
    from fontTools.ttLib import TTFont

    with TTFont(str(FONT_PATH), lazy=True) as font:
        cmap = font.getBestCmap()
    return frozenset(chr(cp) for cp in cmap)


#: Lengths an icon's `size:` may use.  `%` (of the parent box) and `pt`
#: (of an element's own font) both depend on context that is not yet known when
#: the icon font is baked, before layout runs -- see `pixel_size` below.  `%r`
#: and `px` do not: a fraction of the screen's minor radius, or a device pixel
#: count, mean the same thing regardless of where the icon sits.
SIZE_UNITS = ("px", "%r")


def pixel_size(length: Length | None, minor_radius: float, default: float = 24.0) -> int:
    """Resolve an icon's `size:` to its target *visual* height, in device pixels.

    Deliberately independent of any parent box -- callable before layout, so
    the icon font can be baked once per distinct size before the elements that
    use it are placed.  This is why `size:` is restricted to `px`/`%r`
    (enforced in `wfb.ir`): both resolve from `minor_radius` alone.

    This is the height the glyph should visibly draw at, not necessarily the
    font's own nominal em-square size it gets baked at -- see `bake_size`,
    which turns this target into the actual size passed to the font rasteriser.
    """
    if length is None:
        return round(default)
    return max(1, round(length.resolve(box=_UNUSED_BOX, axis=Axis.MINOR, minor_radius=minor_radius)))


_UNUSED_BOX = Box(0.0, 0.0, 0.0, 0.0)


def _ink_height(codepoint: str, nominal_size: int) -> int:
    """The rendered glyph's own ink-bbox height, baked at `nominal_size` -- the
    font's raw em-square size, exactly what `wfb.fonts.bmfont.bake` passes to
    `PIL.ImageFont.truetype`. Used by `bake_size` to find the nominal size
    that makes a glyph's *visual* height match a declared `size:`.
    """
    from PIL import ImageFont

    font = ImageFont.truetype(str(FONT_PATH), max(1, nominal_size))
    bbox = font.getbbox(codepoint)
    if bbox is None:
        return 0
    _, top, _, bottom = bbox
    return max(0, bottom - top)


@lru_cache(maxsize=None)
def bake_size(codepoint: str, target_px: int) -> int:
    """The font nominal size to bake `codepoint` at so its own ink-bbox height
    ends up as close as possible to `target_px`.

    Needed because the vendored font aggregates icon sets with very different
    internal padding conventions inside their em-square: at the same nominal
    font size, a Material Design Icons glyph's ink is noticeably shorter than
    a Font Awesome or Codicons one was (confirmed by measurement: MDI glyphs
    typically fill 77-90% of the nominal size vertically, the older Font
    Awesome/Codicons choices 81-94%). Baking every icon at its declared size
    as a literal font size, as an earlier version of this module did, made
    `size:` mean a different *visual* size depending on which icon set
    happened to supply a name's glyph -- an author moving `heart` from a
    Font Awesome glyph to a Material Design one saw it shrink by ~15-20% at
    the same declared `size:`, with no way to tell why from the YAML alone.
    Compensating here makes `size:` honest: the same declared value produces
    the same rendered height regardless of which of the font's ~10 aggregated
    icon sets contributed the glyph.

    The compensated size is *searched*, not computed from a single measured
    ratio, because FreeType's hinting rounds glyph outlines differently at
    the very small sizes (single-digit to low-teens pixels) real designs
    actually bake icons at -- a ratio measured at a large reference size does
    not reliably predict the exact best integer nominal size down there. The
    search window is small: no glyph in this font is lopsided enough to need
    it any wider, and this only runs once per distinct (codepoint, size:) pair
    per build, cached for the process.
    """
    if target_px <= 0:
        return 1
    reference = 512
    ink_at_reference = _ink_height(codepoint, reference)
    ratio = ink_at_reference / reference if ink_at_reference else 1.0
    guess = max(1, round(target_px / ratio))

    best_size, best_ink = guess, _ink_height(codepoint, guess)
    best_diff = abs(best_ink - target_px)
    for candidate in range(max(1, guess - 4), guess + 9):
        if candidate == guess:
            continue
        ink = _ink_height(codepoint, candidate)
        diff = abs(ink - target_px)
        # On a tie, prefer the candidate that does not undershoot: rendering
        # a hair too big is a much smaller authoring surprise than the "too
        # small" report that motivated this function in the first place.
        better = diff < best_diff or (diff == best_diff and ink >= target_px > best_ink)
        if better:
            best_size, best_ink, best_diff = candidate, ink, diff
    return best_size


#: Maps a Length's unit to a fragment safe inside a Monkey C identifier.
_UNIT_WORD = {"%r": "pctr", "%": "pct", "px": "px", "pt": "pt"}

#: The tag `font_key`/`wfb.emit.resources.icon_font_specs` use in place of a
#: single codepoint for a dynamic (`icon_for:`) icon's shared, multi-glyph
#: font -- see `WEATHER_GLYPH_SET` below.
DYNAMIC_WEATHER_TAG = "weather"


def font_key(length: Length | None, glyph_key: str) -> str:
    """The synthetic font name for every icon declared at this `size:` and glyph.

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

    Also keyed by `glyph_key`: two icons declared at the same `size:` do not
    necessarily bake at the same nominal font size any more (see `bake_size`),
    so they cannot always share one font resource the way they could when
    `size:` and nominal size were the same number. Safe for the same
    device-independence reason as the length itself -- neither a codepoint
    nor `DYNAMIC_WEATHER_TAG` varies per device, only the resolved pixel value
    fed into `bake_size` does.

    `glyph_key` is either a single character (a static icon's own codepoint)
    or `DYNAMIC_WEATHER_TAG` (a dynamic icon's shared, multi-glyph font) --
    never an arbitrary string, so there is no collision to guard against
    between the two forms.
    """
    if length is None:
        unit_value = "default"
    else:
        unit = _UNIT_WORD[length.unit]
        value = f"{length.value:g}".replace(".", "p").replace("-", "neg")
        unit_value = f"{value}{unit}"
    glyph_id = f"u{ord(glyph_key):x}" if len(glyph_key) == 1 else glyph_key
    return f"icon_{unit_value}_{glyph_id}"


# ============================================================================
# Weather condition lookup
#
# Not wired to a live data source at binding time in every sense -- an author
# can already write `icon: weather_rain` today as a static placeholder, and
# `icon_for: weather.condition` (wfb/ir.py) binds one of these dynamically, at
# runtime -- see docs/format.md's `icon_for` section.
#
# The raw values are `Toybox.Weather.CONDITION_*`, cited from
# `doc/Toybox/Weather.html` in the SDK (API level 3.2.0, all of them). Spelled
# out as a literal 0-53 table rather than referencing the constants by name so
# this module stays pure Python (built and tested on the host, no `Toybox`
# needed) and so a device whose SDK build is missing a rarer constant still has
# a complete table to read.
# ============================================================================

#: `Toybox.Weather.CONDITION_*` (`doc/Toybox/Weather.html`, API 3.2.0) mapped to
#: a `CATALOG` name. Every raw value 0-53 is listed explicitly, so a gap is a
#: bug you can see, not a silent fallback.
GARMIN_WEATHER_CONDITION_ICON: dict[int, str] = {
    0: "weather_sunny",  # CONDITION_CLEAR
    1: "weather_cloudy_light",  # CONDITION_PARTLY_CLOUDY
    2: "weather_cloudy_heavy",  # CONDITION_MOSTLY_CLOUDY
    3: "weather_rain",  # CONDITION_RAIN
    4: "weather_snow",  # CONDITION_SNOW
    5: "weather_windy",  # CONDITION_WINDY
    6: "weather_thunderstorm",  # CONDITION_THUNDERSTORMS
    7: "weather_wintry_mix",  # CONDITION_WINTRY_MIX
    8: "weather_fog",  # CONDITION_FOG
    9: "weather_haze",  # CONDITION_HAZY
    10: "weather_hail",  # CONDITION_HAIL
    11: "weather_rain_heavy",  # CONDITION_SCATTERED_SHOWERS
    12: "weather_thunderstorm_showers",  # CONDITION_SCATTERED_THUNDERSTORMS
    13: "weather_rain",  # CONDITION_UNKNOWN_PRECIPITATION -- no dedicated glyph; rain reads closest
    14: "weather_rain_light",  # CONDITION_LIGHT_RAIN
    15: "weather_rain_heavy",  # CONDITION_HEAVY_RAIN
    16: "weather_snow",  # CONDITION_LIGHT_SNOW
    17: "weather_snow_heavy",  # CONDITION_HEAVY_SNOW
    18: "weather_wintry_mix",  # CONDITION_LIGHT_RAIN_SNOW
    19: "weather_wintry_mix",  # CONDITION_HEAVY_RAIN_SNOW
    20: "weather_cloudy",  # CONDITION_CLOUDY
    21: "weather_wintry_mix",  # CONDITION_RAIN_SNOW
    22: "weather_sunny_overcast",  # CONDITION_PARTLY_CLEAR
    23: "weather_sunny_overcast",  # CONDITION_MOSTLY_CLEAR
    24: "weather_rain_light",  # CONDITION_LIGHT_SHOWERS
    25: "weather_rain_heavy",  # CONDITION_SHOWERS
    26: "weather_rain_heavy",  # CONDITION_HEAVY_SHOWERS
    27: "weather_rain_light",  # CONDITION_CHANCE_OF_SHOWERS
    28: "weather_lightning",  # CONDITION_CHANCE_OF_THUNDERSTORMS
    29: "weather_fog",  # CONDITION_MIST
    30: "weather_dust",  # CONDITION_DUST
    31: "weather_rain_light",  # CONDITION_DRIZZLE
    32: "weather_tornado",  # CONDITION_TORNADO
    33: "weather_smoke",  # CONDITION_SMOKE
    34: "weather_ice",  # CONDITION_ICE
    35: "weather_sandstorm",  # CONDITION_SAND
    36: "weather_strong_wind",  # CONDITION_SQUALL
    37: "weather_sandstorm",  # CONDITION_SANDSTORM
    38: "weather_volcano",  # CONDITION_VOLCANIC_ASH
    39: "weather_haze",  # CONDITION_HAZE
    40: "weather_sunny_overcast",  # CONDITION_FAIR
    41: "weather_hurricane",  # CONDITION_HURRICANE
    42: "weather_hurricane_warning",  # CONDITION_TROPICAL_STORM
    43: "weather_snow",  # CONDITION_CHANCE_OF_SNOW
    44: "weather_wintry_mix",  # CONDITION_CHANCE_OF_RAIN_SNOW
    45: "weather_rain",  # CONDITION_CLOUDY_CHANCE_OF_RAIN
    46: "weather_snow",  # CONDITION_CLOUDY_CHANCE_OF_SNOW
    47: "weather_wintry_mix",  # CONDITION_CLOUDY_CHANCE_OF_RAIN_SNOW
    48: "weather_snow",  # CONDITION_FLURRIES
    49: "weather_sleet",  # CONDITION_FREEZING_RAIN
    50: "weather_sleet",  # CONDITION_SLEET
    51: "weather_snow",  # CONDITION_ICE_SNOW
    52: "weather_cloudy_light",  # CONDITION_THIN_CLOUDS -- lighter than CLOUDY(20)
    53: "weather_unknown",  # CONDITION_UNKNOWN
}


def weather_icon_for_condition(condition: int | None, *, night: bool = False) -> str:
    """The codepoint for a `Weather.CONDITION_*` value.

    `night` selects a night-drawn variant where one exists in the font and
    falls back to the day glyph otherwise -- there is no sensible "night dust
    storm" icon, so dust, for instance, does not change. `condition=None` (the
    API returns null when no forecast is available) maps to the same "unknown"
    glyph as the explicit `CONDITION_UNKNOWN` value.
    """
    name = GARMIN_WEATHER_CONDITION_ICON.get(condition, "weather_unknown") \
        if condition is not None else "weather_unknown"
    if night:
        night_name = f"{name}_night"
        if night_name in CATALOG:
            name = night_name
    return CATALOG[name].codepoint


#: Every glyph a *dynamic* weather icon's font must contain (`icon_for:`,
#: `wfb.emit.resources.icon_font_specs`) -- the whole set, since the actual
#: glyph is chosen on-device at runtime (`WfbWeather.mc`) and the font has to
#: already have all of them baked in before that choice is made. A static
#: `icon: weather_rain` keeps baking only the one glyph it names. Day glyphs
#: only, matching `WfbWeather.mc`, which does not resolve night variants yet.
WEATHER_GLYPH_SET: str = "".join(sorted({
    CATALOG[name].codepoint for name in GARMIN_WEATHER_CONDITION_ICON.values()
}))

#: Which glyph `bake_size` is measured against for a dynamic weather icon's
#: one shared nominal font size. The font's 29 weather glyphs are not drawn
#: at a consistent fraction of their em-square -- checked directly, ink height
#: ranges from 40% ("unknown") to 100% ("volcano") of the nominal size across
#: the set -- so no single nominal size makes all of them match a declared
#: `size:` exactly, the same tension `bake_size` exists to solve for a single
#: glyph but genuinely cannot solve for 29 sharing one font. "rain" sits in
#: the largest tight cluster (12 of 29 glyphs land within a few percent of it
#: -- rain, snow, thunderstorm, hail, sleet, lightning, volcano and more), so
#: baking against it puts the common conditions close to the declared size
#: and leaves the rarer ones (dust, sandstorm, unknown, ...) smaller rather
#: than larger -- a legible-but-smaller rare glyph beats a common one that
#: overflows its box.
WEATHER_BAKE_REFERENCE_GLYPH: str = CATALOG["weather_rain"].codepoint


# ============================================================================
# Data-source-to-icon aliases
#
# The most commonly-paired icon for a catalogue source in wfb/catalog.py, so a
# design (or a future auto-suggest feature) does not have to re-derive "which
# icon goes with activity.floors_climbed" from scratch. Adjust freely -- this
# is a default, not a constraint the compiler enforces.
# ============================================================================

METRIC_ICON: dict[str, str] = {
    "activity.steps": "steps",
    "activity.calories": "flame",
    "activity.distance": "distance",
    "activity.floors_climbed": "floors",
    "heart_rate.current": "heart",
    "system.battery": "battery",
    "system.battery_in_days": "battery",
    "system.charging": "battery",
    "device.do_not_disturb": "dnd",
    "device.alarm_count": "alarm",
    "device.notification_count": "notification",
    "device.phone_connected": "phone",
}


def icon_for_source(source_path: str) -> Icon | None:
    """The catalogue icon conventionally paired with a data-source path, if any."""
    name = METRIC_ICON.get(source_path)
    return CATALOG.get(name) if name else None
