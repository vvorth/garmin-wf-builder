"""`wfb.draw`: the program's printer and evaluator, and how the view and the
preview reach a kind's program.

No kind lowers yet, so these build small programs by hand from an element's
own `Layout` constants:

- the printer writes each op the way the hand-written emitters do;
- the evaluator paints each `Dc` primitive, and a text call, exactly as
  today's preview paints the same element;
- a kind that returns a program from `lower` is printed by the view and
  painted by the preview, and neither of its old methods is called.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageDraw

from tests.helpers import find, resolved_example
from wfb import kinds, preview
from wfb.catalog import Type
from wfb.draw import evaluator, printer
from wfb.draw.program import (
    ArcSpan, Blank, Color, Comment, Const, DrawContext, FillPolygon, Font, Grown, IfAod,
    IfNotNull, LetText, Lit, LoadFont, Local, Primitive, Reading, SetColor, SetPen, Shifted,
    StrLit, Text,
)
from wfb.emit.monkeyc.common import NO_AOD, const_prefix
from wfb.emit.monkeyc.view import emit_view
from wfb.emit.writer import Writer

SHAPES = Path("examples/features/shapes/face.yaml")
TEXT = Path("examples/system-fonts/text/face.yaml")
DEVICE = "fenix8solar47mm"


def _renderer(resolved, scale: int = 2, aod: bool = False) -> preview.Renderer:
    values = dict(preview.SAMPLE)
    for name, color in resolved.face.palette.items():
        values.setdefault(f"palette.{name}", color.value)
    image = Image.new("RGB", (resolved.device.width * scale, resolved.device.height * scale))
    return preview.Renderer(resolved, ImageDraw.Draw(image), image, scale, values,
                            preview.PreviewOptions(scale=scale, aod=aod))


def _differing(a: Image.Image, b: Image.Image) -> int:
    return sum(1 for v in ImageChops.difference(a, b).convert("L").tobytes() if v)


def _constants(placed) -> dict[str, Const]:
    prefix = const_prefix(placed.id)
    return {name.removeprefix(prefix + "_"): Const(name, value)
            for name, value, _ in kinds.for_placed(placed).layout_constants(prefix, placed)}


_FILLABLE = {
    "rectangle": ("Rectangle", (("X", "Y"), ("WIDTH", "HEIGHT"))),
    "rounded_rectangle": ("RoundedRectangle", (("X", "Y"), ("WIDTH", "HEIGHT"), ("CORNER",))),
    "ellipse": ("Ellipse", (("CX", "CY"), ("RX", "RY"))),
    "circle": ("Circle", (("CX", "CY", "RADIUS"),)),
}


def _shape_program(placed) -> list:
    """What a plain (unringed) shape draws, from its own constants."""
    e, c = placed.element, _constants(placed)
    ops: list = [SetColor(Color(e.color))]
    if e.shape in _FILLABLE:
        name, groups = _FILLABLE[e.shape]
        args = tuple(tuple(c[s] for s in group) for group in groups)
        if e.filled:
            return ops + [Primitive(f"fill{name}", args)]
        pen = Lit(placed.thickness) if e.shape == "circle" else c["THICKNESS"]
        return ops + [SetPen(pen), Primitive(f"draw{name}", args), SetPen(None)]
    if e.shape == "arc":
        return ops + [ArcSpan(c["CX"], c["CY"], c["RADIUS"], c["THICKNESS"], c["START"],
                              c["SWEEP"])]
    if e.shape == "polygon":
        return ops + [FillPolygon(f"{const_prefix(placed.id)}_POINTS", tuple(placed.points))]
    return ops + [SetPen(c["THICKNESS"]),
                  Primitive("drawLine", ((c["CX"], c["CY"], c["END_X"], c["END_Y"]),)),
                  SetPen(None)]


def _plain_shapes(resolved):
    return [p for p in resolved.shown_items
            if p.kind == "shape" and p.element.outline is None and p.element.aod is None]


# -- the printer ------------------------------------------------------------------


def test_the_printer_writes_each_op_as_the_emitters_do(db):
    resolved = resolved_example(TEXT, db, DEVICE)
    label = next(p for p in resolved.shown_items if p.kind == "text")
    x, y = Const("A_X", 10), Const("A_Y", 20)
    font = Font("Graphics.FONT_SMALL")
    w = Writer()
    printer.print_ops(w, [
        Comment("a comment"),
        SetColor(Color(None)),
        SetPen(Lit(3)),
        Primitive("fillRoundedRectangle", ((Shifted(Const("A_X", 1), -1), Const("A_Y", 2)),
                                           (Grown(Const("A_WIDTH", 3), 2, 2), Lit(4)),
                                           (Lit(5),))),
        SetPen(None),
        FillPolygon("A_POINTS", ((0, 0), (1, 0), (0, 1))),
        ArcSpan(x, y, Const("A_RADIUS", 30), Const("A_THICKNESS", 2), Const("A_START", 90.0),
                Const("A_SWEEP", -45.0)),
        Blank(),
        LoadFont("font", "_fontDigits"),
        LetText(StrLit("--"), StrLit("12"), ("heartRateCurrent",)),
        IfNotNull("font", (Text(x, y, font, Local("text"), ("TEXT_JUSTIFY_LEFT",), "bottom"),)),
        IfAod((Text(x, y, font, StrLit("a"), ("TEXT_JUSTIFY_CENTER",), "top"),),
              (Text(x, y, font, StrLit("b"), ("TEXT_JUSTIFY_CENTER",), "top"),)),
        Text(x, y, Font("font", vector=True), StrLit("R"),
             ("TEXT_JUSTIFY_CENTER", "TEXT_JUSTIFY_VCENTER"), "top", style="radial",
             angle=Const("A_ANGLE", 90.0), radius=Const("A_RADIUS", 100),
             direction="counter_clockwise"),
    ])
    assert w.render() == """\
// a comment
dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
dc.setPenWidth(3);
dc.fillRoundedRectangle(Layout.A_X - 1, Layout.A_Y,
                        Layout.A_WIDTH + 4, 4,
                        5);
dc.setPenWidth(1);
dc.fillPolygon(Layout.A_POINTS);
WfbArc.drawSpan(dc, Layout.A_X, Layout.A_Y, Layout.A_RADIUS,
                Layout.A_THICKNESS, Layout.A_START, Layout.A_SWEEP);

var font = _fontDigits;
if (font == null) {
    return;  // the font resource failed to load
}
var text = "--";
if (heartRateCurrent != null) {
    text = "12";
}
if (font != null) {
    dc.drawText(Layout.A_X, Layout.A_Y - dc.getFontHeight(Graphics.FONT_SMALL), Graphics.FONT_SMALL,
                text,
                Graphics.TEXT_JUSTIFY_LEFT);
}
if (_aod) {
    dc.drawText(Layout.A_X, Layout.A_Y, Graphics.FONT_SMALL,
                "a",
                Graphics.TEXT_JUSTIFY_CENTER);
}
else {
    dc.drawText(Layout.A_X, Layout.A_Y, Graphics.FONT_SMALL,
                "b",
                Graphics.TEXT_JUSTIFY_CENTER);
}
dc.drawRadialText(Layout.A_X, Layout.A_Y, font, "R",
                  Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER, Layout.A_ANGLE, Layout.A_RADIUS + Graphics.getFontAscent(font),
                  Graphics.RADIAL_TEXT_DIRECTION_COUNTER_CLOCKWISE);
"""
    assert label  # the example resolved: its fonts exist for the evaluator tests below


# -- the evaluator against today's preview ----------------------------------------


@pytest.mark.parametrize("scale", [1, 2])
def test_the_evaluator_paints_each_filled_primitive_over_its_resolved_geometry(db, scale):
    """Every filled rectangle, circle, ellipse and polygon in the shapes
    example, from its hand-built program, covers exactly the box its
    resolved geometry gives at the preview's scale: the `Dc` emulation's
    own convention, checked against layout rather than against itself."""
    resolved = resolved_example(SHAPES, db, DEVICE)
    checked = set()
    for placed in _plain_shapes(resolved):
        e = placed.element
        if not e.filled or e.shape not in ("rectangle", "circle", "ellipse", "polygon"):
            continue
        renderer = _renderer(resolved, scale)
        program = _shape_program(placed)
        program[0] = SetColor(Color(None))  # white, whatever the design's colour
        evaluator.evaluate(program, renderer)
        s = scale
        if e.shape == "rectangle":
            box = placed.rect or placed.inner_box
            expected = (box.x * s, box.y * s, box.right * s, box.bottom * s)
        elif e.shape == "polygon":
            xs, ys = [x for x, _ in placed.points], [y for _, y in placed.points]
            expected = (min(xs) * s, min(ys) * s, max(xs) * s + 1, max(ys) * s + 1)
        else:
            rx, ry = ((placed.radius, placed.radius) if e.shape == "circle"
                      else (placed.rx, placed.ry))
            cx, cy = placed.center
            expected = ((cx - rx) * s, (cy - ry) * s, (cx + rx) * s + 1, (cy + ry) * s + 1)
        assert renderer.image.getbbox() == expected, (placed.id, scale)
        checked.add(e.shape)
    assert checked == {"rectangle", "circle", "ellipse", "polygon"}


def test_the_evaluator_paints_a_text_call_as_draw_text_at_its_anchor(db):
    """A `drawText` op is the renderer's own glyph placement at the
    element's anchor, aligned by its justification: checked for every
    literal system-font text in the system-fonts example."""
    resolved = resolved_example(TEXT, db, DEVICE)
    texts = [p for p in resolved.shown_items
             if p.kind == "text" and p.element.literal is not None]
    assert texts
    for placed in texts:
        c = _constants(placed)
        font = Font(f"Graphics.{placed.font.reference}", metric=placed.font.metric)
        direct, program = _renderer(resolved), _renderer(resolved)
        direct.draw_text(None, placed.element.literal, placed.anchor_point, placed.element.align,
                         placed.element.vertical_align, placed.font.metric, (255, 255, 255))
        evaluator.evaluate([
            SetColor(Color(None)),
            Text(c["X"], c["Y"], font, StrLit(placed.element.literal), tuple(placed.justify),
                 placed.element.vertical_align),
        ], program)
        assert direct.image.getbbox() is not None, placed.id
        assert _differing(direct.image, program.image) == 0, placed.id


def test_if_aod_takes_the_branch_of_the_frame_painted(db):
    resolved = resolved_example(SHAPES, db, DEVICE)
    placed = next(p for p in _plain_shapes(resolved) if p.element.shape == "rectangle")
    c = _constants(placed)
    box = Primitive("fillRectangle", ((c["X"], c["Y"]), (c["WIDTH"], c["HEIGHT"])))
    program = [SetColor(Color(None)), IfAod((box,))]  # white, so the box shows
    awake, asleep = _renderer(resolved), _renderer(resolved, aod=True)
    evaluator.evaluate(program, awake)
    evaluator.evaluate(program, asleep)
    assert awake.image.getbbox() is None
    assert asleep.image.getbbox() is not None


def test_let_text_substitutes_only_when_the_reading_is_absent(db):
    resolved = resolved_example(Path("examples/features/units/face.yaml"), db, DEVICE)
    reading = next(p.element.value for p in resolved.shown_items
                   if p.kind == "text" and p.element.value is not None
                   and p.element.value.value.type not in (Type.TIME, Type.DATE))
    let = LetText(StrLit("--"), Reading("{}", reading), ("x",))
    present = evaluator.Evaluator(_renderer(resolved))
    present.run([let])
    assert present.locals["text"] not in (None, "--")
    renderer = _renderer(resolved)
    for source in reading.sources:
        renderer.values[source] = None
    absent = evaluator.Evaluator(renderer)
    absent.run([let])
    assert absent.locals["text"] == "--"


# -- dispatch ---------------------------------------------------------------------


def test_a_kinds_program_is_what_the_view_prints_and_the_preview_paints(db, monkeypatch):
    resolved = resolved_example(SHAPES, db, DEVICE)
    shape_kind = kinds.get("shape")
    programs = {p.id: _shape_program(p) for p in resolved.items if p.kind == "shape"}
    plain = _plain_shapes(resolved)
    for placed in plain:
        # The tag proves the view printed this program.
        programs[placed.id].insert(0, Comment(f"lowered {placed.id}"))

    def lower(ctx: DrawContext, placed):
        assert ctx.aod is not None and ctx.resolved is resolved
        return programs[placed.id]

    monkeypatch.setattr(shape_kind, "lower", lower)
    view = emit_view(resolved).text
    for placed in plain:
        assert f"// lowered {placed.id}\n" in view, placed.id
    for placed in plain:
        through, direct = _renderer(resolved), _renderer(resolved)
        through.render_element(placed)
        evaluator.evaluate(programs[placed.id], direct)
        assert _differing(through.image, direct.image) == 0, placed.id


HALF_DEGREE_ARC = """
format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [fenix8solar47mm]
resources:
  palette:
    fg: "#FFFFFF"
elements:
  tick:
    type: arc
    at: { anchor: center }
    radius: 40%r
    thickness: 3px
    start_angle: 12.5deg
    sweep: 90deg
    color: color.fg
"""


def test_a_half_degree_arc_previews_where_the_watch_draws_it(resolved_for):
    """`start_angle: 12.5deg` is 77.5 in the `Layout` constant, which
    `WfbArc.drawSpan` rounds to 78: the arc starts at 12 degrees clockwise
    from 12 o'clock on the watch.  The preview paints exactly that arc, and
    the old twin (rounding the author's 12.5 to 13, `author_arc_span`) is a
    degree off: the control."""
    from tests.helpers import author_arc_span as arc_span
    from wfb.draw import barrel

    resolved = resolved_for(HALF_DEGREE_ARC)
    placed = find(resolved, "tick")
    assert placed.garmin_start == 77.5

    def arc(span) -> Image.Image:
        r = _renderer(resolved)
        s = r.scale
        cx, cy, rr = placed.center[0] * s, placed.center[1] * s, placed.radius * s
        r.draw.arc([cx - rr, cy - rr, cx + rr, cy + rr], *span, fill=(255, 255, 255),
                   width=placed.thickness * s)
        return r.image

    painted = _renderer(resolved)
    painted.render_element(placed)
    watch = arc(barrel.pillow_arc(barrel.draw_span(placed.garmin_start, placed.sweep)))
    assert _differing(painted.image, watch) == 0
    assert _differing(painted.image, arc(arc_span(placed.start_angle, placed.sweep))) > 0


def test_a_fallback_draws_its_substitute_through_the_same_format(db):
    """`absent: {value: 0}` on `"{heart_rate.current} bpm"`: the reading
    when there is one, else `0 bpm` -- the substitute through the element's
    own format, never the bare value (`tests/fixtures/text_fallback/`)."""
    from wfb.draw import drawn_text

    resolved = resolved_example(Path("tests/fixtures/text_fallback/face.yaml"), db, DEVICE)
    placed = find(resolved, "heart")
    present = dict(preview.SAMPLE)
    absent = {**present, "heart_rate.current": None}
    assert drawn_text(resolved, placed, present) == f"{present['heart_rate.current']} bpm"
    assert drawn_text(resolved, placed, absent) == "0 bpm"
    assert drawn_text(resolved, find(resolved, "heart_ringed"), absent) == "0"
