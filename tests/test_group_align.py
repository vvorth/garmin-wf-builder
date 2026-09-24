"""`align:`/`vertical_align:` on a `group` (plan 06 §4).

Every test picks pixel (`px`) units for `at:`/`size:` so the expected box is
hand-computable exactly, no float rounding to reason about. The device is
`fenix8solar47mm`: a 260x260 screen, minor radius 130, screen centre
(130, 130) (confirmed in `test_layout.py`).

`at: {anchor: center, dx: 20px}` -> (150, 130). `size: {width: 40px,
height: 30px}`. The centred (default) box is therefore
`(150 - 20, 130 - 15, 40, 30) == (130, 115, 40, 30)` -- unchanged from
before this feature existed.
"""

from tests.helpers import find
from wfb.build import load


def _design(align: str = "", vertical_align: str = "") -> str:
    extra = ""
    if align:
        extra += f"    align: {align}\n"
    if vertical_align:
        extra += f"    vertical_align: {vertical_align}\n"
    return f"""
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
elements:
  - id: box
    type: group
    at: {{anchor: center, dx: 20px}}
    size: {{width: 40px, height: 30px}}
{extra}    children:
      - id: child
        type: shape
        shape: rectangle
        at: {{anchor: center}}
        size: {{width: 100%, height: 100%}}
        color: palette.fg
"""


def _resolve(write_design, bag, db, align: str = "", vertical_align: str = ""):
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    face = load(write_design(_design(align, vertical_align)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    fonts = bake_fonts(face, device)
    return resolve(face, device, fonts)


def test_align_right_puts_the_box_right_edge_at_at(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, align="right")
    box = find(resolved, "box").box
    assert (box.x, box.y, box.width, box.height) == (110, 115, 40, 30)
    assert box.x + box.width == 150  # the group's `at:` x

    # A child anchored `center` with `size: 100%` fills exactly the same box.
    child = find(resolved, "child").box
    assert (child.x, child.y, child.width, child.height) == (box.x, box.y, box.width, box.height)


def test_align_left_puts_the_box_left_edge_at_at(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, align="left")
    box = find(resolved, "box").box
    assert (box.x, box.y, box.width, box.height) == (150, 115, 40, 30)
    assert box.x == 150  # the group's `at:` x


def test_vertical_align_top_puts_the_box_top_edge_at_at(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, vertical_align="top")
    box = find(resolved, "box").box
    assert (box.x, box.y, box.width, box.height) == (130, 130, 40, 30)
    assert box.y == 130  # the group's `at:` y


def test_vertical_align_bottom_puts_the_box_bottom_edge_at_at(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, vertical_align="bottom")
    box = find(resolved, "box").box
    assert (box.x, box.y, box.width, box.height) == (130, 100, 40, 30)
    assert box.y + box.height == 130  # the group's `at:` y


def test_omitting_both_keys_matches_explicit_center_center(write_design, bag, db):
    default_box = find(_resolve(write_design, bag, db), "box").box
    explicit_box = find(
        _resolve(write_design, bag, db, align="center", vertical_align="center"), "box"
    ).box
    expected = (130, 115, 40, 30)
    assert (default_box.x, default_box.y, default_box.width, default_box.height) == expected
    assert (explicit_box.x, explicit_box.y, explicit_box.width, explicit_box.height) == expected


def test_schema_accepts_align_on_a_group(write_design, bag, db):
    resolved = _resolve(write_design, bag, db, align="right")
    assert bag.ok()
    assert find(resolved, "box") is not None


def test_schema_rejects_vertical_align_baseline_on_a_group(write_design, bag):
    """A group has no baseline -- that value belongs to `text` only."""
    load(write_design(_design(vertical_align="baseline")), bag)
    assert not bag.ok()
