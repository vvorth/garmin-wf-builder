r"""Icon sizing, resolution and the weather-condition lookup.

The catalogue *data* -- every name, its codepoint, its description -- lives in
:mod:`wfb.icon_catalog`, imported here as :data:`CATALOG`. This module is
everything you do *with* that data: resolving a name or a ``U+XXXX``
codepoint to a glyph, baking it at the right size, keying the generated font
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

import re
from functools import lru_cache
from pathlib import Path

from .icon_catalog import CATALOG, Icon
from .units import Length

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


#: `glyph:`'s accepted spelling -- the Unicode standard's own notation.
#: Deliberately strict: `U+F0BC` is greppable, reviewable in a diff, and
#: survives copy-paste, none of which is true of the bare character `icon:`
#: also accepts (that one is invisible in most editors, which is the same
#: hazard `wfb/icon_catalog.py`'s module docstring warns about for this
#: project's own source).
_CODEPOINT_RE = re.compile(r"^[Uu]\+([0-9A-Fa-f]{1,6})$")


def parse_codepoint(text: str) -> str | None:
    """``"U+F0BC"`` -> the character, or ``None`` if it is not that notation.

    Returning ``None`` for a non-match rather than raising lets the caller
    tell "this is not a codepoint spelling" apart from "this codepoint is not
    in the font", which are different mistakes and deserve different
    diagnostics.
    """
    match = _CODEPOINT_RE.match(text.strip())
    if match is None:
        return None
    try:
        return chr(int(match.group(1), 16))
    except (ValueError, OverflowError):
        return None


def name_for_codepoint(character: str) -> str | None:
    """The catalogue name for a character, if it has one.

    Lets a `glyph:` that duplicates a catalogue entry say so: the name is the
    better spelling, because it keeps meaning if the catalogue ever moves that
    icon to a different codepoint (which it has done -- see `wfb/icons.py`'s
    module docstring on the Font Awesome to Material Design Icons switch).
    """
    for name, icon in CATALOG.items():
        if icon.codepoint == character:
            return name
    return None


def font_has(character: str) -> bool:
    """Is this character in the vendored icon font's own character map?"""
    return character in _available_glyphs()


def resolve_codepoint(name: str) -> str | None:
    """A catalogue name's glyph, or ``None`` if the catalogue does not name it.

    This used to also accept a literal character pasted into the YAML, as the
    escape hatch for the ~10,000 glyphs the maintained catalogue does not name.
    ``glyph: "U+F09B"`` replaced it and is strictly better: the codepoint is
    greppable, visible in a diff, and survives a copy-paste, where the
    character itself renders as a blank box or as nothing at all in most
    editors -- and, worse, a paste that silently fails still parses as valid
    YAML. That is the exact hazard :mod:`wfb.icon_catalog`'s docstring bans
    for this project's own source; there was no reason to keep offering it to
    authors.
    """
    icon = CATALOG.get(name)
    return icon.codepoint if icon is not None else None


@lru_cache(maxsize=1)
def _available_glyphs() -> frozenset[str]:
    """Every character the vendored font can draw -- what :func:`font_has`
    checks a `glyph: "U+XXXX"` codepoint against.

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


# An icon's `size:` and a custom font's `size:` are the *same* declaration
# resolved the *same* way -- `wfb.units.pixel_size` and `wfb.units.SIZE_UNITS`,
# which used to live here and were lifted out when `fonts.<name>.size` gained
# the `Length` spelling an icon already had.  What stays icon-only is
# `bake_size` below; its docstring says why.


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

    **This stays icon-only, on purpose.** `fonts.<name>.size` now accepts the
    same `Length` an icon's `size:` does (`wfb.units.pixel_size` is the one
    shared resolver), and the obvious next step -- normalising a *text* font's
    ink height the same way -- is wrong, for a reason specific to what a font
    is:

    * An icon element draws exactly **one** glyph, placed on its own. There is
      no other character for it to be in proportion with, so "how tall does
      this glyph's ink come out" is the whole of what `size:` can honestly
      mean, and measuring one glyph answers it exactly.
    * A text font draws **many** glyphs against a shared baseline, and their
      *relative* proportions are the typeface. Normalising against a chosen
      reference character would scale the whole face by that one character's
      ink ratio: pick `'0'` and a font whose digits are short but whose caps
      are tall gets silently inflated, its ascenders then overrunning the line
      height the same nominal size still computes. Worse, two fonts declared
      at one `size:` would no longer share a baseline or a line height, which
      is exactly the property a declared size is relied on for when two text
      elements sit in a row.
    * The measurement that motivated this function does not apply either. It
      was a *within-one-file* inconsistency -- the vendored icon font
      aggregates ~10 third-party icon sets with different em-square padding
      conventions, so one file's own glyphs disagree about what a nominal size
      means. An author's text font is one typeface with one such convention;
      nothing inside it is inconsistent for this to correct.

    So a text font's declared size stays the nominal em size handed to the
    rasteriser, and `12px`/`18%r` mean "bake at 12/that many pixels", which is
    also what every existing bare-number `size:` has always meant.
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


def font_key(length: Length | None, glyph_key: str, antialias: bool = False) -> str:
    """The synthetic font name for every icon declared at this `size:`, glyph
    and anti-aliasing setting.

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

    And also keyed by `antialias`: two icons that agree on `size:` and glyph
    but disagree on `antialias:` are two different sheets -- one 1-bit, one an
    8-bit grey ramp -- of the same declared size, so without this in the key
    they would collide into one font resource and whichever icon baked second
    would silently overwrite the other's sheet.  Left out of the key when
    `False` (the default) rather than always appended, so a design that never
    mentions `antialias:` gets byte-identical keys, and therefore byte-
    identical generated output, to before this parameter existed.  Safe to key
    by directly, for the same device-independence reason as the length and the
    glyph: `antialias:` is a design decision an author makes once, not
    something that varies by which screen the face happens to be running on.
    """
    if length is None:
        unit_value = "default"
    else:
        unit = _UNIT_WORD[length.unit]
        value = f"{length.value:g}".replace(".", "p").replace("-", "neg")
        unit_value = f"{value}{unit}"
    glyph_id = f"u{ord(glyph_key):x}" if len(glyph_key) == 1 else glyph_key
    suffix = "_aa" if antialias else ""
    return f"icon_{unit_value}_{glyph_id}{suffix}"


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


# ============================================================================
# Complication-type-to-icon aliases (docs/research/09-data-library-and-config-axes.md §4)
#
# A `type: complication_slot` element draws whichever complication the wearer
# repointed the slot at, and `Complications.Id.getType()` is readable
# on-device regardless of whether the pulled *value* is available -- so the
# icon can be resolved from the type alone, the same "which name, then which
# glyph" split `GARMIN_WEATHER_CONDITION_ICON`/`weather_icon_for_condition`
# already use. This is the "which name" half; `wfb.emit.monkeyc.emit_icon_glyphs`
# is the "which glyph" half, generated straight from `CATALOG` like every other
# dynamic icon.
# ============================================================================

#: `wfb.complications.TYPES` key -> a :data:`CATALOG` name. **Not every one of
#: the 42 types is here, deliberately.** Three reasons a type is left out,
#: each real rather than an oversight:
#:
#: * **The icon would depend on the pulled *value*, not the type.**
#:   `current_weather`/`forecast_weather_*day` report a `Weather.CONDITION_*`
#:   *as their value* -- resolving their icon needs the same
#:   value-to-glyph step `icon_for: weather.condition` already does, which
#:   this element's type-keyed switch has no way to reach without a second,
#:   nested lookup this task does not build. The reading is still drawn as
#:   plain text.
#: * **No catalogue glyph reads unambiguously as that metric.** Reusing an
#:   unrelated icon is a content bug, not a layout bug, and CLAUDE.md already
#:   records one real instance of exactly this mistake (a heart icon
#:   mistakenly standing in for do-not-disturb) -- `body_battery` is not
#:   `battery` (that means device charge), and `pulse_ox` is not `heart`
#:   (blood oxygen, not heart rate). Left unmapped rather than guessed.
#: * **No existing catalogue entry fits at all** (a calendar glyph, a
#:   golf-score glyph, a race-time glyph, ...). Growing the *named* catalogue
#:   for these is future work, the same "grow it as real designs need it"
#:   policy `wfb.icon_catalog`'s own docstring already states -- not
#:   something this table should paper over with an unrelated glyph.
#:
#: An unmapped type simply draws no icon for that slot -- the reading itself
#: still renders normally -- which is a legitimate, documented outcome, not a
#: build error: `docs/format.md`'s `complication_slot` section says so.
COMPLICATION_ICON: dict[str, str] = {
    "battery": "battery",
    "steps": "steps",
    "calories": "flame",
    "floors_climbed": "floors",
    "notification_count": "notification",
    "heart_rate": "heart",
    "weekly_run_distance": "distance",
    "weekly_bike_distance": "distance",
}


def icon_for_complication(type_name: str) -> Icon | None:
    """The catalogue icon conventionally paired with a `wfb.complications.TYPES`
    name, if any -- the reverse direction `COMPLICATION_ICON` records."""
    name = COMPLICATION_ICON.get(type_name)
    return CATALOG.get(name) if name else None
