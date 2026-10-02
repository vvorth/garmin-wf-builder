"""`type: icon` as a draw program (`wfb.kinds.icon.IconKind.lower`): the
glyph printed as the view's `drawText`, painted as its baked tile at the
icon's measured box, ringed from its baked ring font, and, for a dynamic
icon, the glyph `WfbWeather.chooseIcon` picks for the reading."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from tests.helpers import find, resolved_example
from wfb import icons, kinds, preview
from wfb.draw import evaluator
from wfb.draw.jsonform import to_json
from wfb.draw.printer import print_ops
from wfb.draw.program import DrawContext, Glyph, IfNotNull, SetColor
from wfb.emit.monkeyc.common import NO_AOD, RingPass
from wfb.emit.writer import Writer

RINGS = Path("examples/features/rings/face.yaml")
TRAIL = Path("examples/generated_by_skill/trail-utility/face.yaml")
DEVICE = "fenix8solar47mm"


def _renderer(resolved, scale: int = 2, **values: object) -> preview.Renderer:
    sample = dict(preview.SAMPLE)
    for name, color in resolved.face.palette.items():
        sample.setdefault(f"palette.{name}", color.value)
    sample.update(values)
    image = Image.new("RGB", (resolved.device.width * scale, resolved.device.height * scale))
    return preview.Renderer(resolved, ImageDraw.Draw(image), image, scale, sample,
                            preview.PreviewOptions(scale=scale))


def _program(resolved, placed, ring: RingPass | None = None) -> list:
    return kinds.for_placed(placed).lower(DrawContext(resolved, NO_AOD, (), ring), placed)


def _printed(resolved, placed, ring: RingPass | None = None) -> str:
    w = Writer()
    print_ops(w, _program(resolved, placed, ring))
    return w.render()


def test_a_static_icon_prints_its_glyph_as_a_literal(db):
    resolved = resolved_example(RINGS, db, DEVICE)
    alarm = find(resolved, "alarm")
    code = _printed(resolved, alarm)
    assert f'"{alarm.element.codepoint}"' in code
    assert "Layout.ALARM_CX, Layout.ALARM_CY, font" in code
    assert "the icon font resource failed to load" in code


def test_a_dynamic_icon_prints_the_choice_made_on_the_watch(db):
    resolved = resolved_example(TRAIL, db, DEVICE)
    code = _printed(resolved, find(resolved, "weather_icon"))
    assert "IconGlyphs.glyph(WfbWeather.chooseIcon(" in code


def test_a_ring_pass_draws_only_the_ring(db):
    resolved = resolved_example(RINGS, db, DEVICE)
    alarm = find(resolved, "alarm")
    code = _printed(resolved, alarm, RingPass("ringColor", 1))
    assert "ringColor" in code
    assert code.count("dc.drawText(") == 1  # the ring font's one draw, no interior


def test_an_icons_ring_paints_the_stamp_of_its_glyph(db):
    """The ring is one draw in the baked ring font, and that paints what
    stamping the glyph at every offset paints: the dilated glyph, nothing
    shifted."""
    resolved = resolved_example(RINGS, db, DEVICE)
    alarm = find(resolved, "alarm")
    ops = _program(resolved, alarm)
    assert any(isinstance(op, IfNotNull) for op in ops), "expected the baked ring font"

    painted = _renderer(resolved)
    evaluator.evaluate(ops, painted)

    stamped = _renderer(resolved)
    glyph_only = [op for op in ops if isinstance(op, Glyph)]
    ring = alarm.element.outline
    assert ring is not None
    stamped.stamp_ring(stamped.silhouette(lambda: evaluator.Evaluator(stamped).run(glyph_only)),
                       stamped.color(ring.color), ring.width)
    evaluator.Evaluator(stamped).run([op for op in ops if isinstance(op, SetColor)][-1:]
                                     + glyph_only)
    assert not ImageChops.difference(painted.image, stamped.image).getbbox()


def _icon_layer(db, condition: object) -> Image.Image:
    resolved = resolved_example(TRAIL, db, DEVICE)
    renderer = _renderer(resolved, **{"weather.condition": condition})
    evaluator.evaluate(_program(resolved, find(resolved, "weather_icon")), renderer)
    return renderer.image


def _pasted(db, name: str) -> Image.Image:
    """``name``'s glyph pasted straight off the icon's sheet at its box."""
    resolved = resolved_example(TRAIL, db, DEVICE)
    placed = find(resolved, "weather_icon")
    renderer = _renderer(resolved)
    evaluator.paste_glyph(renderer, placed.font_key, icons.CATALOG[name].codepoint,
                          placed.inner_box.x, placed.inner_box.y,
                          renderer.color(placed.element.color))
    return renderer.image


def test_a_dynamic_icon_draws_the_glyph_its_reading_chooses(db):
    for condition, name in ((0, "weather_sunny"), (4, "weather_snow"), (3, "weather_rain"),
                            (None, "weather_unknown")):
        assert not ImageChops.difference(_icon_layer(db, condition),
                                         _pasted(db, name)).getbbox(), condition
    assert ImageChops.difference(_icon_layer(db, 0), _icon_layer(db, 4)).getbbox()


def test_the_preview_sample_is_the_glyph_the_box_is_measured_with():
    for source in ("weather.condition", "weather.condition_today", "weather.condition_tomorrow"):
        name = icons.choose_weather_icon(preview.SAMPLE[source])
        assert icons.CATALOG[name].codepoint == icons.WEATHER_BAKE_REFERENCE_GLYPH


def test_the_chooser_falls_back_as_the_barrel_does():
    for condition in (None, 54, -1, True, "3"):
        assert icons.choose_weather_icon(condition) == "weather_unknown"
    assert icons.choose_weather_icon(3.0) == "weather_rain"


def test_the_json_names_the_anchor_an_editor_moves(db):
    resolved = resolved_example(RINGS, db, DEVICE)
    renderer = _renderer(resolved)
    ops, fonts = to_json(renderer, find(resolved, "alarm"))
    glyphs = [op for op in ops if op["op"] == "glyph"]
    assert glyphs, ops
    interior = glyphs[-1]
    assert interior["x"] == {"const": "ALARM_CX", "value": find(resolved, "alarm").center[0],
                             "add": 0}
    assert fonts[interior["font"]].baked == find(resolved, "alarm").font_key
