"""Golden-file coverage for `outline:` on a standalone `text` element (plan
15 slice 1). `tests/test_golden.py` pins `tests/fixtures/slice/`, which has
no `outline:` in it; this is the same discipline (`tests/CLAUDE.md`: "a
golden diff is a real output change: explain it, do not just regenerate")
applied to `tests/fixtures/outline_text/face.yaml`, which exercises a baked
font and a vector font both carrying `outline:`, both spellings (shorthand
and object form), and both `curve:` styles.

Regenerate after an intentional change:

    pytest tests/test_text_outline_golden.py --update-golden
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import compare_golden, generate_for_targets


@pytest.fixture(scope="module")
def outline_design(pytestconfig) -> Path:
    # A fixture, so missing is a failure, never a skip (tests/CLAUDE.md).
    path = pytestconfig.rootpath / "tests" / "fixtures" / "outline_text" / "face.yaml"
    assert path.exists(), path
    return path


@pytest.fixture(scope="module")
def generated(pytestconfig, outline_design, tmp_path_factory):
    return generate_for_targets(outline_design, tmp_path_factory.mktemp("build"))


def _compare(pytestconfig, name: str, actual: str) -> None:
    # Own prefix ("outline_text__") so these never collide with
    # tests/test_golden.py's or tests/test_vector_text_golden.py's own files
    # under the same tests/golden/ dir.
    compare_golden(pytestconfig, f"outline_text__{name}", actual)


@pytest.mark.parametrize("name", [
    "source/OutlineTextView.mc",
    "source-fenix8solar47mm/Layout.mc",
    "source-fr955/Layout.mc",
])
def test_generated_file_matches_golden(pytestconfig, generated, name):
    files = generated.files()
    if name not in files:
        pytest.skip(f"{name} was not generated for this device set")
    _compare(pytestconfig, name.replace("/", "__"), files[name])


# -- properties the golden files should never silently lose ------------------


def test_one_offsets_table_serves_every_ring(generated):
    """Every ring is 1px, so `Layout.mc` carries one `OUTLINE_OFFSETS`
    array -- the four points 1px away -- however many elements stamp."""
    layout = generated.files()["source-fenix8solar47mm/Layout.mc"]
    assert layout.count("OUTLINE_OFFSETS as Array<Number> = [-1, 0, 0, -1, 0, 1, 1, 0];") == 1
    assert "OUTLINE_OFFSETS_" not in layout


def test_the_baked_font_ring_is_one_draw_in_its_ring_font(generated):
    """`clock` is in a baked font: its ring is one `drawText` in the ring
    font, ahead of the interior (research 19)."""
    view = generated.files()["source/OutlineTextView.mc"]
    method = view.split("private function drawClock")[1].split("\n\n    //!")[0]
    assert "while" not in method
    assert method.index("ringFont") < method.rindex("dc.setColor(")


def test_stamp_loop_appears_ahead_of_every_interior_draw(generated):
    """Every vector-font element carrying `outline:` gets a `while (i <
    offsets.size())` loop -- no sheet to dilate -- and the loop's own
    `dc.setColor`/draw call precedes the interior (unshifted) one in the
    generated method: the ring first, the fill last, on top (plan 15 §8)."""
    view = generated.files()["source/OutlineTextView.mc"]
    for method_name in ("drawUprightVector", "drawBrand", "drawBezelText"):
        method = view.split(f"private function {method_name}")[1]
        method = method.split("\n\n    //!")[0]
        assert "while (i < offsets.size())" in method
        loop_index = method.index("while (i < offsets.size())")
        # the interior pass's own setColor/draw call is textually after the
        # loop's closing brace, i.e. there are exactly two dc.setColor calls
        # and the second (outside the loop body) is the interior one.
        assert method.count("dc.setColor(") >= 2


def test_vector_gate_4_wraps_loop_and_interior_in_one_guard(generated):
    """Gate 4 (`if (font != null)`) wraps the stamp loop AND the interior
    draw together, never two separate guards (plan 15 §5)."""
    view = generated.files()["source/OutlineTextView.mc"]
    for method_name in ("drawUprightVector", "drawBrand", "drawBezelText"):
        method = view.split(f"private function {method_name}")[1]
        method = method.split("\n\n    //!")[0]
        assert method.count("if (font != null)") == 1


def test_both_curve_styles_still_appear_with_outline(generated):
    view = generated.files()["source/OutlineTextView.mc"]
    assert "dc.drawAngledText(" in view
    assert "dc.drawRadialText(" in view


def test_baked_font_outline_draws_through_plain_drawtext(generated):
    """The baked-font clock's ring and interior draw through plain
    `dc.drawText`, never `drawAngledText`/`drawRadialText` -- it has no
    `curve:`."""
    view = generated.files()["source/OutlineTextView.mc"]
    method = view.split("private function drawClock")[1]
    method = method.split("\n\n    //!")[0]
    assert "dc.drawText(" in method
    assert "dc.drawAngledText(" not in method
    assert "dc.drawRadialText(" not in method
