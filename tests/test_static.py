"""`static:` -- content painted once into an offscreen buffer.

The design shipped is the **opaque** one: the buffer covers the screen, so the
static content has to be a contiguous prefix of draw order and there is exactly
one buffer per face.  Why that rather than the transparent version everyone
wants is in `docs/research/probes/static-buffer/`; the point here is that every
consequence of it is a *checked* consequence, not an assumption.

Every guard below was watched fail before it was believed -- each test names,
in its own docstring or by construction, the unfixed input it goes red against.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_diagnostics import load
from wfb import ir
from wfb.diagnostics import Bag

ROOT = Path(__file__).resolve().parent.parent

HEAD = """format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm, fenix8solar51mm, fr955]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
"""

#: One static group (written as the top-level block) and one dynamic element.
BLOCK_FORM = HEAD + """static:
  backdrop:
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
  caption:
    type: text
    text: "STEPS"
    font: FONT_XTINY
    at: {anchor: center, dy: 30%}
    color: palette.fg
elements:
  clock:
    type: text
    value: time.clock
    format: "{:%H:%M}"
    font: FONT_NUMBER_MEDIUM
    at: {anchor: center}
    color: palette.fg
"""

#: The same design written with `static: true` on an explicit group, which is
#: what the block above is rewritten into.
GROUP_FORM = HEAD + """elements:
  - id: static
    type: group
    static: true
    children:
      - id: backdrop
        type: shape
        shape: rectangle
        at: {anchor: center}
        size: {width: 100%, height: 100%}
        color: palette.bg
      - id: caption
        type: text
        text: "STEPS"
        font: FONT_XTINY
        at: {anchor: center, dy: 30%}
        color: palette.fg
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    font: FONT_NUMBER_MEDIUM
    at: {anchor: center}
    color: palette.fg
"""


def _face(text, write_design, bag):
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    return face


def _errors(text, write_design):
    bag = Bag()
    load(write_design(text), bag)
    return [d for d in bag.items if d.severity.value == "error"]


# -- the two spellings ------------------------------------------------------


def test_the_block_and_the_group_are_the_same_design(write_design, bag):
    """The top-level `static:` block is sugar, and this is what "sugar" means.

    Not merely "both build": the *same* elements, in the same order, with the
    same static roots.  If the desugar ever produced a subtly different tree,
    every downstream check would be reasoning about a design the author did not
    write.
    """
    block = _face(BLOCK_FORM, write_design, bag)
    group = _face(GROUP_FORM, write_design, Bag())

    def shape(face):
        return [(e.id, e.kind, e.static, e.static_root) for e in face.walk()]

    assert shape(block) == shape(group)
    assert shape(block) == [
        ("static", "group", True, "static"),
        ("backdrop", "shape", False, "static"),
        ("caption", "text", False, "static"),
        ("clock", "text", False, None),
    ]


def _generate(text, write_design, db, root):
    """Every generated file for every installed target, as path -> text."""
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    face = _face(text, write_design, Bag())
    devices = [db.get(d) for d in face.targets if d in db.ids()]
    assert len(devices) == 3, "this gate is about all three targets"
    reference = min(d.minor_radius for d in devices)
    baked = {d.id: bake_fonts(face, d, reference) for d in devices}
    return generate(face, devices, root, baked).files()


def test_the_two_spellings_generate_byte_identical_monkey_c(write_design, db, tmp_path):
    """The strongest gate available: identical generated output, per target.

    Not just the view -- every file, Monkey C, per-device Layout, resource XML,
    manifest and jungle alike, byte for byte, the same gate the mapping form of
    `elements:` is held to in `tests/test_desugar.py`.
    """
    from_block = _generate(BLOCK_FORM, write_design, db, tmp_path / "block")
    from_group = _generate(GROUP_FORM, write_design, db, tmp_path / "group")
    assert sorted(from_block) == sorted(from_group)
    for name, text in from_block.items():
        assert from_group[name] == text, name


def test_the_block_takes_both_spellings_and_composes_with_them(write_design, bag):
    """`static:` accepts a list or a mapping, and so does a group inside it.

    The block is rewritten *before* the element-list rewrite recurses into it,
    so the two conveniences compose rather than one shadowing the other.  Worth
    pinning: they are separate rewrites in the same pass, and nothing else would
    notice if the recursion stopped at the block's own boundary.
    """
    text = HEAD + """static:
  - id: backdrop
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
  - id: ticks
    type: group
    children:
      caption:
        type: text
        text: "STEPS"
        font: FONT_XTINY
        at: {anchor: center, dy: 30%}
        color: palette.fg
elements:
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    font: FONT_NUMBER_MEDIUM
    at: {anchor: center}
    color: palette.fg
"""
    face = _face(text, write_design, bag)
    assert [(e.id, e.static_root) for e in face.walk()] == [
        ("static", "static"),
        ("backdrop", "static"),
        ("ticks", "static"),
        ("caption", "static"),
        ("clock", None),
    ]


def test_static_true_on_a_leaf_is_a_subtree_of_one(write_design, bag):
    text = HEAD + """elements:
  - id: backdrop
    type: shape
    shape: rectangle
    static: true
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    font: FONT_NUMBER_MEDIUM
    at: {anchor: center}
    color: palette.fg
"""
    face = _face(text, write_design, bag)
    roots = face.static_roots()
    assert [e.id for e in roots] == ["backdrop"]
    assert roots[0].static_root == "backdrop"


def test_the_reserved_id_is_reported_against_the_authors_own_element(write_design):
    """Red against a design that names an element `static` beside the block.

    Without the check this collides into one `duplicate-id` reported against a
    group that has no line in the source file.
    """
    text = BLOCK_FORM.replace("  clock:", "  static:\n    type: text\n"
                              "    text: \"x\"\n    font: FONT_XTINY\n"
                              "    at: {anchor: center, dy: 40%}\n"
                              "    color: palette.fg\n  clock:")
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["static"]
    assert "reserved" in errors[0].message


def test_a_static_block_that_is_not_a_list_or_mapping_is_rejected(write_design):
    text = HEAD + "static: true\nelements:\n  clock:\n    type: text\n" \
        "    value: time.clock\n    format: \"{:%H:%M}\"\n" \
        "    font: FONT_NUMBER_MEDIUM\n    at: {anchor: center}\n" \
        "    color: palette.fg\n"
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["static"]
    assert "`static: true` on a single element" in " ".join(errors[0].notes)


# -- the gates --------------------------------------------------------------


def test_a_data_binding_inside_a_static_subtree_is_an_error(write_design):
    """The gate the whole feature rests on: a buffer filled once cannot show
    a reading that changes.  Red against the same design with `static:` removed,
    which validates cleanly."""
    text = BLOCK_FORM.replace(
        '    text: "STEPS"',
        "    value: activity.steps\n    format: \"{:d}\"\n    when_absent: hide")
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["static"]
    assert "'caption' binds a value to 'activity.steps'" in errors[0].message
    # ...and the same design without the block is clean, which is what makes
    # this a check on `static:` rather than on the binding.
    assert not _errors(text.replace("static:\n", "elements:\n", 1)
                       .replace("elements:\n  clock:", "  clock:"), write_design)


def test_a_bound_visible_inside_a_static_subtree_is_an_error(write_design):
    """`visible:` is a binding too -- it was the one easiest to forget, because
    it is not the element's *value*."""
    text = BLOCK_FORM.replace(
        "    color: palette.fg\nelements:",
        '    color: palette.fg\n    visible: "activity.steps > 100"\nelements:')
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["static"]
    assert "binds visible to 'activity.steps'" in errors[0].message


def test_a_constant_expression_inside_a_static_subtree_is_fine(write_design, bag):
    """It is the *binding* that is rejected, not the syntax."""
    text = BLOCK_FORM.replace(
        "    color: palette.fg\nelements:",
        '    color: palette.fg\n    visible: "true"\nelements:')
    assert load(write_design(text), bag) is not None, bag.render()


def test_low_power_inside_a_static_subtree_is_an_error(write_design):
    text = BLOCK_FORM.replace("    color: palette.fg\nelements:",
                              "    color: palette.fg\n    modes: [active, low_power]\nelements:")
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["static"]
    assert "low_power" in errors[0].message
    assert "charged by clip *area*" in " ".join(errors[0].notes)


def test_mixed_modes_inside_one_buffer_are_an_error(write_design):
    """One buffer is blitted as a whole, so its contents cannot disagree about
    which mode they belong to."""
    text = BLOCK_FORM.replace("    color: palette.fg\nelements:",
                              "    color: palette.fg\n    modes: [always_on]\nelements:")
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["static"]
    assert "draws in always_on but the static 'backdrop' draws in active" in errors[0].message


def test_a_nested_static_names_the_outer_one(write_design):
    text = BLOCK_FORM.replace("    color: palette.fg\nelements:",
                              "    color: palette.fg\n    static: true\nelements:")
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["static"]
    assert "inside the static subtree of 'static'" in errors[0].message


def test_a_carousel_cannot_be_static(write_design):
    text = HEAD + """elements:
  - id: data
    type: carousel
    static: true
    at: {anchor: center}
    size: {width: 80%, height: 20%}
    color: palette.fg
    inactive_color: palette.bg
    items:
      - value: activity.steps
        format: "{:d}"
        when_absent: hide
      - value: activity.calories
        format: "{:d}"
        when_absent: hide
"""
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["static"]
    assert "is a carousel and cannot be static" in errors[0].message


def test_static_content_must_come_first_in_draw_order(write_design):
    """The consequence of an opaque buffer, and the one an author will hit.

    Red against the same design with the `z: -1` removed.
    """
    text = BLOCK_FORM.replace("    color: palette.fg\nelements:",
                              "    color: palette.fg\nelements:")
    text = text.replace("    at: {anchor: center}\n    color: palette.fg\n",
                        "    at: {anchor: center}\n    color: palette.fg\n    z: -1\n")
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["static"]
    assert "'clock' is drawn before, or in between, the static content" in errors[0].message
    assert not _errors(text.replace("    z: -1\n", ""), write_design)


def test_two_static_groups_may_not_interleave(write_design):
    """Each group is painted into the buffer in one run, so a `z:` that
    shuffles one group's element into the middle of another's is rejected."""
    text = HEAD + """elements:
  - id: first
    type: group
    static: true
    children:
      - id: a1
        type: shape
        shape: circle
        at: {anchor: center, dx: -20%}
        radius: 5px
        color: palette.fg
      - id: a2
        type: shape
        shape: circle
        at: {anchor: center, dx: -10%}
        radius: 5px
        color: palette.fg
        z: 2
  - id: second
    type: group
    static: true
    children:
      - id: b1
        type: shape
        shape: circle
        at: {anchor: center, dx: 10%}
        radius: 5px
        color: palette.fg
        z: 1
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    font: FONT_NUMBER_MEDIUM
    at: {anchor: center}
    color: palette.fg
    z: 3
"""
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["static"]
    assert "split apart by" in errors[0].message
    assert not _errors(text.replace("        z: 2\n", "").replace("        z: 1\n", ""),
                       write_design)


def test_two_contiguous_static_groups_are_allowed(write_design, bag):
    """Several roots, one buffer, one `drawStatic<Id>` each."""
    text = HEAD + """elements:
  - id: first
    type: group
    static: true
    children:
      - id: a1
        type: shape
        shape: circle
        at: {anchor: center, dx: -20%}
        radius: 5px
        color: palette.fg
  - id: second
    type: shape
    shape: circle
    static: true
    at: {anchor: center, dx: 10%}
    radius: 5px
    color: palette.fg
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    font: FONT_NUMBER_MEDIUM
    at: {anchor: center}
    color: palette.fg
"""
    face = _face(text, write_design, bag)
    assert [e.id for e in face.static_roots()] == ["first", "second"]


# -- draw order, and the claim it rests on ----------------------------------


@pytest.mark.parametrize("design", sorted((ROOT / "examples").glob("*/face.yaml")),
                         ids=lambda p: p.parent.name)
def test_ir_draw_order_matches_the_resolved_one(design, bag, db):
    """`Face.draw_order` re-derives what `wfb.layout` computes.

    The static prefix check runs in the IR, once, on the strength of this: draw
    order is document order then a stable sort by `z`, and neither depends on
    the device.  If that ever stops being true the check would be policing an
    order nothing draws in, so it is asserted against the real resolver on every
    worked example rather than argued for in a comment.
    """
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    face = load(design, bag)
    assert face is not None, bag.render()
    expected = [e.id for e in face.draw_order()]
    for device_id in face.targets:
        if device_id not in db.ids():
            continue
        device = db.get(device_id)
        resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
        assert [p.id for p in resolved.items if p.kind != "group"] == expected


# -- codegen ----------------------------------------------------------------


def _view(text, write_design, db, tmp_path, device_id="fenix8solar47mm"):
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    bag = Bag()
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get(device_id)
    baked = {device.id: bake_fonts(face, device, device.minor_radius)}
    return generate(face, [device], tmp_path, baked).files()["source/TestView.mc"]


def test_the_generated_view_has_a_buffer_a_fallback_and_one_blit(write_design, db, tmp_path):
    view = _view(BLOCK_FORM, write_design, db, tmp_path)
    # allocation, guarded exactly the way the Analog sample guards it
    assert "private var _staticBuffer as BufferedBitmap?;" in view
    assert "if (Graphics has :createBufferedBitmap)" in view
    assert ").get() as BufferedBitmap?;" in view
    # filled once, from onLayout, through the same method onUpdate falls back to
    assert "renderStatic(buffer.getDc());" in view
    assert "dc.drawBitmap(0, 0, buffer);" in view
    assert "renderStatic(dc);" in view
    # ...and the static elements are no longer called from onUpdate directly
    on_update = view.split("function onUpdate")[1].split("function ")[0]
    assert "drawBackdrop(dc)" not in on_update
    assert "drawCaption(dc)" not in on_update
    assert "drawClock(dc" in on_update
    # one drawStatic<Id> per static group, and the buffer starts from a known ground
    assert "private function drawStatic(dc as Dc) as Void {" in view
    assert "dc.clear();" in view


def test_always_on_gets_the_blit_in_both_branches(write_design, db, tmp_path):
    """`onUpdate` forks on `_sleeping`, so the blit has to be in both arms.

    The static content declares the same modes as everything else it shares the
    buffer with, so if it draws while awake and while asleep, both branches
    blit.  Emitted per branch rather than hoisted above the fork, because a
    design whose static content is `active`-only must *not* blit while asleep.
    """
    text = BLOCK_FORM.replace("    color: palette.bg\n",
                              "    color: palette.bg\n    modes: [active, always_on]\n")
    text = text.replace("    at: {anchor: center, dy: 30%}\n    color: palette.fg\n",
                        "    at: {anchor: center, dy: 30%}\n    color: palette.fg\n"
                        "    modes: [active, always_on]\n")
    text = text.replace("    at: {anchor: center}\n    color: palette.fg\n",
                        "    at: {anchor: center}\n    color: palette.fg\n"
                        "    modes: [active, always_on]\n")
    view = _view(text, write_design, db, tmp_path)
    on_update = view.split("function onUpdate")[1].split("\n    function ")[0]
    assert on_update.count("dc.drawBitmap(0, 0, buffer);") == 2
    assert on_update.count("renderStatic(dc);") == 2


def test_a_face_with_nothing_static_generates_exactly_what_it_did_before(write_design, db, tmp_path):
    """The feature must cost nothing to a design that does not use it.

    `tests/golden/` is the real guarantee here -- no golden design declares
    `static:` -- but this states it locally too, because a stray field or an
    always-emitted helper is exactly the kind of regression a golden file would
    catch only after someone noticed the diff.
    """
    plain = HEAD + """elements:
  - id: clock
    type: text
    value: time.clock
    format: "{:%H:%M}"
    font: FONT_NUMBER_MEDIUM
    at: {anchor: center}
    color: palette.fg
"""
    view = _view(plain, write_design, db, tmp_path)
    assert "_staticBuffer" not in view
    assert "renderStatic" not in view
    assert "BufferedBitmap" not in view


def test_a_static_group_named_static_does_not_generate_drawstaticstatic(write_design, db, tmp_path):
    """`drawStaticStatic` is not something a person would write (ADR 0003)."""
    assert ir.static_group_method("static") == "drawStatic"
    assert ir.static_group_method("hour_ticks") == "drawStaticHourTicks"
    view = _view(BLOCK_FORM, write_design, db, tmp_path)
    assert "drawStaticStatic" not in view


def test_a_static_group_reserves_its_third_symbol(write_design):
    """A group `foo` owns `drawStaticFoo`, so an element `static_foo` cannot.

    Red against the pre-fix candidate list, which reserved only `FOO`/`drawFoo`
    and let `monkeyc` discover the redefinition in generated code.
    """
    text = HEAD + """elements:
  - id: foo
    type: group
    at: {anchor: center}
    children:
      - id: dot
        type: shape
        shape: circle
        at: {anchor: center}
        radius: 5px
        color: palette.fg
  - id: static_foo
    type: shape
    shape: circle
    at: {anchor: center, dx: 20%}
    radius: 5px
    color: palette.fg
"""
    errors = _errors(text, write_design)
    assert [d.code for d in errors] == ["duplicate-id"]
    assert "drawStaticFoo" in errors[0].message


# -- the lint ---------------------------------------------------------------


def test_the_graphics_pool_note_reports_the_estimate(write_design, db):
    from wfb import lint
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    bag = Bag()
    face = load(write_design(BLOCK_FORM), bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    lint.check_graphics_pool(resolved, bag)
    found = [d for d in bag.items if d.code == "graphics-pool"]
    assert len(found) == 1
    assert found[0].severity.value == "note"
    assert "67,600 B of the 1,048,576 B" in found[0].message
    # ADR 0008: a check that cannot be exact must not sound exact.
    assert "estimate" in (found[0].confidence or "")


def test_the_graphics_pool_check_warns_when_the_pool_is_small(write_design, db, monkeypatch):
    """Driven red the only way it can be on these targets.

    One full-screen buffer is 6.4% of a 1 MB pool, so on `fenix8solar47mm`,
    `fenix8solar51mm` and `fr955` this check will never warn -- the threshold is
    there for a device with a smaller pool, and the only way to watch it fire is
    to be that device.  Said plainly in the report as well: on today's targets
    the warning branch is unreachable.
    """
    from wfb import lint
    from wfb.devices import Device
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    bag = Bag()
    face = load(write_design(BLOCK_FORM), bag)
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    monkeypatch.setattr(Device, "graphics_pool_bytes",
                        property(lambda self: 100 * 1024))
    lint.check_graphics_pool(resolved, bag)
    found = [d for d in bag.items if d.code == "graphics-pool"]
    assert [d.severity.value for d in found] == ["warning"]


def test_the_graphics_pool_warning_is_suppressible(write_design, db, monkeypatch):
    """Two checks in this compiler once advertised suppression they did not
    honour, so this is asserted rather than assumed."""
    from wfb import lint
    from wfb.devices import Device
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    text = GROUP_FORM.replace(
        "    static: true\n",
        "    static: true\n    lint: {allow: [graphics-pool], reason: \"deliberate\"}\n")
    bag = Bag()
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    monkeypatch.setattr(Device, "graphics_pool_bytes",
                        property(lambda self: 100 * 1024))
    lint.check_graphics_pool(resolved, bag)
    assert not [d for d in bag.items if d.code == "graphics-pool"]


def test_the_pool_estimate_uses_the_devices_own_bits_per_pixel(db):
    for device_id, expected in (("fenix8solar47mm", 260 * 260),
                                ("fenix8solar51mm", 280 * 280),
                                ("fr955", 260 * 260)):
        device = db.get(device_id)
        assert device.bits_per_pixel == 8
        assert device.buffer_bytes() == expected


# -- the second renderer ----------------------------------------------------


def test_preview_does_not_know_about_static_at_all():
    """`wfb preview` renders the resolved items in draw order and nothing else.

    That is the reason preview and device still agree: buffering changes *when*
    something is painted, never what.  Asserted against the source rather than
    argued, so that a future change to `preview.py` that starts consulting
    `static` has to come and edit this claim.
    """
    text = (ROOT / "wfb" / "preview.py").read_text(encoding="utf-8")
    assert "static" not in text
