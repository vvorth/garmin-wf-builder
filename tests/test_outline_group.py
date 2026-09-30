"""`outline:` on `group` (research 19): every member's 1px ring just before
the group's first member, then the members -- the union's ring.  A member
rings nothing of its own and no outlined group nests in another, so every
ring stays 1px.  `tests/fixtures/outline_group/` is built for real by
`tests/test_outline_build.py` (`slow`)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from wfb.preview import PreviewOptions, render

from tests.helpers import find, generate_for_targets, load_errors, resolve_text

FIXTURE = Path(__file__).parent / "fixtures" / "outline_group" / "face.yaml"


@pytest.fixture(scope="module")
def view(tmp_path_factory) -> str:
    files = generate_for_targets(FIXTURE, tmp_path_factory.mktemp("build")).files()
    return next(body for name, body in files.items() if name.endswith("View.mc"))


def _function(view: str, name: str) -> str:
    match = re.search(rf"function {name}\(.*?\n    }}\n", view, re.S)
    assert match is not None, name
    return match.group(0)


def _calls(body: str) -> list[str]:
    return re.findall(r"^\s+((?:ring|draw)\w+)\(", body, re.M)


# -- codegen ---------------------------------------------------------------------


def test_every_ring_comes_before_every_member(view):
    """Ring, ring, ring, then draw, draw, draw -- a member's ring drawn
    after an earlier member would cut into it (research 19 §4.4)."""
    calls = _calls(_function(view, "onUpdate"))
    badge = calls[:6]
    assert badge == ["ringDisc", "ringHeart", "ringRate", "drawDisc", "drawHeart", "drawRate"]


def test_every_member_is_ringed_in_the_groups_colour(view):
    """A plain group nested in an outlined one: its members are the outer
    group's members too."""
    update = _function(view, "onUpdate")
    assert "ringRate(dc, activityInfo, Palette.RING);" in update
    assert "ringDisc(dc, Palette.RING);" in update
    assert "ringBar(dc, Palette.FG);" in update and "ringDot(dc, Palette.FG);" in update


def test_a_ring_method_reads_what_its_draw_method_reads(view):
    ring = _function(view, "ringRate")
    assert ring.startswith("function ringRate(dc as Dc, activityInfo as Activity.Info?, "
                           "ringColor as Number)")
    assert 'var text = "--";' in ring  # the same absent placeholder
    assert "dc.setColor(ringColor, Graphics.COLOR_TRANSPARENT);" in ring
    assert "Palette.FG" not in ring and "Palette.BG" not in ring  # nothing but the ring


def test_a_grown_member_grows_by_1px(view):
    assert "dc.fillCircle(Layout.DISC_CX, Layout.DISC_CY, Layout.DISC_RADIUS + 1);" \
        in _function(view, "ringDisc")


def test_a_static_group_rings_into_the_buffer(view):
    static = _function(view, "drawStatic")
    assert _calls(static) == ["drawBackground", "ringPlate", "ringKnob", "drawPlate", "drawKnob"]
    assert "ringPlate" not in _function(view, "onUpdate")


def test_a_low_power_member_is_ringed_in_the_partial_update(view):
    assert _calls(_function(view, "onPartialUpdate")) == ["ringSecs", "drawSecs"]


def test_no_offsets_table_is_emitted(tmp_path_factory):
    """Every stamp is unrolled with literal offsets: nothing to read."""
    files = generate_for_targets(FIXTURE, tmp_path_factory.mktemp("build")).files()
    assert "OUTLINE_OFFSETS" not in files["source-fenix8solar47mm/Layout.mc"]


def test_the_aod_frame_rings_under_each_members_own_guard_and_dimmed(write_design, tmp_path):
    text = FIXTURE.read_text().replace(
        "build:\n  targets:\n    - fenix8solar47mm\n    - fenix8solar51mm\n    - fr955",
        "build:\n  targets: [fenix847mm]\ndefaults:\n  aod: show\naod:\n  dim: 0.5\n  mask: false").replace(
        '        sleep_update: true\n', "        aod: {visible: \"time.second > 1\"}\n")
    files = generate_for_targets(write_design(text), tmp_path / "out").files()
    view = next(body for name, body in files.items() if name.endswith("View.mc"))
    update = _function(view, "onUpdate")
    aod = update[update.index("if (_aod)"):update.index("WfbAodMask") if "WfbAodMask" in update
                 else update.index("\n        else {")]
    assert "ringDisc(" in aod
    ring_disc = next(line for line in aod.splitlines() if "ringDisc(" in line)
    assert "_aod ?" in ring_disc  # the ring colour, dimmed like every AOD colour
    guard = aod[:aod.index("ringSecs(")].rsplit("if (", 1)[1]
    assert "1" in guard  # `ringSecs` sits under `secs`'s own aod: visible guard


# -- build checks ------------------------------------------------------------------

_BASE = """
format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [fenix8solar47mm]
resources:
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
elements:
"""


def test_a_member_that_cannot_ring_is_an_error(write_design):
    errors = load_errors(_BASE + """
  g:
    type: group
    outline: color.fg
    children:
      dot: {type: circle, at: {anchor: center}, radius: 5px, color: color.fg}
      hr:
        type: graph
        at: {anchor: center}
        size: {width: 40px, height: 20px}
        series: heart_rate
        range: 4h
        style: line
        color: color.fg
""", write_design)
    assert [e.code for e in errors] == ["outline"], errors
    assert "'hr' is a 'graph'" in errors[0].message


def test_a_member_ringing_itself_is_an_error(write_design):
    """Its own ring would put the group's 2px out -- one error, on it."""
    errors = load_errors(_BASE + """
  g:
    type: group
    outline: color.fg
    children:
      dot: {type: circle, at: {anchor: center}, radius: 5px, color: color.fg,
            outline: color.bg}
""", write_design)
    assert [e.code for e in errors] == ["outline"], errors
    assert "'dot' has an 'outline:' of its own" in errors[0].message


def test_an_outlined_group_inside_an_outlined_group_is_an_error(write_design):
    errors = load_errors(_BASE + """
  g:
    type: group
    outline: color.fg
    children:
      inner:
        type: group
        outline: color.bg
        children:
          dot: {type: circle, at: {anchor: center}, radius: 5px, color: color.fg}
""", write_design)
    assert [e.code for e in errors] == ["outline"], errors
    assert "'inner' has an 'outline:' of its own" in errors[0].message


def test_a_group_ring_colour_reading_data_is_an_error(write_design):
    errors = load_errors(_BASE + """
  g:
    type: group
    outline: "system.battery < 20 ? color.fg : color.bg"
    children:
      dot: {type: circle, at: {anchor: center}, radius: 5px, color: color.fg}
""", write_design)
    assert [e.code for e in errors] == ["outline"], errors
    assert "cannot read data" in errors[0].message


# -- preview -------------------------------------------------------------------------

_OVERLAP = _BASE.replace('fg: "#FFFFFF"', 'fg: "#0055AA"\n    ring: "#FFFF00"') + """
  background:
    type: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: color.bg
  g:
    type: group
    GROUP_RING
    children:
      disc: {type: circle, at: {anchor: center}, radius: 20px, color: color.fg MEMBER_RING}
      bar:
        type: rectangle
        at: {anchor: center, dx: 25px}
        size: {width: 40px, height: 10px}
        color: color.fg MEMBER_RING
"""


def _render(write_design, bag, db, *, group: bool):
    text = (_OVERLAP.replace("GROUP_RING", "outline: color.ring" if group else "")
            .replace(" MEMBER_RING}", "}" if group else ", outline: color.ring}")
            .replace(" MEMBER_RING", "" if group else "\n        outline: color.ring"))
    _, resolved = resolve_text(text, write_design, bag, db)
    return resolved, render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))


def test_the_group_ring_goes_round_the_union_not_between_members(write_design, bag, db):
    """Where the bar enters the disc, a per-member ring cuts into the disc
    (the bar's ring is drawn after the disc); the group's ring does not --
    and both still ring the outside."""
    resolved, grouped = _render(write_design, bag, db, group=True)
    _, separate = _render(write_design, bag, db, group=False)
    cx, cy = find(resolved, "disc").center
    ring = (255, 255, 0)
    inside = [(x, y) for x in range(cx - 20, cx + 46) for y in range(cy - 20, cy + 21)
              if (x - cx) ** 2 + (y - cy) ** 2 < 19 ** 2
              or (cx + 5 <= x < cx + 45 and cy - 5 <= y < cy + 5)]
    assert not [p for p in inside if grouped.getpixel(p) == ring]
    assert [p for p in inside if separate.getpixel(p) == ring]
    assert grouped.getpixel((cx - 21, cy)) == ring and grouped.getpixel((cx + 45, cy)) == ring
