"""Vector fonts and `curve:` (plan 11) -- preview rendering (`wfb.preview`).

The simulator does not run in this environment (`CLAUDE.md` §3), so preview
is the only way this feature can be seen at all -- these tests exercise the
three draw styles `wfb.preview._Renderer._draw_vector_text` dispatches to
(upright, `angled`, `radial`) plus `if_unavailable: hide` drawing nothing,
each against a contrast a backwards angle/direction or a mirrored glyph run
would actually fail (`docs/lore/working-agreement.md`: a test must exercise
the contrast it claims). Real installed devices throughout:
`fenix8solar47mm` has vector fonts, `fenix6` does not
(`tests/test_vector_text_layout.py`'s own module docstring).

`tests/test_patterns_preview.py`'s own conventions: a solid black
background, `scale: 1` so device pixels map 1:1 onto image pixels, no
quantising/bezel mask, and an ink probe that tolerates anti-aliased edges
(a real `FreeTypeFont` glyph, unlike a baked 1-bit sheet, is not solid at
its boundary) instead of an exact-colour match.
"""

from __future__ import annotations

import math

import pytest

from wfb import build
from wfb import preview as preview_module
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render

CX, CY = 130, 130
BACKGROUND = (0, 0, 0)

_HEADER = """\
format: 1
face:
  id: 8f14e45f-ceea-467e-9c0c-89f7c6a9309c
  name: VectorTextPreviewTest
targets: [{target}]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
fonts:
  bezel:
    face: RobotoCondensedBold
    size: {font_size}
{if_unavailable}
elements:
  - id: background
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.bg
{body}
"""


def _render(write_design, db, bag, body: str, *, target: str = "fenix8solar47mm",
           hide: bool = False, font_size: str = "10%r", **options):
    if_unavailable = "    if_unavailable: hide\n" if hide else ""
    design = _HEADER.format(target=target, if_unavailable=if_unavailable, body=body,
                            font_size=font_size)
    path = write_design(design)
    face = build.load(path, bag)
    assert face is not None, bag.render()
    device = db.get(target)
    resolved = resolve(face, device, bake_fonts(face, device))
    opts = {"scale": 1, "mask_shape": False, "quantise": False, **options}
    return render(resolved, PreviewOptions(**opts))


def _has_ink(image, point: tuple[int, int], tolerance: int = 3, min_channel: int = 60) -> bool:
    """Whether any pixel within `tolerance` px of `point` is meaningfully
    lit above the pure-black background -- a real `FreeTypeFont` glyph
    anti-aliases toward the background at its edges, so this checks "some
    ink nearby" rather than one exact pixel or an exact colour match
    (`test_patterns_preview.py`'s own `_near`, adapted for continuous ink)."""
    x0, y0 = point
    w, h = image.size
    for dx in range(-tolerance, tolerance + 1):
        for dy in range(-tolerance, tolerance + 1):
            x, y = x0 + dx, y0 + dy
            if 0 <= x < w and 0 <= y < h:
                r, g, b = image.getpixel((x, y))
                if r > min_channel or g > min_channel or b > min_channel:
                    return True
    return False


def _ink_bbox(image, region: tuple[int, int, int, int], min_channel: int = 60):
    """The tight bounding box of every lit pixel inside `region`
    (`x0, y0, x1, y1`, exclusive), or `None` if the region is all
    background -- used to compare the upright and `angled` extents, which a
    real rotation must swap (`test_angled_box_is_the_rotated_bounding_box`'s
    own contrast, re-run here against the actual drawn ink instead of the
    lint box)."""
    x0r, y0r, x1r, y1r = region
    minx = miny = None
    maxx = maxy = None
    for y in range(y0r, y1r):
        for x in range(x0r, x1r):
            r, g, b = image.getpixel((x, y))
            if r > min_channel or g > min_channel or b > min_channel:
                minx = x if minx is None else min(minx, x)
                maxx = x if maxx is None else max(maxx, x)
                miny = y if miny is None else min(miny, y)
                maxy = y if maxy is None else max(maxy, y)
    if minx is None:
        return None
    return minx, miny, maxx, maxy


def _glyph_mask(image, bbox, min_channel: int = 60):
    """The lit/unlit pixel mask of `image` cropped tightly to `bbox`
    (`x0, y0, x1, y1`, inclusive -- an `_ink_bbox` result) -- factored out
    of `test_angled_180deg_is_a_true_rotation_not_a_mirror`'s own nested
    `_mask` so the radial facing tests below can reuse the same true-
    rotation-vs-mirror methodology without a second copy."""
    x0, y0, x1, y1 = bbox
    crop = image.crop((x0, y0, x1 + 1, y1 + 1))
    return [[1 if crop.getpixel((x, y))[0] > min_channel else 0
             for x in range(crop.width)]
            for y in range(crop.height)]


def _mask_mismatch_fraction(expected, actual) -> float:
    """Fraction of overlapping cells that disagree between two glyph masks
    (`_glyph_mask` results) -- low means "the same shape", high means "a
    different shape (e.g. mirrored, or a different rotation)". Compares
    only the overlapping `h x w` region, as `test_angled_180deg...` does,
    so a few pixels of size difference from rounding does not itself count
    as a mismatch."""
    h = min(len(expected), len(actual))
    w = min(len(expected[0]), len(actual[0]))
    assert h > 5 and w > 5, "glyph too small to compare reliably"
    mismatches = sum(
        1 for y in range(h) for x in range(w) if expected[y][x] != actual[y][x]
    )
    return mismatches / (h * w)


def _polar(cx: int, cy: int, r: float, garmin_degrees: float) -> tuple[int, int]:
    """A point on the circle of radius `r` about `(cx, cy)`, at Garmin's own
    angle convention (degrees counter-clockwise from 3 o'clock, screen y
    down) -- `wfb.preview._Renderer._draw_radial_vector_text`'s own
    position formula, reproduced here (not imported) so a bug in that
    method cannot also hide from the test that checks it."""
    theta = math.radians(garmin_degrees)
    return (round(cx + r * math.cos(theta)), round(cy - r * math.sin(theta)))


# -- upright -----------------------------------------------------------------


def test_upright_vector_text_draws_at_the_anchor(write_design, db, bag):
    body = """\
  - id: brand
    type: text
    text: "AB"
    font: font.bezel
    color: palette.fg
    at: {anchor: center}
    align: center
    vertical_align: center
"""
    image = _render(write_design, db, bag, body)
    assert _has_ink(image, (CX, CY))
    # Far from the anchor, in a corner no glyph reaches.
    assert not _has_ink(image, (20, 20))


def test_upright_vector_text_is_wider_than_it_is_tall_for_a_multi_char_string(write_design, db, bag):
    """The fixture assumption `test_angled_box_is_the_rotated_bounding_box`
    also relies on -- proven here against real drawn ink, not just the
    measured layout box, so a bug that measures one but draws the other
    would still be caught."""
    body = """\
  - id: brand
    type: text
    text: "GARMIN"
    font: font.bezel
    color: palette.fg
    at: {anchor: center}
    align: center
    vertical_align: center
"""
    image = _render(write_design, db, bag, body)
    bbox = _ink_bbox(image, (0, 0, 260, 260))
    assert bbox is not None
    minx, miny, maxx, maxy = bbox
    assert (maxx - minx) > (maxy - miny)


# -- angled --------------------------------------------------------------------


def test_angled_quarter_turn_swaps_width_and_height(write_design, db, bag):
    """`angled`'s `angle:` is a rotation from upright (0 = level), so
    `angle: 0deg` alone would draw the plain, unrotated shape and could not
    prove anything got rotated at all -- `angle: 90deg` is the quarter turn
    instead (`wfb.layout.garmin_curve_angle`: Garmin angle `270deg`,
    `tests/test_vector_text_layout.py::
    test_angled_box_is_the_rotated_bounding_box`) -- so the drawn ink must
    come out *taller* than it is wide, the opposite of the upright string
    above. A renderer that ignored `curve:` entirely, or rotated by the
    wrong (unconverted) angle, would still draw the wide/short shape and
    fail this."""
    body = """\
  - id: brand
    type: text
    text: "GARMIN"
    font: font.bezel
    color: palette.fg
    at: {anchor: center}
    align: center
    vertical_align: center
    curve: {style: angled, angle: 90deg}
"""
    image = _render(write_design, db, bag, body)
    bbox = _ink_bbox(image, (0, 0, 260, 260))
    assert bbox is not None
    minx, miny, maxx, maxy = bbox
    assert (maxy - miny) > (maxx - minx)


def test_angled_45deg_tilts_down_and_to_the_right_not_the_mirror_image(write_design, db, bag):
    """`angle: 45deg` is a *rotation*, positive = clockwise from level
    (`docs/format.md` "Angles"): Garmin `315deg` (`wfb.layout.
    garmin_curve_angle`: `(-45) % 360 == 315`). Visually, rotating a
    level, rightward-reading baseline clockwise tips its far end *down* --
    the same sense a clock hand sweeps from 3 toward 4-5 o'clock. `align:
    left` (rather than `center`) makes the contrast unambiguous: the whole
    string extends to *one* side of the anchor, not symmetrically through
    it, so every lit pixel must land down-and-right of the anchor and none
    up-or-left of it -- a backwards-signed rotation (the likely bug) would
    tilt the string up-and-right instead (mirrored about the horizontal),
    and an unrotated string would sit flat to the right with no vertical
    spread at all."""
    body = """\
  - id: brand
    type: text
    text: "GARMIN"
    font: font.bezel
    color: palette.fg
    at: {anchor: center}
    align: left
    vertical_align: center
    curve: {style: angled, angle: 45deg}
"""
    image = _render(write_design, db, bag, body)
    bbox = _ink_bbox(image, (0, 0, 260, 260))
    assert bbox is not None
    minx, miny, maxx, maxy = bbox
    # Every pixel is down and to the right of the anchor: the box's own
    # upper-left corner sits at (or past) the anchor, never inside the
    # opposite quadrant. Tolerance is 2px, not 1px: plan 12 R2 rasterises
    # this run through a 4x-supersampled layer instead of resampling an
    # already-blurred one, so a corner that used to anti-alias down below
    # `_ink_bbox`'s own 60-level threshold before it could ever reach this
    # pixel grid now clears it -- verified by hand (2026-09-21) that this
    # is real ink genuinely closer to the anchor, not a placement shift:
    # the pre-change render already had faint (~13/255) ink one row lower
    # at the same column, well under the threshold. A real backwards-signed
    # rotation would still fail this by tens of pixels, not two.
    assert minx >= CX - 2
    assert miny >= CY - 2
    # And it is genuinely tilted, not flat: real vertical spread, not a
    # one-pixel-tall sliver sitting exactly on the horizontal through the
    # anchor (which an un-rotated `align: left` upright string would draw).
    assert (maxy - miny) > (maxx - minx) * 0.3


def test_angled_180deg_is_a_true_rotation_not_a_mirror(write_design, db, bag):
    """Isolates *mirroring* (drawing a flipped glyph instead of a truly
    rotated one) from the direction-sign bugs the other angled tests above
    already cover. Design `angle: 180deg` is Garmin `180deg`
    (`wfb.layout.garmin_curve_angle`: `(-180) % 360 == 180`); a 180deg
    rotation is its own inverse regardless of which way is clockwise, so it
    cannot be satisfied by accident the way a smaller angle's direction
    might be -- an asymmetric glyph's `curve:`-drawn ink must match that
    same glyph's own upright ink run through a plain, independently-
    computed `PIL.Image.rotate(180)`, pixel region for pixel region. A
    mirror-instead-of-rotate bug (verified by hand while writing this test:
    flipping only the glyph layer's own rotation call, and not the
    paste-offset math that places it, produces exactly this -- same
    bounding box, backwards letterforms) fails this while still passing
    every bounding-box-direction test above."""
    upright_body = """\
  - id: glyph
    type: text
    text: "F4"
    font: font.bezel
    color: palette.fg
    at: {anchor: center}
    align: left
    vertical_align: top
"""
    angled_body = """\
  - id: glyph
    type: text
    text: "F4"
    font: font.bezel
    color: palette.fg
    at: {anchor: center}
    align: left
    vertical_align: top
    curve: {style: angled, angle: 180deg}
"""
    upright = _render(write_design, db, bag, upright_body, font_size="30%r")
    angled = _render(write_design, db, bag, angled_body, font_size="30%r")

    up_bbox = _ink_bbox(upright, (0, 0, 260, 260))
    an_bbox = _ink_bbox(angled, (0, 0, 260, 260))
    assert up_bbox is not None and an_bbox is not None

    def _mask(image, bbox):
        x0, y0, x1, y1 = bbox
        crop = image.crop((x0, y0, x1 + 1, y1 + 1))
        return [[1 if crop.getpixel((x, y))[0] > 60 else 0
                 for x in range(crop.width)]
                for y in range(crop.height)]

    upright_mask = _mask(upright, up_bbox)
    # An independent, plain 180deg rotation of the *upright* ink -- ground
    # truth this test computes itself, not through any of the code under
    # test.
    expected = [row[::-1] for row in upright_mask[::-1]]
    actual = _mask(angled, an_bbox)

    h = min(len(expected), len(actual))
    w = min(len(expected[0]), len(actual[0]))
    assert h > 5 and w > 5, "glyph too small to compare reliably"
    mismatches = sum(
        1 for y in range(h) for x in range(w) if expected[y][x] != actual[y][x]
    )
    total = h * w
    assert mismatches / total < 0.15, (
        f"{mismatches}/{total} pixels disagree with a true 180deg rotation "
        "of the upright glyph -- this looks mirrored, not rotated"
    )


# -- radial ----------------------------------------------------------------------


def test_radial_text_follows_the_circle_near_the_start_angle(write_design, db, bag):
    """`angle: 90deg` (design) is Garmin `0deg` -- the 3 o'clock point --
    and `align: left` starts the string exactly there."""
    body = """\
  - id: dial
    type: text
    text: "W"
    font: font.bezel
    color: palette.fg
    at: {anchor: center}
    align: left
    vertical_align: center
    curve: {style: radial, angle: 90deg, radius: 40%r, direction: clockwise}
"""
    image = _render(write_design, db, bag, body)
    start = _polar(CX, CY, 0.40 * 130, 0.0)
    assert _has_ink(image, start, tolerance=8)


def test_radial_clockwise_and_counter_clockwise_sweep_opposite_ways(write_design, db, bag):
    """Both runs start at the same Garmin-0deg (3 o'clock) point
    (`align: left`, `angle: 90deg` design); `direction:` alone decides
    which way subsequent glyphs go. `clockwise` must sweep toward
    *negative* Garmin angle (down and to the right, toward 4-5 o'clock);
    `counter_clockwise` toward *positive* Garmin angle (up and to the
    right, toward 1-2 o'clock) -- verified against the SDK's own
    `RADIAL_TEXT_SCENARIO` sample (`angle=0, orientation=CLOCKWISE,
    justification=LEFT` reads from 3 o'clock toward 6 o'clock). A reversed
    `direction_sign` would swap these two images, or a mirrored one would
    put ink in neither expected spot."""
    cw_body = """\
  - id: dial
    type: text
    text: "WWWWW"
    font: font.bezel
    color: palette.fg
    at: {anchor: center}
    align: left
    vertical_align: center
    curve: {style: radial, angle: 90deg, radius: 35%r, direction: clockwise}
"""
    ccw_body = cw_body.replace("direction: clockwise", "direction: counter_clockwise")

    below = _polar(CX, CY, 0.35 * 130, -40.0)  # toward 4-5 o'clock
    above = _polar(CX, CY, 0.35 * 130, 40.0)  # toward 1-2 o'clock

    cw_image = _render(write_design, db, bag, cw_body)
    assert _has_ink(cw_image, below, tolerance=10)
    assert not _has_ink(cw_image, above, tolerance=10)

    ccw_image = _render(write_design, db, bag, ccw_body)
    assert _has_ink(ccw_image, above, tolerance=10)
    assert not _has_ink(ccw_image, below, tolerance=10)


def test_radial_counter_clockwise_at_six_oclock_faces_inward_not_outward(write_design, db, bag):
    """The defect this step fixes. `curve: {style: radial}`'s per-glyph
    facing is `pos - 90` (outward) for `clockwise`, `pos + 90` (inward) for
    `counter_clockwise` (`wfb.preview._Renderer._draw_radial_vector_text`'s
    own docstring has the derivation). At the 6 o'clock point (design
    `angle: 180deg` is Garmin `270deg`), inward happens to land on exactly
    *zero* local rotation (`270 + 90 == 360 == 0`), so a single glyph drawn
    there with `counter_clockwise` must be pixel-for-pixel the same shape
    as that glyph drawn as ordinary upright `text` -- not the shape of the
    same glyph rotated 180deg, which is what the pre-fix "always outward"
    behaviour drew there instead (`pos - 90 == 180`). A single character
    with `align: left` isolates facing from letter order entirely: with
    only one glyph, `direction:` cannot be observed through sweep order
    (`test_radial_clockwise_and_counter_clockwise_sweep_opposite_ways`
    above already covers order), only through which way it faces."""
    upright_body = """\
  - id: glyph
    type: text
    text: "R"
    font: font.bezel
    color: palette.fg
    at: {anchor: center}
    align: left
    vertical_align: center
"""
    radial_ccw_body = """\
  - id: glyph
    type: text
    text: "R"
    font: font.bezel
    color: palette.fg
    at: {anchor: center}
    align: left
    vertical_align: center
    curve: {style: radial, angle: 180deg, radius: 40%r, direction: counter_clockwise}
"""
    upright = _render(write_design, db, bag, upright_body, font_size="30%r")
    ccw = _render(write_design, db, bag, radial_ccw_body, font_size="30%r")

    up_bbox = _ink_bbox(upright, (0, 0, 260, 260))
    ccw_bbox = _ink_bbox(ccw, (0, 0, 260, 260))
    assert up_bbox is not None and ccw_bbox is not None

    upright_mask = _glyph_mask(upright, up_bbox)
    ccw_mask = _glyph_mask(ccw, ccw_bbox)
    rotated_180_mask = [row[::-1] for row in upright_mask[::-1]]

    same_as_upright = _mask_mismatch_fraction(upright_mask, ccw_mask)
    same_as_180 = _mask_mismatch_fraction(rotated_180_mask, ccw_mask)
    assert same_as_upright < 0.15, (
        f"counter_clockwise glyph at 6 o'clock disagrees with plain upright "
        f"text in {same_as_upright:.0%} of pixels -- it should face inward, "
        "which is unrotated at this exact point"
    )
    assert same_as_180 > 0.3, (
        "counter_clockwise glyph at 6 o'clock matches a 180deg-rotated "
        "upright glyph -- it is facing outward (upside down), the pre-fix "
        "bug this test exists to catch"
    )


def test_radial_clockwise_at_six_oclock_faces_outward_upside_down(write_design, db, bag):
    """The mirror image of the test above, and together with it a full
    discriminator between the two `direction:` values' facing (not just
    their sweep order). At 6 o'clock, `clockwise`'s *outward* facing is a
    true 180deg rotation of upright (`pos - 90 == 180` there) -- checked
    against an independently-computed 180deg rotation of the same glyph's
    own upright mask, exactly as
    `test_angled_180deg_is_a_true_rotation_not_a_mirror` isolates a true
    rotation from a mirrored glyph for `angled` text."""
    upright_body = """\
  - id: glyph
    type: text
    text: "R"
    font: font.bezel
    color: palette.fg
    at: {anchor: center}
    align: left
    vertical_align: center
"""
    radial_cw_body = """\
  - id: glyph
    type: text
    text: "R"
    font: font.bezel
    color: palette.fg
    at: {anchor: center}
    align: left
    vertical_align: center
    curve: {style: radial, angle: 180deg, radius: 40%r, direction: clockwise}
"""
    upright = _render(write_design, db, bag, upright_body, font_size="30%r")
    cw = _render(write_design, db, bag, radial_cw_body, font_size="30%r")

    up_bbox = _ink_bbox(upright, (0, 0, 260, 260))
    cw_bbox = _ink_bbox(cw, (0, 0, 260, 260))
    assert up_bbox is not None and cw_bbox is not None

    upright_mask = _glyph_mask(upright, up_bbox)
    cw_mask = _glyph_mask(cw, cw_bbox)
    rotated_180_mask = [row[::-1] for row in upright_mask[::-1]]

    same_as_180 = _mask_mismatch_fraction(rotated_180_mask, cw_mask)
    same_as_upright = _mask_mismatch_fraction(upright_mask, cw_mask)
    assert same_as_180 < 0.15, (
        f"clockwise glyph at 6 o'clock disagrees with a true 180deg "
        f"rotation of upright text in {same_as_180:.0%} of pixels -- this "
        "looks mirrored or unrotated, not a true 180deg rotation"
    )
    assert same_as_upright > 0.3, (
        "clockwise glyph at 6 o'clock matches plain upright text -- it "
        "should face outward (upside down at this point), not inward"
    )


# -- font_available: False (if_unavailable: hide) --------------------------------


def test_unavailable_vector_font_draws_nothing_upright_or_curved(write_design, db, bag):
    """fenix6 has no vector fonts at all (gate 1) -- `if_unavailable: hide`
    on the font means every element using it draws nothing, upright or
    curved, the same as the real watch (plan 11 §2.4): the honest preview
    of "this element does not exist on this device" is a blank image, not
    a fallback face drawn at the wrong place."""
    body = """\
  - id: upright
    type: text
    text: "HIDDEN"
    font: font.bezel
    color: palette.fg
    at: {anchor: center, dy: -30%r}
    align: center
    vertical_align: center
  - id: angled
    type: text
    text: "HIDDEN"
    font: font.bezel
    color: palette.fg
    at: {anchor: center, dy: 30%r}
    align: center
    vertical_align: center
    curve: {style: angled, angle: 20deg}
"""
    image = _render(write_design, db, bag, body, target="fenix6", hide=True)
    for y in range(0, 260, 4):
        for x in range(0, 260, 4):
            assert image.getpixel((x, y)) == BACKGROUND, (x, y)


# -- R2 (plan 12): rasterised, not resampled --------------------------------


def _weighted_centroid(image, region: tuple[int, int, int, int] = (0, 0, 260, 260),
                       min_channel: int = 10) -> tuple[float, float]:
    """Intensity-weighted centre of mass of every pixel in `region` lit
    above `min_channel` -- `_paste_rotated_run`'s own R2.2 contrast.
    Weighted, not a hard bounding box (`_ink_bbox`): R2's whole point is
    that ink gets *sharper*, which is exactly the kind of change a single
    threshold-crossing pixel at one corner can misreport as "moved" by a
    pixel or two on its own (see the tolerance note on
    `test_angled_45deg_tilts_down_and_to_the_right_not_the_mirror_image`
    above, hit while writing this test) -- a soft, low-level anti-aliased
    tail and a tight, high-contrast edge both contribute their own real
    weight to a centroid instead."""
    x0, y0, x1, y1 = region
    sx = sy = total = 0.0
    for y in range(y0, y1):
        for x in range(x0, x1):
            r, g, b = image.getpixel((x, y))
            w = max(r, g, b)
            if w > min_channel:
                sx += w * x
                sy += w * y
                total += w
    assert total > 0, "no ink drawn at all"
    return sx / total, sy / total


def _assert_centre_of_mass_stable(write_design, db, bag, monkeypatch, body: str) -> None:
    """Renders `body` twice -- once with R2's supersample-then-downsample
    path live, once with `_ROTATED_TEXT_SUPERSAMPLE` monkeypatched to `1`
    -- and asserts the drawn ink's centre of mass moved by under a pixel.

    Forcing the factor to `1` is not a second, independently-typed copy of
    the pre-R2 formula that could quietly drift from what
    `_paste_rotated_run` actually does: `ss == 1` skips every line R2
    added (the supersampled `_system_face` lookup, the wider layer, the
    `Image.LANCZOS` downsample) and falls straight through to exactly the
    arithmetic that shipped before this slice, so this comparison *is* the
    "against the pre-change implementation" check plan 12 R2.2 asks for,
    read from the one place that arithmetic lives rather than re-derived.

    A regression here would mean every `angled`/`radial` element this
    preview draws silently moved -- the reason this test is the point of
    the slice, not an afterthought."""
    with monkeypatch.context() as m:
        m.setattr(preview_module, "_ROTATED_TEXT_SUPERSAMPLE", 1)
        baseline = _render(write_design, db, bag, body, font_size="30%r")
    supersampled = _render(write_design, db, bag, body, font_size="30%r")

    bx, by = _weighted_centroid(baseline)
    sx, sy = _weighted_centroid(supersampled)
    drift = math.hypot(bx - sx, by - sy)
    assert drift < 1.0, (
        f"centre of mass moved {drift:.3f}px when supersampling was "
        "turned on -- R2 must change ink weight, not placement"
    )


@pytest.mark.parametrize("angle", [0, 20, 45, 90, 135, 200, 270, 330])
def test_angled_supersampling_does_not_move_the_centre_of_mass(write_design, db, bag, monkeypatch, angle):
    """R2.2, `angled` -- a spread of angles, including axis-aligned ones
    (`0`/`90`/`270`, where `Image.rotate`'s own `expand=True` bounding box
    is a no-op or a pure swap) and oblique ones (`45`/`135`/`200`/`330`,
    where it genuinely grows). A single glyph (`"R"`), not a multi-
    character word, isolates the anchor maths from a second, expected,
    unrelated source of sub-pixel movement: a supersampled face's own
    per-glyph advances are measured on a different (larger) pixel grid
    than the ordinary-scale face's `hmtx` rounding, so a multi-glyph run's
    *total* width can differ from the ordinary-scale run's by a fraction
    of a pixel purely from independent rounding at each scale -- real,
    harmless, and not what this test is checking."""
    body = f"""\
  - id: glyph
    type: text
    text: "R"
    font: font.bezel
    color: palette.fg
    at: {{anchor: center}}
    align: center
    vertical_align: center
    curve: {{style: angled, angle: {angle}deg}}
"""
    _assert_centre_of_mass_stable(write_design, db, bag, monkeypatch, body)


@pytest.mark.parametrize("angle", [0, 45, 90, 180, 270])
def test_radial_supersampling_does_not_move_the_centre_of_mass(write_design, db, bag, monkeypatch, angle):
    """R2.2, `radial` -- `_draw_radial_vector_text` calls
    `_paste_rotated_run` once per glyph (its own docstring), so it
    inherits R2 exactly the same way `angled` text does and needs the same
    guard; a bug that only threaded `font_metric` through one of the two
    call sites (R2.3's own warning) would leave this one still resampling
    while `test_angled_supersampling_does_not_move_the_centre_of_mass`
    passed, so the two tests together are what actually confirm "both call
    sites... consistent." """
    body = f"""\
  - id: glyph
    type: text
    text: "R"
    font: font.bezel
    color: palette.fg
    at: {{anchor: center}}
    align: center
    vertical_align: center
    curve: {{style: radial, angle: {angle}deg, radius: 30%r, direction: clockwise}}
"""
    _assert_centre_of_mass_stable(write_design, db, bag, monkeypatch, body)


def test_paste_rotated_run_skips_supersampling_for_a_bitmap_face():
    """R2.4: a bitmap (`.cft`) face has no outline to supersample.
    Purely defensive -- gate 2 (`docs/lore/codegen.md`) only ever publishes
    an outline face as a vector `face:` font, so `_draw_vector_text` can
    never actually hand `_paste_rotated_run` a bitmap `SystemFace` from a
    real design, which is why this test builds a bare `_Renderer` and a
    stand-in bitmap face directly instead of going through `_render` --
    there is no `curve:` design that could reach this branch to exercise
    it any other way.

    The stand-in `bitmap` is not a real decoded `.cft` (`wfb.fonts.cft`'s
    own tests already cover that decode); it only needs the one method
    `SystemFace.advances` calls. What this test actually checks is that
    `_paste_rotated_run` never calls `_system_face` at all when
    `face.bitmap` is set (monkeypatched to raise if it is) and draws
    through the bitmap face itself, at `ss == 1` -- the layer it hands
    `_draw_system_line` is exactly `layer_w x layer_h`, never
    `_ROTATED_TEXT_SUPERSAMPLE` times larger."""
    from PIL import Image, ImageDraw

    from wfb.fonts.fallback import SystemFace
    from wfb.preview import PreviewOptions, _Renderer

    class _StubBitmap:
        def advances(self, text: str) -> list[float]:
            return [6.0 for _ in text]

    face = SystemFace(font=None, line_height=12, baseline=9, match="garmin",
                      path="stand-in.cft", bitmap=_StubBitmap())

    canvas = Image.new("RGB", (40, 40), (0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    renderer = _Renderer(None, draw, canvas, 1, {}, PreviewOptions())

    def _boom(*args, **kwargs):
        raise AssertionError("_system_face must not be called for a bitmap face")

    renderer._system_face = _boom

    seen: dict = {}
    real_draw_system_line = _Renderer._draw_system_line

    def _spy(self, drawn_face, left, baseline_y, text, color, *, draw=None, image=None):
        seen["face"] = drawn_face
        seen["layer_size"] = image.size
        return real_draw_system_line(self, drawn_face, left, baseline_y, text, color,
                                     draw=draw, image=image)

    renderer._draw_system_line = _spy.__get__(renderer, _Renderer)

    renderer._paste_rotated_run(face, "R", 30.0, "left", "top", (20, 20),
                                (255, 255, 255), font_metric=object())

    assert seen["face"] is face  # render_face stayed the bitmap face itself
    # Same `pad`/`layer_w`/`layer_h` formula `_paste_rotated_run` itself
    # uses, reproduced rather than hand-computed, so this assertion is
    # about `ss` staying `1` (no widening), not a second copy of the sizing
    # arithmetic that could drift from the real one.
    pad = max(2, int(math.ceil(face.line_height * 0.2)))
    width = face.width("R")
    layer_w = int(math.ceil(width)) + 2 * pad
    layer_h = int(math.ceil(face.line_height)) + 2 * pad
    assert seen["layer_size"] == (layer_w, layer_h)  # ss == 1, no widening
