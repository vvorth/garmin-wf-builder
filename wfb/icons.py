"""The icon catalogue.

An icon is a single glyph from a vendored icon font
(``wfb/assets/icons/SymbolsNerdFont-Regular.ttf`` -- see the README there for
what it is and its licensing), baked into a BMFont sheet at build time by the
same pipeline that bakes an author's own custom text font
(:mod:`wfb.fonts.bmfont`).  Drawing an icon is therefore drawing text: one
``drawText`` call against a baked bitmap font, exactly like any other bound
text element.  Nothing is drawn from primitives (no ``fillCircle`` /
``fillPolygon`` calls hand-written per icon), which is what earlier versions of
this catalogue did -- see git history and CLAUDE.md for why that was replaced:
it capped the vocabulary at whatever anyone had hand-drawn, and nothing stopped
an icon meaning the wrong thing (a heart drawn for "do not disturb").

A name in :data:`CATALOG` is the documented, common-case way to reach a glyph.
It is not the only way: :func:`resolve_codepoint` also accepts a single literal
character, checked against the font's own character map -- the same relationship
``color:`` has between a named palette entry and a literal hex value.

Every codepoint below is written as ``\\uXXXX``/``\\U000XXXXX`` rather than
pasted as a raw character on purpose: the actual glyph is invisible in most
editors and terminals (that is the whole reason it needs an icon font), so a
literal escape is what stays readable, greppable, and safe to move between
files without silent corruption -- which matters because this catalogue is
meant to be hand-edited. Every codepoint here was looked up directly against
the vendored font's own cmap (fontTools ``getBestCmap()``), not typed from
memory -- the same "never invent an API" discipline CLAUDE.md asks for Monkey C
symbols applies just as much to which glyph a name actually points at.
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


# Preference, per user direction: prefer a Material Design Icons glyph
# (nf-md, prefix "md-") over other icon sets when one exists and reads at
# least as well at small size -- MDI is the largest, most consistently drawn
# set in the vendored font (7,000+ glyphs, one design language) and, once
# `wfb.emit.resources` stopped putting a `filter=` attribute on any font that
# needs one (see `_available_glyphs` below), there is no longer a reason to
# avoid it.
#
# `steps` is the deliberate exception: MDI's closest equivalents (a walking or
# running figure) read as "activity" or "exercise", not specifically "step
# count", and are less clear at a glance than Font Awesome's two-offset-
# footprints glyph, which was drawn for exactly this. Compared side by side at
# 12-20px before deciding, the same way the original six icons were chosen.
CATALOG: dict[str, Icon] = {
    icon.name: icon
    for icon in [
        Icon("heart", "\U000f02d1", "a heart, for heart rate (Material Design md-heart)"),
        Icon("steps", "",
             "two offset footprints, for step count (Font Awesome fa-shoe_prints -- "
             "kept over MDI's walking/running figures, which read as \"activity\" "
             "rather than \"steps\" at a glance)"),
        Icon("flame", "\U000f0238", "a flame, for calories (Material Design md-fire)"),
        Icon("alarm", "\U000f0020",
             "an alarm clock with bells, for an alarm indicator "
             "(Material Design md-alarm)"),
        Icon("dnd", "\U000f009b",
             "a solid bell with a slash, for do-not-disturb (Material Design "
             "md-bell_off -- a solid glyph reads more reliably than an outline "
             "one at the small sizes a status row uses)"),
        Icon("notification", "\U000f017a",
             "a speech bubble; draw a count on top of it (Material Design md-comment)"),
        Icon("battery", "\U000f0079", "a battery outline (Material Design md-battery)"),
        Icon("floors", "\U000f04cd",
             "a flight of stairs, for floors climbed (Material Design md-stairs)"),
        Icon("distance", "\U000f08f0",
             "a map pin with a distance mark (Material Design md-map_marker_distance)"),
        Icon("phone", "\U000f011c",
             "a phone, for phone-connected status (Material Design md-cellphone)"),
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
    """Every character the vendored font can draw -- the raw-glyph escape hatch's
    universe, and what :func:`resolve_codepoint` checks a literal character against.

    Includes codepoints above the Basic Multilingual Plane (Material Design
    Icons and Weather Icons, both used by this catalogue, live entirely above
    it). An earlier version of this function excluded them out of caution
    about how Monkey C would handle a UTF-16 surrogate pair. Checked since,
    against the real toolchain: `monkeyc` compiles such a character in a string
    literal without complaint, but the **resource compiler's `filter`
    attribute** on a `<font>` element -- which is Java, and parses that
    attribute as UTF-16 code units -- splits the character into two surrogate
    halves that match no real glyph and fails the build with "does not have
    characters in the given filter". That is a real, reproduced compile error,
    not a guess. `wfb.emit.resources.build_bundle` works around it by omitting
    `filter` for any font that needs a glyph above U+FFFF; the `.fnt` itself,
    which this project's own baking already subsets correctly, is authoritative
    regardless. See that function for the detail.
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


# ============================================================================
# Weather icons
#
# Not wired to a live data source yet -- `weather.*` is not in wfb/catalog.py
# (docs/limitations.md records why: no data source exists to bind it to). What
# follows is deliberately just the *mapping*, so it is ready the day a
# `weather.condition` source lands and something needs to turn its value into
# an icon, and so an author can already write `icon: weather_rain` today for a
# static placeholder without waiting for that.
#
# The raw values are `Toybox.Weather.CONDITION_*`, cited from
# `doc/Toybox/Weather.html` in the SDK (API level 3.2.0, all of them). Spelled
# out as a literal 0-53 table rather than referencing the constants by name so
# this module stays pure Python (built and tested on the host, no `Toybox`
# needed) and so a device whose SDK build is missing a rarer constant still has
# a complete table to read.
#
# The glyphs come from the font's dedicated "Weather Icons" set (prefix
# "weather-"), not Material Design Icons' own `md-weather_*` glyphs -- every
# `md-weather_*` glyph lives above the Basic Multilingual Plane, while every
# `weather-*` glyph here does not (confirmed against the font's cmap), and the
# dedicated set also simply has more distinct conditions and day/night pairs
# to choose from. This is the one place in this catalogue where "prefer nf-md"
# loses to a better-fitting alternative set, by design.
# ============================================================================

#: Named weather glyphs, one name per glyph actually used below, so changing
#: the icon for every condition that shares it is a one-line edit here rather
#: than a search-and-replace through `GARMIN_WEATHER_CONDITION_ICON`.
_WEATHER_GLYPH: dict[str, str] = {
    "sunny": "",  # weather-day_sunny
    "sunny_overcast": "",  # weather-day_sunny_overcast
    "cloudy_light": "",  # weather-day_cloudy
    "cloudy": "",  # weather-cloudy
    "cloudy_heavy": "",  # weather-day_cloudy_high
    "fog": "",  # weather-day_fog
    "haze": "",  # weather-day_haze
    "smoke": "",  # weather-smoke
    "dust": "",  # weather-dust
    "sandstorm": "",  # weather-sandstorm
    "rain_light": "",  # weather-day_sprinkle
    "rain": "",  # weather-day_rain
    "rain_heavy": "",  # weather-day_showers
    "snow": "",  # weather-day_snow
    "snow_heavy": "",  # weather-day_snow_wind
    "ice": "",  # weather-snowflake_cold
    "wintry_mix": "",  # weather-day_rain_mix
    "sleet": "",  # weather-day_sleet
    "hail": "",  # weather-day_hail
    "thunderstorm": "",  # weather-day_thunderstorm
    "thunderstorm_showers": "",  # weather-day_storm_showers
    "lightning": "",  # weather-day_lightning
    "windy": "",  # weather-day_windy
    "strong_wind": "",  # weather-strong_wind
    "tornado": "",  # weather-tornado
    "hurricane": "",  # weather-hurricane
    "hurricane_warning": "",  # weather-hurricane_warning
    "volcano": "",  # weather-volcano
    "unknown": "",  # weather-na
}

#: Night variants, for glyph names where the font has a specifically-drawn
#: one. A name not listed here has no distinct night glyph in this font and
#: falls back to the day one -- reasonable for things like dust, strong wind,
#: or a tornado, which do not read differently after dark.
_WEATHER_GLYPH_NIGHT: dict[str, str] = {
    "sunny": "",  # weather-night_clear
    "cloudy_light": "",  # weather-night_alt_partly_cloudy
    "cloudy": "",  # weather-night_alt_cloudy
    "fog": "",  # weather-night_fog
    "rain_light": "",  # weather-night_alt_sprinkle
    "rain": "",  # weather-night_alt_rain
    "rain_heavy": "",  # weather-night_alt_showers
    "snow": "",  # weather-night_alt_snow
    "snow_heavy": "",  # weather-night_snow_wind
    "wintry_mix": "",  # weather-night_alt_rain_mix
    "sleet": "",  # weather-night_alt_sleet
    "hail": "",  # weather-night_alt_hail
    "thunderstorm": "",  # weather-night_alt_thunderstorm
    "thunderstorm_showers": "",  # weather-night_alt_storm_showers
}

#: `Toybox.Weather.CONDITION_*` (`doc/Toybox/Weather.html`, API 3.2.0) mapped to
#: one of the glyph names above. Every raw value 0-53 is listed explicitly, so
#: a gap is a bug you can see, not a silent fallback.
GARMIN_WEATHER_CONDITION_ICON: dict[int, str] = {
    0: "sunny",  # CONDITION_CLEAR
    1: "cloudy_light",  # CONDITION_PARTLY_CLOUDY
    2: "cloudy_heavy",  # CONDITION_MOSTLY_CLOUDY
    3: "rain",  # CONDITION_RAIN
    4: "snow",  # CONDITION_SNOW
    5: "windy",  # CONDITION_WINDY
    6: "thunderstorm",  # CONDITION_THUNDERSTORMS
    7: "wintry_mix",  # CONDITION_WINTRY_MIX
    8: "fog",  # CONDITION_FOG
    9: "haze",  # CONDITION_HAZY
    10: "hail",  # CONDITION_HAIL
    11: "rain_heavy",  # CONDITION_SCATTERED_SHOWERS
    12: "thunderstorm_showers",  # CONDITION_SCATTERED_THUNDERSTORMS
    13: "rain",  # CONDITION_UNKNOWN_PRECIPITATION -- no dedicated glyph; rain reads closest
    14: "rain_light",  # CONDITION_LIGHT_RAIN
    15: "rain_heavy",  # CONDITION_HEAVY_RAIN
    16: "snow",  # CONDITION_LIGHT_SNOW
    17: "snow_heavy",  # CONDITION_HEAVY_SNOW
    18: "wintry_mix",  # CONDITION_LIGHT_RAIN_SNOW
    19: "wintry_mix",  # CONDITION_HEAVY_RAIN_SNOW
    20: "cloudy",  # CONDITION_CLOUDY
    21: "wintry_mix",  # CONDITION_RAIN_SNOW
    22: "sunny_overcast",  # CONDITION_PARTLY_CLEAR
    23: "sunny_overcast",  # CONDITION_MOSTLY_CLEAR
    24: "rain_light",  # CONDITION_LIGHT_SHOWERS
    25: "rain_heavy",  # CONDITION_SHOWERS
    26: "rain_heavy",  # CONDITION_HEAVY_SHOWERS
    27: "rain_light",  # CONDITION_CHANCE_OF_SHOWERS
    28: "lightning",  # CONDITION_CHANCE_OF_THUNDERSTORMS
    29: "fog",  # CONDITION_MIST
    30: "dust",  # CONDITION_DUST
    31: "rain_light",  # CONDITION_DRIZZLE
    32: "tornado",  # CONDITION_TORNADO
    33: "smoke",  # CONDITION_SMOKE
    34: "ice",  # CONDITION_ICE
    35: "sandstorm",  # CONDITION_SAND
    36: "strong_wind",  # CONDITION_SQUALL
    37: "sandstorm",  # CONDITION_SANDSTORM
    38: "volcano",  # CONDITION_VOLCANIC_ASH
    39: "haze",  # CONDITION_HAZE
    40: "sunny_overcast",  # CONDITION_FAIR
    41: "hurricane",  # CONDITION_HURRICANE
    42: "hurricane_warning",  # CONDITION_TROPICAL_STORM
    43: "snow",  # CONDITION_CHANCE_OF_SNOW
    44: "wintry_mix",  # CONDITION_CHANCE_OF_RAIN_SNOW
    45: "rain",  # CONDITION_CLOUDY_CHANCE_OF_RAIN
    46: "snow",  # CONDITION_CLOUDY_CHANCE_OF_SNOW
    47: "wintry_mix",  # CONDITION_CLOUDY_CHANCE_OF_RAIN_SNOW
    48: "snow",  # CONDITION_FLURRIES
    49: "sleet",  # CONDITION_FREEZING_RAIN
    50: "sleet",  # CONDITION_SLEET
    51: "snow",  # CONDITION_ICE_SNOW
    52: "cloudy_light",  # CONDITION_THIN_CLOUDS -- lighter than CLOUDY(20)
    53: "unknown",  # CONDITION_UNKNOWN
}


def weather_icon_for_condition(condition: int | None, *, night: bool = False) -> str:
    """The codepoint for a `Weather.CONDITION_*` value.

    `night` selects a night-drawn variant where one exists in the font and
    falls back to the day glyph otherwise -- there is no sensible "night dust
    storm" icon, so dust, for instance, does not change. `condition=None` (the
    API returns null when no forecast is available) maps to the same "unknown"
    glyph as the explicit `CONDITION_UNKNOWN` value.
    """
    name = GARMIN_WEATHER_CONDITION_ICON.get(condition, "unknown") if condition is not None else "unknown"
    if night:
        return _WEATHER_GLYPH_NIGHT.get(name, _WEATHER_GLYPH[name])
    return _WEATHER_GLYPH[name]


# Named, so `icon: weather_rain` already works today -- a static placeholder,
# independent of whether anything binds it live yet. One entry per glyph name
# above that is a reasonable *design-time choice* on its own; the finer
# light/heavy variants and the two hurricane glyphs are folded into their
# plainer sibling here, since picking between them needs the live reading this
# table exists to eventually automate.
_WEATHER_NAMED = {
    "weather_clear": "sunny",
    "weather_partly_cloudy": "cloudy_light",
    "weather_cloudy": "cloudy",
    "weather_fog": "fog",
    "weather_rain": "rain",
    "weather_snow": "snow",
    "weather_wintry_mix": "wintry_mix",
    "weather_thunderstorm": "thunderstorm",
    "weather_windy": "windy",
    "weather_dust": "dust",
    "weather_tornado": "tornado",
    "weather_hurricane": "hurricane",
}
for _catalog_name, _glyph_name in _WEATHER_NAMED.items():
    CATALOG[_catalog_name] = Icon(
        _catalog_name, _WEATHER_GLYPH[_glyph_name],
        f"weather: {_glyph_name.replace('_', ' ')} (Weather Icons weather-{_glyph_name})",
    )
del _catalog_name, _glyph_name


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
