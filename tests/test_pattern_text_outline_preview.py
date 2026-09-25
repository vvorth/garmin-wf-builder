"""`outline:` on a pattern's own `shape: text` part (plan 15 §14 slice 2) --
preview rendering, one level down from `tests/test_text_outline_preview.py`.

The property genuinely new at this level (the orchestrator's own brief):
a radial pattern's per-copy rotation must not smear the ring -- every copy
gets its own full ring, not just copy 0. `test_every_copy_gets_its_own_
ring_not_just_copy_0` checks the *actual pixels* near each copy's own
(independently computed) anchor, which is exactly the check that would
fail against a plausible broken implementation: a stamp loop hoisted
outside the per-copy body by mistake would light a ring near copy 0 alone
and leave the other three copies bare.
"""

from __future__ import annotations

from wfb import build
from wfb.kinds.pattern import pattern_text_anchor
from wfb.layout import PlacedPattern, resolve
from wfb.preview import PreviewOptions, render

FG = (255, 255, 255)
RING = (255, 0, 0)

_HEADER = """\
format: 1
face:
  id: 8f14e45f-ceea-467e-9c0c-89f7c6a9309d
  name: PatternOutlinePreviewTest
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
  ring: "#FF0000"
fonts:
  clock:
    source: {source}
    size: 80px
  bezel:
    face: RobotoCondensedBold
    size: 80px
elements:
  - id: background
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.bg
{body}
"""


def _resolved(write_design, db, bag, repo_root, body: str):
    from wfb.emit.resources import bake_fonts

    source = repo_root / "tests" / "fixtures" / "slice" / "assets" / "OpenSans-Regular.ttf"
    design = _HEADER.format(source=source, body=body)
    path = write_design(design)
    face = build.load(path, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device))


def _render(resolved, **options):
    opts = {"scale": 1, "mask_shape": False, "quantise": False, **options}
    return render(resolved, PreviewOptions(**opts))


def _count_color(image, color: tuple[int, int, int],
                 region: tuple[int, int, int, int] | None = None) -> int:
    x0, y0, x1, y1 = region if region is not None else (0, 0, *image.size)
    count = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            if image.getpixel((x, y)) == color:
                count += 1
    return count


_RING_ELEMENT = """\
  - id: ring
    type: pattern
    pattern: radial
    at: {{anchor: center}}
    count: 1
    parts:
      - shape: text
        text: "8"
        font: font.clock
        at: {{dy: -60px}}
{extra}"""


def test_pattern_ring_alone_is_visible_when_interior_matches_background(
    write_design, db, bag, repo_root,
):
    """The canonical hollow idiom, one level down: `color: palette.bg` (the
    interior is invisible against the background) plus `outline:` -- the
    ring must still be visible, not gated on the interior colour. A baked
    (1-bit, non-anti-aliased) font, the same reason `tests/test_text_
    outline_preview.py` picks one: exact colour equality is what an "outline
    lights strictly fewer/more pixels" pixel count needs, and an
    anti-aliased vector glyph's own soft edges would blend `RING`/`FG`
    towards the background instead of hitting either exactly."""
    resolved = _resolved(write_design, db, bag, repo_root, _RING_ELEMENT.format(
        extra="        color: palette.bg\n        outline: {color: palette.ring, width: 2}\n"))
    image = _render(resolved)
    ring = _count_color(image, RING)
    fg = _count_color(image, FG)
    assert ring > 0
    assert fg == 0, "the interior pass must paint the background colour, not the old fill"


def test_pattern_ring_lights_fewer_pixels_than_a_solid_fill(write_design, db, bag, repo_root):
    """Research 14 §1's own headline number, for a pattern text part: a
    stamped ring lights strictly fewer pixels than the same glyph drawn
    solid."""
    solid = _render(_resolved(write_design, db, bag, repo_root, _RING_ELEMENT.format(
        extra="        color: palette.fg\n")))
    ringed = _render(_resolved(write_design, db, bag, repo_root, _RING_ELEMENT.format(
        extra="        color: palette.bg\n        outline: {color: palette.ring, width: 2}\n")))
    solid_count = _count_color(solid, FG)
    ring_count = _count_color(ringed, RING)
    assert 0 < ring_count < solid_count


def test_pattern_ring_width_scales_the_lit_ring_pixel_count(write_design, db, bag, repo_root):
    narrow = _render(_resolved(write_design, db, bag, repo_root, _RING_ELEMENT.format(
        extra="        color: palette.bg\n        outline: {color: palette.ring, width: 1}\n")))
    wide = _render(_resolved(write_design, db, bag, repo_root, _RING_ELEMENT.format(
        extra="        color: palette.bg\n        outline: {color: palette.ring, width: 3}\n")))
    narrow_ring = _count_color(narrow, RING)
    wide_ring = _count_color(wide, RING)
    assert narrow_ring > 0
    assert wide_ring > narrow_ring


def test_pattern_outline_shorthand_matches_object_form_in_preview(write_design, db, bag, repo_root):
    shorthand = _render(_resolved(write_design, db, bag, repo_root, _RING_ELEMENT.format(
        extra="        color: palette.bg\n        outline: palette.ring\n")))
    explicit = _render(_resolved(write_design, db, bag, repo_root, _RING_ELEMENT.format(
        extra="        color: palette.bg\n        outline: {color: palette.ring, width: 2}\n")))
    assert shorthand.tobytes() == explicit.tobytes()


# -- the property genuinely new at this level: rotation does not smear -----


_ROTATING_RING = """\
  - id: ring
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 4
    color: palette.bg
    parts:
      - shape: text
        text: "8"
        font: font.bezel
        at: {dy: -70px}
        outline: {color: palette.ring, width: 2}
        curve: {style: angled, angle: 0deg}
"""


def test_every_copy_gets_its_own_ring_not_just_copy_0(write_design, db, bag, repo_root):
    """Four copies, `curve: {style: angled}`, each turned 90 degrees
    further than the last -- every one of them must show ring pixels near
    its OWN anchor (independently computed by `wfb.layout.pattern_text_
    anchor`, not hand-derived trigonometry that could share a mistake with
    the implementation under test). A stamp loop that only ran for copy 0
    -- the most plausible way to get this wrong, e.g. hoisting the loop
    out of the per-copy body by mistake -- would leave three of these four
    checks with zero ring pixels."""
    resolved = _resolved(write_design, db, bag, repo_root, _ROTATING_RING)
    placed = next(p for p in resolved.items if p.id == "ring")
    assert isinstance(placed, PlacedPattern)
    part = placed.parts[0]
    assert len(placed.copies) == 4

    image = _render(resolved)
    w, h = image.size
    for index in placed.copies:
        ox, oy, sin_t, cos_t = placed.transform(index)
        ax, ay = pattern_text_anchor(part, ox, oy, sin_t, cos_t)
        box = (max(0, ax - 20), max(0, ay - 20), min(w, ax + 20), min(h, ay + 20))
        count = _count_color(image, RING, box)
        assert count > 0, f"copy {index}'s own anchor ({ax}, {ay}) has no ring pixels nearby"


def test_rotated_ring_does_not_smear_into_a_solid_disc(write_design, db, bag, repo_root):
    """The negative half of the same claim: a genuinely SMEARED ring (one
    stamped at every angle along the rotation, rather than once per
    discrete copy) would fill in the space between the four numerals with
    ring-coloured pixels too. With only 4 discrete copies and a real gap
    between them (`count: 4` around a full turn, `dy: -70px`), the point
    exactly between two adjacent copies must show no ring colour at all."""
    resolved = _resolved(write_design, db, bag, repo_root, _ROTATING_RING)
    image = _render(resolved)
    w, h = image.size
    cx, cy = w // 2, h // 2
    # Copy 0 sits straight up from centre (angle 0), copy 1 a quarter turn
    # clockwise (straight right) -- the point diagonally between them
    # (up-and-right, not on either copy's own radius) must be untouched.
    px, py = cx + 50, cy - 50
    assert image.getpixel((px, py)) != RING
