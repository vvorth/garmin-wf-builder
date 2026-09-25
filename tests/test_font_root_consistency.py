"""Plan 18 item 8: `wfb preview --fonts DIR` used to measure with one font
and draw with another.

`--fonts` used to reach only `PreviewOptions.fonts_root` (`wfb/cli.py`,
`wfb/preview.py`'s own `_system_face`); everything that *measures* --
`wfb.fonts.fallback.measure`/`line_height`/`ascent` (called from
`wfb.layout`, both directly and through `_curve_ascent`/`text_ink`'s own
safe-area re-derivation), the complication-slot measurement in
`wfb.kinds.complication_slot.ComplicationSlotKind.draw_preview`, and `wfb.devices.Device.
system_fonts`' third (derived-metrics) source -- used the *default* font
root regardless. The fix threads one root through `wfb.devices.
DeviceDatabase`/`Device.fonts_root`, read by all three.

Every test here builds its own `DeviceDatabase` (never the session-scoped
`db` fixture, which never overrides `fonts_root`) so a real difference
between "default root" and "overridden root" is what each assertion
actually rests on.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.helpers import find, resolve_design
from wfb.devices import DeviceDatabase, DeviceError
from wfb.diagnostics import Bag
from wfb.fonts import fallback

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "wfb.py"

#: `FONT_NUMBER_HOT`... `FONT_NUMBER_MILD` on `fenix8solar47mm` all resolve
#: to this device-published stem (`ww`'s own `filename`, what `wfb.fonts.
#: fetch_system.locate`/`garmin_any_file` match against, never the `:face`
#: string) -- confirmed against the installed device file, and already the
#: fixed point `tests/test_cli.py::test_preview_fonts_flag_silences_the_
#: warning` and `tests/test_preview_font_warning.py` key their own
#: `--fonts`/`fonts_root` overrides on.
_BIONIC_STEM = "Bionic_semibold"

#: A real, freely-licensed TTF this repo already ships
#: (`wfb/assets/system-fonts/`, installed by `tools/setup-env.sh`) whose
#: glyphs are wide enough to move `_BIONIC_STEM`'s measured advance by a
#: clearly different amount than the registry's own `bionic-substitute`
#: stand-in the default root draws with -- not the *real* Garmin file
#: (this project never ships or fabricates one), just a second, different
#: real face so "the override root's own file" and "the default root's own
#: file" can never measure the same.
_OVERRIDE_FACE = ROOT / "wfb" / "assets" / "system-fonts" / "roboto-black.ttf"


def _default_db() -> DeviceDatabase:
    try:
        db = DeviceDatabase.discover()
    except DeviceError as exc:
        pytest.skip(str(exc))
    if "fenix8solar47mm" not in db.ids():
        pytest.skip("fenix8solar47mm is not installed")
    return db


def _require_override_face() -> None:
    if not _OVERRIDE_FACE.is_file():
        pytest.skip(f"{_OVERRIDE_FACE} is not installed")


DESIGN = """
format: 1
face:
  id: 3a1c9e02-6b4d-4a1a-9f3e-0c7b5d2a6e11
  name: FontsRootTest
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
elements:
  - id: label
    type: text
    text: "8888"
    font: FONT_NUMBER_HOT
    align: center
    vertical_align: center
    at: {anchor: center}
    color: palette.fg
"""


# -- 1. layout measures with the `--fonts` root, not the default one -------


def test_layout_measures_with_the_database_fonts_root(write_design, tmp_path):
    """A `DeviceDatabase` built with a `fonts_root` override must resolve a
    text element's width from *that* file, not the default root's stand-in
    -- the exact contrast plan 18 item 8 names: layout measured with one
    font while (before the fix) drawing used another.
    """
    default_db = _default_db()
    _require_override_face()

    design = write_design(DESIGN)

    default_resolved = resolve_design(design, Bag(), default_db, "fenix8solar47mm")
    default_width = find(default_resolved, "label").measured_width

    fonts_root = tmp_path / "fonts"
    fonts_root.mkdir()
    (fonts_root / f"{_BIONIC_STEM}.ttf").write_bytes(_OVERRIDE_FACE.read_bytes())

    override_db = DeviceDatabase.discover(fonts_root=fonts_root)
    override_resolved = resolve_design(design, Bag(), override_db, "fenix8solar47mm")
    override_placed = find(override_resolved, "label")

    # Not merely "different from the default" -- exactly what a direct
    # `fallback.measure` of the override file reports, so this is checking
    # *which* file was measured with, not just that something changed.
    metric = override_db.get("fenix8solar47mm").system_fonts["FONT_NUMBER_HOT"]
    expected_width, from_real_metrics = fallback.measure(
        "8888", metric, fonts_root=override_db.fonts_root)
    assert from_real_metrics
    assert override_placed.measured_width == expected_width
    assert override_placed.measured_width != default_width


# -- 2. fenix947mm's derived metrics need the database's own root ----------


#: `~/.Garmin/ConnectIQ/Fonts` -- the user's own licensed copy
#: (`wfb.fonts.fetch_system.garmin_font_root`'s own candidate 4), used here
#: directly (not through `WFB_FONTS`/`WFB_NO_GARMIN_FONTS`) so this test
#: exercises `DeviceDatabase(fonts_root=...)`/`Device.fonts_root` itself,
#: never the environment-variable search order `tests/test_derived_font_
#: metrics.py` already covers.
_GARMIN_FONTS_DIR = Path.home() / ".Garmin" / "ConnectIQ" / "Fonts"


def test_fenix9_gets_derived_metrics_only_through_the_database_root():
    """`fenix947mm` has no scraped reference page at all (plan 17), so its
    system-font metrics can only come from the third, derived source --
    which needs a real `.ttf` under *some* Garmin font root. The session-
    wide `WFB_NO_GARMIN_FONTS=1` (`tests/conftest.py`) makes the ordinary
    search order find nothing, so the default database gets none; only a
    `DeviceDatabase` built with an explicit `fonts_root` -- what `--fonts`
    ends up setting -- reaches the file and gets them.
    """
    default_db = _default_db()
    if "fenix947mm" not in default_db.ids():
        pytest.skip("fenix947mm is not installed")
    if not _GARMIN_FONTS_DIR.is_dir():
        pytest.skip(f"{_GARMIN_FONTS_DIR} is not present on this machine")

    without_root = default_db.get("fenix947mm")
    assert without_root.system_fonts == {}

    with_root_db = DeviceDatabase.discover(fonts_root=_GARMIN_FONTS_DIR)
    with_root = with_root_db.get("fenix947mm")
    assert "FONT_XTINY" in with_root.system_fonts
    assert with_root.system_fonts["FONT_XTINY"].size_px > 0


# -- 3. measurement and drawing agree: `wfb preview --fonts` moves layout --


def _run_preview(*args: str):
    import subprocess

    return subprocess.run(
        [sys.executable, str(ENTRY), "preview", *args],
        capture_output=True, cwd=str(ROOT), check=False,
    )


#: A text box positioned so its right edge sits just inside
#: `fenix8solar47mm`'s visible round area at the *default* root's own
#: measured width, and just outside it once the wider `_OVERRIDE_FACE` is
#: measured instead (picked by direct search against the real resolver --
#: see the exploration this file's own history records). If this ever
#: drifts (a registry/stand-in change), the two `assert`s below would both
#: see the same warning and fail loudly rather than silently passing.
OVERFLOW_DESIGN = """
format: 1
face:
  id: 5c2e8a14-7d3b-4f9a-8e1c-2b6a4d9f0c33
  name: OverflowRootTest
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
elements:
  - id: label
    type: text
    text: "8888"
    font: FONT_NUMBER_MILD
    align: left
    vertical_align: center
    at: {anchor: center, angle: 90deg, radius: 30px}
    color: palette.fg
"""


def test_preview_fonts_flag_moves_the_layout_not_just_the_drawing(tmp_path):
    """The bug's own shape: before the fix, `--fonts DIR` reached
    `PreviewOptions.fonts_root` (drawing) but never the `DeviceDatabase`
    (measuring), so `wfb.layout`'s own box -- and every lint that reads it,
    `text-overflow` here -- never moved. Without `--fonts` the design's own
    text fits (measured against the default stand-in); pointing `--fonts`
    at a directory with a wider real face for the same device-published
    file name must make the *same* design's layout widen enough to trip
    `text-overflow`/`off-screen` -- proof the override reached measurement,
    not only the pixels drawn.
    """
    _default_db()
    _require_override_face()

    design = tmp_path / "face.yaml"
    design.write_text(OVERFLOW_DESIGN, encoding="utf-8")

    baseline = _run_preview(str(design), "-d", "fenix8solar47mm", "-o", "-")
    assert baseline.returncode == 0, baseline.stderr.decode()
    assert "text-overflow" not in baseline.stderr.decode()

    fonts_root = tmp_path / "fonts"
    fonts_root.mkdir()
    (fonts_root / f"{_BIONIC_STEM}.ttf").write_bytes(_OVERRIDE_FACE.read_bytes())

    overridden = _run_preview(str(design), "-d", "fenix8solar47mm", "-o", "-",
                              "--fonts", str(fonts_root))
    assert overridden.returncode == 0, overridden.stderr.decode()
    stderr = overridden.stderr.decode()
    assert "text-overflow" in stderr
    assert "104px" in stderr
