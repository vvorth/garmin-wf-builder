"""A located `.cft` becomes a usable `wfb.fonts.fallback.SystemFace`, measured and drawn
through it, never through the free-stand-in registry -- for 8 of the 13
installed devices, every `FONT_*` symbol resolves to one.

**Never relies on the real `vendor/fonts/`** (the user's licensed Garmin
files): every test here builds its own tiny synthetic `.cft` with
`tests.test_cft.write_cft` (the test-side encoder) in a fake font root,
and monkeypatches `wfb.fonts.fetch_system.garmin_font_root` to point at it --
the same isolation `tests/test_system_font_metrics.py`'s `_no_garmin_fonts`
fixture uses in the other direction (forcing the registry path). The device
files (`db`/`write_design`/`bag` fixtures) are a separate, already-gated
dependency (`tests/conftest.py`), not Garmin's proprietary font files.
"""

from __future__ import annotations

import pytest

from tests.test_cft import write_cft
from tests.test_diagnostics import load
from wfb.devices import Device, FontMetric
from wfb.emit.resources import bake_fonts
from wfb.fonts import fallback, fetch_system
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render

#: The synthetic font's file stem -- deliberately `FNT_`-prefixed, matching
#: a real bitmap `FONT_*` symbol's own file naming (plan 10 §2.1), though
#: nothing here depends on the prefix specifically (an exact-stem match is
#: `garmin_any_file`'s first `.cft` try either way; see
#: `tests/test_system_fonts_fetch.py` for the prefix-guessing fallback).
FONT_STEM = "FNT_TESTBITMAP_20B"

#: 1 bpp, so a pixel is either background (0) or full ink (1) -- makes the
#: preview-ink assertions pixel-exact with no antialiasing/blend to reason
#: about (plan §2.4's linear blend is exercised elsewhere by construction --
#: 1 bpp is just the 0/max_level endpoints of that same blend).
_HEIGHT = 10
_ASCENT = 8
_ADVANCE = 6


def _solid_grid(advance: int, height: int) -> list[list[int]]:
    return [[1] * advance for _ in range(height)]


def _blank_grid(advance: int, height: int) -> list[list[int]]:
    return [[0] * advance for _ in range(height)]


@pytest.fixture
def bitmap_root(tmp_path):
    """A fake Garmin font root holding one synthetic `.cft`: glyph 0 (the
    "missing" box, unused by these tests) is a blank 4x10 cell; glyph 1, the
    only cmap entry, maps `'A'` to a solid `_ADVANCE`x`_HEIGHT` cell of full
    ink -- a shape simple enough that its preview ink can be checked
    pixel-for-pixel."""
    root = tmp_path / "fonts"
    root.mkdir()
    write_cft(
        root / f"{FONT_STEM}.cft",
        header_size=36, rle=False, bpp=1, height=_HEIGHT, ascent=_ASCENT,
        glyphs=[
            (4, _blank_grid(4, _HEIGHT)),
            (_ADVANCE, _solid_grid(_ADVANCE, _HEIGHT)),
        ],
        cmap_groups=[(ord("A"), ord("A"), 1)],
    )
    return root


@pytest.fixture(autouse=True)
def _clear_system_face_cache():
    fallback.system_face.cache_clear()
    yield
    fallback.system_face.cache_clear()


def _bitmap_metric(size_px: int = 99) -> FontMetric:
    """A `FontMetric` naming only the synthetic `.cft` -- `size_px` is
    deliberately wrong (99, not the file's own height 10) so that a test
    checking the override (`line_height`/`system_face`) cannot pass by
    accident just because the two numbers happened to agree."""
    return FontMetric("FONT_MEDIUM", "", FONT_STEM, size_px)


# -- B.3: system_face on a .cft-only metric ----------------------------------


def test_system_face_on_a_cft_only_metric_gives_a_bitmap_face(bitmap_root, monkeypatch):
    monkeypatch.setattr(fetch_system, "garmin_font_root", lambda *a, **k: bitmap_root)
    metric = _bitmap_metric()

    face = fallback.system_face(metric)

    assert face is not None
    assert face.match == "garmin"
    assert face.font is None  # no Pillow FreeTypeFont for a bitmap face
    assert face.bitmap is not None
    assert face.line_height == _HEIGHT
    assert face.baseline == _ASCENT
    assert face.advances("A") == [_ADVANCE]


def test_measure_equals_the_sum_of_the_cft_advances(bitmap_root, monkeypatch):
    monkeypatch.setattr(fetch_system, "garmin_font_root", lambda *a, **k: bitmap_root)
    metric = _bitmap_metric()

    width, real = fallback.measure("AA", metric)

    assert real is True
    assert width == 2 * _ADVANCE


def test_line_height_overrides_the_scraped_size_px_once_the_cft_is_found(
        bitmap_root, monkeypatch):
    """Plan §2.3's decision: a located `.cft`'s own `height` is the line
    box, overriding `size_px` (99 here) -- `wfb.layout` and `wfb.preview`
    must agree on this, which is exactly what `fallback.line_height` (what
    `wfb.layout` calls) and `fallback.system_face.line_height` (what
    `wfb.preview` draws with) both being 10 here proves."""
    monkeypatch.setattr(fetch_system, "garmin_font_root", lambda *a, **k: bitmap_root)
    metric = _bitmap_metric()

    assert fallback.line_height(metric) == _HEIGHT
    assert fallback.system_face(metric).line_height == _HEIGHT


def test_a_ttf_with_the_same_stem_still_wins_over_the_cft(bitmap_root, monkeypatch, repo_root):
    """`fetch_system.garmin_any_file`'s own order: a `.ttf`/`.otf` beats a
    `.cft` at the very same stem (plan §3 B.2)."""
    real_ttf = repo_root / "tests" / "fixtures" / "slice" / "assets" / "OpenSans-Regular.ttf"
    (bitmap_root / f"{FONT_STEM}.ttf").write_bytes(real_ttf.read_bytes())
    monkeypatch.setattr(fetch_system, "garmin_font_root", lambda *a, **k: bitmap_root)
    metric = _bitmap_metric()

    face = fallback.system_face(metric)

    assert face is not None
    assert face.match == "garmin"
    assert face.bitmap is None
    assert face.font is not None


def test_with_the_root_absent_the_registry_path_is_used(monkeypatch):
    """No Garmin root at all (registry only): a
    bitmap-shaped metric still measures through the free stand-in, never
    through a `.cft` branch that has nothing to locate."""
    monkeypatch.setattr(fetch_system, "garmin_font_root", lambda *a, **k: None)
    metric = FontMetric("FONT_MEDIUM", "Roboto Condensed", "FENIX6_CDPG_ROBOTO_24B", 37)

    face = fallback.system_face(metric)

    assert face is not None
    assert face.bitmap is None
    assert face.match in ("exact", "family", "substitute", "none")


# -- B.1: Device.system_fonts carries the installed filename ---------------


def test_device_system_fonts_carries_the_simulator_filename_for_a_bitmap_entry():
    """`fenix6`'s own scraped `FONT_MEDIUM` (`docs/research/data/devices/
    fenix6.json`, no Garmin device install needed to read it) names
    `FENIX6_CDPG_ROBOTO_24B` -- no `FNT_` prefix. A bitmap `simulator.json`
    `ww` entry (no `type` key at all) must still replace it with the
    installed device's own filename (plan §3 B.1's decision), the same way
    a `type: "ttf"` entry's `filename` already did before this change."""
    device = Device(
        id="fenix6", root=None, compiler={},
        simulator={"fonts": [{"fontSet": "ww", "fonts": [
            {"name": "medium", "filename": "FNT_FENIX6_CDPG_ROBOTO_24B"},
        ]}]},
    )
    metric = device.system_fonts["FONT_MEDIUM"]
    assert metric.font == "FNT_FENIX6_CDPG_ROBOTO_24B"
    assert metric.face == "Roboto Condensed"  # scraped face is kept
    assert metric.size_px == 37  # scraped size_px is kept (may be overridden later)
    assert metric.em_px is None
    assert metric.ascent_px is None
    assert metric.height_px is None


# -- B.4: preview ink, pixel-exact, top/center/bottom -----------------------


_DESIGN_TEMPLATE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f59
  name: BitmapPreviewTest
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
elements:
  - id: line
    type: text
    text: "A"
    font: FONT_MEDIUM
    align: left
    vertical_align: {valign}
    at: {{anchor: top_left, dx: 20px, dy: 100px}}
    color: palette.fg
"""

_ANCHOR_X, _ANCHOR_Y = 20, 100


@pytest.mark.parametrize("valign,box_top", [
    ("top", _ANCHOR_Y),
    ("center", _ANCHOR_Y - _HEIGHT // 2),
    ("bottom", _ANCHOR_Y - _HEIGHT),
])
def test_bitmap_glyph_ink_lands_on_the_exact_pixels(
        write_design, bag, db, bitmap_root, monkeypatch, valign, box_top):
    """The glyph cell (a solid `_ADVANCE`x`_HEIGHT` rectangle) must land
    exactly at `(anchor_x, box_top)`, sized exactly `_ADVANCE`x`_HEIGHT` --
    full `fg` inside, a 1px ring of `bg` just outside on every side. This
    is `_draw_bitmap_line`'s own placement rule (plan §3 B.4: cell top =
    `baseline_y - ascent*scale`) proven against real ink, not just the
    `SystemFace` numbers `test_system_face_on_a_cft_only_metric_gives_a_
    bitmap_face` already checked."""
    monkeypatch.setattr(fetch_system, "garmin_font_root", lambda *a, **k: bitmap_root)
    design = _DESIGN_TEMPLATE.format(valign=valign)
    face_design = load(write_design(design), bag)
    assert face_design is not None, bag.render()

    device = db.get("fenix8solar47mm")
    patched = Device(id=device.id, root=device.root, compiler=device.compiler,
                     simulator=device.simulator)
    patched.system_fonts = {**device.system_fonts, "FONT_MEDIUM": _bitmap_metric()}

    resolved = resolve(face_design, patched, bake_fonts(face_design, patched))
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))

    bg = face_design.palette["bg"]
    fg = face_design.palette["fg"]
    bg_rgb, fg_rgb = (bg.r, bg.g, bg.b), (fg.r, fg.g, fg.b)

    left, top = _ANCHOR_X, box_top
    right, bottom = left + _ADVANCE, top + _HEIGHT

    for y in range(top, bottom):
        for x in range(left, right):
            assert image.getpixel((x, y)) == fg_rgb, (x, y)

    for x, y in ((left - 1, top), (right, top), (left, top - 1), (left, bottom)):
        assert image.getpixel((x, y)) == bg_rgb, (x, y)
