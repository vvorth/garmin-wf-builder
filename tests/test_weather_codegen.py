"""Generated Monkey C for `weather.*` sources and `icon_for:` -- the slow-tier
cache and the dynamic icon draw call.

Builds a real design and asserts on the emitted text directly, the same way
tests/test_resources.py checks the filter-omission fix -- these need no
Garmin toolchain, only the device files (for font baking).
"""

from __future__ import annotations

from tests.test_diagnostics import load
from wfb import icons
from wfb.emit.project import generate
from wfb.emit.resources import bake_fonts

DESIGN = """
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}}
targets: [fenix8solar47mm]
palette: {{bg: "#000000", fg: "#FFFFFF"}}
elements:
  - id: bg
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.bg
{elements}
"""

ONE_ICON = """
  - id: wicon
    type: icon
    icon_for: weather.condition
    size: 20%r
    at: {anchor: center}
    color: palette.fg
"""

TWO_DAILY_ICONS = """
  - id: today
    type: icon
    icon_for: weather.condition_today
    size: 20%r
    at: {anchor: center, dx: -25%r}
    color: palette.fg
  - id: tomorrow
    type: icon
    icon_for: weather.condition_tomorrow
    size: 20%r
    at: {anchor: center, dx: 25%r}
    color: palette.fg
"""


def _project_files(write_design, bag, db, tmp_path, elements: str) -> dict[str, str]:
    face = load(write_design(DESIGN.format(elements=elements)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = bake_fonts(face, device, device.minor_radius)
    project = generate(face, [device], tmp_path, {device.id: baked})
    return project.files()


def _view(write_design, bag, db, tmp_path, elements: str) -> str:
    return _project_files(write_design, bag, db, tmp_path, elements)["source/TestView.mc"]


def test_a_slow_reader_is_cached_not_read_every_frame(write_design, bag, db, tmp_path):
    view = _view(write_design, bag, db, tmp_path, ONE_ICON)
    assert "private var _weatherCurrentCache as Weather.CurrentConditions?;" in view
    assert "private var _weatherCurrentCacheTime as Number?;" in view
    assert "WfbCache.stale(_weatherCurrentCacheTime, 900)" in view
    assert "_weatherCurrentCache = Weather.getCurrentConditions();" in view
    assert "_weatherCurrentCacheTime = Time.now().value();" in view
    # not called unconditionally every frame -- only inside the stale check.
    lines = view.splitlines()
    unconditional = [l for l in lines if "Weather.getCurrentConditions()" in l
                      and "_weatherCurrentCache =" in l]
    assert len(unconditional) == 1


def test_today_and_tomorrow_share_one_daily_forecast_read(write_design, bag, db, tmp_path):
    """Two icons bound to the same reader (weather_daily) must not fetch the
    forecast twice -- ReadPlan hoists reads per reader, not per element."""
    view = _view(write_design, bag, db, tmp_path, TWO_DAILY_ICONS)
    assert view.count("Weather.getDailyForecast()") == 1
    assert "weatherDaily[0].condition" in view
    assert "weatherDaily[1].condition" in view
    assert "weatherDaily.size() > 0" in view
    assert "weatherDaily.size() > 1" in view


def test_dynamic_icon_resolves_name_then_glyph(write_design, bag, db, tmp_path):
    """Two steps, not one: WfbWeather picks a *name*, IconGlyphs (generated,
    catalogue-derived) turns that name into a glyph -- not a weather-only
    shadow table baked directly into WfbWeather.mc."""
    view = _view(write_design, bag, db, tmp_path, ONE_ICON)
    assert "IconGlyphs.glyph(WfbWeather.chooseIcon(weatherCondition))" in view
    # no literal glyph string baked in for a dynamic icon.
    assert 'dc.drawText(Layout.WICON_CX, Layout.WICON_CY, font,\n            "' not in view


def test_icon_glyphs_module_is_generated_from_the_catalogue(write_design, bag, db, tmp_path):
    files = _project_files(write_design, bag, db, tmp_path, ONE_ICON)
    assert "source/IconGlyphs.mc" in files
    glyphs = files["source/IconGlyphs.mc"]
    assert "module IconGlyphs" in glyphs
    assert "function glyph(name as String) as String" in glyphs
    # every name weather.condition* could ever select is covered, and each
    # one's glyph matches the catalogue exactly.
    for name in set(icons.GARMIN_WEATHER_CONDITION_ICON.values()):
        codepoint = icons.CATALOG[name].codepoint
        assert f'case "{name}": return "{codepoint}";' in glyphs


def test_icon_glyphs_module_is_absent_without_a_dynamic_icon(write_design, bag, db, tmp_path):
    static_icon = """
  - id: heart
    type: icon
    icon: heart
    size: 20%r
    at: {anchor: center}
    color: palette.fg
"""
    files = _project_files(write_design, bag, db, tmp_path, static_icon)
    assert "source/IconGlyphs.mc" not in files
    # a static icon's glyph is still a literal, resolved at build time.
    view = files["source/TestView.mc"]
    assert "IconGlyphs" not in view


def test_dynamic_icon_hides_when_condition_is_absent(write_design, bag, db, tmp_path):
    view = _view(write_design, bag, db, tmp_path, ONE_ICON)
    assert "if (weatherCondition == null) {\n            return;\n        }" in view


def test_barrel_includes_cache_and_weather_modules(write_design, bag, db):
    from wfb.emit.project import _barrel_for
    from wfb.layout import resolve

    face = load(write_design(DESIGN.format(elements=ONE_ICON)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = bake_fonts(face, device, device.minor_radius)
    resolved = resolve(face, device, baked)
    barrel = _barrel_for(face, resolved)
    assert "WfbCache.mc" in barrel
    assert "WfbWeather.mc" in barrel


def test_view_imports_time_and_weather(write_design, bag, db, tmp_path):
    view = _view(write_design, bag, db, tmp_path, ONE_ICON)
    assert "import Toybox.Time;" in view
    assert "import Toybox.Weather;" in view
