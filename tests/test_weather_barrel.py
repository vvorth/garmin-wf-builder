"""`runtime-lib/WfbWeather.mc` -- the on-device twin of
`wfb.icons.GARMIN_WEATHER_CONDITION_ICON`.

It only ever selects a catalogue *name* (never a glyph -- see its own module
docstring, and `wfb/icon_catalog.py`'s, for why that split exists). It is
hand-written, not generated, so nothing enforces it stays in step with the
Python table except this test. Parses the real file rather than re-deriving
expectations by hand, so a change to either side that breaks the pairing
fails here first.

The other half -- name -> glyph -- is `source/IconGlyphs.mc`, generated fresh
each build directly from `wfb.icon_catalog.CATALOG`; see
tests/test_weather_codegen.py for that half, which needs no separate drift
test since it is generated, not hand-maintained.
"""

from __future__ import annotations

import re
from pathlib import Path

from wfb import icons

BARREL = Path(__file__).resolve().parent.parent / "runtime-lib" / "WfbWeather.mc"

_CASE_RE = re.compile(r'case (\d+): return "(\w+)";')


def _parse_cases() -> dict[int, str]:
    text = BARREL.read_text(encoding="utf-8")
    return {int(m.group(1)): m.group(2) for m in _CASE_RE.finditer(text)}


def test_every_condition_matches_wfb_icons_exactly():
    cases = _parse_cases()
    assert set(cases) == set(range(54))
    for condition, name in cases.items():
        expected_name = icons.GARMIN_WEATHER_CONDITION_ICON[condition]
        assert name == expected_name, f"condition {condition}: name drifted"


def test_every_case_name_is_a_real_catalogue_entry():
    for _, name in _parse_cases().items():
        assert name in icons.CATALOG, f"{name!r} is not in the catalogue"


def test_default_and_null_case_both_choose_unknown():
    text = BARREL.read_text(encoding="utf-8")
    default_name = re.search(r'default: return "(\w+)";', text).group(1)
    null_name = re.search(r'condition == null.*?\n\s*return "(\w+)";', text, re.S).group(1)
    assert default_name == "weather_unknown"
    assert null_name == "weather_unknown"


def test_the_barrel_never_embeds_a_raw_glyph():
    """The whole point of the split: this file only ever returns ASCII
    catalogue names, never a drawn character."""
    text = BARREL.read_text(encoding="utf-8")
    assert all(ord(c) < 128 for c in text), "WfbWeather.mc contains a non-ASCII character"


# -- WfbCarousel ------------------------------------------------------------


def test_the_carousel_barrel_wraps_and_clamps(repo_root):
    """Two things the module is *for*, both easy to get subtly wrong by hand.

    `step` must wrap at both ends -- Monkey C's `%` keeps the sign of its left
    operand, so stepping back from 0 without the `+ count` gives -1 and reads
    off the end of the generated switch.  `restore` must clamp, because a
    rebuild with fewer items leaves a stored index past the end.
    """
    source = (repo_root / "runtime-lib" / "WfbCarousel.mc").read_text(encoding="utf-8")
    assert "(index + direction + count) % count" in source
    assert "stored < 0 || stored >= count" in source
    assert "instanceof Number" in source
