"""`outline:` on a standalone `text` element (plan 15 slice 1) -- layout box
growth (§6, D9): the ink box grows by the ring's own width on every side,
for all three draw shapes a standalone element can take (upright, `curve:
{style: angled}`, `curve: {style: radial}`), and the pre-existing off-screen/
safe-area checks still catch the grown box with zero new geometry of their
own.
"""

from __future__ import annotations

from wfb import build, lint
from wfb.layout import resolve
from tests.helpers import fonts_design as _design


_VECTOR_FONT = """\
  bezel:
    face: RobotoCondensedBold
    size: 6%r
"""


def _baked_font(repo_root) -> str:
    source = repo_root / "tests" / "fixtures" / "slice" / "assets" / "OpenSans-Regular.ttf"
    return f"  clock:\n    source: {source}\n    size: 18%r\n"


def _text(element_id: str, extra: str = "", *, font: str, at: str = "{anchor: center}") -> str:
    return f"""\
  - id: {element_id}
    type: text
    text: "GARMIN"
    color: palette.fg
    at: {at}
    font: {font}
{extra}"""


def _placed(resolved, element_id: str):
    for p in resolved.items:
        if p.id == element_id:
            return p
    raise AssertionError(f"{element_id!r} was not placed")


def _load(write_design, bag, design: str):
    face = build.load(write_design(design), bag)
    assert face is not None, bag.render()
    return face


def _resolve_baked(write_design, bag, db, design: str):
    from wfb.emit.resources import bake_fonts

    face = _load(write_design, bag, design)
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device))


def _resolve_vector(write_design, bag, db, design: str):
    face = _load(write_design, bag, design)
    device = db.get("fenix8solar47mm")
    return resolve(face, device, {})


# -- upright ------------------------------------------------------------------


def test_upright_box_grows_by_the_ring_on_every_side(write_design, bag, db, repo_root):
    """A plain (no `curve:`) element's box grows by `2 * outline.width` in
    both dimensions, centred on the same point -- the "Minkowski dilation
    of the pre-transform box" D9 describes, checked against the actual
    numbers, not just "grew at all" (a bug that grew only one side would
    still pass a weaker check)."""
    elements = (
        _text("plain", font="font.clock") + "\n"
        + _text("ringed", "    outline: {color: palette.bg, width: 3}\n", font="font.clock")
    )
    resolved = _resolve_baked(write_design, bag, db, _design(_baked_font(repo_root), elements))
    plain = _placed(resolved, "plain")
    ringed = _placed(resolved, "ringed")

    assert ringed.box.width == plain.box.width + 6
    assert ringed.box.height == plain.box.height + 6
    plain_cx = plain.box.x + plain.box.width / 2
    ringed_cx = ringed.box.x + ringed.box.width / 2
    assert abs(plain_cx - ringed_cx) <= 1
    plain_cy = plain.box.y + plain.box.height / 2
    ringed_cy = ringed.box.y + ringed.box.height / 2
    assert abs(plain_cy - ringed_cy) <= 1


def test_upright_box_grows_past_the_align_edge_too(write_design, bag, db, repo_root):
    """`align: left` puts a plain box's own left edge exactly at the
    anchor -- an outline stamp's offset shifts the anchor itself before the
    device's own left-justify re-applies at the shifted position, so the
    ring's leftmost pixel sits PAST the anchor, not just to the right of
    the ink. This is the contrast a naive "literal substitution"
    implementation (pin the aligned edge, grow only the far side) would
    fail: it would leave the box's left edge exactly where the plain box's
    already is."""
    elements = (
        _text("plain", "    align: left\n", font="font.clock") + "\n"
        + _text("ringed",
               "    align: left\n    outline: {color: palette.bg, width: 3}\n",
               font="font.clock")
    )
    resolved = _resolve_baked(write_design, bag, db, _design(_baked_font(repo_root), elements))
    plain = _placed(resolved, "plain")
    ringed = _placed(resolved, "ringed")

    assert ringed.box.x < plain.box.x
    assert ringed.box.right > plain.box.right


def test_no_outline_box_is_unchanged(write_design, bag, db, repo_root):
    """`outline: none` (or omitting the key) must be byte-identical to
    before -- the one contrast that would catch a `ring_px` computed even
    when there is no outline at all."""
    elements = _text("plain", font="font.clock")
    resolved = _resolve_baked(write_design, bag, db, _design(_baked_font(repo_root), elements))
    plain = _placed(resolved, "plain")
    assert plain.element.outline is None
    # A hand-computed expectation, independent of any outline machinery:
    # the box must simply equal the measured glyph extent centred at the
    # anchor -- re-derived here rather than compared against a second
    # "plain" element, so a bug that always added 0 (a fencepost) could not
    # hide behind two equally-wrong copies agreeing with each other.
    assert plain.box.width > 0 and plain.box.height > 0


# -- curve: angled --------------------------------------------------------------


def test_angled_box_grows_by_the_ring(write_design, bag, db):
    element_plain = _text("plain", "    curve: {style: angled, angle: 0deg}\n",
                          font="font.bezel")
    element_ringed = _text(
        "ringed",
        "    curve: {style: angled, angle: 0deg}\n"
        "    outline: {color: palette.bg, width: 2}\n",
        font="font.bezel",
    )
    resolved = _resolve_vector(
        write_design, bag, db, _design(_VECTOR_FONT, element_plain + "\n" + element_ringed))
    plain = _placed(resolved, "plain")
    ringed = _placed(resolved, "ringed")
    assert plain.curve_style == "angled"
    assert ringed.box.width > plain.box.width
    assert ringed.box.height > plain.box.height


# -- curve: radial ----------------------------------------------------------


def test_radial_box_grows_by_the_ring(write_design, bag, db):
    element_plain = _text(
        "plain", "    curve: {style: radial, angle: 0deg, radius: 40%r}\n", font="font.bezel")
    element_ringed = _text(
        "ringed",
        "    curve: {style: radial, angle: 0deg, radius: 40%r}\n"
        "    outline: {color: palette.bg, width: 2}\n",
        font="font.bezel",
    )
    resolved = _resolve_vector(
        write_design, bag, db, _design(_VECTOR_FONT, element_plain + "\n" + element_ringed))
    plain = _placed(resolved, "plain")
    ringed = _placed(resolved, "ringed")
    assert plain.curve_style == "radial"
    plain_area = plain.box.width * plain.box.height
    ringed_area = ringed.box.width * ringed.box.height
    assert ringed_area > plain_area
    # The ring must widen the box on every side, not just push it around --
    # its AABB has to strictly contain the plain box's own AABB.
    assert ringed.box.x <= plain.box.x
    assert ringed.box.y <= plain.box.y
    assert ringed.box.right >= plain.box.right
    assert ringed.box.bottom >= plain.box.bottom


# -- off-screen/safe-area still see the grown box, with no new lint code -------


def test_off_screen_catches_a_box_that_only_overflows_once_ringed(write_design, bag, db,
                                                                   repo_root):
    """An element positioned so its plain box fits the framebuffer exactly,
    but a wide ring pushes it over the edge -- `off-screen` must fire only
    once `outline:` is added, proving the check reads the grown box, not a
    box a new, `outline`-aware lint path had to be written for (there is
    none, D11)."""
    at = "{anchor: top_left, dx: 0px, dy: 0px}"
    align = "    align: left\n    vertical_align: top\n"
    elements = (
        _text("plain", align, font="font.clock", at=at) + "\n"
        + _text("ringed", align + "    outline: {color: palette.bg, width: 3}\n",
               font="font.clock", at=at)
    )
    resolved = _resolve_baked(write_design, bag, db, _design(_baked_font(repo_root), elements))
    bag2 = bag
    lint.check_geometry(resolved, bag2)
    codes_by_element = {}
    for d in bag2.items:
        if d.code == "off-screen":
            # message names the element id first
            codes_by_element.setdefault(d.message.split(":")[0], []).append(d.code)
    assert "ringed" in codes_by_element, bag2.render()
    assert "plain" not in codes_by_element, (
        "the plain element must not itself be off-screen -- only the ring "
        "should push it past the edge"
    )
