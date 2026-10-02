"""`type: hands` as a draw program (`wfb.kinds.hands.HandsKind.lower`): each
hand turned by its clock angle at the sample time, an `awake` second hand
gone while asleep, and each hand ringed whole before its own parts."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

from tests.helpers import find, resolved_example
from wfb import kinds, preview
from wfb.draw.jsonform import to_json
from wfb.draw.printer import print_ops
from wfb.draw.program import DrawContext
from wfb.emit.monkeyc.common import NO_AOD
from wfb.emit.writer import Writer

OUTLINED = Path("tests/fixtures/outline_hands/face.yaml")
DEVICE = "fenix8solar47mm"


def _renderer(resolved, **options: object) -> preview.Renderer:
    opts = preview.PreviewOptions(**options)
    sample = preview.sample_values(resolved, opts, None)
    scale = opts.scale
    image = Image.new("RGB", (resolved.device.width * scale, resolved.device.height * scale))
    return preview.Renderer(resolved, ImageDraw.Draw(image), image, scale, sample, opts)


def _printed(resolved, placed) -> str:
    w = Writer()
    print_ops(w, kinds.for_placed(placed).lower(DrawContext(resolved, NO_AOD), placed))
    return w.render()


def test_an_awake_second_hand_is_gone_while_asleep(db):
    resolved = resolved_example(OUTLINED, db, DEVICE)
    hands = find(resolved, "hands")
    assert "if (!_sleeping)" in _printed(resolved, hands)
    awake, _ = to_json(_renderer(resolved), hands)
    asleep, _ = to_json(_renderer(resolved, asleep=True), hands)
    assert len(asleep) < len(awake)
    second = hands.second
    assert second is not None
    # Asleep draws exactly the hour and minute hands' share.
    shown, _ = to_json(_renderer(resolved, aod=True), hands)
    assert len(shown) == len(asleep)


def test_a_hand_turns_by_its_clock_angle_at_the_sample_time(db):
    """The minute hand's first vertex, at 10:09 (the sample), turned by
    9 * 6 degrees about the axis."""
    resolved = resolved_example(OUTLINED, db, DEVICE)
    hands = find(resolved, "hands")
    renderer = _renderer(resolved, time=(10, 9, 30))
    ops, _ = to_json(renderer, hands)
    minute = hands.minute
    assert minute is not None and minute.parts[0].shape == "polygon"
    theta = math.radians(9 * 6.0)
    x, y = minute.parts[0].points[0]
    cx, cy = hands.center
    expected = [cx + (x * math.cos(theta) - y * math.sin(theta)),
                cy + (x * math.sin(theta) + y * math.cos(theta))]
    polygons = [op["points"][0] for op in ops if op["op"] == "fillPolygon"]
    assert expected in polygons


def test_each_hand_is_ringed_whole_before_its_parts(db):
    """The ring colour, every part's ring, then the hand's own colour: per
    hand, so a hand's ring is drawn over the hand beneath it."""
    resolved = resolved_example(OUTLINED, db, DEVICE)
    hands = find(resolved, "hands")
    code = _printed(resolved, hands)
    for name in ("// hour", "// minute"):
        block = code.split(name, 1)[1].split("// ", 1)[0]
        assert block.index("WfbRingWide.") < block.index("WfbGeom.")
