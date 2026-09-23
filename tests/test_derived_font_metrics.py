"""Plan 17: derived `FONT_*` metrics for a device the SDK's scraped device
reference has no page for at all (the fenix 9 family -- `fenix947mm`,
`fenix9prosolar47mm`, `fenix9prosolar51mm`).

`wfb.devices.Device.system_fonts`' third source (after the scraped-table
loop and the "stated `height`" loop) derives a standard `FONT_*` symbol's
`size_px` straight from a locatable real `.ttf`/`.otf`'s own `head`/`hhea`
tables, with a stdlib `struct` reader (`_sfnt_head_hhea`) so `wfb.devices`
stays free of Pillow/fontTools. It only ever fires for a symbol in the
documented vocabulary (`_documented_font_symbols`), only when nothing
scraped or stated already covers it, and only when the user's own licensed
Garmin fonts are actually installed and locatable
(`_locate_garmin_outline_font` -- never the free-stand-in registry, never a
`.cft`).

Most tests here build a throwaway `Device` directly (no device root on
disk needed -- `system_fonts` only reads `self.simulator`/`self.compiler`
and the module-level scraped-fonts directory keyed by `self.id`), the same
"construct what no installed device can" move `tests/test_build.py::
test_a_device_below_the_manifest_floor_is_a_friendly_build_error` already
uses. A fake id is chosen so it never collides with a real scraped
`docs/research/data/devices/<id>.json`.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from wfb.devices import Device, _documented_font_symbols, _sfnt_head_hhea
from wfb.fonts import fetch_system

FIXTURE_TTF = Path(__file__).parent / "fixtures" / "slice" / "assets" / "OpenSans-Regular.ttf"

#: A device id guaranteed not to collide with any real scraped device file.
FAKE_DEVICE_ID = "testfakefenix9000"


def _device(*, ppi: int | None = 326, ww_entries: list[dict] | None = None,
            device_id: str = FAKE_DEVICE_ID) -> Device:
    simulator: dict = {}
    if ppi is not None:
        simulator["ppi"] = ppi
    if ww_entries is not None:
        simulator["fonts"] = [{"fontSet": "ww", "fonts": ww_entries}]
    return Device(id=device_id, root=Path("/nonexistent"), compiler={}, simulator=simulator)


def _independent(device: Device) -> Device:
    """A fresh `Device` sharing `device`'s own files/dicts but with its own
    `cached_property` cache -- so overriding `_scraped`/`system_fonts` on it
    (test 5) never mutates the session-scoped `db` fixture's shared,
    cached `Device` (the same move `tests/test_system_font_metrics.py::
    _independent` already makes for the same reason)."""
    return Device(id=device.id, root=device.root, compiler=device.compiler, simulator=device.simulator)


def _read_hhea_with_fonttools(path: Path) -> tuple[int, int, int]:
    """`(unitsPerEm, hhea.ascent, hhea.descent)`, read independently with
    fontTools -- the cross-check test 1 needs a second, unrelated
    implementation to compare the stdlib `struct` reader against."""
    from fontTools.ttLib import TTFont

    font = TTFont(str(path))
    upm = font["head"].unitsPerEm
    hhea = font["hhea"]
    return int(upm), int(hhea.ascent), int(hhea.descent)


# -- 1. deterministic, no licensed fonts, cross-checked against fontTools --


def test_derived_metric_matches_an_independent_fonttools_reading(tmp_path, monkeypatch):
    monkeypatch.delenv("WFB_NO_GARMIN_FONTS", raising=False)
    fonts_root = tmp_path / "fonts"
    fonts_root.mkdir()
    dest = fonts_root / "OpenSans-Regular.ttf"
    dest.write_bytes(FIXTURE_TTF.read_bytes())
    monkeypatch.setenv("WFB_FONTS", str(fonts_root))

    ppi = 326
    size_pt = 20
    device = _device(ppi=ppi, ww_entries=[
        {"name": "numberMild", "filename": "OpenSans-Regular", "size": size_pt, "type": "ttf"},
    ])

    upm, asc, desc = _read_hhea_with_fonttools(FIXTURE_TTF)
    em = size_pt * ppi / 72
    expected_size_px = round(em * (asc - desc) / upm)

    metric = device.system_fonts["FONT_NUMBER_MILD"]
    assert metric.size_px == expected_size_px
    assert metric.em_px == pytest.approx(em)
    assert metric.font == "OpenSans-Regular"


# -- 2. WFB_NO_GARMIN_FONTS=1 (the default test env) yields nothing --------


def test_no_garmin_fonts_env_var_suppresses_the_third_source(tmp_path, monkeypatch):
    # WFB_NO_GARMIN_FONTS=1 is already set for the whole session
    # (tests/conftest.py); this test relies on that default rather than
    # setting it itself, to prove the *ordinary* test environment is safe.
    fonts_root = tmp_path / "fonts"
    fonts_root.mkdir()
    (fonts_root / "OpenSans-Regular.ttf").write_bytes(FIXTURE_TTF.read_bytes())
    monkeypatch.setenv("WFB_FONTS", str(fonts_root))

    device = _device(ppi=326, ww_entries=[
        {"name": "numberMild", "filename": "OpenSans-Regular", "size": 20, "type": "ttf"},
    ])
    assert "FONT_NUMBER_MILD" not in device.system_fonts


# -- 3. a symbol outside the documented vocabulary is never derived --------


def test_a_symbol_outside_the_vocabulary_is_not_added(tmp_path, monkeypatch):
    monkeypatch.delenv("WFB_NO_GARMIN_FONTS", raising=False)
    fonts_root = tmp_path / "fonts"
    fonts_root.mkdir()
    (fonts_root / "OpenSans-Regular.ttf").write_bytes(FIXTURE_TTF.read_bytes())
    monkeypatch.setenv("WFB_FONTS", str(fonts_root))

    # "glanceFont" -> FONT_GLANCE_FONT, which is not in the 22-symbol
    # vocabulary (the real symbol is FONT_GLANCE) -- plan 17 §3 rule 2's own
    # example.
    assert "FONT_GLANCE_FONT" not in _documented_font_symbols()
    device = _device(ppi=326, ww_entries=[
        {"name": "glanceFont", "filename": "OpenSans-Regular", "size": 20, "type": "ttf"},
    ])
    assert "FONT_GLANCE_FONT" not in device.system_fonts


# -- 4. a scraped device keeps its scraped size_px even with fonts present -


def test_a_scraped_device_keeps_its_scraped_size_px(db, monkeypatch):
    if "fenix847mm" not in db.ids():
        pytest.skip("fenix847mm is not installed")
    monkeypatch.delenv("WFB_NO_GARMIN_FONTS", raising=False)
    if fetch_system.garmin_font_root() is None:
        pytest.skip("no Garmin font root available on this machine")

    without_garmin = _independent(db.get("fenix847mm"))
    monkeypatch.setattr(fetch_system, "garmin_font_root", lambda *a, **k: None)
    keys_without = set(without_garmin.system_fonts.keys())
    monkeypatch.undo()

    monkeypatch.delenv("WFB_NO_GARMIN_FONTS", raising=False)
    with_garmin = _independent(db.get("fenix847mm"))
    metrics_with = with_garmin.system_fonts
    assert metrics_with["FONT_NUMBER_MILD"].size_px == 113
    assert set(metrics_with.keys()) == keys_without


# -- 5. leave-one-out against real data -------------------------------------


def _garmin_root_has_bionic_medium() -> Path | None:
    root = fetch_system.garmin_font_root()
    if root is None:
        return None
    found = fetch_system.garmin_any_file("Bionic_Medium", root)
    if found is not None and found.suffix.lower() in (".ttf", ".otf"):
        return root
    return None


def test_leave_one_out_reproduces_the_scraped_values(db, monkeypatch):
    monkeypatch.delenv("WFB_NO_GARMIN_FONTS", raising=False)
    if _garmin_root_has_bionic_medium() is None:
        pytest.skip("no Garmin font root with Bionic_Medium.ttf on this machine")
    if "fenix847mm" not in db.ids():
        pytest.skip("fenix847mm is not installed")

    fenix847 = _independent(db.get("fenix847mm"))
    real_scraped = dict(fenix847.system_fonts)
    monkeypatch.setattr(Device, "_scraped", property(lambda self: {}))
    forced = _independent(db.get("fenix847mm"))
    derived = forced.system_fonts

    symbols = [
        "FONT_XTINY", "FONT_TINY", "FONT_SMALL", "FONT_MEDIUM", "FONT_LARGE",
        "FONT_NUMBER_MILD", "FONT_NUMBER_MEDIUM", "FONT_NUMBER_HOT", "FONT_NUMBER_THAI_HOT",
    ]
    for symbol in symbols:
        assert derived[symbol].size_px == real_scraped[symbol].size_px, symbol

    monkeypatch.undo()
    monkeypatch.delenv("WFB_NO_GARMIN_FONTS", raising=False)

    if "fenix947mm" not in db.ids():
        pytest.skip("fenix947mm is not installed")
    fenix947 = _independent(db.get("fenix947mm"))
    expected = {
        "FONT_XTINY": 37, "FONT_TINY": 47, "FONT_SMALL": 53, "FONT_MEDIUM": 61,
        "FONT_LARGE": 71, "FONT_NUMBER_MILD": 113, "FONT_NUMBER_MEDIUM": 153,
        "FONT_NUMBER_HOT": 173, "FONT_NUMBER_THAI_HOT": 210,
    }
    for symbol, size_px in expected.items():
        assert fenix947.system_fonts[symbol].size_px == size_px, symbol


# -- 6. a .cft-only or unlocatable filename yields nothing, no exception ---


def test_a_cft_only_filename_yields_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("WFB_NO_GARMIN_FONTS", raising=False)
    fonts_root = tmp_path / "fonts"
    fonts_root.mkdir()
    # A real, perfectly parseable sfnt -- but under a `.cft` extension, so
    # only the suffix gate (never the sfnt reader itself) can be what keeps
    # this out. That is the point: a `.cft` name resolving to bitmap bytes
    # this reader cannot parse anyway would pass even with the suffix check
    # removed, and would not actually exercise rule 4's "a `.cft` result
    # doesn't qualify."
    (fonts_root / "FakeBitmap.cft").write_bytes(FIXTURE_TTF.read_bytes())
    monkeypatch.setenv("WFB_FONTS", str(fonts_root))

    device = _device(ppi=326, ww_entries=[
        {"name": "xtiny", "filename": "FakeBitmap", "size": 20, "type": "ttf"},
    ])
    assert "FONT_XTINY" not in device.system_fonts


def test_an_unlocatable_filename_yields_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("WFB_NO_GARMIN_FONTS", raising=False)
    fonts_root = tmp_path / "fonts"
    fonts_root.mkdir()
    monkeypatch.setenv("WFB_FONTS", str(fonts_root))

    device = _device(ppi=326, ww_entries=[
        {"name": "xtiny", "filename": "NoSuchFont", "size": 20, "type": "ttf"},
    ])
    assert "FONT_XTINY" not in device.system_fonts


# -- struct reader: a corrupt/truncated file never raises -------------------


def test_sfnt_head_hhea_returns_none_for_garbage(tmp_path):
    junk = tmp_path / "junk.ttf"
    junk.write_bytes(b"not a font" * 4)
    assert _sfnt_head_hhea(str(junk)) is None


def test_sfnt_head_hhea_reads_the_real_fixture_ttf():
    upm, asc, desc = _read_hhea_with_fonttools(FIXTURE_TTF)
    result = _sfnt_head_hhea(str(FIXTURE_TTF))
    assert result == (upm, asc, desc)
