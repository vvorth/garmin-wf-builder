"""Golden-file coverage for vector fonts and `curve:` (plan 11 slice 1,
step 3 -- codegen). `tests/test_golden.py` pins `tests/fixtures/slice/`,
which has no vector font in it; this is the same discipline
(`tests/CLAUDE.md`: "a golden diff is a real output change: explain it, do
not just regenerate") applied to `tests/fixtures/vector_text/face.yaml`,
which exercises a baked font and a vector font in the same face, both
`curve:` styles, and plain upright vector text.

Regenerate after an intentional change:

    pytest tests/test_vector_text_golden.py --update-golden
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import compare_golden, generate_for_targets


@pytest.fixture(scope="module")
def vector_design(pytestconfig) -> Path:
    # A fixture, so missing is a failure, never a skip (tests/CLAUDE.md).
    path = pytestconfig.rootpath / "tests" / "fixtures" / "vector_text" / "face.yaml"
    assert path.exists(), path
    return path


@pytest.fixture(scope="module")
def generated(pytestconfig, vector_design, tmp_path_factory):
    return generate_for_targets(vector_design, tmp_path_factory.mktemp("build"))


def _compare(pytestconfig, name: str, actual: str) -> None:
    # Own prefix ("vector_text__") so these never collide with
    # tests/test_golden.py's own files under the same tests/golden/ dir.
    compare_golden(pytestconfig, f"vector_text__{name}", actual)


@pytest.mark.parametrize("name", [
    "source/VectorTextView.mc",
    "source-fenix8solar47mm/Layout.mc",
    "source-fr955/Layout.mc",
])
def test_generated_file_matches_golden(pytestconfig, generated, name):
    files = generated.files()
    if name not in files:
        pytest.skip(f"{name} was not generated for this device set")
    _compare(pytestconfig, name.replace("/", "__"), files[name])


# -- properties the golden files should never silently lose ----------------


def test_bezel_uses_getvectorfont_not_loadresource(generated):
    """A vector and a baked font coexist in one face, loaded two different
    ways: `Graphics.getVectorFont` for the vector one, `WatchUi.
    loadResource(Rez.Fonts....)` for the baked one -- never the other way
    round for either."""
    view = generated.files()["source/VectorTextView.mc"]
    assert "_fontBezel = Graphics.getVectorFont(" in view
    assert "_fontBezel = WatchUi.loadResource(" not in view
    assert "_fontClock = WatchUi.loadResource(Rez.Fonts." in view
    assert "_fontClock = Graphics.getVectorFont(" not in view


def test_no_font_resource_or_glyph_set_for_the_vector_font(generated):
    """Plan 11 step 3's own headline fix: a vector font contributes no
    `<font>` resource and no glyph set, because there is no sheet."""
    fonts_xml = generated.files()["resources-fenix8solar47mm/fonts/fonts.xml"]
    assert "bezel" not in fonts_xml
    assert "RobotoCondensed" not in fonts_xml


def test_both_curve_styles_appear(generated):
    view = generated.files()["source/VectorTextView.mc"]
    assert "dc.drawAngledText(" in view
    assert "dc.drawRadialText(" in view
    layout = generated.files()["source-fenix8solar47mm/Layout.mc"]
    assert "const BRAND_ANGLE as Float" in layout
    assert "const BEZEL_TEXT_ANGLE as Float" in layout
    assert "const BEZEL_TEXT_RADIUS as Number" in layout


def test_upright_vector_text_uses_plain_drawtext(generated):
    view = generated.files()["source/VectorTextView.mc"]
    method = view.split("private function drawUprightVector")[1]
    method = method.split("\n\n    //!")[0]
    assert "dc.drawText(" in method
    assert "dc.drawAngledText(" not in method
    assert "dc.drawRadialText(" not in method


def test_gate_4_null_check_present_for_every_vector_draw(generated):
    view = generated.files()["source/VectorTextView.mc"]
    for method_name in ("drawUprightVector", "drawBrand", "drawBezelText"):
        method = view.split(f"private function {method_name}")[1]
        method = method.split("\n\n    //!")[0]
        assert "if (font != null)" in method


def test_every_target_resolves_so_no_available_guard_is_emitted(generated):
    """Every one of this design's three targets (`fenix8solar47mm`/`51mm`/
    `fr955`) publishes RobotoCondensedBold (plan 11 §1's own verified
    claim) -- so the plain, unguarded construction form is generated, not
    the `if (Layout.FONT_BEZEL_AVAILABLE && ...)` one, and no `_AVAILABLE`
    constant is emitted at all ("no guard for a thing every target has")."""
    view = generated.files()["source/VectorTextView.mc"]
    assert "FONT_BEZEL_AVAILABLE" not in view
    layout = generated.files()["source-fenix8solar47mm/Layout.mc"]
    assert "FONT_BEZEL_AVAILABLE" not in layout
    on_layout = view.split("function onLayout")[1].split("\n    }")[0]
    assert "if (Layout.FONT_BEZEL_AVAILABLE" not in on_layout
    assert "_fontBezel = Graphics.getVectorFont(" in on_layout
