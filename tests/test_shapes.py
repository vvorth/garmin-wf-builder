"""The `shape:` primitives, one per native `Dc` drawing call.

Three of them -- `arc`, `ellipse` and `polygon` -- and one silent bug -- `filled:
false` being parsed, validated and then ignored on `rectangle` and
`rounded_rectangle` -- arrived together, so they are tested together.

Everything about the polygon constant's *shape* was decided by building rather
than by preference; `docs/research/probes/polygon-const/` is that build.
"""

from __future__ import annotations

import pytest

from tests.test_diagnostics import load
from wfb.emit import generate
from wfb.emit.resources import bake_fonts
from wfb.layout import garmin_arc, resolve

BASE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm, fenix8solar51mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
elements:
  - id: background
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
"""


def design(*elements: str) -> str:
    return BASE + "".join(elements)


ARC = """
  - id: ring
    type: shape
    shape: arc
    at: {anchor: center}
    radius: 50%r
    thickness: 6px
    start_angle: 180deg
    sweep: 340deg
    color: palette.fg
"""

ELLIPSE = """
  - id: pill
    type: shape
    shape: ellipse
    at: {anchor: center}
    size: {width: 40%, height: 20%}
    color: palette.fg
"""

POLYGON = """
  - id: chevron
    type: shape
    shape: polygon
    color: palette.fg
    points:
      - {anchor: center, dy: -10%}
      - {anchor: center, dx: -10%, dy: 10%}
      - {anchor: center, dx: 10%, dy: 10%}
"""


@pytest.fixture
def resolved_for(write_design, bag, db):
    def _resolve(text: str, device_id: str = "fenix8solar47mm"):
        face = load(write_design(text), bag)
        assert face is not None, bag.render()
        device = db.get(device_id)
        return resolve(face, device, bake_fonts(face, device, device.minor_radius))

    return _resolve


@pytest.fixture
def generated_for(write_design, bag, db):
    def _generate(text: str, tmp):
        face = load(write_design(text), bag)
        assert face is not None, bag.render()
        ids = [d for d in face.targets if d in db.ids()]
        if not ids:
            pytest.skip("none of the design's targets are installed")
        devices = [db.get(d) for d in ids]
        reference = min(d.minor_radius for d in devices)
        baked = {d.id: bake_fonts(face, d, reference) for d in devices}
        return generate(face, devices, tmp, baked)

    return _generate


def find(resolved, element_id):
    return next(p for p in resolved.items if p.id == element_id)


# -- one angle convention ---------------------------------------------------


def test_a_plain_arc_and_a_progress_arc_share_one_angle_convention(resolved_for):
    """The reason `garmin_arc` exists: two arcs, one conversion.

    A second convention that agreed on the common cases and disagreed at the
    wrap-around would be invisible until someone drew an arc through 12
    o'clock, which is exactly where a watch face puts them.
    """
    ring = find(resolved_for(design(ARC)), "ring")
    assert ring.start_angle == 180.0                      # author: 6 o'clock
    assert (ring.garmin_start, ring.garmin_direction) == garmin_arc(180.0, 340.0)
    assert ring.garmin_start == 270.0                     # Garmin: 6 o'clock
    assert ring.garmin_direction == "ARC_CLOCKWISE"


def test_a_negative_sweep_reverses_the_direction(resolved_for):
    ring = find(resolved_for(design(ARC.replace("sweep: 340deg", "sweep: -80deg"))), "ring")
    assert ring.sweep == -80.0
    assert ring.garmin_direction == "ARC_COUNTER_CLOCKWISE"


def test_an_arc_resolves_per_device(resolved_for):
    small = find(resolved_for(design(ARC), "fenix8solar47mm"), "ring")
    large = find(resolved_for(design(ARC), "fenix8solar51mm"), "ring")
    assert (small.radius, large.radius) == (65, 70)   # 50% of 130 / 140


def test_an_arcs_extent_is_circular_not_its_bounding_box(resolved_for):
    """A full-width arc must not report as cropped on a round screen -- the
    same reason `PlacedProgress` is special-cased in `circular_extent`."""
    from wfb.layout import circular_extent

    ring = find(resolved_for(design(ARC.replace("radius: 50%r", "radius: 92%r"))), "ring")
    extent = circular_extent(ring)
    assert extent is not None
    assert extent[2] == pytest.approx(ring.radius + ring.thickness / 2.0)


# -- ellipse ----------------------------------------------------------------


def test_an_ellipse_resolves_semi_axes_not_a_box(resolved_for):
    pill = find(resolved_for(design(ELLIPSE)), "pill")
    assert (pill.rx, pill.ry) == (52, 26)             # 40% and 20% of 260
    assert pill.box.width == 104 and pill.box.height == 52


def test_an_outlined_ellipse_reaches_half_a_pen_width_further(resolved_for):
    outlined = ELLIPSE.replace("color: palette.fg",
                               "thickness: 6px\n    filled: false\n    color: palette.fg")
    pill = find(resolved_for(design(outlined)), "pill")
    # The semi-axes handed to drawEllipse are unchanged; only the reach grows.
    assert (pill.rx, pill.ry) == (52, 26)
    assert pill.box.width > 104 and pill.box.height > 52


# -- polygon ----------------------------------------------------------------


def test_polygon_points_resolve_like_a_lines_to(resolved_for):
    chevron = find(resolved_for(design(POLYGON)), "chevron")
    assert chevron.points == ((130, 104), (104, 156), (156, 156))
    # The box is the vertices' own bounding box, not the parent's.
    assert (chevron.box.x, chevron.box.y) == (104, 104)


def test_polygon_points_resolve_per_device(resolved_for):
    small = find(resolved_for(design(POLYGON), "fenix8solar47mm"), "chevron")
    large = find(resolved_for(design(POLYGON), "fenix8solar51mm"), "chevron")
    assert small.points != large.points


# -- `filled:` is honoured, and refused where the platform has no primitive --


def test_filled_false_on_a_rectangle_draws_an_outline(generated_for, tmp_path):
    """Regression: `filled:` was parsed, validated, and then ignored outright --
    `_emit_shape` always called fillRectangle and only `circle` branched."""
    outlined = """
  - id: card
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 40%, height: 20%}
    thickness: 3px
    filled: false
    color: palette.fg
"""
    project = generated_for(design(outlined), tmp_path)
    view = next(s.text for s in project.sources if s.path.endswith("View.mc"))
    assert "dc.setPenWidth(Layout.CARD_THICKNESS);" in view
    assert "dc.drawRectangle(Layout.CARD_X" in view
    assert "dc.fillRectangle(Layout.CARD_X" not in view


def test_filled_false_on_a_rounded_rectangle_draws_an_outline(generated_for, tmp_path):
    outlined = """
  - id: card
    type: shape
    shape: rounded_rectangle
    at: {anchor: center}
    size: {width: 40%, height: 20%}
    corner_radius: 6px
    filled: false
    color: palette.fg
"""
    project = generated_for(design(outlined), tmp_path)
    view = next(s.text for s in project.sources if s.path.endswith("View.mc"))
    assert "dc.drawRoundedRectangle(Layout.CARD_X" in view
    assert "dc.fillRoundedRectangle(Layout.CARD_X" not in view


def test_an_outlined_rectangle_keeps_its_declared_geometry(resolved_for):
    """`box` grows by the pen; the constants handed to drawRectangle do not."""
    outlined = """
  - id: card
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 40%, height: 20%}
    thickness: 5px
    filled: false
    color: palette.fg
"""
    card = find(resolved_for(design(outlined)), "card")
    assert card.rect is not None
    assert (card.rect.width, card.rect.height) == (104, 52)
    assert card.box.width > card.rect.width


def test_a_filled_rectangle_has_no_separate_rect(resolved_for):
    """Nothing changes for the shapes that were already correct."""
    background = find(resolved_for(design()), "background")
    assert background.rect is None
    assert (background.box.width, background.box.height) == (260, 260)


def test_filled_is_refused_on_an_arc(write_design, bag):
    """CLAUDE.md constraint 3: there is no fillArc/fillSector/drawSector."""
    load(write_design(design(ARC.replace("color: palette.fg",
                                         "filled: true\n    color: palette.fg"))), bag)
    errors = [d for d in bag.errors if d.code == "element"]
    assert errors, bag.render()
    assert "no filled-arc primitive" in errors[0].message
    assert any("fillSector" in note for note in errors[0].notes)


def test_filled_false_is_refused_on_a_polygon(write_design, bag):
    """Dc has fillPolygon and no drawPolygon."""
    load(write_design(design(POLYGON.replace("color: palette.fg",
                                             "filled: false\n    color: palette.fg"))), bag)
    errors = [d for d in bag.errors if d.code == "element"]
    assert errors, bag.render()
    assert "no drawPolygon" in errors[0].message


def test_filled_true_is_accepted_on_a_polygon(write_design, bag):
    """Redundant, but not wrong -- only `false` names something impossible."""
    face = load(write_design(design(POLYGON.replace("color: palette.fg",
                                                    "filled: true\n    color: palette.fg"))), bag)
    assert face is not None and bag.ok(), bag.render()


def test_an_arc_needs_a_radius(write_design, bag):
    load(write_design(design(ARC.replace("    radius: 50%r\n", ""))), bag)
    assert any("arc needs a radius" in d.message for d in bag.errors), bag.render()


def test_an_ellipse_needs_a_size(write_design, bag):
    load(write_design(design(ELLIPSE.replace(
        "    size: {width: 40%, height: 20%}\n", ""))), bag)
    assert any("ellipse needs size" in d.message for d in bag.errors), bag.render()


def test_a_polygon_needs_three_points(write_design, bag):
    two = POLYGON.replace("      - {anchor: center, dx: 10%, dy: 10%}\n", "")
    load(write_design(design(two)), bag)
    assert any("at least 3" in d.message for d in bag.errors), bag.render()


def test_a_polygon_is_capped_at_fillpolygons_own_limit(write_design, bag):
    points = "\n".join(f"      - {{dx: {i % 40}px, dy: {i}px}}" for i in range(65))
    over = f"""
  - id: blob
    type: shape
    shape: polygon
    color: palette.fg
    points:
{points}
"""
    load(write_design(design(over)), bag)
    assert any("at most 64" in d.message for d in bag.errors), bag.render()


@pytest.mark.parametrize("key, shape, body", [
    # the keys added alongside arc/ellipse/polygon
    ("points", "circle", "    radius: 6px\n    points: [{dx: -1%}, {dx: 1%}, {dy: 1%}]"),
    ("start_angle", "circle", "    radius: 6px\n    start_angle: 90deg"),
    ("sweep", "circle", "    radius: 6px\n    sweep: 90deg"),
    # and the ones that predate them, silently dropped until now
    ("radius", "rectangle", "    size: {width: 10%, height: 10%}\n    radius: 6px"),
    ("radius", "rounded_rectangle",
     "    size: {width: 10%, height: 10%}\n    corner_radius: 4px\n    radius: 6px"),
    ("corner_radius", "line", "    to: {dx: 10%}\n    corner_radius: 4px"),
    ("to", "circle", "    radius: 6px\n    to: {dx: 10%}"),
    ("size", "circle", "    radius: 6px\n    size: {width: 10%, height: 10%}"),
    ("points", "arc", "    radius: 6px\n    points: [{dx: -1%}, {dx: 1%}, {dy: 1%}]"),
])
def test_a_key_the_shape_does_not_read_is_an_error(write_design, bag, key, shape, body):
    """The same class of bug `filled:` had: parsed, validated, then dropped.

    `radius:` on a rounded_rectangle is the one that actually bites -- the
    author means `corner_radius:`, the corners come out square, and nothing
    says a word.  Most of these predate `SHAPE_GEOMETRY_KEYS`; the table is
    what turned a three-key special case into the whole class.
    """
    wrong = f"""
  - id: dot
    type: shape
    shape: {shape}
    at: {{anchor: center}}
{body}
    color: palette.fg
"""
    load(write_design(design(wrong)), bag)
    assert any(key in d.message and "is not used by" in d.message
               for d in bag.errors), bag.render()


def test_thickness_on_a_filled_shape_is_an_error(write_design, bag):
    """`thickness:` is the pen width of an outline, and a fill has none.

    Checked apart from SHAPE_GEOMETRY_KEYS because whether it is read depends
    on `filled:` rather than on the shape -- a line and an arc always use it.
    """
    wrong = """
  - id: dot
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 6px
    thickness: 3px
    color: palette.fg
"""
    load(write_design(design(wrong)), bag)
    assert any("thickness" in d.message and "is not used by" in d.message
               for d in bag.errors), bag.render()


@pytest.mark.parametrize("shape, body", [
    ("circle", "    radius: 6px\n    filled: false\n    thickness: 3px"),
    ("line", "    to: {dx: 10%}\n    thickness: 3px"),
    ("arc", "    radius: 6px\n    start_angle: 0deg\n    sweep: 90deg\n    thickness: 3px"),
])
def test_thickness_is_accepted_where_it_is_actually_drawn(write_design, bag, shape, body):
    """The other half of the check above: it must not reject a real outline."""
    ok = f"""
  - id: dot
    type: shape
    shape: {shape}
{body}
    at: {{anchor: center}}
    color: palette.fg
"""
    face = load(write_design(design(ok)), bag)
    assert face is not None, bag.render()


# -- codegen ----------------------------------------------------------------


def test_a_polygons_points_are_one_typed_layout_constant(generated_for, tmp_path):
    """ADR 0004: the device does no layout arithmetic, so the vertices are a
    constant here -- and `Point2D` is a fixed-size tuple type, so declaring the
    array as `Array<Array<Number> >` compiles the const and then fails at the
    fillPolygon call site (docs/research/probes/polygon-const/)."""
    project = generated_for(design(POLYGON), tmp_path)
    layout = next(s.text for s in project.sources
                  if s.path == "source-fenix8solar47mm/Layout.mc")
    assert ("const CHEVRON_POINTS as Array<Graphics.Point2D> = "
            "[[130, 104], [104, 156], [156, 156]];") in layout
    # The only reason a Layout module ever imports anything but Toybox.Lang.
    assert "import Toybox.Graphics;" in layout
    view = next(s.text for s in project.sources if s.path.endswith("View.mc"))
    assert "dc.fillPolygon(Layout.CHEVRON_POINTS);" in view


def test_a_layout_without_a_polygon_does_not_import_graphics(generated_for, tmp_path):
    project = generated_for(design(ELLIPSE), tmp_path)
    layout = next(s.text for s in project.sources
                  if s.path == "source-fenix8solar47mm/Layout.mc")
    assert "import Toybox.Graphics;" not in layout


def test_a_plain_arc_draws_through_the_same_barrel_a_progress_track_does(
        generated_for, tmp_path):
    project = generated_for(design(ARC), tmp_path)
    view = next(s.text for s in project.sources if s.path.endswith("View.mc"))
    assert "WfbArc.drawSpan(dc, Layout.RING_CX" in view
    assert "WfbArc.mc" in project.barrel


def test_an_ellipse_picks_fill_or_draw_from_filled(generated_for, tmp_path):
    filled = generated_for(design(ELLIPSE), tmp_path / "a")
    view = next(s.text for s in filled.sources if s.path.endswith("View.mc"))
    assert "dc.fillEllipse(Layout.PILL_CX" in view

    outlined = generated_for(
        design(ELLIPSE.replace("color: palette.fg",
                               "thickness: 3px\n    filled: false\n    color: palette.fg")),
        tmp_path / "b",
    )
    view = next(s.text for s in outlined.sources if s.path.endswith("View.mc"))
    assert "dc.drawEllipse(Layout.PILL_CX" in view
    assert "dc.setPenWidth(Layout.PILL_THICKNESS);" in view


# -- preview ----------------------------------------------------------------


def test_the_preview_draws_every_new_shape(resolved_for):
    """`wfb/preview.py` is the second renderer; a shape it does not know is a
    silent disagreement with the device, which is the one thing sharing the
    resolved geometry exists to prevent."""
    from wfb.preview import PreviewOptions, render

    for element in (ARC, ELLIPSE, POLYGON):
        resolved = resolved_for(design(element))
        image = render(resolved, PreviewOptions(scale=1, mask_shape=False))
        lit = sum(1 for pixel in image.convert("RGB").get_flattened_data() if pixel != (0, 0, 0))
        assert lit > 0, "the shape rendered nothing at all"


def test_the_preview_honours_filled_false(resolved_for):
    from wfb.preview import PreviewOptions, render

    solid = """
  - id: card
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 40%, height: 20%}
    color: palette.fg
"""
    outlined = solid.replace("color: palette.fg", "filled: false\n    color: palette.fg")

    def lit(text: str) -> int:
        image = render(resolved_for(design(text)), PreviewOptions(scale=1, mask_shape=False))
        return sum(1 for pixel in image.convert("RGB").get_flattened_data() if pixel != (0, 0, 0))

    assert 0 < lit(outlined) < lit(solid) / 4


# -- the lint that a new shape could have fooled ----------------------------


#: A design with no filled full-screen rectangle in it, so `_backdrop` has to
#: decide for itself what is behind everything.
NO_BACKGROUND = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
elements:
"""


@pytest.mark.parametrize("covering", [
    # A triangle across three corners: its bounding *box* is the whole screen,
    # its ink is half of it.
    """
  - id: wedge
    type: shape
    shape: polygon
    color: palette.fg
    points:
      - {anchor: top_left}
      - {anchor: top_right}
      - {anchor: bottom_left}
""",
    # An outlined full-screen rectangle paints only its own edge.
    """
  - id: frame
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    thickness: 2px
    filled: false
    color: palette.fg
""",
], ids=["polygon", "outlined-rectangle"])
def test_a_screen_sized_shape_that_paints_a_sliver_is_not_the_backdrop(
        resolved_for, covering):
    """`_backdrop` reads the first shape whose *box* covers the screen, and
    then every other element's contrast is measured against it.  Two of the
    shapes added here can cover the screen with a bounding box while painting
    almost none of it, which would make every contrast warning on the face
    wrong in the same direction at once."""
    from wfb.lint import _backdrop

    resolved = resolved_for(NO_BACKGROUND + covering)
    # palette.bg's black, not the white shape on top of it.
    assert _backdrop(resolved).value == 0x000000
