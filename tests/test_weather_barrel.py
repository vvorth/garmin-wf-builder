"""`runtime-lib/WfbWeather.mc` -- the on-device twin of
`wfb.icons.weather_icon_for_condition()`.

It is hand-written, not generated (see its own module docstring for why), so
nothing enforces the two stay in step except this test. Parses the real file
rather than re-deriving expectations by hand, so a change to either side that
breaks the pairing fails here first.
"""

from __future__ import annotations

import re
from pathlib import Path

from wfb import icons

BARREL = Path(__file__).resolve().parent.parent / "runtime-lib" / "WfbWeather.mc"

_CASE_RE = re.compile(r'case (\d+): return "(.)";\s*//\s*(\S+)')


def _parse_cases() -> dict[int, tuple[str, str]]:
    text = BARREL.read_text(encoding="utf-8")
    return {int(m.group(1)): (m.group(2), m.group(3)) for m in _CASE_RE.finditer(text)}


def test_every_condition_matches_wfb_icons_exactly():
    cases = _parse_cases()
    assert set(cases) == set(range(54))
    for condition, (glyph, name) in cases.items():
        expected_name = icons.GARMIN_WEATHER_CONDITION_ICON[condition]
        expected_glyph = icons.CATALOG[expected_name].codepoint
        assert name == expected_name, f"condition {condition}: name drifted"
        assert glyph == expected_glyph, f"condition {condition} ({name}): glyph drifted"


def test_default_and_null_case_both_match_the_unknown_glyph():
    text = BARREL.read_text(encoding="utf-8")
    default_glyph = re.search(r'default: return "(.)";', text).group(1)
    null_glyph = re.search(r"condition == null.*?\n\s*return \"(.)\";", text, re.S).group(1)
    unknown = icons.CATALOG["weather_unknown"].codepoint
    assert default_glyph == unknown
    assert null_glyph == unknown


def test_every_case_glyph_is_a_real_font_character():
    for _, (glyph, _) in _parse_cases().items():
        assert glyph in icons._available_glyphs()
