"""The host-side preview renderer."""

import pytest

from wfb.build import load
from wfb import formatting
from wfb.catalog import Type
from wfb.diagnostics import Bag
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import (
    PreviewOptions, UnknownStyleError, render, render_all_styles,
)
from wfb.palette import MIP64_LEVELS


@pytest.fixture
def resolved(repo_root, db, bag):
    design = repo_root / "tests" / "fixtures" / "slice" / "face.yaml"
    face = load(design, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device))


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


def test_preview_renders_an_off_screen_element_cropped_without_crashing(
    write_design, bag, db,
):
    """Drawing off the framebuffer is now a suppressible warning, not a hard
    build error (`wfb.lint.check_geometry`), so the preview -- which mirrors
    the device's own silent-clip behaviour rather than throwing -- has to
    stay well-behaved when an element's resolved box has a negative
    coordinate or runs past the screen edge in either direction. Pillow
    itself clips off-canvas draws silently; this pins that down against the
    actual resolved geometry this compiler produces, not just Pillow's
    documented behaviour in isolation.
    """
    design = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
elements:
  - id: background
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
  - id: stray
    type: shape
    shape: circle
    at: {anchor: center, dx: -500%}
    radius: 30px
    color: palette.fg
    lint:
      allow: [off-screen]
      reason: "probing"
"""
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    stray = next(p for p in resolved.items if p.id == "stray")
    assert stray.box.x < 0  # confirms this exercises the negative-box path
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False))
    assert image.size == (device.width, device.height)


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
    resolved = resolve(face, device, bake_fonts(face, device))
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
    resolved = resolve(face, device, bake_fonts(face, device))
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

    resolved = resolve(face, device, bake_fonts(face, device))
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
    resolved = resolve(face, device, bake_fonts(face, device))
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
# now walk the same tables (`parse`, `parse_time`, `TIME_CODES`/`DATE_CODES`,
# `_numeric_spec`), which is
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
# device's own answer, worked out by hand from `_emit_numeric`'s and each
# `TIME_CODES`/`DATE_CODES` row's own Monkey C (`.toNumber()`, `.format("%...")`, string
# concatenation), so a parity bug in `render` can't hide by agreeing with
# itself.
_TIME_VALUES = {"time.hour": 7, "time.minute": 5, "time.second": 9}
_TIME_VALUES_12H = {**_TIME_VALUES, "device.is_24_hour": False}
_DATE_VALUES = {"date.day_of_week": "Thu", "date.day": 3, "date.month": "Sep",
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
    ("{:%a %e %b}", Type.DATE, None, _DATE_VALUES, "Thu 3 Sep"),
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
    resolved = resolve(face, device, bake_fonts(face, device))
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


# -- `PreviewOptions.style` / `--style` / `--all-styles` -----------------------


#: Two layouts (`a`, `b`), each with one marker at a fixed, config-independent
#: colour (`palette.red`) so "is this layout's marker drawn" can be checked by
#: colour alone -- and two `color_scheme:` entries (`dark`/`light`) bound only
#: to the shared background, so "did the colours switch" is a *second*,
#: independent question from "did the drawn set switch".
LAYOUT_STYLE_DESIGN = """format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: LayoutPreview
targets: [fenix8solar47mm]
palette:
  black: "#000000"
  white: "#FFFFFF"
  red: "#FF0000"
color_scheme:
  dark:
    colors: { bg: palette.black }
  light:
    colors: { bg: palette.white }
layouts:
  a:
    elements:
      marker_a:
        type: shape
        shape: circle
        at: {anchor: center, dx: -30%}
        radius: 8%
        color: palette.red
  b:
    elements:
      marker_b:
        type: shape
        shape: circle
        at: {anchor: center, dx: 30%}
        radius: 8%
        color: palette.red
config:
  style:
    default: style_a
    choices:
      style_a: { label: "A", layout: a, colors: dark }
      style_b: { label: "B", layout: b, colors: light }
elements:
  shared:
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: config.colors.bg
"""


@pytest.fixture
def layout_style_resolved(write_design, db):
    bag = Bag()
    face = load(write_design(LAYOUT_STYLE_DESIGN), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device))


def test_style_option_switches_colours_and_drawn_set(layout_style_resolved):
    """`--style` must change both *what* is drawn (the active layout's own
    content) and *how* it is coloured (the entry's scheme) -- checked by
    sampling actual pixels, not by inspecting the resolved tree."""
    resolved = layout_style_resolved
    common = dict(scale=1, mask_shape=False, quantise=False)

    style_a = render(resolved, PreviewOptions(**common, style="style_a"))
    style_b = render(resolved, PreviewOptions(**common, style="style_b"))

    # The shared background: dark scheme (style_a) is black, light (style_b)
    # is white -- a corner pixel, away from either marker.
    assert style_a.getpixel((2, 2)) == (0, 0, 0)
    assert style_b.getpixel((2, 2)) == (255, 255, 255)

    # marker_a's own centre: (130 - 78, 130) on a 260x260 screen (dx: -30%).
    # Drawn (red) only while layout 'a' is active.
    marker_a_point = (52, 130)
    assert style_a.getpixel(marker_a_point) == (255, 0, 0)
    assert style_b.getpixel(marker_a_point) != (255, 0, 0)

    # marker_b's own centre: (130 + 78, 130).  The mirror image of the above.
    marker_b_point = (208, 130)
    assert style_b.getpixel(marker_b_point) == (255, 0, 0)
    assert style_a.getpixel(marker_b_point) != (255, 0, 0)


def test_style_none_renders_the_default_entry(layout_style_resolved):
    """Omitting `--style` (`PreviewOptions.style is None`) must render
    exactly what naming the default entry explicitly would."""
    resolved = layout_style_resolved
    common = dict(scale=1, mask_shape=False, quantise=False)
    default = render(resolved, PreviewOptions(**common, style=None))
    explicit = render(resolved, PreviewOptions(**common, style="style_a"))
    assert list(default.get_flattened_data()) == list(explicit.get_flattened_data())


def test_an_unknown_style_name_is_a_clean_error(layout_style_resolved):
    with pytest.raises(UnknownStyleError) as excinfo:
        render(layout_style_resolved, PreviewOptions(style="bogus"))
    message = str(excinfo.value)
    assert "style_a" in message and "style_b" in message


def test_style_on_a_design_with_no_config_style_is_a_clean_error(write_design, db, bag):
    text = """format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: NoStyle
targets: [fenix8solar47mm]
palette:
  fg: "#FFFFFF"
elements:
  - id: label
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.fg
"""
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    with pytest.raises(UnknownStyleError):
        render(resolved, PreviewOptions(style="anything"))
    with pytest.raises(UnknownStyleError):
        render_all_styles(resolved)


def test_all_styles_lays_out_every_entry_side_by_side(layout_style_resolved):
    """One panel per entry, same width apiece plus the gap between them --
    exactly `render`'s own per-entry width, not a guessed constant."""
    resolved = layout_style_resolved
    one = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False,
                                          style="style_a"))
    composed = render_all_styles(
        resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))
    gap = 1
    assert composed.width == one.width * 2 + gap
    assert composed.height > one.height  # the caption bar adds height


def test_text_with_no_font_metrics_renders_without_crashing(write_design, db, bag, monkeypatch):
    """A device missing from the scraped SDK reference (the fenix 9 family)
    has no system-font metrics at all, so layout gives its text a 0x0 box.
    The preview used to outline that box and Pillow rejected the inverted
    rectangle, which crashed `wfb build` through the aod-burn-in lint.

    Unmeasured text now draws nothing; other elements still render."""
    from wfb.devices import Device

    monkeypatch.setattr(Device, "system_fonts", property(lambda self: {}))
    design = write_design("""
format: 1
face:
  id: 0b7f3c1e-2a4d-4e8f-9c6b-5d1a7e3f9b20
  name: Unmeasured
  version: 1.0.0
targets: [fenix8solar47mm]
palette:
  white: "#FFFFFF"
elements:
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    font: FONT_NUMBER_MEDIUM
    at: { anchor: center }
    color: palette.white
  - id: dot
    type: shape
    shape: circle
    at: { anchor: center, dy: 30% }
    radius: 5%r
    filled: true
    color: palette.white
""")
    face = load(design, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    clock = next(p for p in resolved.items if p.id == "clock")
    assert clock.box.width == 0 and clock.box.height == 0  # the case under test

    for scale in (1, 2):
        image = render(resolved, PreviewOptions(scale=scale, mask_shape=False, quantise=False))
        assert image.getbbox() is not None  # the dot still draws
