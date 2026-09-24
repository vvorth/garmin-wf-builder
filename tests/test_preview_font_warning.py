"""Plan 12 (`docs/plans/12-preview-font-fidelity.md`) slice 1, R1: `wfb
preview` reports the faces it actually drew with.

`wfb.fonts.fallback.system_face` already carries a `.match` level
(`"garmin"`/`"exact"`/`"family"`/`"substitute"`/`"none"`) and a `.path`; the
only thing missing before this plan was anywhere that *said* so. These tests
drive `wfb.preview.render`'s own `used_faces` collector and
`wfb.preview.stand_in_warning` directly -- the same two pieces
`wfb.cli._render_preview` wires together for the real CLI warning
(`tests/test_cli.py` covers that wiring end to end, including that `-o -`
does not suppress it).

Every test here goes through the session-wide `WFB_NO_GARMIN_FONTS=1`
(`tests/conftest.py`) for its "no root" half, so the red case never depends
on whether this machine happens to hold the user's own licensed Garmin
fonts (`vendor/fonts/` is gitignored, but not empty on every machine that
runs this suite) -- and the green case points `fonts_root` at an isolated
`tmp_path` directory instead of relying on that same machine state, for the
same reason.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wfb.build import load
from wfb.emit.resources import bake_fonts
from wfb.fonts import fetch_system
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render, stand_in_warning

#: A real TTF this repo already ships for font tests (`tests/CLAUDE.md`) --
#: reused here as stand-in bytes for "the real Garmin file", since
#: `wfb.fonts.fetch_system.locate`'s `"garmin"` match is decided by the
#: located file's *name and location*, never its contents (`wfb.fonts.
#: fallback.system_face`'s own `_pillow_fallback` branch reports `"garmin"`
#: even when the file fails to parse at all) -- a green test does not need
#: Garmin's own proprietary bytes to prove the root is being consulted.
_REAL_FONT_STAND_IN = (
    Path(__file__).resolve().parent / "fixtures" / "slice" / "assets" / "OpenSans-Regular.ttf"
)

#: `FONT_NUMBER_HOT` on `fenix8solar47mm` resolves to `Bionic_semibold`
#: (`docs/plans/12-preview-font-fidelity.md` §1.1's own worked example),
#: which `wfb/fonts/registry.json`'s `names` table maps to the
#: `bionic-substitute` free stand-in, match `"substitute"` -- a different
#: family entirely, not a free release of Bionic itself
#: (`tests/test_font_registry.py`).
DESIGN = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
elements:
  - id: label
    type: text
    text: "88"
    font: FONT_NUMBER_HOT
    align: center
    vertical_align: center
    at: {anchor: center}
    color: palette.fg
"""


def _resolved(write_design, bag, db):
    face = load(write_design(DESIGN), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device))


def _require_bionic_substitute() -> None:
    if fetch_system.path_for("bionic-substitute") is None:
        pytest.skip("bionic-substitute.ttf is not installed at wfb/assets/system-fonts/")


def test_a_stand_in_font_is_named_in_the_warning(write_design, bag, db):
    """R1.2/R1.6 (red): with no Garmin font root at all (the session-wide
    `WFB_NO_GARMIN_FONTS=1`), `FONT_NUMBER_HOT` resolves to the free
    `bionic-substitute` stand-in, not Bionic itself -- `render`'s own
    `used_faces` records exactly that face at match `"substitute"`, and
    `stand_in_warning` turns it into one block naming the affected font,
    what was drawn instead, and how to fix it."""
    _require_bionic_substitute()
    resolved = _resolved(write_design, bag, db)

    used: dict = {}
    render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False), used_faces=used)

    assert len(used) == 1
    (face,) = used.values()
    assert face.match == "substitute"

    warning = stand_in_warning(used)
    assert warning is not None
    assert "warning:" in warning
    assert "Bionic" in warning
    assert "bionic-substitute.ttf" in warning
    assert "(substitute)" in warning
    assert "wfb doctor" in warning


def test_a_garmin_root_face_draws_silently(write_design, bag, db, tmp_path):
    """R1.2/R1.5/R1.6 (green): pointing `fonts_root` (what `--fonts DIR`
    sets `PreviewOptions.fonts_root` to) at a directory holding a file
    named exactly like the device's own `Bionic_semibold` stem makes
    `fetch_system.locate` report match `"garmin"` -- outranking the
    registry stand-in even though the *bytes* are not Garmin's own
    (`_REAL_FONT_STAND_IN`'s own docstring) -- and a `"garmin"` match is
    never warned about (R1.3): the whole run is silent."""
    _require_bionic_substitute()
    resolved = _resolved(write_design, bag, db)

    font_root = tmp_path / "fonts"
    font_root.mkdir()
    (font_root / "Bionic_semibold.ttf").write_bytes(_REAL_FONT_STAND_IN.read_bytes())

    used: dict = {}
    render(
        resolved,
        PreviewOptions(scale=1, mask_shape=False, quantise=False, fonts_root=str(font_root)),
        used_faces=used,
    )

    assert len(used) == 1
    (face,) = used.values()
    assert face.match == "garmin"
    assert stand_in_warning(used) is None


def test_an_exact_registry_match_is_never_warned_about(write_design, bag, db):
    """R1.3: `exact`/`family` share the real letterforms (a free release of
    the very same, or a closely related, typeface) -- only `substitute`/
    `none` change the glyph shapes, so a design that only ever touches an
    `exact`-matched symbol (`FONT_MEDIUM` -> `RobotoCondensed-Bold`, plan
    09's own worked example) must stay silent even with no Garmin root."""
    if fetch_system.path_for("roboto-condensed-bold") is None:
        pytest.skip("roboto-condensed-bold.ttf is not installed at wfb/assets/system-fonts/")
    design = DESIGN.replace("font: FONT_NUMBER_HOT", "font: FONT_MEDIUM")
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))

    used: dict = {}
    render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False), used_faces=used)

    assert len(used) == 1
    (face_used,) = used.values()
    assert face_used.match == "exact"
    assert stand_in_warning(used) is None


def test_used_faces_none_costs_nothing_and_nothing_is_collected(write_design, bag, db):
    """A bare `render(resolved, options)` call -- every test elsewhere in
    this repo, and any direct caller that does not care -- must keep
    working exactly as before: no `used_faces` dict means no collection
    and no warning to compute, not a crash."""
    resolved = _resolved(write_design, bag, db)
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))
    assert image is not None
