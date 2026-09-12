"""The host-side preview renderer."""

import pytest

from tests.test_diagnostics import load
from wfb import formatting
from wfb.catalog import Type
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render
from wfb.palette import MIP64_LEVELS


@pytest.fixture
def resolved(repo_root, db, bag):
    design = repo_root / "examples" / "slice" / "face.yaml"
    if not design.exists():
        pytest.skip("the example design is missing")
    face = load(design, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device, device.minor_radius))


def test_preview_is_the_devices_own_size(resolved):
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False))
    assert image.size == (resolved.device.width, resolved.device.height)


def test_scale_multiplies_both_axes(resolved):
    image = render(resolved, PreviewOptions(scale=3, mask_shape=False))
    assert image.size == (resolved.device.width * 3, resolved.device.height * 3)


def test_quantising_snaps_to_the_devices_own_palette(resolved):
    """A dithered colour should look wrong in the preview the way it will on the wrist."""
    image = render(resolved, PreviewOptions(scale=1, quantise=True, mask_shape=False))
    channels = {value for pixel in image.get_flattened_data() for value in pixel}
    assert channels <= set(MIP64_LEVELS)


def test_the_face_actually_draws_something(resolved):
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False))
    colors = {pixel for pixel in image.get_flattened_data()}
    assert len(colors) > 2, "the preview is blank"


def test_sample_readings_drive_the_bound_elements(resolved):
    """Different step counts must produce different pixels, or nothing is bound."""
    low = render(resolved, PreviewOptions(scale=1, mask_shape=False,
                                          sample={"activity.steps": 100}))
    high = render(resolved, PreviewOptions(scale=1, mask_shape=False,
                                           sample={"activity.steps": 9900}))
    assert list(low.get_flattened_data()) != list(high.get_flattened_data())


def test_an_absent_reading_hides_a_hidden_element(resolved):
    present = render(resolved, PreviewOptions(scale=1, mask_shape=False))
    absent = render(resolved, PreviewOptions(scale=1, mask_shape=False,
                                             sample={"activity.steps": None}))
    assert list(present.get_flattened_data()) != list(absent.get_flattened_data())


def test_preview_and_codegen_read_the_same_geometry(resolved):
    """The anti-drift guarantee: both consume the resolved IR, not two layouts."""
    from wfb.emit.monkeyc import emit_layout

    layout = emit_layout(resolved).text
    ring = next(p for p in resolved.items if p.id == "step_ring")
    assert f"const STEP_RING_RADIUS as Number = {ring.radius};" in layout
    assert f"const STEP_RING_CX as Number = {ring.center[0]};" in layout


def test_a_progress_fallback_renders_the_same_fraction_the_device_draws(
        write_design, db, bag, tmp_path):
    """Preview and device must agree about an absent reading, not just a present
    one.

    `when_absent: fallback` used to be honoured here and silently dropped by
    codegen, so the two renderers disagreed in exactly the case the policy
    exists for. They now substitute the same fill fraction, so a half-full
    fallback ring is half full in both -- distinguishable here from the 0.0 an
    unhandled absence would produce.
    """
    from tests.test_semantics import RING, design

    path = write_design(design(RING.replace("__FALLBACK__", "0.5")))
    face = load(path, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    # No reading for either bound source: the fallback is the only thing left.
    options = PreviewOptions(scale=1, mask_shape=False,
                             sample={"activity.steps": None, "activity.step_goal": None})
    filled = render(resolved, options)
    empty = render(resolved, PreviewOptions(
        scale=1, mask_shape=False,
        sample={"activity.steps": 0, "activity.step_goal": 1000}))
    lit = sum(1 for p in filled.get_flattened_data() if p != (0, 0, 0))
    dark = sum(1 for p in empty.get_flattened_data() if p != (0, 0, 0))
    assert lit > dark, "the fallback fraction drew nothing"


def test_an_antialiased_icon_previews_with_intermediate_grey(write_design, bag, db):
    """No anti-aliasing machinery was added to `wfb/preview.py` for this --
    `_paste_glyph` already pastes a glyph tile as an alpha mask, so an
    anti-aliased (multi-grey-level) sheet blends into the background for
    free, and a 1-bit sheet cannot, because its mask has only two values.
    This proves that fall-out actually happens end to end, from `antialias:`
    on the element through layout and baking to the rendered pixels, rather
    than asserting it against the baked sheet alone.
    """
    design = """
format: 1
face: {id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}
targets: [fenix8solar47mm]
palette: {bg: "#000000", fg: "#FFFFFF"}
elements:
  - id: bg
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
  - id: crisp
    type: icon
    icon: heart
    size: 30%r
    at: {anchor: center, dx: -25%}
    color: palette.fg
    antialias: false
  - id: smooth
    type: icon
    icon: heart
    size: 30%r
    at: {anchor: center, dx: 25%}
    color: palette.fg
    antialias: true
"""
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False))

    def colors_in(element_id: str) -> set:
        box = next(p for p in resolved.items if p.id == element_id).box
        return {image.getpixel((x, y))
                for x in range(box.x, box.x + box.width)
                for y in range(box.y, box.y + box.height)}

    crisp_colors = colors_in("crisp")
    smooth_colors = colors_in("smooth")
    assert crisp_colors == {(0, 0, 0), (255, 255, 255)}, crisp_colors
    intermediate = smooth_colors - {(0, 0, 0), (255, 255, 255)}
    assert intermediate, f"anti-aliased icon has no intermediate grey: {smooth_colors}"


GRAPH_DESIGN = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
elements:
  - id: bg
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.bg
  - id: hr_graph
    type: graph
    series: heart_rate
    range: 4h
    style: {style}
    {style_key}
    color: palette.fg
    at: {{anchor: center}}
    size: {{width: 60%, height: 20%}}
"""


@pytest.mark.parametrize("style,style_key", [
    ("line", "thickness: 3px"),
    ("area", ""),
    ("bars", "bar_width: 4px"),
])
def test_a_graph_actually_draws_something_in_every_style(write_design, bag, db, style, style_key):
    """Not a blank rectangle -- the synthetic series must produce real ink,
    for whichever `style:` the design chose."""
    face = load(write_design(GRAPH_DESIGN.format(style=style, style_key=style_key)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False))
    fg = face.palette["fg"]
    colors = {pixel for pixel in image.get_flattened_data()}
    assert (fg.r, fg.g, fg.b) in colors, f"style={style} drew no ink at all"


def test_a_graphs_geometry_matches_its_resolved_box(write_design, bag, db):
    """Preview and device must agree: the drawn ink stays inside the
    resolved box, not merely near it."""
    from wfb.emit.resources import bake_fonts
    from wfb.layout import PlacedGraph, resolve

    face = load(write_design(
        GRAPH_DESIGN.format(style="bars", style_key="bar_width: 4px")), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    placed = next(p for p in resolved.items if isinstance(p, PlacedGraph))

    image = render(resolved, PreviewOptions(scale=1, mask_shape=False))
    fg = face.palette["fg"]
    bg = face.palette["bg"]
    # A row two pixels above the box's own top must still be pure background:
    # if the graph painted there, its geometry has drifted from what
    # wfb.layout resolved.
    for x in range(placed.box.x, placed.box.right):
        assert image.getpixel((x, placed.box.y - 2)) == (bg.r, bg.g, bg.b)


# -- formatting.render parity -------------------------------------------------
#
# `wfb.formatting.render` is the host-side twin of `wfb.formatting.emit`: both
# now walk the same tables (`parse`, `parse_time`, `_NUMERIC_SPEC_RE`), which is
# what makes it impossible for `wfb preview` and the generated Monkey C to show
# a different string for the same declaration. Before this, `wfb/preview.py`
# had a *third*, hand-written ladder (`_render_numeric`/`_apply_spec`) that
# fell back to plain `str(value)` whenever Python's `format()` did not like the
# spec -- which is exactly what happens for `{:d}` on a Float, since
# `format(8.5, 'd')` raises `ValueError`. Confirmed against the actual old
# code before it was removed:
#
#     def _apply_spec(spec, value):
#         if not spec:
#             return str(value)
#         try:
#             return format(value, spec)
#         except (ValueError, TypeError):
#             return str(value)
#
#     _apply_spec('d', 8.5)               -> '8.5'   (WRONG: silent fallback)
#     formatting.emit('{:d}', 'x', FLOAT)  -> 'x.toNumber().format("%d")' -> 8
#
# Each row below is (spec, value_type, value, values, expected) where
# `expected` is *not* derived by running Python's `format()` -- it is the
# device's own answer, worked out by hand from `_emit_numeric`/`_emit_time`/
# `_emit_date`'s own Monkey C (`.toNumber()`, `.format("%...")`, string
# concatenation), so a parity bug in `render` can't hide by agreeing with
# itself.
_TIME_VALUES = {"time.hour": 7, "time.minute": 5, "time.second": 9}
_TIME_VALUES_12H = {**_TIME_VALUES, "device.is_24_hour": False}
_DATE_VALUES = {"date.weekday": "Wed", "date.day": 3, "date.month": "Sep",
                "date.month_number": 9, "date.year": 2026}

PARITY_CASES = [
    # -- the bug: {:d} on a Float must truncate like Monkey C's .toNumber(),
    # not raise-and-fall-back-to-str() like Python's own format() does.
    ("{:d}", Type.FLOAT, 8.5, None, "8"),
    # truncation, not rounding: .toNumber() truncates toward zero, so 8.9 -> 8.
    ("{:d}", Type.FLOAT, 8.9, None, "8"),
    ("{:d}", Type.FLOAT, -8.9, None, "-8"),
    ("{:d}", Type.NUMBER, 8, None, "8"),
    ("{:02d}", Type.NUMBER, 3, None, "03"),
    ("{:.1f}", Type.FLOAT, 3.14159, None, "3.1"),
    # a written-out zero precision is still zero decimals, not the "precision
    # or 1" default -- the regex group is the *string* "0", which is truthy.
    ("{:.0f}", Type.FLOAT, 8.6, None, "9"),
    ("{}", Type.NUMBER, 42, None, "42"),
    ("{}", Type.FLOAT, 3.5, None, "3.5"),
    ("{:s}", Type.NUMBER, 42, None, "42"),
    # a literal suffix alongside the field.
    ("{:d}%", Type.NUMBER, 87, None, "87%"),
    ("{:%H:%M}", Type.TIME, None, _TIME_VALUES, "07:05"),
    ("{:%h:%M}", Type.TIME, None, _TIME_VALUES, "07:05"),
    ("{:%h:%M}", Type.TIME, None, _TIME_VALUES_12H, "7:05"),
    ("{:%a %e %b}", Type.DATE, None, _DATE_VALUES, "Wed 3 Sep"),
]


@pytest.mark.parametrize("spec,value_type,value,values,expected", PARITY_CASES)
def test_render_matches_the_devices_own_answer(spec, value_type, value, values, expected):
    assert formatting.render(spec, value, value_type, values) == expected


def test_the_bug_reproduces_against_the_old_apply_spec():
    """Confirms the disagreement this task fixes, against the *old* logic
    (kept here verbatim rather than re-imported, since the buggy function no
    longer exists in `wfb/preview.py`) -- this is the red failure the fix
    corrects, not a currently-passing assertion about `render`."""

    def old_apply_spec(spec, value):
        if not spec:
            return str(value)
        try:
            return format(value, spec)
        except (ValueError, TypeError):
            return str(value)

    assert old_apply_spec("d", 8.5) == "8.5"
    assert formatting.emit("{:d}", "x", Type.FLOAT) == 'x.toNumber().format("%d")'
    # The device truncates to 8; the fixed renderer must agree, not the old
    # code's silent "8.5".
    assert formatting.render("{:d}", 8.5, Type.FLOAT) == "8"
    assert formatting.render("{:d}", 8.5, Type.FLOAT) != old_apply_spec("d", 8.5)


def test_an_unparseable_numeric_spec_raises_rather_than_guessing():
    """`render` mirrors `emit`'s own refusal instead of falling back to
    `str(value)` -- the fallback is exactly the bug above, generalised."""
    with pytest.raises(formatting.FormatError):
        formatting.render("{:q}", 8.5, Type.FLOAT)


# -- end to end: a Float formatted `{:d}` must preview as the device would --

_FLOAT_TEXT_DESIGN = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
elements:
  - id: label
    type: text
    {content}
    font: FONT_TINY
    at: {{anchor: center}}
    color: palette.fg
"""


def _render_label(write_design, bag, db, content: str, sample: dict | None = None):
    face = load(write_design(_FLOAT_TEXT_DESIGN.format(content=content)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    return render(resolved, PreviewOptions(scale=1, mask_shape=False,
                                           quantise=False, sample=sample))


def test_preview_renders_8_not_8_5_for_a_float_formatted_d(write_design, bag, db):
    """End to end: `system.battery` (Type.FLOAT) at 8.5, formatted `{:d}`,
    must preview identically to the literal text "8" -- not "8.5" -- because
    that is what `.toNumber().format("%d")` draws on the wrist. Comparing
    whole images (rather than guessing at a bounding box) is exact: the same
    font, size, colour and anchor render pixel-for-pixel identically for the
    same string, and differently for a different one.
    """
    formatted = _render_label(
        write_design, bag, db,
        content='value: system.battery\n    format: "{:d}"',
        sample={"system.battery": 8.5},
    )
    literal_8 = _render_label(write_design, bag, db, content='text: "8"')
    literal_8_5 = _render_label(write_design, bag, db, content='text: "8.5"')

    assert list(formatted.get_flattened_data()) == list(literal_8.get_flattened_data())
    assert list(formatted.get_flattened_data()) != list(literal_8_5.get_flattened_data())
