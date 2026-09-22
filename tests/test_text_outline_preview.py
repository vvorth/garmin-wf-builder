"""`outline:` on a standalone `text` element (plan 15 slice 1) -- preview
rendering (`wfb.preview`). The simulator does not run in this environment
(`CLAUDE.md` §3), so preview is the only way this feature can be seen at
all: these tests render a real baked (1-bit, non-anti-aliased) glyph three
ways -- solid fill only, ring only (interior hidden against the
background), and both together -- and check the *actual pixels*, not just
"it rendered something" (`docs/lore/working-agreement.md`: a test must
exercise the contrast it claims). `tests/test_vector_text_preview.py`'s own
conventions: a solid black background, `scale: 1` so device pixels map 1:1
onto image pixels, no quantising/bezel mask.
"""

from __future__ import annotations

from wfb import build
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render

FG = (255, 255, 255)
RING = (255, 0, 0)

_HEADER = """\
format: 1
face:
  id: 8f14e45f-ceea-467e-9c0c-89f7c6a9309c
  name: OutlinePreviewTest
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
  ring: "#FF0000"
fonts:
  clock:
    source: {source}
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


def _render(write_design, db, bag, repo_root, body: str, **options):
    source = repo_root / "tests" / "fixtures" / "slice" / "assets" / "OpenSans-Regular.ttf"
    design = _HEADER.format(source=source, body=body)
    path = write_design(design)
    face = build.load(path, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    opts = {"scale": 1, "mask_shape": False, "quantise": False, **options}
    return render(resolved, PreviewOptions(**opts))


def _count_color(image, color: tuple[int, int, int], region: tuple[int, int, int, int] | None = None) -> int:
    x0, y0, x1, y1 = region if region is not None else (0, 0, *image.size)
    count = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            if image.getpixel((x, y)) == color:
                count += 1
    return count


_ELEMENT = """\
  - id: clock
    type: text
    text: "12:34"
    font: font.clock
    at: {{anchor: center}}
    align: center
    vertical_align: center
{extra}"""

# `None` -- the whole rendered frame -- rather than a fixed box: "12:34" at
# 80px (research 14 §1's own exact font size, deliberately matched here so
# the ring/solid ratio this project's own renderer measures is directly
# comparable to that document's) is wide enough that a small, hand-picked
# region risks clipping it. A smaller font (e.g. this project's usual
# `%r`-relative sizes) makes stroke width thin enough, relative to a 1-3px
# ring, that the ring/solid ratio flips above 1 -- a real, documented
# effect of thin strokes having a large perimeter-to-area ratio, not a bug,
# but the wrong regime for the "ring lights fewer pixels" contrast below.
_REGION = None


def test_solid_fill_alone_lights_the_glyph(write_design, db, bag, repo_root):
    """Baseline: plain `color:`, no `outline:` -- some white pixels, no red
    ones (there is no ring colour anywhere in this render)."""
    image = _render(write_design, db, bag, repo_root,
                    _ELEMENT.format(extra="    color: palette.fg\n"))
    solid = _count_color(image, FG, _REGION)
    ring = _count_color(image, RING, _REGION)
    assert solid > 0
    assert ring == 0


def test_ring_alone_is_visible_when_interior_matches_background(write_design, db, bag,
                                                                 repo_root):
    """`color: palette.bg` (interior invisible against the background) plus
    `outline:` -- the ring must still be visible: this is the canonical
    "hollow" case plan 15 §3 documents, and it fails outright if the
    stamped ring were somehow gated on the interior colour."""
    image = _render(write_design, db, bag, repo_root, _ELEMENT.format(
        extra="    color: palette.bg\n    outline: {color: palette.ring, width: 2}\n"))
    ring = _count_color(image, RING, _REGION)
    fg = _count_color(image, FG, _REGION)
    assert ring > 0
    assert fg == 0, "the interior pass must paint the background colour, not the old fill"


def test_ring_lights_fewer_pixels_than_a_solid_fill_of_the_same_glyph(write_design, db, bag,
                                                                       repo_root):
    """Research 14 §1's own headline number: a stamped ring lights strictly
    fewer pixels than the same glyph drawn solid, at every radius tested
    (ring/solid ratio 0.2-0.6 for r=1-3) -- checked here against this
    project's own renderer, not just asserted from the research document."""
    solid_image = _render(write_design, db, bag, repo_root,
                          _ELEMENT.format(extra="    color: palette.fg\n"))
    ring_image = _render(write_design, db, bag, repo_root, _ELEMENT.format(
        extra="    color: palette.bg\n    outline: {color: palette.ring, width: 2}\n"))
    solid = _count_color(solid_image, FG, _REGION)
    ring = _count_color(ring_image, RING, _REGION)
    assert 0 < ring < solid


def test_solid_plus_ring_lights_more_pixels_than_solid_alone(write_design, db, bag, repo_root):
    """The full `outline:` picture (interior AND ring both visible, distinct
    colours) must light strictly more pixels overall than the plain fill it
    replaces -- the ring adds ink at the glyph's edge, it does not merely
    recolour existing ink. This is the exact "more lit pixels at the
    glyph's edge" contrast plan 15 §14 slice 1 asks the preview test to
    exercise."""
    solid_image = _render(write_design, db, bag, repo_root,
                          _ELEMENT.format(extra="    color: palette.fg\n"))
    both_image = _render(write_design, db, bag, repo_root, _ELEMENT.format(
        extra="    color: palette.fg\n    outline: {color: palette.ring, width: 2}\n"))
    solid_total = _count_color(solid_image, FG, _REGION)
    both_fg = _count_color(both_image, FG, _REGION)
    both_ring = _count_color(both_image, RING, _REGION)
    assert both_fg == solid_total, "the interior pass itself must be unchanged by outline:"
    assert both_ring > 0
    assert both_fg + both_ring > solid_total


def test_ring_width_scales_the_lit_ring_pixel_count(write_design, db, bag, repo_root):
    """A wider ring (`width: 3` vs `width: 1`) must light more ring pixels
    -- not merely "a ring exists", but that `width:` actually drives the
    resolved offset table (16 disc-perimeter points at r=3 vs. 4 at r=1,
    research 14 §1's own measured counts)."""
    narrow = _render(write_design, db, bag, repo_root, _ELEMENT.format(
        extra="    color: palette.bg\n    outline: {color: palette.ring, width: 1}\n"))
    wide = _render(write_design, db, bag, repo_root, _ELEMENT.format(
        extra="    color: palette.bg\n    outline: {color: palette.ring, width: 3}\n"))
    narrow_ring = _count_color(narrow, RING, _REGION)
    wide_ring = _count_color(wide, RING, _REGION)
    assert narrow_ring > 0
    assert wide_ring > narrow_ring


def test_outline_shorthand_matches_object_form_in_preview(write_design, db, bag, repo_root):
    """The shorthand (`outline: palette.ring`) and the equivalent explicit
    object form (`{color: palette.ring, width: 2}`) must render
    pixel-identical -- D7's own claim that the two spellings resolve to the
    same `Outline` node, verified end to end through the renderer, not just
    at the IR."""
    shorthand = _render(write_design, db, bag, repo_root, _ELEMENT.format(
        extra="    color: palette.bg\n    outline: palette.ring\n"))
    explicit = _render(write_design, db, bag, repo_root, _ELEMENT.format(
        extra="    color: palette.bg\n    outline: {color: palette.ring, width: 2}\n"))
    assert shorthand.tobytes() == explicit.tobytes()
