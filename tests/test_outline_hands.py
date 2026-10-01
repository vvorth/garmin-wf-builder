"""`outline:` on `hands`: each hand ringed whole,
just before its own parts, so its parts never ring each other and its ring
is drawn over the hand beneath it.  `tests/fixtures/outline_hands/` is built
for real by `tests/test_outline_build.py` (`slow`)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from wfb.preview import PreviewOptions, render

from tests.helpers import find, generate_for_targets, resolve_design

FIXTURE = Path(__file__).parent / "fixtures" / "outline_hands" / "face.yaml"
RING = (255, 255, 0)


@pytest.fixture(scope="module")
def view(tmp_path_factory) -> str:
    files = generate_for_targets(FIXTURE, tmp_path_factory.mktemp("build")).files()
    return next(body for name, body in files.items() if name.endswith("View.mc"))


def _hands(view: str) -> str:
    match = re.search(r"private function drawHands\(.*?\n    }\n", view, re.S)
    assert match is not None
    return match.group(0)


def test_each_hand_is_ringed_just_before_its_own_parts(view):
    """Ring, parts, ring, parts -- not every ring first (which would ring
    the union of all three hands) and not one ring per part."""
    body = _hands(view)
    order = [m.group(0) for m in re.finditer(
        r"dc\.setColor\(Palette\.(BG|FG|ACCENT)", body)]
    assert order == ["dc.setColor(Palette.BG", "dc.setColor(Palette.FG",
                     "dc.setColor(Palette.BG", "dc.setColor(Palette.FG",
                     "dc.setColor(Palette.BG", "dc.setColor(Palette.ACCENT"], order


def test_each_part_is_ringed_once_without_moving_the_axis(view):
    """One ring op per part: the polygon rotated once and shifted in place,
    the filled circle grown 2px, the line's ends rotated once -- never a
    loop re-rotating (and re-allocating) the part per offset, which is what
    made a stamped hand cost 18ms on a watch (research 19 §4.5).  The
    fixture's ring is 2px, so each walks `Layout.OUTLINE_OFFSETS_2`."""
    body = _hands(view)
    assert body.count("WfbRingWide.rotated(dc, Layout.HANDS_HOUR_0_POINTS, cx, cy, sin, cos, "
                      "Layout.OUTLINE_OFFSETS_2);") == 1
    assert "Layout.HANDS_MINUTE_1_RADIUS + 2," in body
    assert ("WfbRingWide.lineRotated(dc, [Layout.HANDS_SECOND_0_X1, Layout.HANDS_SECOND_0_Y1, "
            "Layout.HANDS_SECOND_0_X2, Layout.HANDS_SECOND_0_Y2]") in body
    assert "cx = " not in body.replace("var cx = ", "")


def test_a_1px_hand_ring_calls_the_spelled_out_functions(tmp_path, write_design):
    text = FIXTURE.read_text().replace("    outline: { color: color.bg, width: 2 }\n",
                                       "    outline: color.bg\n")
    project = generate_for_targets(write_design(text), tmp_path / "out")
    files = project.files()
    body = _hands(next(body for name, body in files.items() if name.endswith("View.mc")))
    assert "WfbRing.rotated(dc, Layout.HANDS_HOUR_0_POINTS, cx, cy, sin, cos);" in body
    assert "WfbRing.lineRotated(dc, Layout.HANDS_SECOND_0_X1" in body
    assert "OUTLINE_OFFSETS" not in body
    assert "OUTLINE_OFFSETS" not in files["source-fenix8solar47mm/Layout.mc"]
    # nothing wider is drawn, so nothing wider is compiled
    assert "WfbRing.mc" in project.barrel and "WfbRingWide.mc" not in project.barrel


def test_a_wider_hand_ring_gets_its_offsets_table(tmp_path_factory):
    project = generate_for_targets(FIXTURE, tmp_path_factory.mktemp("build"))
    layout = project.files()["source-fenix8solar47mm/Layout.mc"]
    line = next(l for l in layout.splitlines() if "OUTLINE_OFFSETS_2 as Array<Number>" in l)
    numbers = line.split("[", 1)[1].split("]", 1)[0]
    assert len([n for n in numbers.split(",") if n.strip()]) == 16  # 8 points
    assert "OUTLINE_OFFSETS_1" not in layout
    assert "WfbRingWide.mc" in project.barrel and "WfbRing.mc" not in project.barrel


def test_an_awake_only_second_hand_keeps_its_ring_inside_the_gate(view):
    body = _hands(view)
    gate = body[body.index("if (!_sleeping)"):]
    assert "WfbRingWide.lineRotated(" in gate
    assert "lineRotated(" not in body[:body.index("if (!_sleeping)")]


def test_no_outline_emits_no_ring(tmp_path, write_design):
    text = FIXTURE.read_text().replace("    outline: { color: color.bg, width: 2 }\n", "")
    files = generate_for_targets(write_design(text), tmp_path / "out").files()
    view = next(body for name, body in files.items() if name.endswith("View.mc"))
    assert "offsets" not in _hands(view)


def _render(write_design, bag, db, ring: str | None, time: tuple[int, int, int]):
    text = FIXTURE.read_text().replace('accent: "#FF5500"', 'accent: "#FF5500"\n    ring: "#FFFF00"')
    replacement = "" if ring is None else f"    outline: {{ color: color.ring, width: {ring} }}\n"
    text = text.replace("    outline: { color: color.bg, width: 2 }\n", replacement)
    resolved = resolve_design(write_design(text), bag, db, "fenix8solar47mm")
    return resolved, render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False,
                                                      time=time))


def test_the_preview_rings_a_hand_over_the_hand_beneath_it(write_design, bag, db):
    """At 3:00 the minute hand crosses the hour hand at the axis: with a
    ring, some pixel white in the plain render (the hour hand) turns ring
    coloured -- the minute hand's ring drawn over it -- while the minute
    hand itself, drawn after its ring, stays white."""
    _, plain = _render(write_design, bag, db, None, (3, 0, 30))
    resolved, ringed = _render(write_design, bag, db, "2", (3, 0, 30))
    cx, cy = find(resolved, "hands").center
    white = (255, 255, 255)
    cut = [(x, y) for x in range(cx - 12, cx + 13) for y in range(cy - 12, cy + 13)
           if plain.getpixel((x, y)) == white and ringed.getpixel((x, y)) == RING]
    assert cut, "no hand pixel was overdrawn by a later hand's ring"
    # the minute hand's shaft, well away from the axis, is still white
    assert ringed.getpixel((cx, cy - 60)) == white
    # and ringed on both sides
    row = [ringed.getpixel((x, cy - 60)) for x in range(cx - 8, cx + 9)]
    assert row.count(RING) >= 2, row
