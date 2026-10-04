"""An element's own guards as part of its draw program (`wfb.draw.program`):
`visible:` first, then the null guard its `absent:` policy asks for, then
the `antialias:` bracket around the drawing -- printed into `draw<Id>` and
honoured by the preview, so the two hide an element on the same readings."""

from __future__ import annotations

from PIL import Image, ImageDraw

from tests.helpers import find, resolve_text
from wfb import preview
from wfb.draw import DrawContext, paint, program
from wfb.draw.program import AntiAlias, NullGuard, VisibleGuard
from wfb.emit.monkeyc.common import NO_AOD
from wfb.emit.monkeyc.readplan import ReadPlan
from wfb.emit.monkeyc.view import emit_view

BASE = """
format: 2
face:
  id: 3c1d9a7e-2b4f-4e6a-8d1c-5f7a9b2e4c60
  name: Test
build:
  targets: [fenix8solar47mm]
resources:
  palette:
    fg: "#FFFFFF"
    acc: "#FF5500"
defaults:
  antialias: false
elements:
"""

DOT = """  dot:
    type: circle
    at: {anchor: center}
    radius: 20px
    antialias: true
    visible: "system.battery > 50"
    color: "heart_rate.current > 100 ? color.acc : color.fg"
"""


def _program(resolved, placed):
    plan = ReadPlan(resolved)
    ctx = DrawContext(resolved, NO_AOD, tuple(plan.value_guards(placed)))
    return program(ctx, placed, plan, antialias_default=False)


def _painted(resolved, placed, **values: object) -> Image.Image:
    """The element's program alone (`wfb.draw.paint`), without the frame's
    own `visible:` check, so its guards are what decides."""
    options = preview.PreviewOptions()
    sample = preview.sample_values(resolved, options, None)
    sample.update(values)
    image = Image.new("RGB", (resolved.device.width * 2, resolved.device.height * 2))
    renderer = preview.Renderer(resolved, ImageDraw.Draw(image), image, 2, sample, options)
    paint(renderer, placed)
    return renderer.image


def test_the_guards_come_first_and_the_bracket_wraps_only_the_drawing(write_design, bag, db):
    _, resolved = resolve_text(BASE + DOT, write_design, bag, db)
    ops = _program(resolved, find(resolved, "dot"))
    assert isinstance(ops[0], VisibleGuard)
    assert isinstance(ops[1], NullGuard) and ops[1].sources == ("heart_rate.current",)
    assert ops[2] == AntiAlias(True, comment=True)
    assert ops[-1] == AntiAlias(False)


def test_the_view_prints_the_guards_in_draw_order(write_design, bag, db):
    _, resolved = resolve_text(BASE + DOT, write_design, bag, db)
    view = emit_view(resolved).text
    body = view.split("private function drawDot(", 1)[1].split("\n    }\n", 1)[0]
    visible = body.index("// visible: ")
    absent = body.index("// absent: hide")
    toggle = body.index("applyAntiAlias(dc, true);")
    fill = body.index("dc.fillCircle(")
    assert visible < absent < toggle < fill < body.index("applyAntiAlias(dc, false);")


def test_the_preview_hides_an_element_whose_binding_is_absent(write_design, bag, db):
    """The colour reads heart rate: with a reading the dot draws, without one
    the null guard hides it, as on the watch."""
    _, resolved = resolve_text(BASE + DOT, write_design, bag, db)
    dot = find(resolved, "dot")
    assert _painted(resolved, dot, **{"system.battery": 80.0,
                                      "heart_rate.current": 72}).getbbox() is not None
    assert _painted(resolved, dot, **{"system.battery": 80.0,
                                      "heart_rate.current": None}).getbbox() is None


def test_the_preview_hides_an_element_whose_visible_is_false(write_design, bag, db):
    _, resolved = resolve_text(BASE + DOT, write_design, bag, db)
    dot = find(resolved, "dot")
    assert _painted(resolved, dot, **{"system.battery": 30.0,
                                      "heart_rate.current": 72}).getbbox() is None


def test_a_group_ring_is_each_members_own_ring_pass(db):
    """`badge`'s ring is every member's `ring<Id>` at its own width: the
    filled disc's share is the disc grown by 2 px, as the watch draws it --
    nothing past that, and no stamp of the group's union."""
    from pathlib import Path

    from tests.helpers import resolved_example
    from wfb.ir.rings import ring_groups

    resolved = resolved_example(Path("tests/fixtures/outline_group/face.yaml"), db,
                                "fenix8solar47mm")
    badge = next(r for r in ring_groups(resolved.face.elements) if r.group.id == "badge")
    disc = find(resolved, "disc")
    assert badge.width_of("disc") == 2
    options = preview.PreviewOptions()
    sample = preview.sample_values(resolved, options, None)
    image = Image.new("RGB", (resolved.device.width * 2, resolved.device.height * 2))
    renderer = preview.Renderer(resolved, ImageDraw.Draw(image), image, 2, sample, options)
    renderer.render_ring(badge, [disc])
    s = renderer.scale
    cx, cy = disc.center
    edge = disc.radius + 2
    ring = renderer.aod_dimmed(badge.group, badge.group.outline.color)
    assert image.getpixel(((cx + edge) * s - 1, cy * s)) == ring
    assert image.getpixel(((cx + edge) * s + 2, cy * s)) == (0, 0, 0)
