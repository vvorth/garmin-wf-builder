"""`aod: {jitter: ...}` (plan 14 slice 5): the deterministic per-minute
sequence, format/resolution rules, codegen offsets, preview and the
heatmap.

Each test names, in its own docstring, the contrast it drives (`docs/lore/
working-agreement.md`: a guard nobody has watched fail is not a guard).
"""

from __future__ import annotations

import pytest

from tests.test_build import toolchain  # noqa: F401  -- a fixture, used by name
from tests.test_diagnostics import load
from wfb.aod_jitter import MAX_JITTER_PX, MINUTES_PER_DAY, offset
from wfb.build import build as real_build
from wfb.diagnostics import Bag
from wfb.emit import generate
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve

BASE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix847mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
"""


def _face(text, write_design, bag):
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    return face


def _by_id(face, element_id):
    return next(e for e in face.walk() if e.id == element_id)


def _view_text(text, write_design, bag, db, device_id="fenix847mm"):
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get(device_id)
    baked = {device.id: bake_fonts(face, device)}
    project = generate(face, [device], write_design("").parent / "build", baked)
    return next(v for k, v in project.files().items() if k.endswith("View.mc"))


# --------------------------------------------------------------------------
# the sequence (wfb.aod_jitter, and its Monkey C twin runtime-lib/WfbJitter.mc)


def test_offset_is_bounded():
    """|dx| and |dy| never exceed n, for every minute and every n."""
    for n in range(1, MAX_JITTER_PX + 1):
        for minute in range(MINUTES_PER_DAY):
            dx, dy = offset(minute, n)
            assert -n <= dx <= n
            assert -n <= dy <= n


def test_offset_pair_never_repeats_for_3_consecutive_minutes():
    """The weaker, whole-pair version of Garmin's 3-minute rule (research
    11 §1.2): the ``(dx, dy)`` pair itself never sits still for 3+
    consecutive minutes, including across the 23:59 -> 00:00 wrap.

    **This is necessary but not sufficient** -- see
    `test_no_pixel_of_a_long_line_stays_lit_for_3_consecutive_minutes`
    below for the contrast that actually matters: a 1px *line*'s own lit
    pixels can stay lit far longer than 3 minutes even while the offset
    *pair* changes every single minute, if only one axis is doing the
    changing. A first version of this sequence (a plain raster scan)
    passed this exact test while failing that one badly -- this test alone
    would not have caught the bug, which is why it stays as a floor, not
    the real contrast."""
    for n in range(1, MAX_JITTER_PX + 1):
        run = 1
        previous = offset(MINUTES_PER_DAY - 1, n)
        for minute in range(MINUTES_PER_DAY):
            current = offset(minute, n)
            run = run + 1 if current == previous else 1
            assert run < 3, f"n={n} minute={minute}: offset repeated {run} minutes running"
            previous = current


def _line_pixels(kind: str, half: int) -> set[tuple[int, int]]:
    """A 1px line's own pixel set, centred on the origin, ``2 * half + 1``
    pixels long -- long enough (``half`` chosen by the caller to exceed the
    jitter range) that a real ring edge, progress bar or text baseline is
    the shape being modelled, not a token stand-in for one."""
    if kind == "horizontal":
        return {(x, 0) for x in range(-half, half + 1)}
    if kind == "vertical":
        return {(0, y) for y in range(-half, half + 1)}
    return {(d, d) for d in range(-half, half + 1)}  # "diagonal", 45 degrees


def test_no_pixel_of_a_long_line_stays_lit_for_3_consecutive_minutes():
    """The real contrast (plan 14 slice 5 review, coordinator, 2026-09-23):
    Garmin's 3-minute rule is about *pixels*, not about the offset pair as
    a number. A 1px horizontal line (a ring's top/bottom edge, a progress
    bar, a text baseline) sliding along its own row keeps every interior
    pixel lit for as long as `dy` alone stays put, regardless of what `dx`
    does meanwhile -- so "the pair changes every minute" does not imply
    "no pixel stays lit too long" the way it looks like it should.

    For each `n` and each of three long (longer than the jitter range),
    axis-aligned/diagonal 1px lines, this renders the line's own offset
    pixel set for every minute of the day (plain set arithmetic -- no
    drawing) and checks that no pixel is a member of three
    *consecutive* minutes' sets, wrapping across 23:59 -> 00:00.

    **Confirmed to fail against the previous (raster-scan) sequence**
    before the fix: `dy` there only advanced once every `w = 2n+1` minutes,
    so the horizontal line's own interior sat completely still -- every
    interior pixel lit -- for up to 9 consecutive minutes at `n = 4`, and
    similarly for the other two lines and every other `n`. The stride
    sequence (`wfb.aod_jitter.offset`'s own docstring) moves both axes
    every single step, which is what makes this pass now.
    """
    for n in range(1, MAX_JITTER_PX + 1):
        half = 2 * n + 3  # comfortably longer than the +-n jitter range
        for kind in ("horizontal", "vertical", "diagonal"):
            base = _line_pixels(kind, half)
            lit_by_minute = []
            for minute in range(MINUTES_PER_DAY):
                dx, dy = offset(minute, n)
                lit_by_minute.append({(x + dx, y + dy) for x, y in base})
            for minute in range(MINUTES_PER_DAY):
                a = lit_by_minute[minute]
                b = lit_by_minute[(minute + 1) % MINUTES_PER_DAY]
                c = lit_by_minute[(minute + 2) % MINUTES_PER_DAY]
                stuck = a & b & c
                assert not stuck, (
                    f"n={n} kind={kind} minute={minute}: pixel(s) {stuck} lit 3 "
                    f"minutes running"
                )


def test_offset_deterministic():
    """Same (minute, n) always yields the same offset -- the host preview
    and the device must be able to compute this with no shared state."""
    for n in range(1, MAX_JITTER_PX + 1):
        for minute in (0, 1, 517, 1439):
            assert offset(minute, n) == offset(minute, n)


def test_offset_covers_the_whole_grid():
    """'the heatmap spreads well': every one of the (2n+1)^2 reachable
    offsets is actually visited somewhere over the day, for every n --
    not just a narrow diagonal slice of the grid."""
    for n in range(1, MAX_JITTER_PX + 1):
        w = 2 * n + 1
        seen = {offset(minute, n) for minute in range(MINUTES_PER_DAY)}
        assert len(seen) == w * w


def test_offset_rejects_out_of_range_n():
    with pytest.raises(ValueError):
        offset(0, 0)
    with pytest.raises(ValueError):
        offset(0, MAX_JITTER_PX + 1)


def test_offset_rejects_out_of_range_minute():
    with pytest.raises(ValueError):
        offset(-1, 1)
    with pytest.raises(ValueError):
        offset(MINUTES_PER_DAY, 1)


#: Python <-> Monkey C parity (`runtime-lib/WfbJitter.mc`'s own docstring):
#: hand-derived from the stride formula the module docstring spells out
#: (`w = 2n+1; stride = 2w+1; cell = (m * stride) % (w*w); dx = cell % w -
#: n; dy = cell // w - n`), independently of `wfb.aod_jitter.offset`'s own
#: implementation, so this is a real check against the *documented*
#: algorithm, not a tautology against the same code. `runtime-lib/
#: WfbJitter.mc`'s `offsetX`/`offsetY` compute the exact same two numbers
#: with Monkey C's own integer `%`/`/` -- there is no simulator in this
#: environment to execute it and compare (`docs/lore/toolchain.md`), so
#: `test_wfb_jitter_compiles_warning_free` below is the closest available
#: check on the Monkey C half: a real `monkeyc` build of a design that
#: calls it, warning-free.
_SPOT_CHECK = {
    (0, 1): (-1, -1),
    (1, 1): (0, 1),
    (2, 1): (1, 0),
    (3, 1): (-1, 0),
    (0, 4): (-4, -4),
    (8, 4): (4, 3),
    (9, 4): (-4, -3),
    (80, 4): (4, 2),
    (1439, 4): (4, 0),
    (1439, 1): (1, -1),
    (0, 2): (-2, -2),
    (12, 2): (0, -1),
}


def test_python_matches_the_spot_check_table_for_every_minute():
    """Runs `wfb.aod_jitter.offset` for all 1,440 minutes of the day, for
    every `n`, and checks the handful of entries in `_SPOT_CHECK` -- the
    Python half of the plan 14 §5.2 parity requirement (see `_SPOT_CHECK`'s
    own comment for why this stands in for direct comparison against the
    Monkey C module)."""
    for n in range(1, MAX_JITTER_PX + 1):
        for minute in range(MINUTES_PER_DAY):
            dx, dy = offset(minute, n)
            key = (minute, n)
            if key in _SPOT_CHECK:
                assert (dx, dy) == _SPOT_CHECK[key], key


@pytest.mark.slow
def test_wfb_jitter_compiles_warning_free(write_design, db, tmp_path, toolchain):
    """A real `monkeyc` build of a design that actually calls
    `WfbJitter.offsetX`/`offsetY` (through `aod: {jitter: ...}`) -- the
    same "a Python-level codegen test cannot catch a missing barrel file"
    lesson `test_a_runtime_dimmed_colour_compiles_warning_free` in
    `tests/test_aod.py` already recorded for `WfbColor.mc`."""
    text = BASE.replace("palette:\n", "aod:\n  jitter: 3\npalette:\n") + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: show
"""
    bag = Bag()
    result = real_build(write_design(text), output=tmp_path, bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    warnings = [d for d in bag.items if d.severity.value == "warning"]
    assert not warnings, bag.render()


# --------------------------------------------------------------------------
# format: group/face allowed, a non-group element rejected, >4 rejected


def test_group_jitter_is_accepted(write_design, bag):
    text = BASE + """
elements:
  - id: g
    type: group
    aod: {jitter: 3}
    children:
      - id: clock
        type: text
        text: "12:00"
        color: palette.fg
        aod: show
"""
    face = _face(text, write_design, bag)
    assert _by_id(face, "g").aod_jitter_own == 3


def test_face_jitter_is_accepted(write_design, bag):
    text = BASE.replace("palette:\n", "aod:\n  jitter: 2\npalette:\n") + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: show
"""
    face = _face(text, write_design, bag)
    assert face.aod_jitter == 2
    assert _by_id(face, "clock").aod_jitter == 2


@pytest.mark.parametrize("kind_yaml,element_id", [
    ("""  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: {jitter: 2}
""", "clock"),
    ("""  - id: dot
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 3px
    filled: true
    color: palette.fg
    aod: {jitter: 2}
""", "dot"),
])
def test_jitter_on_a_non_group_element_is_a_friendly_error(
        write_design, bag, kind_yaml, element_id):
    """Per-element jitter would break relationships between an element and
    its neighbours -- the builder rejects it with the reason, on every kind
    that isn't 'group' (schema-accepted, builder-refused, the same shape
    'aod: {filled: ...}' on 'shape: polygon' already uses)."""
    text = BASE + "elements:\n" + kind_yaml
    face = load(write_design(text), bag)
    assert face is None
    hits = [d for d in bag.errors if d.code == "aod"]
    assert hits, bag.render()
    assert "jitter" in hits[0].message
    assert "group" in hits[0].message
    assert any("hands" in note or "relationship" in note for note in hits[0].notes)


def test_jitter_over_4_is_a_schema_error(write_design, bag):
    text = BASE.replace("palette:\n", "aod:\n  jitter: 5\npalette:\n") + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
"""
    face = load(write_design(text), bag)
    assert face is None
    assert any(d.code == "schema" for d in bag.errors), bag.render()


def test_jitter_below_1_is_a_schema_error(write_design, bag):
    text = BASE.replace("palette:\n", "aod:\n  jitter: 0\npalette:\n") + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
"""
    face = load(write_design(text), bag)
    assert face is None
    assert any(d.code == "schema" for d in bag.errors), bag.render()


# --------------------------------------------------------------------------
# resolution: nearest wins, no accumulation


def test_nested_group_jitter_nearest_wins_no_accumulation(write_design, bag):
    """A group's own `jitter:` replaces its ancestry's for its whole
    subtree -- an inner group's own value wins outright over an outer
    group's, never composing into a sum of the two."""
    text = BASE + """
elements:
  - id: outer
    type: group
    aod: {jitter: 4}
    children:
      - id: inner
        type: group
        aod: {jitter: 1}
        children:
          - id: clock
            type: text
            text: "12:00"
            color: palette.fg
            aod: show
      - id: sibling
        type: text
        text: "OK"
        color: palette.fg
        aod: show
"""
    face = _face(text, write_design, bag)
    assert _by_id(face, "clock").aod_jitter == 1  # inner wins, not 4 + 1
    assert _by_id(face, "sibling").aod_jitter == 4  # outer's own value


def test_group_jitter_fills_only_its_own_subtree(write_design, bag):
    text = BASE.replace("palette:\n", "aod:\n  jitter: 2\npalette:\n") + """
elements:
  - id: g
    type: group
    aod: {jitter: 4}
    children:
      - id: clock
        type: text
        text: "12:00"
        color: palette.fg
        aod: show
  - id: outside
    type: text
    text: "OK"
    color: palette.fg
    aod: show
"""
    face = _face(text, write_design, bag)
    assert _by_id(face, "clock").aod_jitter == 4     # the group's own
    assert _by_id(face, "outside").aod_jitter == 2   # the face default


def test_no_jitter_anywhere_resolves_to_none(write_design, bag):
    text = BASE + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: show
"""
    face = _face(text, write_design, bag)
    assert _by_id(face, "clock").aod_jitter is None


# --------------------------------------------------------------------------
# codegen: jittered elements get the offset in AOD, non-jittered ones don't,
# awake is unaffected, all-MIP is byte-identical


def test_jittered_element_gets_the_offset_in_its_draw_method(write_design, bag, db):
    text = BASE.replace("palette:\n", "aod:\n  jitter: 3\npalette:\n") + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: show
"""
    view = _view_text(text, write_design, bag, db)
    body = view.split("function drawClock(")[1].split("\n    }")[0]
    assert "_aodDxN3" in body
    assert "_aodDyN3" in body
    assert "Layout.CLOCK_X + _aodDxN3" in body
    assert "Layout.CLOCK_Y + _aodDyN3" in body


def test_non_jittered_element_gets_no_offset(write_design, bag, db):
    """The other half of the same contrast: an element outside any
    jittered scope must not reference the field at all, even in a design
    that uses jitter elsewhere."""
    text = BASE.replace("palette:\n", "aod:\n  default: hide\npalette:\n") + """
elements:
  - id: g
    type: group
    aod: {jitter: 3}
    children:
      - id: clock
        type: text
        text: "12:00"
        color: palette.fg
        aod: show
  - id: dot
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 3px
    filled: true
    color: palette.fg
    aod: show
"""
    view = _view_text(text, write_design, bag, db)
    dot_body = view.split("function drawDot(")[1].split("\n    }")[0]
    assert "_aodDxN3" not in dot_body
    assert "_aodDyN3" not in dot_body


def test_multiple_distinct_magnitudes_get_separate_field_pairs(write_design, bag, db):
    text = BASE.replace("palette:\n", "aod:\n  jitter: 2\npalette:\n") + """
elements:
  - id: g
    type: group
    aod: {jitter: 4}
    children:
      - id: clock
        type: text
        text: "12:00"
        color: palette.fg
        aod: show
  - id: dot
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 3px
    filled: true
    color: palette.fg
    aod: show
"""
    view = _view_text(text, write_design, bag, db)
    assert "private var _aodDxN2 as Number = 0;" in view
    assert "private var _aodDxN4 as Number = 0;" in view
    assert "WfbJitter.offsetX(aodMinuteOfDay, 2);" in view
    assert "WfbJitter.offsetX(aodMinuteOfDay, 4);" in view


def test_awake_draw_is_unaffected_by_jitter(write_design, bag, db):
    """The shared draw method adds the jitter field unconditionally, but
    the field itself is 0 whenever the watch is not actively drawing a
    jittered AOD frame (reset in onExitSleep) -- so the *awake* branch's
    own generated call sequence and read plan are untouched by whether
    `jitter:` is declared at all."""
    without = BASE + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
"""
    with_jitter = BASE.replace("palette:\n", "aod:\n  jitter: 3\npalette:\n") + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: show
"""
    bag_a, bag_b = Bag(), Bag()
    view_a = _view_text(without, write_design, bag_a, db)
    view_b = _view_text(with_jitter, write_design, bag_b, db)
    active_a = view_a.split("else {")[1].split("\n    }")[0]
    active_b = view_b.split("else {")[1].split("\n    }")[0]
    assert active_a == active_b


MIP_BASE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
"""


def test_an_all_mip_build_is_byte_identical_with_jitter_declared(write_design, bag, db):
    without = MIP_BASE + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
"""
    with_jitter = MIP_BASE.replace(
        "palette:\n", "aod:\n  jitter: 4\npalette:\n"
    ) + """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: show
"""
    bag_a, bag_b = Bag(), Bag()
    text_a = _view_text(without, write_design, bag_a, db, device_id="fenix8solar47mm")
    text_b = _view_text(with_jitter, write_design, bag_b, db, device_id="fenix8solar47mm")
    assert text_a == text_b
    assert "_aodD" not in text_a
    assert "_aodD" not in text_b
    assert "WfbJitter" not in text_a
    assert "WfbJitter" not in text_b


# --------------------------------------------------------------------------
# preview: `--aod --minute N` shifts by the expected (dx, dy)


def _minute_face(write_design, n):
    text = BASE.replace("palette:\n", f"aod:\n  jitter: {n}\npalette:\n") + """
elements:
  - id: dot
    type: shape
    shape: circle
    at: {anchor: top_left, dx: 60px, dy: 60px}
    radius: 1px
    filled: true
    color: palette.fg
    aod: show
"""
    return write_design(text)


def test_preview_at_minute_shifts_by_the_expected_offset(write_design, bag, db):
    from wfb.preview import PreviewOptions, render

    n = 3
    face = load(_minute_face(write_design, n), bag)
    assert face is not None, bag.render()
    device = db.get("fenix847mm")
    resolved = resolve(face, device, bake_fonts(face, device))

    minute = 0
    dx, dy = offset(minute, n)
    assert (dx, dy) != (0, 0)  # otherwise this minute would not prove anything
    options = PreviewOptions(scale=1, mask_shape=False, aod=True,
                             time=(minute // 60, minute % 60, 0))
    image = render(resolved, options)
    px = image.load()
    assert px[60 + dx, 60 + dy] != (0, 0, 0)
    assert px[60, 60] == (0, 0, 0)  # the unshifted anchor is dark: it moved away


# --------------------------------------------------------------------------
# heatmap sanity


def test_heatmap_reports_a_sane_max_fraction(write_design, bag, db):
    from wfb.preview import PreviewOptions, render_aod_heatmap

    face = load(_minute_face(write_design, 2), bag)
    assert face is not None, bag.render()
    device = db.get("fenix847mm")
    resolved = resolve(face, device, bake_fonts(face, device))
    options = PreviewOptions(scale=1, mask_shape=False)
    # A small sample of minutes, not the full 1,440 -- this only has to
    # check the accumulation logic, not re-measure the sequence itself
    # (already covered above).
    heat, max_fraction = render_aod_heatmap(resolved, options, minutes=range(0, 1440, 60))
    assert heat.size == (device.width, device.height)
    assert 0.0 < max_fraction <= 1.0
    extrema = heat.convert("L").getextrema()
    assert extrema[0] == 0        # most of the frame is never lit
    assert extrema[1] > 0         # the jittered dot lights something, somewhere
