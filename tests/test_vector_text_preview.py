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

import itertools
import math

import pytest

from wfb import build
from wfb import preview as preview_module
from wfb.emit.resources import bake_fonts
from wfb.fonts.fallback import system_face
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
    (`docs/guide/placement.md` "Angles"): Garmin `315deg` (`wfb.layout.
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
    with `align: center` isolates facing from letter order entirely: with
    only one glyph, `direction:` cannot be observed through sweep order
    (`test_radial_clockwise_and_counter_clockwise_sweep_opposite_ways`
    above already covers order), only through which way it faces. `align:
    center` (not `left`, the per-glyph midline fix) is what puts this
    single glyph's own centre -- not its left edge -- exactly on the 6
    o'clock point
    (`align_offset == advance / 2` cancels the fix's own `pen + advance /
    2` for a one-character string, for *any* advance), so the exact-180
    comparison below is checking facing alone, with no residual position
    offset of its own to confound it."""
    upright_body = """\
  - id: glyph
    type: text
    text: "R"
    font: font.bezel
    color: palette.fg
    at: {anchor: center}
    align: center
    vertical_align: center
"""
    radial_ccw_body = """\
  - id: glyph
    type: text
    text: "R"
    font: font.bezel
    color: palette.fg
    at: {anchor: center}
    align: center
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
    rotation from a mirrored glyph for `angled` text. `align: center`
    (not `left`, the per-glyph midline fix) puts this single glyph's own
    centre -- not its left edge -- exactly on the 6 o'clock point, so the
    same-shape comparison below is not confounded by a residual position
    offset of its own (`test_radial_counter_clockwise_at_six_oclock_faces_
    inward_not_outward`'s own docstring has the exact-cancellation
    reasoning)."""
    upright_body = """\
  - id: glyph
    type: text
    text: "R"
    font: font.bezel
    color: palette.fg
    at: {anchor: center}
    align: center
    vertical_align: center
"""
    radial_cw_body = """\
  - id: glyph
    type: text
    text: "R"
    font: font.bezel
    color: palette.fg
    at: {anchor: center}
    align: center
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


def _weighted_mean_radius(image, cx: int, cy: int,
                          region: tuple[int, int, int, int] = (0, 0, 260, 260),
                          min_channel: int = 60) -> float:
    """Intensity-weighted mean *radial* distance from `(cx, cy)` of every
    lit pixel in `region` -- the same anti-aliasing-tolerant weighting
    `_weighted_centroid` above uses for centre-of-mass (`w = max(r, g,
    b)`), folded onto one radial axis instead of two Cartesian ones: what
    `vertical_align` under `curve: {style: radial}` actually claims is
    about the *circle* -- how far out or in the ink sits -- not where its
    centroid falls in x/y, which a curved run can also shift sideways
    along the arc for reasons (advance rounding, `align:`) unrelated to
    vertical alignment."""
    x0, y0, x1, y1 = region
    wsum = total = 0.0
    for y in range(y0, y1):
        for x in range(x0, x1):
            r, g, b = image.getpixel((x, y))
            w = max(r, g, b)
            if w > min_channel:
                wsum += w * math.hypot(x - cx, y - cy)
                total += w
    assert total > 0, "no ink drawn at all"
    return wsum / total


# `curve: {style: radial, angle: 90deg, radius: 40%r}` places the single
# glyph these tests draw at the Garmin-0deg (3 o'clock) point, `0.40 * 130`
# preview px out from `(CX, CY)` -- the same `_polar`/`radius` combination
# `test_radial_text_follows_the_circle_near_the_start_angle` above already
# uses, reused here as the "nominal" (`center`-aligned, no baseline shift)
# radius bottom/top ink is claimed to sit outside/inside of.
_NOMINAL_RADIUS = 0.40 * 130


def _radial_mean_radius(write_design, db, bag, *, direction: str, vertical_align: str) -> float:
    body = f"""\
  - id: glyph
    type: text
    text: "R"
    font: font.bezel
    color: palette.fg
    at: {{anchor: center}}
    align: left
    vertical_align: {vertical_align}
    curve: {{style: radial, angle: 90deg, radius: 40%r, direction: {direction}}}
"""
    # A large-ish glyph (`font_size` well above the other radial tests'
    # default `10%r`): the gap this bug produces is about one ascent
    # (`face.baseline`), so the glyph has to be big enough for that gap to
    # dominate anti-aliasing noise at the pixel level.
    image = _render(write_design, db, bag, body, font_size="20%r")
    return _weighted_mean_radius(image, CX, CY)


def test_radial_clockwise_vertical_align_orders_ink_radius_top_lt_center_lt_bottom(write_design, db, bag):
    """The bug this test guards: `Dc.drawRadialText` WITHOUT
    `TEXT_JUSTIFY_VCENTER` puts the text's BASELINE on the circle, each
    glyph growing toward its own "up" -- outward for `clockwise`
    (`wfb.preview._Renderer._draw_radial_vector_text`'s own facing model:
    `clockwise` faces outward). So under `clockwise`: `top` (line box top
    edge on the circle, hanging inward/"down") sits closest to the centre,
    `center` (VCENTER, box straddling the circle) in the middle, and
    `bottom` (baseline on the circle, ascender reaching further outward
    than the box-centre case) sits furthest out -- `r(top) < r(center) <
    r(bottom)`. A broken `bottom` branch (the pre-fix state: no ascent
    shift at all, or the shift's sign flipped so it moves `bottom` in
    instead of out) would either put `bottom` at the same radius as `top`
    (no ordering) or push it inward past `center`, failing the strict
    ordering asserted below -- this is the exact contrast the fix claims,
    not just "some difference exists.\""""
    r_top = _radial_mean_radius(write_design, db, bag, direction="clockwise", vertical_align="top")
    r_center = _radial_mean_radius(write_design, db, bag, direction="clockwise", vertical_align="center")
    r_bottom = _radial_mean_radius(write_design, db, bag, direction="clockwise", vertical_align="bottom")
    assert r_top < r_center < r_bottom, (r_top, r_center, r_bottom)
    # And the two extremes actually cross the circle itself, not merely
    # order correctly on the same side of it.
    assert r_bottom > _NOMINAL_RADIUS, (
        f"clockwise 'bottom' ink (mean r={r_bottom:.1f}) should sit mostly "
        f"OUTSIDE the nominal circle radius ({_NOMINAL_RADIUS:.1f}px) -- "
        "the baseline sits ON the circle and glyphs face outward"
    )
    assert r_top < _NOMINAL_RADIUS, (
        f"clockwise 'top' ink (mean r={r_top:.1f}) should sit mostly "
        f"INSIDE the nominal circle radius ({_NOMINAL_RADIUS:.1f}px)"
    )


def test_radial_counter_clockwise_vertical_align_orders_ink_radius_bottom_lt_center_lt_top(write_design, db, bag):
    """The mirror of the test above: `counter_clockwise` faces INWARD, so
    every "up"/"outward" in that test's reasoning flips -- `bottom`
    (baseline on the circle, ascender reaching further inward) sits
    closest to the centre, `top` (box top edge on the circle, hanging
    outward) sits furthest out, `r(bottom) < r(center) < r(top)` -- and
    `bottom` ink lands mostly INSIDE the circle, `top` mostly OUTSIDE,
    exactly the opposite pairing from `clockwise` above. A `bottom` branch
    that used the wrong sign for `counter_clockwise` specifically (e.g. it
    happened to get `clockwise` right by accident but shares one un-mirrored
    sign for both directions) would fail only this test while the
    `clockwise` one above still passed, which is why both directions are
    asserted, not just one."""
    r_top = _radial_mean_radius(write_design, db, bag, direction="counter_clockwise", vertical_align="top")
    r_center = _radial_mean_radius(write_design, db, bag, direction="counter_clockwise", vertical_align="center")
    r_bottom = _radial_mean_radius(write_design, db, bag, direction="counter_clockwise", vertical_align="bottom")
    assert r_bottom < r_center < r_top, (r_bottom, r_center, r_top)
    assert r_bottom < _NOMINAL_RADIUS, (
        f"counter_clockwise 'bottom' ink (mean r={r_bottom:.1f}) should sit "
        f"mostly INSIDE the nominal circle radius ({_NOMINAL_RADIUS:.1f}px) "
        "-- the baseline sits ON the circle and glyphs face inward"
    )
    assert r_top > _NOMINAL_RADIUS, (
        f"counter_clockwise 'top' ink (mean r={r_top:.1f}) should sit "
        f"mostly OUTSIDE the nominal circle radius ({_NOMINAL_RADIUS:.1f}px)"
    )


# -- R1: per-glyph midline on its own radius, not half an advance off ------------


def _perp_distance_from_ray(cx: float, cy: float, angle_garmin_degrees: float,
                             point: tuple[float, float]) -> float:
    """How far `point` sits from the infinite line through `(cx, cy)` at
    Garmin angle `angle_garmin_degrees` -- the "off its own radius" measure
    R1 claims fixes: a glyph whose midline truly lies on the radius through
    its own centre has its ink's centre of mass land on this line (distance
    ~0); the pre-fix left-edge-anchored placement displaces it tangentially
    instead, so this distance is what catches it. `(cos, -sin)` is the
    outward unit vector at that angle in Garmin's convention (screen y
    down, `_polar`'s own convention above); the perpendicular distance from
    a point to a line through the origin along a *unit* direction is the
    magnitude of their 2D cross product."""
    theta = math.radians(angle_garmin_degrees)
    ux, uy = math.cos(theta), -math.sin(theta)
    vx, vy = point[0] - cx, point[1] - cy
    return abs(vx * uy - vy * ux)


def _find_ink_blobs(image, region: tuple[int, int, int, int] = (0, 0, 260, 260),
                     min_channel: int = 60) -> list[list[tuple[int, int]]]:
    """4-connected flood fill over every lit pixel in `region`, returning
    one pixel list per connected component -- how this file tells "several
    separate glyphs" apart in a single rendered image without assuming
    anything about where each one landed (which is exactly what is under
    test): a bug that shifts every glyph would still leave them as
    separate blobs (they stay well clear of each other, by design -- see
    `test_radial_same_width_glyphs_each_sit_on_their_own_radius`'s own
    spacing), just at the wrong positions, which the caller checks
    separately."""
    x0, y0, x1, y1 = region
    w, h = x1 - x0, y1 - y0
    visited = [[False] * w for _ in range(h)]

    def lit(x: int, y: int) -> bool:
        r, g, b = image.getpixel((x, y))
        return r > min_channel or g > min_channel or b > min_channel

    blobs: list[list[tuple[int, int]]] = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            lx, ly = x - x0, y - y0
            if visited[ly][lx]:
                continue
            visited[ly][lx] = True
            if not lit(x, y):
                continue
            stack = [(x, y)]
            pixels = [(x, y)]
            while stack:
                cx0, cy0 = stack.pop()
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx0 + dx, cy0 + dy
                    if x0 <= nx < x1 and y0 <= ny < y1:
                        nlx, nly = nx - x0, ny - y0
                        if not visited[nly][nlx]:
                            visited[nly][nlx] = True
                            if lit(nx, ny):
                                stack.append((nx, ny))
                                pixels.append((nx, ny))
            blobs.append(pixels)
    return blobs


def _blob_centroid(image, pixels: list[tuple[int, int]], min_channel: int = 60) -> tuple[float, float]:
    """Intensity-weighted centre of mass of one `_find_ink_blobs` blob --
    the same weighting `_weighted_centroid` above uses, restricted to one
    connected component's own pixels instead of a whole region."""
    sx = sy = total = 0.0
    for x, y in pixels:
        r, g, b = image.getpixel((x, y))
        w = max(r, g, b)
        if w > min_channel:
            sx += w * x
            sy += w * y
            total += w
    assert total > 0
    return sx / total, sy / total


def _render_with_resolved(write_design, db, bag, body: str, *, target: str = "fenix8solar47mm",
                          font_size: str = "10%r", **options):
    """Like `_render` above, but also hands back the `ResolvedFace` --
    `wfb.layout.resolve`'s own output, built by the *same* pipeline `wfb
    build`/`wfb preview` use, never by `wfb.preview`'s per-glyph loop
    (`_draw_radial_vector_text`, the code under test here). The two tests
    below read `curve.radius_px`/`curve.angle_garmin`/`anchor_point` off it
    directly (`wfb.layout`'s own resolved geometry -- already verified
    elsewhere, e.g. `tests/test_vector_text_layout.py`) and real glyph
    advances off `wfb.fonts.fallback.system_face` -- both independent of
    the placement arithmetic being tested -- so the *expected* slot a
    glyph should land at can be predicted without importing or re-running
    any of `_draw_radial_vector_text`'s own code, the same
    independent-prediction discipline `_polar` above uses for the simpler,
    whole-string tests."""
    design = _HEADER.format(target=target, if_unavailable="", body=body, font_size=font_size)
    path = write_design(design)
    face = build.load(path, bag)
    assert face is not None, bag.render()
    device = db.get(target)
    resolved = resolve(face, device, bake_fonts(face, device))
    opts = {"scale": 1, "mask_shape": False, "quantise": False, **options}
    image = render(resolved, PreviewOptions(**opts))
    return image, resolved


def _placed(resolved, element_id: str):
    """The `Placed*` item for `element_id` -- `resolved.items` has one per
    element, each carrying its own source `.element` back-reference."""
    return next(item for item in resolved.items
                if getattr(getattr(item, "element", None), "id", None) == element_id)


def _expected_radial_slot(placed, text: str, index: int) -> float:
    """R1's own formula (`pen + advance/2 - align_offset`, turned into an
    angle with `direction_sign`/`radius`) for `text[index]`'s expected
    Garmin angle, assuming `placed.align == "center"` (so `align_offset ==
    sum(advances) / 2`, matching every design below) -- reproduced here,
    independently, using real advances from `wfb.fonts.fallback.
    system_face` (never from `wfb.preview`'s own per-glyph loop, the code
    under test), so a bug in that loop cannot also hide from the
    prediction it is checked against. `sum(text[:index])`'s pen still
    counts a space's own advance even though a space draws no ink -- the
    same pen a real render advances by."""
    face = system_face(placed.font.metric)
    advances = face.advances(text)
    align_offset = sum(advances) / 2.0
    pen = sum(advances[:index])
    pixel_offset = pen + advances[index] / 2.0 - align_offset
    direction_sign = 1.0 if placed.curve.direction == "counter_clockwise" else -1.0
    theta = math.radians(placed.curve.angle_garmin) + direction_sign * (pixel_offset / placed.curve.radius_px)
    return math.degrees(theta) % 360.0


def test_radial_wide_glyph_centre_of_mass_sits_on_its_own_radius(write_design, db, bag):
    """R1: `_draw_radial_vector_text` must place a glyph at the arc
    position of the *middle* of its advance, not its left edge -- ground
    truth from the real simulator (2026-09-21, `fenix8solar51mm`, large
    roman numerals in `examples/showcase`): every glyph's own vertical
    midline lies on the radius through that glyph's own centre, like
    spokes. A single glyph with `align: center` isolates this cleanly: the
    whole-string `align:` (already correct, out of scope for R1) places
    this one glyph's *slot* exactly at `curve.angle` regardless of its
    advance width (`align_offset == total / 2 == advance / 2` for a
    one-character string, so `pixel_offset` is exactly `0` under the fix,
    for *any* advance) -- so a correct per-glyph placement puts the ink's
    centre of mass exactly on the radius through `curve.angle` (Garmin
    `40deg` for the design `50deg` used below -- away from every axis in
    either convention, so the bug cannot hide behind the glyph's own
    left/right or top/bottom symmetry), while the pre-fix left-edge-
    anchored placement (`pixel_offset = pen - align_offset`, i.e.
    `-advance / 2`, always pasted `align="left"`) rotates the glyph about
    its own left edge instead of its centre, displacing the ink
    tangentially. A very large glyph relative to a small radius (`80%r`
    font, `20%r` radius) makes the pre-fix displacement tens of pixels,
    not a fraction of one -- confirmed against the unfixed code (the
    mandatory red run) before this fix landed: centre of mass ~12-18px off
    this same ray, an order of magnitude past the tolerance below, never a
    coin-flip near it."""
    body = f"""\
  - id: glyph
    type: text
    text: "H"
    font: font.bezel
    color: palette.fg
    at: {{anchor: center}}
    align: center
    vertical_align: center
    curve: {{style: radial, angle: 50deg, radius: 20%r, direction: clockwise}}
"""
    image, resolved = _render_with_resolved(write_design, db, bag, body, font_size="80%r")
    placed = _placed(resolved, "glyph")
    centroid = _weighted_centroid(image)
    cx, cy = placed.anchor_point
    dist = _perp_distance_from_ray(cx, cy, placed.curve.angle_garmin, centroid)
    assert dist < 3.0, (
        f"glyph centre of mass is {dist:.2f}px off the radius through "
        f"curve.angle ({placed.curve.angle_garmin:.1f}deg Garmin) -- "
        "expected it to sit on that radius (R1); a distance anywhere near "
        "the glyph's own half-advance width means the pre-fix left-edge-"
        "anchored placement bug is back"
    )


def test_radial_same_width_glyphs_each_sit_on_their_own_radius(write_design, db, bag):
    """The multi-glyph half of R1/R2: three same-width glyphs ("H"),
    spaced out with literal spaces (which advance the pen and draw no ink)
    so each glyph's own blob stays well clear of its neighbours -- three
    *adjacent* "H"s touch/overlap into a single connected blob at any
    font/radius ratio big enough to make the bug's displacement clear
    anti-aliasing noise, regardless of the bug, which would make this test
    measure glyph spacing instead of glyph placement (verified by hand
    while tuning these parameters: this exact font/radius/spacing
    combination gives three separate blobs both before and after R1 --
    the two states move the ink by only a few px, not by the tens of px a
    single, un-spaced glyph can show, so the spacing has to be tuned
    against *both* to avoid a red run that merely fails to find three
    blobs at all, and R2 requires the red run to fail for the *placement*
    reason). `align: center` on the whole string keeps the classic
    three-slot symmetry (`-a, 0, +a` arc-length offsets from `curve.angle`
    for the first/middle/last "H"), but each glyph's own expected slot is
    computed independently by `_expected_radial_slot` (real advances, not
    assumed equal) rather than relying on that symmetry alone.

    Blobs are matched to expected slots by nearest total distance
    (`itertools.permutations` over just 3 candidates), not by sorting on
    raw Garmin angle: `direction: clockwise` sweeps through *decreasing*
    Garmin angle as the pen advances, which wraps through 0/360 for this
    design's own angle/spacing (discovered while tuning this test --
    sorting by angle mod 360 silently mismatched glyphs to the wrong
    slots across the wraparound and produced a nonsense ~25-30px "red"
    failure for the wrong reason). The pre-fix bug's tangential
    displacement is close to uniform across the three glyphs -- confirmed
    against the unfixed code (the mandatory red run): all three land
    ~3-4px off their own expected slot, not just one of them, which is
    what proves each glyph independently sits on its own radius rather
    than merely holding together as a group."""
    text = "H  H  H"
    body = f"""\
  - id: glyphs
    type: text
    text: "{text}"
    font: font.bezel
    color: palette.fg
    at: {{anchor: center}}
    align: center
    vertical_align: center
    curve: {{style: radial, angle: 50deg, radius: 28%r, direction: clockwise}}
"""
    image, resolved = _render_with_resolved(write_design, db, bag, body, font_size="65%r")
    placed = _placed(resolved, "glyphs")
    glyph_indices = [i for i, ch in enumerate(text) if ch != " "]
    expected_angles = [_expected_radial_slot(placed, text, i) for i in glyph_indices]
    n = len(expected_angles)

    blobs = [b for b in _find_ink_blobs(image) if len(b) > 10]  # drop stray AA specks
    assert len(blobs) == n, f"expected {n} separate glyph blobs, found {len(blobs)}"

    cx, cy = placed.anchor_point
    centroids = [_blob_centroid(image, b) for b in blobs]
    # Nearest-match assignment (see the docstring above for why this is
    # not a simple angle sort): the permutation of blobs -> expected slots
    # that minimises the total perpendicular distance.
    best_perm = min(
        itertools.permutations(range(n)),
        key=lambda perm: sum(_perp_distance_from_ray(cx, cy, expected_angles[i], centroids[perm[i]])
                             for i in range(n)),
    )

    for i in range(n):
        centroid = centroids[best_perm[i]]
        dist = _perp_distance_from_ray(cx, cy, expected_angles[i], centroid)
        assert dist < 2.0, (
            f"glyph {i} ('H' #{i}) centre of mass is {dist:.2f}px off the "
            f"radius through its own expected slot ({expected_angles[i]:.2f}deg "
            f"Garmin) -- each same-width glyph must sit on its own radius, "
            "not offset by (roughly) half an advance from it"
        )


def _principal_axis_angle(image, pixels: list[tuple[int, int]],
                          min_channel: int = 60) -> tuple[float, tuple[float, float]]:
    """The weighted second-moment principal (major) axis of one ink blob,
    as an angle in image coordinates (screen y-down, same frame as every
    `(x, y)` pixel), together with its weighted centroid. A thin, roughly
    straight bar (an "I") has one dominant axis of inertia running along
    its own length, so this recovers "which way this stroke points"
    directly from the pixels -- not from any angle the code under test
    computed -- exactly the standard image-moments formula for an
    ellipse's major axis (`0.5 * atan2(2*Sxy, Sxx - Syy)` on the
    intensity-weighted central second moments), range `(-90, 90]` degrees
    since a *line*'s own orientation (not a directed vector) is only
    defined modulo 180 degrees -- `_acute_angle_diff` below is what
    compares two such orientations correctly."""
    sx = sy = sw = 0.0
    weighted = []
    for x, y in pixels:
        r, g, b = image.getpixel((x, y))
        w = max(r, g, b)
        if w > min_channel:
            weighted.append((x, y, w))
            sx += w * x
            sy += w * y
            sw += w
    assert sw > 0
    mx, my = sx / sw, sy / sw
    sxx = syy = sxy = 0.0
    for x, y, w in weighted:
        dx, dy = x - mx, y - my
        sxx += w * dx * dx
        syy += w * dy * dy
        sxy += w * dx * dy
    angle = math.degrees(0.5 * math.atan2(2 * sxy, sxx - syy))
    return angle, (mx, my)


def _acute_angle_diff(a_degrees: float, b_degrees: float) -> float:
    """The smallest angle between two *undirected* lines' own orientations
    (each only defined modulo 180 degrees) -- `0` when parallel, up to `90`
    when perpendicular."""
    diff = (a_degrees - b_degrees) % 180.0
    return min(diff, 180.0 - diff)


def test_radial_glyph_stroke_points_at_the_circles_centre(write_design, db, bag):
    """The user-visible defect, measured directly by orientation rather
    than by centre of mass (the two tests above): ground truth from the
    real simulator (2026-09-21, `fenix8solar51mm`, large roman numerals in
    `examples/showcase`) is that every stroke of every "I" points exactly
    at the circle's centre, like spokes. The two centre-of-mass tests
    above only see this defect as a *second-order* effect (the pre-fix
    anchor and the pre-fix paste-alignment shift partly cancel in
    *position*, which is why those tests needed an extreme font-to-radius
    ratio to separate red from green) -- the defect is really about
    *orientation*: the pre-fix code rotates a glyph by the tangent at its
    own LEFT edge, so its stroke tilts off the true radius through its own
    centroid by about `advance / (2 * radius)` radians, independent of how
    close that radius is to the glyph's own position. Measuring
    orientation directly catches this at an ordinary, realistic size --
    close to `examples/showcase`'s own numerals -- with no extreme ratio
    needed.

    "III" gives three separate, thin, straight bars -- an ink shape whose
    weighted second-moment principal axis (`_principal_axis_angle`) is a
    robust, direct read of "which way this stroke points," unlike a wider
    or more complex glyph shape. For each "I"'s own blob, that axis must
    be (near) parallel to the radius from the circle's centre through
    that same blob's own centroid -- not to `curve.angle`, not to some
    other glyph's radius, but to its *own*. `angle: 50deg` (design) is
    away from every axis in either convention, so the defect cannot hide
    behind the glyph's own symmetry. Driven red against the unfixed code
    (temporarily reverting R1's two lines): every "I" tilts by
    ~2.0-2.4deg off its own radius; the fixed code holds every "I" under
    0.6deg -- both measured by hand while writing this test, see the
    tolerance below."""
    body = """\
  - id: glyphs
    type: text
    text: "III"
    font: font.bezel
    color: palette.fg
    at: {anchor: center}
    align: center
    vertical_align: center
    curve: {style: radial, angle: 50deg, radius: 80%r, direction: clockwise}
"""
    image = _render(write_design, db, bag, body, font_size="35%r")
    blobs = [b for b in _find_ink_blobs(image) if len(b) > 20]
    assert len(blobs) == 3, f"expected 3 separate 'I' blobs, found {len(blobs)}"

    for i, pixels in enumerate(blobs):
        axis_angle, (mx, my) = _principal_axis_angle(image, pixels)
        # Image-coordinate direction from the circle's centre to this
        # blob's own centroid -- same frame as `axis_angle`, so no Garmin
        # conversion is needed to compare the two.
        radius_dir_angle = math.degrees(math.atan2(my - CY, mx - CX))
        tilt = _acute_angle_diff(axis_angle, radius_dir_angle)
        assert tilt < 1.0, (
            f"'I' blob {i} (centroid ({mx:.1f}, {my:.1f})) has its stroke "
            f"tilted {tilt:.2f}deg off the radius through its own centroid "
            "-- every glyph's own midline should point at the circle's "
            "centre, like a spoke, not be rotated about its left edge"
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
