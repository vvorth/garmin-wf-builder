"""Plan 09 §4 R2: real device typefaces for system-font measurement/preview.

`wfb.devices.Device.system_fonts` merges the scraped SDK reference table
(`face`/`font`/`size_px`) with the installed device's own `simulator.json`
`ww` font set (`em_px`/`ascent_px`/`height_px`, `docs/research/
10-system-fonts.md` §3's verified metric model); `wfb.fonts.fallback` turns
the resulting `FontMetric` into a real, measurable Pillow face via
`wfb.fonts.fetch_system.locate`, and `wfb.layout`/`wfb.preview` measure and
draw through that one face so the two cannot disagree.

Every test here goes through `_no_garmin_fonts` (autouse): it monkeypatches
`fetch_system.garmin_font_root` to always report nothing, so these tests
exercise the registry/free-stand-in path exclusively and never the user's
own licensed Garmin font files (`vendor/fonts/`, the platform Garmin
`Fonts` directories) -- those may appear on this machine after this file was
written (plan 09 R1b), and a test that happened to pick them up would not be
reproducible. `WFB_OFFLINE=1` is already set for the whole session
(`tests/conftest.py`); the free stand-ins these tests need
(`roboto-condensed-bold`, `roboto-black`, `bionic-substitute`, ...) are
expected to already be installed at `wfb/assets/system-fonts/` in this
sandbox (`tools/fetch-system-fonts.py`) -- a test skips only when one it
specifically needs is actually missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import find
from wfb.build import load
from wfb.devices import Device, FontMetric
from wfb.emit.resources import bake_fonts
from wfb.fonts import fallback, fetch_system
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render


@pytest.fixture(autouse=True)
def _no_garmin_fonts(monkeypatch):
    monkeypatch.setattr(fetch_system, "garmin_font_root", lambda *a, **k: None)
    fallback.system_face.cache_clear()
    yield
    fallback.system_face.cache_clear()


def _require_font(key: str) -> None:
    if fetch_system.path_for(key) is None:
        pytest.skip(f"{key}.ttf is not installed at wfb/assets/system-fonts/")


def _independent(device: Device) -> Device:
    """A `Device` that shares `device`'s files but has its own
    `cached_property` cache, so a test can override `.system_fonts` (a
    plain instance-attribute assignment over a `cached_property` -- no
    `__set__`, so it just replaces the cached value) without mutating the
    session-scoped `db` fixture's shared, cached `Device`."""
    return Device(id=device.id, root=device.root, compiler=device.compiler,
                  simulator=device.simulator)


def _rightmost_ink_x(image, bg) -> int:
    bg_rgb = (bg.r, bg.g, bg.b)
    width, height = image.size
    rightmost = -1
    for y in range(height):
        for x in range(width - 1, rightmost, -1):
            if image.getpixel((x, y)) != bg_rgb:
                rightmost = max(rightmost, x)
                break
    return rightmost


def _ink_y_bounds(image, bg, x_lo: int, x_hi: int,
                  y_lo: int = 0, y_hi: int | None = None) -> tuple[int | None, int | None]:
    """The topmost/bottommost row with non-background ink inside
    `x_lo:x_hi`, restricted to `y_lo:y_hi` -- two elements sharing an
    `x` range (as `top_line`/`bottom_line` do below) would otherwise have
    each other's ink picked up by an unrestricted full-image scan."""
    bg_rgb = (bg.r, bg.g, bg.b)
    y_hi = image.height if y_hi is None else y_hi
    top = bottom = None
    for y in range(y_lo, y_hi):
        if any(image.getpixel((x, y)) != bg_rgb for x in range(x_lo, x_hi)):
            if top is None:
                top = y
            bottom = y
    return top, bottom


# -- 1. fenix8solar47mm FONT_MEDIUM: the plan's own worked example ----------


def test_fenix8_font_medium_matches_the_worked_example(db):
    """plan 09 §4 R2.6's own numbers: Roboto
    Condensed Bold at `FONT_MEDIUM`, em ~32.86 (`11.7109 * 202 / 72`), a
    line height of 39 and a baseline of 30 (`round(32.8556 * 1900/2048)`,
    RobotoCondensed-Bold's own `hhea`)."""
    _require_font("roboto-condensed-bold")
    device = db.get("fenix8solar47mm")
    metric = device.system_fonts["FONT_MEDIUM"]
    assert metric.font == "RobotoCondensed-Bold"
    assert metric.em_px == pytest.approx(32.86, abs=0.01)

    face = fallback.system_face(metric)
    assert face is not None
    assert face.match == "exact"
    assert face.line_height == 39
    assert face.baseline == 30


# -- 2. a real located face measures differently from Pillow's own default --


def test_measured_width_differs_from_the_pillow_default_stand_in(db):
    """Before this: every system font measured against Pillow's bundled
    default face, scaled to the device's published height
    (`fallback.font_for_height`, kept for the style-sheet caption only now).
    `fallback.measure` must measure against the *located* device typeface
    instead -- a different family at the same nominal line height gives a
    different width for the same string, or this whole plan step is a
    no-op."""
    _require_font("roboto-condensed-bold")
    device = db.get("fenix8solar47mm")
    metric = device.system_fonts["FONT_MEDIUM"]
    text = "Hxg 0123"

    real_width, real = fallback.measure(text, metric)
    assert real is True

    stand_in = fallback.font_for_height(metric.size_px)
    assert stand_in is not None
    stand_in_width = round(stand_in.getlength(text))

    assert real_width != stand_in_width


# -- 3. one source of truth: em moves layout width and preview ink together -


DESIGN_TEMPLATE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
elements:
{elements}
"""

_LABEL_ELEMENT = """  - id: label
    type: text
    text: "88888"
    font: FONT_MEDIUM
    align: left
    vertical_align: top
    at: {anchor: top_left, dx: 4px, dy: 4px}
    color: palette.fg
"""


def test_a_monkeypatched_em_moves_layout_width_and_preview_ink_the_same_way(
        write_design, bag, db):
    """`wfb.layout` and `wfb.preview` both derive width/ink from exactly one
    face (`fallback.system_face`) -- there is no second, independent
    estimate to drift out of step with it. Doubling `em_px` on a fresh,
    independent `Device` (never the shared `db` one) must widen both the
    resolved box *and* the rendered ink, in the same direction, because
    both come from the one face this doubled metric now describes."""
    _require_font("roboto-condensed-bold")
    face_design = load(write_design(DESIGN_TEMPLATE.format(elements=_LABEL_ELEMENT)), bag)
    assert face_design is not None, bag.render()
    device = db.get("fenix8solar47mm")

    resolved = resolve(face_design, device, bake_fonts(face_design, device))
    normal_width = find(resolved, "label").measured_width
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))
    normal_ink_right = _rightmost_ink_x(image, face_design.palette["bg"])

    base_metric = device.system_fonts["FONT_MEDIUM"]
    base_em = base_metric.em_px if base_metric.em_px is not None else float(base_metric.size_px)
    doubled_metric = FontMetric(
        base_metric.symbol, base_metric.face, base_metric.font, base_metric.size_px,
        base_em * 2, base_metric.ascent_px, base_metric.height_px,
    )
    doubled_device = _independent(device)
    doubled_device.system_fonts = {**device.system_fonts, "FONT_MEDIUM": doubled_metric}

    doubled_resolved = resolve(face_design, doubled_device, bake_fonts(face_design, doubled_device))
    doubled_width = find(doubled_resolved, "label").measured_width
    doubled_image = render(doubled_resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))
    doubled_ink_right = _rightmost_ink_x(doubled_image, face_design.palette["bg"])

    assert doubled_width > normal_width
    assert doubled_ink_right > normal_ink_right


# -- 4. vertical_align top/bottom ink vs. the anchor, in a rendered preview -


_ALIGN_ELEMENTS = """  - id: top_line
    type: text
    text: "Hxg"
    font: FONT_LARGE
    align: left
    vertical_align: top
    at: {{anchor: top_left, dx: 10px, dy: {top_y}px}}
    color: palette.fg
  - id: bottom_line
    type: text
    text: "Hxg"
    font: FONT_LARGE
    align: left
    vertical_align: bottom
    at: {{anchor: top_left, dx: 10px, dy: {bottom_y}px}}
    color: palette.fg
"""


def test_vertical_align_top_and_bottom_ink_sits_against_the_anchor(write_design, bag, db):
    """`wfb.preview._draw_text`'s line-box model (plan 09 §4 R2.4):
    a `top`-aligned line's box starts exactly at the anchor, a `bottom`-
    aligned line's box ends exactly at it -- so the ink (which sits inside
    the box, offset only by internal leading/descender) must appear at or
    just below the anchor for `top`, and at or just above it for `bottom`,
    never the other way around."""
    _require_font("roboto-condensed-bold")
    top_y, bottom_y = 60, 180
    design = DESIGN_TEMPLATE.format(
        elements=_ALIGN_ELEMENTS.format(top_y=top_y, bottom_y=bottom_y))
    face_design = load(write_design(design), bag)
    assert face_design is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face_design, device, bake_fonts(face_design, device))
    top_placed = find(resolved, "top_line")
    bottom_placed = find(resolved, "bottom_line")

    image = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))
    bg = face_design.palette["bg"]

    midpoint = (top_y + bottom_y) // 2
    top_ink_top, top_ink_bottom = _ink_y_bounds(
        image, bg, top_placed.anchor_point[0], top_placed.anchor_point[0] + top_placed.measured_width,
        y_lo=0, y_hi=midpoint)
    assert top_ink_top is not None, "top_line drew no ink at all"
    # The box starts at the anchor; ink is inside the box, never above it.
    assert top_ink_top >= top_y
    assert top_ink_top < top_y + top_placed.box.height

    bottom_ink_top, bottom_ink_bottom = _ink_y_bounds(
        image, bg, bottom_placed.anchor_point[0],
        bottom_placed.anchor_point[0] + bottom_placed.measured_width,
        y_lo=midpoint)
    assert bottom_ink_bottom is not None, "bottom_line drew no ink at all"
    # The box ends at the anchor; ink is inside the box, never below it.
    assert bottom_ink_bottom <= bottom_y
    assert bottom_ink_bottom > bottom_y - bottom_placed.box.height

    # And the two must disagree with each other -- a `top`/`bottom` swap
    # that drew identically would still pass either check above alone.
    assert top_ink_top < bottom_ink_top


# -- 5. a `substitute` match is reported as such -----------------------------


def test_bionic_semibold_resolves_with_match_substitute(db):
    """Bionic is proprietary (`docs/research/10-system-fonts.md` §4):
    `Bionic_semibold` maps to the free `roboto-black` stand-in, match
    `"substitute"` -- never silently reported as `"exact"`."""
    _require_font("bionic-substitute")
    device = db.get("fenix8solar47mm")
    metric = device.system_fonts["FONT_NUMBER_HOT"]
    assert metric.font == "Bionic_semibold"

    face = fallback.system_face(metric)
    assert face is not None
    assert face.match == "substitute"


# -- 6. a device with no ppi (fenix6, bitmap FNT_* names) still measures ----


def test_fenix6_has_no_ppi_and_falls_back_to_the_scraped_metrics(db):
    """fenix6's `simulator.json` has no top-level `ppi` and its `ww` fonts
    are pre-rasterised bitmaps (no `type: "ttf"`, no `size` in points), so
    `Device.system_fonts` cannot compute `em_px` -- `fallback.system_face`
    must still produce a usable face, deriving the em itself from the
    located TTF's own `hhea` table, with `metric.size_px` (the scraped line
    height) staying the line box height."""
    if "fenix6" not in db.ids():
        pytest.skip("fenix6 is not installed")
    _require_font("roboto-condensed-bold")
    device = db.get("fenix6")
    metric = device.system_fonts["FONT_MEDIUM"]
    assert metric.em_px is None
    assert metric.size_px == 37

    face = fallback.system_face(metric)
    assert face is not None
    assert face.line_height == 37
    assert 0 < face.baseline < face.line_height
    assert face.match in ("exact", "family", "substitute")


# -- the device's own numbers (plan 09 §7) ------------------------------------

#: `docs/research/probes/system-font-metrics/results-2026-09-18.txt`: what the
#: simulator itself reported, per device and symbol.
PROBE_RESULTS = (Path(__file__).resolve().parent.parent / "docs" / "research" / "probes"
                 / "system-font-metrics" / "results-2026-09-18.txt")

#: Symbols a design may name that the probe measured (`FONT_GLANCE*`/
#: `FONT_AUX*` are not in `wfb.ir.SYSTEM_FONTS`).
_AUTHORABLE = ("FONT_XTINY", "FONT_TINY", "FONT_SMALL", "FONT_MEDIUM", "FONT_LARGE",
               "FONT_NUMBER_MILD", "FONT_NUMBER_MEDIUM", "FONT_NUMBER_HOT",
               "FONT_NUMBER_THAI_HOT")


def _probe_rows():
    for line in PROBE_RESULTS.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            device, symbol, *numbers = line.split()
            if symbol in _AUTHORABLE:
                yield (device, symbol, *map(int, numbers))


@pytest.mark.parametrize("device_id,symbol,height,ascent,descent,w_mixed,w_digits",
                         list(_probe_rows()), ids=lambda v: str(v))
def test_metrics_match_what_the_simulator_reported(
        db, device_id, symbol, height, ascent, descent, w_mixed, w_digits):
    """Line height, baseline and widths against the device's own
    `getFontHeight`/`getFontAscent`/`getTextWidthInPixels`.

    Roboto faces must be exact: every glyph advances by its `hmtx` width
    at the whole-pixel em, rounded on its own. Before that model, Pillow's
    fractional, hinted `getlength` had `FONT_TINY` digits a pixel narrow
    each (120 against 130). Bionic is a substitute here (the tests never
    see the user's Garmin files) and gets 5 % -- measured error with the
    real Bionic is <= 4 px over ten digits, with Roboto Condensed Bold
    standing in <= 3.5 %.
    """
    metric = db.get(device_id).system_fonts[symbol]
    face = fallback.system_face(metric)
    if face is None or face.match == "none":
        pytest.skip(f"no font installed for {metric.font}")
    assert face.line_height == height
    if metric.font.startswith("Bionic") and metric.ascent_px is None:
        # The device's baseline comes from Bionic's own `hhea` (930/1000);
        # the stand-in's (1900/2048) lands within a pixel of it.
        assert abs(face.baseline - ascent) <= 1
    else:
        assert (face.baseline, face.line_height - face.baseline) == (ascent, descent)
    widths = (fallback.measure("Hxg0123", metric)[0], fallback.measure("0123456789", metric)[0])
    if metric.font.startswith("Bionic"):
        assert face.match == "substitute"
        for got, want in zip(widths, (w_mixed, w_digits)):
            assert abs(got - want) <= 0.05 * want
    else:
        assert widths == (w_mixed, w_digits)
