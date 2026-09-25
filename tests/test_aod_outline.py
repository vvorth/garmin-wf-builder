"""`aod: {outline: ...}` on a `text` element, the AOD frame's own ring
applying `dim:` to an `outline:` ring, and the schema error an `aod:`
block with a key it does not take gets.

The override replaces the awake ring whole, in the element's own
`outline:` grammar: `none` drops it in AOD, a colour or `{color, width}`
draws that ring instead. Each codegen test pins the one generated shape
its case takes (a ring only in AOD, a ring only while awake, one loop
with ternaries); each preview test reads the ring's own pixels, so it
fails against a preview that still draws the awake ring in AOD.
"""

from __future__ import annotations

import pytest

from wfb.build import build as real_build
from wfb.build import load
from wfb.diagnostics import Bag
from wfb.emit import generate
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render

BASE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix847mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
  dim: "#555555"
  red: "#FF0000"
"""

DIM = BASE.replace("palette:\n", "aod:\n  dim: 0.4\npalette:\n")


def _clock(outline: str = "", aod: str = "{outline: palette.dim}") -> str:
    own = f"\n    outline: {outline}" if outline else ""
    return f"""
elements:
  - id: clock
    type: text
    text: "88"
    font: FONT_NUMBER_HOT
    at: {{anchor: center}}
    color: palette.fg{own}
    aod: {aod}
"""


def _face(text, write_design, bag):
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    return face


def _project(text, write_design, bag, db, device_id="fenix847mm"):
    face = _face(text, write_design, bag)
    device = db.get(device_id)
    baked = {device.id: bake_fonts(face, device)}
    return generate(face, [device], write_design("").parent / "build", baked).files()


def _view(text, write_design, bag, db, device_id="fenix847mm"):
    files = _project(text, write_design, bag, db, device_id)
    return next(v for k, v in files.items() if k.endswith("View.mc"))


def _layout(text, write_design, bag, db, device_id="fenix847mm"):
    files = _project(text, write_design, bag, db, device_id)
    return next(v for k, v in files.items() if k.endswith("Layout.mc"))


def _method(view: str, name: str) -> str:
    return view.split(f"function {name}")[1].split("\n    }")[0]


# -- the schema error ----------------------------------------------------------


def test_an_unknown_aod_key_is_named_and_pointed_at(write_design, bag):
    """An `aod:` block with a key its kind does not take must say which key,
    on that key's own line -- must fail against the bare "is not valid under
    any of the given schemas" (the whole block, on its first key's line)
    that the `hide`/`show`-or-block choice produced before."""
    text = BASE + """
elements:
  - id: clock
    type: text
    text: "88"
    aod:
      format: "{}"
      thickness: 2px
"""
    assert load(write_design(text), bag) is None
    [error] = [d for d in bag.errors if d.code == "schema"]
    assert "unknown key ('thickness' was unexpected)" in error.message, bag.render()
    assert "not valid under any" not in error.message
    assert error.span.line == text.splitlines().index("      thickness: 2px") + 1
    assert any("keys allowed here: color, font, format, outline, visible" in n
               for n in error.notes), error.notes


def test_a_misspelled_aod_keyword_lists_hide_and_show(write_design, bag):
    """A string `aod:` belongs to the `hide`/`show` branch, not the
    override-block one -- the error must say which strings are allowed, not
    that a string is not an object."""
    text = BASE + """
elements:
  - id: clock
    type: text
    text: "88"
    aod: hid
"""
    assert load(write_design(text), bag) is None
    [error] = [d for d in bag.errors if d.code == "schema"]
    assert "'hid' is not valid here" in error.message, bag.render()
    assert any("'hide', 'show'" in n for n in error.notes), error.notes


# -- builder -------------------------------------------------------------------


def test_the_override_parses_in_both_spellings_and_none(write_design, bag):
    shorthand = _face(BASE + _clock(aod="{outline: palette.dim}"), write_design, bag)
    aod = shorthand.elements[0].aod
    assert (aod.outline.color.text, aod.outline.width, aod.outline_none) == (
        "palette.dim", 2, False)
    full = _face(BASE + _clock(aod="{outline: {color: palette.red, width: 3}}"),
                 write_design, bag)
    assert (full.elements[0].aod.outline.color.text, full.elements[0].aod.outline.width) == (
        "palette.red", 3)
    none = _face(BASE + _clock("palette.dim", aod="{outline: none}"), write_design, bag)
    assert none.elements[0].aod.outline is None and none.elements[0].aod.outline_none


def test_the_override_width_cap_is_the_same_build_error(write_design, bag):
    assert load(write_design(BASE + _clock(aod="{outline: {color: palette.dim, width: 4}}")),
                bag) is None
    [error] = bag.errors
    assert error.code == "text-outline" and error.message.startswith("clock.aod: "), bag.render()


def test_a_group_passes_its_outline_down_to_a_text(write_design, bag):
    text = BASE + """
elements:
  - id: group
    type: group
    aod: {outline: palette.dim}
    children:
      - id: clock
        type: text
        text: "88"
        color: palette.fg
"""
    clock = _face(text, write_design, bag).elements[0].items[0]
    assert clock.aod.outline.color.text == "palette.dim"


# -- codegen -------------------------------------------------------------------


def test_a_ring_only_in_aod_is_guarded_by_aod(write_design, bag, db):
    method = _method(_view(BASE + _clock(), write_design, bag, db), "drawClock")
    ring = method.split("if (_aod) {")[1].split("\n        }")[0]
    assert "dc.setColor(Palette.DIM, Graphics.COLOR_TRANSPARENT);" in ring
    assert "var offsets = Layout.OUTLINE_OFFSETS_2;" in ring
    assert "while (i < offsets.size())" in ring
    # the interior pass still follows, outside the guard
    assert method.index("if (_aod) {") < method.rindex("dc.setColor(Palette.FG")


def test_outline_none_keeps_the_awake_ring_out_of_aod(write_design, bag, db):
    method = _method(_view(BASE + _clock("palette.dim", aod="{outline: none}"),
                           write_design, bag, db), "drawClock")
    ring = method.split("if (!_aod) {")[1].split("\n        }")[0]
    assert "var offsets = Layout.OUTLINE_OFFSETS_2;" in ring
    assert method.count("while (") == 1


def test_a_ring_in_both_frames_is_one_loop_with_ternaries(write_design, bag, db):
    method = _method(_view(
        BASE + _clock("palette.dim", aod="{outline: {color: palette.red, width: 1}}"),
        write_design, bag, db), "drawClock")
    assert method.count("while (") == 1 and "if (_aod) {" not in method
    assert "dc.setColor((_aod ? Palette.RED : Palette.DIM), Graphics.COLOR_TRANSPARENT);" in method
    assert ("var offsets = (_aod ? Layout.OUTLINE_OFFSETS_1 : Layout.OUTLINE_OFFSETS_2);"
            in method)


def test_the_same_width_in_both_frames_needs_no_offsets_ternary(write_design, bag, db):
    method = _method(_view(BASE + _clock("palette.dim", aod="{outline: palette.red}"),
                           write_design, bag, db), "drawClock")
    assert "var offsets = Layout.OUTLINE_OFFSETS_2;" in method


def test_an_aod_only_width_gets_its_offsets_table(write_design, bag, db):
    layout = _layout(BASE + _clock("palette.dim", aod="{outline: {color: palette.dim, width: 3}}"),
                     write_design, bag, db)
    assert "OUTLINE_OFFSETS_2 " in layout and "OUTLINE_OFFSETS_3 " in layout


def test_an_all_mip_build_ignores_the_override(write_design, bag, db):
    """With no AMOLED target no AOD code is emitted, so the override's own
    ring and its width's offsets table must not be either -- the view is
    byte-identical to the same design without the key."""
    mip = BASE.replace("targets: [fenix847mm]", "targets: [fenix8solar47mm]")
    with_key = mip + _clock("palette.dim", aod="{outline: {color: palette.red, width: 3}}")
    without = mip + _clock("palette.dim", aod="show")
    assert (_view(with_key, write_design, bag, db, "fenix8solar47mm")
            == _view(without, write_design, bag, db, "fenix8solar47mm"))
    assert "OUTLINE_OFFSETS_3" not in _layout(with_key, write_design, bag, db, "fenix8solar47mm")


def test_a_vector_font_takes_the_override_too(write_design, bag, db):
    text = BASE.replace("palette:\n", "fonts:\n  bezel: {face: RobotoCondensedBold, size: 8%r}\n"
                                      "palette:\n") + """
elements:
  - id: clock
    type: text
    text: "88"
    font: font.bezel
    at: {anchor: center}
    color: palette.fg
    aod: {outline: palette.dim}
"""
    method = _method(_view(text, write_design, bag, db), "drawClock")
    guarded = method.split("if (font != null) {")[1]
    assert "if (_aod) {" in guarded and "Layout.OUTLINE_OFFSETS_2" in guarded


# -- dim: reaches an `outline:` ring like every other AOD colour ---------------


def test_the_awake_ring_is_dimmed_in_aod_and_the_override_is_not(write_design, bag, db):
    """0x55 * 0.4 rounds to 0x22. Must fail against the ring colour going
    out undimmed (as it did before) -- and the override in the same build
    must stay exactly as written."""
    carried = _method(_view(DIM + _clock("palette.dim", aod="show"), write_design, bag, db),
                      "drawClock")
    assert "dc.setColor((_aod ? 0x222222 : Palette.DIM), Graphics.COLOR_TRANSPARENT);" in carried
    overridden = _method(_view(DIM + _clock("palette.fg", aod="{outline: palette.dim}"),
                               write_design, bag, db), "drawClock")
    assert "dc.setColor((_aod ? Palette.DIM : Palette.FG), Graphics.COLOR_TRANSPARENT);" in overridden


_PATTERN = """
elements:
  - id: ring
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 1
    color: palette.fg
    aod: {color: palette.red}
    parts:
      - shape: text
        text: "12"
        font: FONT_XTINY
        at: {dy: -40%r}
        outline: palette.dim
"""


def test_a_pattern_parts_ring_is_dimmed_and_its_interior_keeps_the_aod_colour(
        write_design, bag, db):
    """The ring is dimmed (no `aod:` key reaches it); the interior pass that
    follows it must restore the part's *AOD* colour, the one the outer copy
    loop set -- must fail against restoring the plain awake `Palette.FG`."""
    method = _method(_view(DIM + _PATTERN, write_design, bag, db), "drawRing")
    assert "dc.setColor((_aod ? 0x222222 : Palette.DIM), Graphics.COLOR_TRANSPARENT);" in method
    after_ring = method.split("outlineIRING_0 += 2;")[1]
    assert "dc.setColor((_aod ? Palette.RED : Palette.FG), Graphics.COLOR_TRANSPARENT);" in after_ring
    assert "dc.setColor(Palette.FG, Graphics.COLOR_TRANSPARENT);" not in after_ring


# -- preview ---------------------------------------------------------------------


def _ring_pixels(text, write_design, bag, db, *, aod: bool, dim: bool = False):
    """Every distinct non-black, non-interior colour the clock draws."""
    face = _face(text, write_design, bag)
    device = db.get("fenix847mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False, aod=aod,
                                            aod_mask=False, time=(10, 8, 0)))
    colours = {c for _, c in image.getcolors(1 << 20)}
    return colours - {(0, 0, 0)}


def test_preview_draws_the_aod_ring_in_its_own_colour(write_design, bag, db):
    colours = _ring_pixels(BASE + _clock("palette.dim", aod="{outline: palette.red}"),
                           write_design, bag, db, aod=True)
    assert (255, 0, 0) in colours and (0x55, 0x55, 0x55) not in colours
    awake = _ring_pixels(BASE + _clock("palette.dim", aod="{outline: palette.red}"),
                         write_design, bag, db, aod=False)
    assert (0x55, 0x55, 0x55) in awake and (255, 0, 0) not in awake


def test_preview_draws_no_ring_for_outline_none(write_design, bag, db):
    colours = _ring_pixels(BASE + _clock("palette.red", aod="{outline: none}"),
                           write_design, bag, db, aod=True)
    assert (255, 0, 0) not in colours and (255, 255, 255) in colours


def test_preview_dims_the_awake_ring_in_aod(write_design, bag, db):
    """A black interior leaves the ring the only ink, so the brightest pixel
    is the ring's full colour (edges only anti-alias darker): 0x55 awake,
    0x22 in the dimmed AOD frame."""
    text = DIM + _clock("palette.dim", aod="show").replace("color: palette.fg",
                                                           "color: palette.bg")
    assert max(c[0] for c in _ring_pixels(text, write_design, bag, db, aod=False)) == 0x55
    assert max(c[0] for c in _ring_pixels(text, write_design, bag, db, aod=True)) == 0x22


# -- a real build ------------------------------------------------------------------


@pytest.mark.slow
def test_every_ring_shape_compiles_warning_free(write_design, db, tmp_path, toolchain):
    """The three generated shapes (a ring only in AOD, only while awake,
    both with ternaries), on a system and a vector font, in one real
    `monkeyc` build for an AMOLED and a MIP target -- the Python-level
    tests above read the source text, which cannot see a Monkey C typing
    or scoping error in it."""
    text = BASE.replace("targets: [fenix847mm]", "targets: [fenix847mm, fr955]").replace(
        "palette:\n", "aod:\n  dim: 0.5\nfonts:\n  bezel: {face: RobotoCondensedBold, size: 8%r}\n"
                      "palette:\n") + """
elements:
  - id: only_aod
    type: text
    text: "12"
    at: {anchor: center, dy: -30%}
    color: palette.fg
    aod: {outline: palette.dim}
  - id: only_awake
    type: text
    text: "34"
    at: {anchor: center}
    color: palette.fg
    outline: palette.red
    aod: {outline: none}
  - id: both
    type: text
    text: "56"
    at: {anchor: center, dy: 30%}
    color: palette.fg
    outline: palette.red
    aod: {outline: {color: palette.dim, width: 1}}
  - id: curved
    type: text
    text: "78"
    font: font.bezel
    at: {anchor: center}
    curve: {style: radial, angle: 90deg, radius: 40%r}
    color: palette.fg
    outline: palette.red
    aod: show
"""
    bag = Bag()
    result = real_build(write_design(text), output=tmp_path, bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    warnings = [d for d in bag.items if d.severity.value == "warning"]
    assert not warnings, "\n".join(d.message for d in warnings)
