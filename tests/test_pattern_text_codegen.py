"""Codegen for pattern text parts (plan 06 §3.4, phase B2): the barrel
helper, the `Layout` constants, and the draw calls `wfb/emit/monkeyc/rotated.py`
emits for a `shape: text` pattern part.

Phase B1 (`tests/test_pattern_text.py`) already covers schema, IR, layout
and the glyph lint; this only exercises what changed here -- the view and
`Layout` module text, asserted the same way `tests/test_hands_codegen.py`
does for analog hands.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wfb.build import load
from wfb.diagnostics import Bag
from wfb.emit.monkeyc import emit_layout, emit_view
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve

ROOT = Path(__file__).resolve().parent.parent
OPEN_SANS = ROOT / "tests/fixtures/slice/assets/OpenSans-Regular.ttf"

BASE = """
format: 1
face: {id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}
targets: [fenix8solar47mm]
palette: {bg: "#000000", fg: "#FFFFFF"}
"""

#: Radial: twelve hour numerals, the exact plan §3.1 example, in the system
#: default font (FONT_MEDIUM) -- no `fonts:` block needed.
HOURS = """  - id: hours
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 12
    color: palette.fg
    parts:
      - shape: text
        value: "(copy + 11) % 12 + 1"
        at: {dy: -80%r}
"""

#: Linear: a three-copy row with a literal `text:` part, one custom font
#: (`font.small`), and a non-constant per-part `visible:` that reads only
#: `copy` -- exercises the font-loading, literal-value and visible-gate
#: paths a HOURS-only fixture would not.
ROW = f"""fonts:
  small:
    source: {OPEN_SANS}
    size: 20px
elements:
  - id: row
    type: pattern
    pattern: linear
    at: {{anchor: center}}
    count: 3
    step: {{dx: 20px}}
    color: palette.fg
    parts:
      - shape: text
        text: "x"
        font: font.small
        visible: "copy < 2"
"""


def _design(text: str) -> str:
    return BASE + "\n" + text


@pytest.fixture
def hours_resolved(write_design, bag, db):
    face = load(write_design(_design("elements:\n" + HOURS)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device))


@pytest.fixture
def hours_layout_text(hours_resolved):
    return emit_layout(hours_resolved).text


@pytest.fixture
def hours_view_text(hours_resolved):
    return emit_view(hours_resolved).text


@pytest.fixture
def row_resolved(write_design, bag, db):
    face = load(write_design(_design(ROW)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device))


@pytest.fixture
def row_layout_text(row_resolved):
    return emit_layout(row_resolved).text


@pytest.fixture
def row_view_text(row_resolved):
    return emit_view(row_resolved).text


# -- Layout constants ---------------------------------------------------------


def test_a_text_part_gets_x_y_constants_and_nothing_else(hours_layout_text):
    assert "const HOURS_0_X as Number" in hours_layout_text
    assert "const HOURS_0_Y as Number" in hours_layout_text
    assert "HOURS_0_RADIUS" not in hours_layout_text
    assert "HOURS_0_THICKNESS" not in hours_layout_text
    assert "HOURS_0_POINTS" not in hours_layout_text


# -- radial draw: WfbGeom.rotatedX/rotatedY ----------------------------------


def test_radial_text_part_calls_draw_text_rotated_with_the_anchor_and_trig(hours_view_text):
    # A single 10-argument `drawTextRotated` call doesn't compile on CIQ 3.x
    # (docs/lore/monkeyc.md), so the rotate-the-point step is split into
    # `rotatedX`/`rotatedY`, each fed straight into `dc.drawText`.
    assert "dc.drawText(WfbGeom.rotatedX(Layout.HOURS_0_X, Layout.HOURS_0_Y, cx, sin, cos)," in hours_view_text
    assert "WfbGeom.rotatedY(Layout.HOURS_0_X, Layout.HOURS_0_Y, cy, sin, cos)," in hours_view_text


def test_radial_text_value_compiles_copy_to_the_loop_index(hours_view_text):
    # `value: "(copy + 11) % 12 + 1"` -- `copy` compiles to the loop's `i`
    # (the same binding a pattern colour or `visible:` already uses), so the
    # generated value expression reads `i`, not `copy`.
    method = hours_view_text.split("private function drawHours")[1]
    assert "((i + 11) % 12) + 1" in method or "(i + 11) % 12 + 1" in method
    assert "copy" not in method.split("for (")[1].split("\n\n")[0]


def test_radial_pattern_declares_sin_and_cos_for_a_text_part(hours_view_text):
    method = hours_view_text.split("private function drawHours")[1]
    loop_setup = method.split("for (var i = 0")[1]
    assert "var sin = Math.sin(angle);" in loop_setup
    assert "var cos = Math.cos(angle);" in loop_setup


# -- linear draw: plain dc.drawText ------------------------------------------


def test_linear_text_part_calls_plain_draw_text_off_ox_oy(row_view_text):
    assert "dc.drawText(ox + Layout.ROW_0_X, oy + Layout.ROW_0_Y," in row_view_text
    assert "WfbGeom.rotatedX" not in row_view_text
    assert "WfbGeom.rotatedY" not in row_view_text


def test_literal_text_emits_the_quoted_literal(row_view_text):
    assert '"x"' in row_view_text


# -- custom font loading ------------------------------------------------------


def test_the_custom_font_is_loaded_into_a_local_before_the_loop(row_view_text):
    method = row_view_text.split("private function drawRow")[1]
    method = method.split("\n\n    //!")[0]
    load_at = method.index("var font0 = _fontSmall;")
    guard_at = method.index("if (font0 == null)")
    loop_at = method.index("for (")
    assert load_at < guard_at < loop_at


def test_the_custom_font_is_referenced_by_its_local_in_the_draw_call(row_view_text):
    assert "font0," in row_view_text


def test_the_custom_font_is_in_loaded_fonts_so_on_layout_loads_it(row_view_text):
    assert "_fontSmall = WatchUi.loadResource(Rez.Fonts." in row_view_text


# -- visible: gate -------------------------------------------------------------


def test_the_parts_visible_wraps_the_draw_call(row_view_text):
    method = row_view_text.split("private function drawRow")[1]
    method = method.split("\n\n    //!")[0]
    visible_at = method.index("if ((i < 2))")
    draw_at = method.index("dc.drawText(ox + Layout.ROW_0_X")
    assert visible_at < draw_at


# -- the barrel ---------------------------------------------------------------


def test_wfb_geom_has_rotated_x_and_y_rounding_half_up():
    # `drawTextRotated` combined all ten arguments into one call, past CIQ
    # 3.x's 9-parameter ceiling (docs/lore/monkeyc.md); it is split into
    # `rotatedX`/`rotatedY`, each still rounding half up.
    barrel = (ROOT / "runtime-lib/WfbGeom.mc").read_text()
    assert "function rotatedX" in barrel
    assert "function rotatedY" in barrel
    assert "function drawTextRotated" not in barrel
    assert barrel.count("+ 0.5).toNumber()") >= 2


# -- real toolchain: the CIQ 3.x regression itself ---------------------------


@pytest.mark.slow
def test_a_radial_text_part_compiles_on_ciq_3x(write_design, tmp_path, db, toolchain):
    """Found 2026-09-18: a combined `WfbGeom.drawTextRotated(dc, x, y, cx,
    cy, sin, cos, font, text, justify)` call is 10 arguments, and CIQ 3.x
    rejects a function past 9 outright -- `monkeyc` failed fenix6/
    fenix6xpro/fr245 with "Too many arguments passed to method
    'drawTextRotated'. Only 9 arguments are allowed." (docs/lore/monkeyc.md).
    `tests/test_parameter_limits.py` proves the *shape* of every signature
    with no toolchain; this is the one test that proves a radial `shape:
    text` pattern part -- the HOURS fixture above -- actually compiles with
    the real `monkeyc`, on the oldest and smallest of the three affected
    devices.
    """
    from wfb.build import build

    if "fenix6" not in db.ids():
        pytest.skip("fenix6 is not installed")
    design = write_design(_design("elements:\n" + HOURS))
    bag = Bag()
    result = build(design, output=tmp_path, bag=bag, db=db, toolchain=toolchain,
                   devices_only=["fenix6"])
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    assert set(result.products) == {"fenix6"}
