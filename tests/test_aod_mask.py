"""`aod: {mask: ...}` (plan 16 slice 1): the moving 2x2 pixel mask over the
AOD frame -- format + codegen only. Host-side (`wfb/aod_mask.py`, preview,
heatmap, lint) is slice 2, in `tests/test_aod_mask_preview.py`.

Each test names, in its own docstring, the contrast it drives -- the same
discipline `tests/test_aod.py` documents at its own top
(`docs/lore/working-agreement.md`: a guard nobody has watched fail is not a
guard).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from wfb.build import load
from wfb.build import build as real_build
from wfb.diagnostics import Bag
from wfb.emit import generate
from wfb.emit.resources import bake_fonts

ROOT = Path(__file__).resolve().parent.parent

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

#: A mixed AMOLED + MIP build -- `fenix847mm` is where `_aod` (and so the
#: mask call) can ever be true; `fenix8solar47mm` is the MIP witness that the
#: shared-view byte-identity guarantee (constraint 5) still holds.
MIXED_BASE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix847mm, fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
"""

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

_ONE_SHOWN_CLOCK = """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
    aod: show
"""

_ONE_HIDDEN_CLOCK = """
elements:
  - id: clock
    type: text
    text: "12:00"
    color: palette.fg
"""


def _project(text, write_design, bag, db, device_ids):
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    devices = [db.get(device_id) for device_id in device_ids]
    baked = {device.id: bake_fonts(face, device) for device in devices}
    return generate(face, devices, write_design("").parent / "build", baked)


def _view_text_from(project):
    return next(v for k, v in project.files().items() if k.endswith("View.mc"))


def _view_text(text, write_design, bag, db, device_ids=("fenix847mm",)):
    project = _project(text, write_design, bag, db, device_ids)
    return _view_text_from(project)


# --------------------------------------------------------------------------
# the call itself: present, ordered after the element draws, barrelled


def test_mask_call_emitted_after_element_draws_on_a_mixed_build(write_design, bag, db):
    """An AMOLED target (`fenix847mm`) plus a MIP one (`fenix8solar47mm`), one
    AOD-shown element: `WfbAodMask.apply(` must appear inside the `_aod`
    branch, *after* the element's own draw call -- masking has to run last,
    or it would black out pixels the mask itself is supposed to spare before
    the element ever draws them. `WfbAodMask.mc` must also be in the
    project's barrel. Must fail against an implementation that emits the
    mask call before the element draws, or omits the barrel entry."""
    project = _project(
        MIXED_BASE + _ONE_SHOWN_CLOCK, write_design, bag, db,
        ["fenix847mm", "fenix8solar47mm"],
    )
    view = _view_text_from(project)
    body = view.split("function onUpdate(dc as Dc) as Void {")[1]
    else_index = body.find("else {")
    draw_index = body.find("drawClock(dc);")
    mask_index = body.find("WfbAodMask.apply(dc, System.getClockTime().min);")
    assert draw_index != -1, view
    assert mask_index != -1, view
    assert else_index != -1, view
    assert draw_index < mask_index < else_index, (
        "the mask call must come after the element draw, both inside the _aod branch"
    )
    assert "WfbAodMask.mc" in project.barrel, project.barrel


def test_mask_true_and_mask_absent_are_byte_identical(write_design, bag, db):
    """`mask:` omitted and `mask: true` written out mean the same thing --
    D2 of plan 16 -- so their generated sources must match exactly."""
    bag_a, bag_b = Bag(), Bag()
    text_absent = BASE + _ONE_SHOWN_CLOCK
    text_true = BASE.replace("palette:\n", "aod:\n  mask: true\npalette:\n") + _ONE_SHOWN_CLOCK
    view_absent = _view_text(text_absent, write_design, bag_a, db)
    view_true = _view_text(text_true, write_design, bag_b, db)
    assert view_absent == view_true
    assert "WfbAodMask.apply(" in view_absent


# --------------------------------------------------------------------------
# `mask: false`: no call, no barrel file, and nothing else changes


def test_mask_false_emits_no_call_and_no_barrel_file(write_design, bag, db):
    text = BASE.replace("palette:\n", "aod:\n  mask: false\npalette:\n") + _ONE_SHOWN_CLOCK
    project = _project(text, write_design, bag, db, ["fenix847mm"])
    view = _view_text_from(project)
    assert "WfbAodMask" not in view
    assert "WfbAodMask.mc" not in project.barrel


def test_mask_false_differs_from_mask_on_by_exactly_the_added_lines(write_design, bag, db):
    """The only diff between `mask: false` and the mask on (the default)
    must be the comment + call this slice adds -- nothing about the rest of
    the element's own draw sequence may move or change."""
    bag_a, bag_b = Bag(), Bag()
    text_off = BASE.replace("palette:\n", "aod:\n  mask: false\npalette:\n") + _ONE_SHOWN_CLOCK
    text_on = BASE + _ONE_SHOWN_CLOCK
    view_off = _view_text(text_off, write_design, bag_a, db)
    view_on = _view_text(text_on, write_design, bag_b, db)
    assert view_off != view_on
    lines_off = view_off.splitlines()
    lines_on = view_on.splitlines()
    added = [line for line in lines_on if line not in lines_off]
    removed = [line for line in lines_off if line not in lines_on]
    assert removed == []
    stripped_added = [line.strip() for line in added]
    assert "WfbAodMask.apply(dc, System.getClockTime().min);" in stripped_added
    assert any("mask" in line for line in stripped_added), stripped_added
    # Nothing besides the mask's own comment/call lines was added.
    assert len(added) == len(stripped_added) == 2, added


def test_mask_false_matches_the_ir_field_forced_off_directly(write_design, bag, db):
    """`mask: false` in YAML goes through the schema and
    `Builder._build_face_aod`; this checks the *emitter*'s own gate
    independently, by forcing `Face.aod_mask` to `False` on an
    otherwise-default (mask-absent, so builder-parsed as `True`) face and
    generating straight from that mutated IR object, bypassing the YAML
    parse entirely for this half of the comparison. Must fail against an
    implementation whose emitter reads something other than
    `resolved.face.aod_mask` to decide whether to emit the call (e.g. a
    stale closure or a second, disconnected flag) -- forcing only the field
    would then fail to suppress the call, and this would catch it."""
    bag_a, bag_b = Bag(), Bag()
    text_explicit_off = BASE.replace(
        "palette:\n", "aod:\n  mask: false\npalette:\n"
    ) + _ONE_SHOWN_CLOCK
    project_explicit = _project(
        text_explicit_off, write_design, bag_a, db, ["fenix847mm"]
    )
    view_explicit = _view_text_from(project_explicit)

    face = load(write_design(BASE + _ONE_SHOWN_CLOCK), bag_b)
    assert face is not None, bag_b.render()
    assert face.aod_mask is True  # sanity: absent really did default to True
    face.aod_mask = False
    device = db.get("fenix847mm")
    baked = {device.id: bake_fonts(face, device)}
    project_forced = generate(face, [device], write_design("").parent / "build2", baked)
    view_forced = _view_text_from(project_forced)

    assert view_explicit == view_forced
    assert "WfbAodMask" not in view_forced


# --------------------------------------------------------------------------
# an all-MIP build is unaffected, whatever `mask:` says


@pytest.mark.parametrize("aod_block", ["", "aod:\n  mask: true\n", "aod:\n  mask: false\n"])
def test_an_all_mip_build_is_byte_identical_whatever_mask_says(
        write_design, db, aod_block):
    """MIP-only targets never emit `_aod` at all (constraint 5) -- `mask:`
    must not change that, in any of its three spellings."""
    baseline_bag = Bag()
    baseline = _view_text(
        MIP_BASE + _ONE_HIDDEN_CLOCK, write_design, baseline_bag, db,
        device_ids=["fenix8solar47mm"],
    )
    bag = Bag()
    text = MIP_BASE.replace("palette:\n", aod_block + "palette:\n") + _ONE_HIDDEN_CLOCK
    view = _view_text(text, write_design, bag, db, device_ids=["fenix8solar47mm"])
    assert view == baseline
    assert "_aod" not in view
    assert "WfbAodMask" not in view


# --------------------------------------------------------------------------
# an empty AOD set draws nothing to mask


def test_empty_aod_set_emits_no_mask_call(write_design, bag, db):
    """An AMOLED target with nothing shown in AOD (the face default `hide`,
    no element opts in) must not emit the mask call either -- masking an
    all-black frame is pure waste (plan 16 §4)."""
    text = BASE + _ONE_HIDDEN_CLOCK  # no `aod:` on the element -> hidden by default
    project = _project(text, write_design, bag, db, ["fenix847mm"])
    view = _view_text_from(project)
    assert "WfbAodMask" not in view
    assert "WfbAodMask.mc" not in project.barrel


# --------------------------------------------------------------------------
# schema


def test_mask_non_boolean_is_a_schema_error(write_design, bag):
    text = BASE.replace(
        "palette:\n", 'aod:\n  mask: "yes"\npalette:\n'
    ) + _ONE_SHOWN_CLOCK
    face = load(write_design(text), bag)
    assert face is None
    hits = [d for d in bag.errors if d.code == "schema"]
    assert hits and "mask" in hits[0].message, bag.render()


# --------------------------------------------------------------------------
# the phase table (plan 16 §2): parsed straight out of the real .mc source,
# not re-typed from the plan, so a transposed dx/dy or an off-by-one phase
# boundary in the actual runtime file would be caught.


def test_phase_table_matches_the_plan(write_design):
    text = (ROOT / "runtime-lib" / "WfbAodMask.mc").read_text()
    dx_match = re.search(r"var dx = \((?P<cond>.*?)\) \? 1 : 0;", text)
    dy_match = re.search(r"var dy = \((?P<cond>.*?)\) \? 1 : 0;", text)
    assert dx_match, text
    assert dy_match, text

    def _as_python(cond: str) -> str:
        return cond.replace("||", " or ").replace("&&", " and ")

    table = [(0, 0), (1, 0), (1, 1), (0, 1)]
    for phase, (expected_dx, expected_dy) in enumerate(table):
        env = {"phase": phase}
        dx = 1 if eval(_as_python(dx_match.group("cond")), {}, env) else 0  # noqa: S307
        dy = 1 if eval(_as_python(dy_match.group("cond")), {}, env) else 0  # noqa: S307
        assert (dx, dy) == (expected_dx, expected_dy), (
            f"phase {phase}: got ({dx}, {dy}), expected ({expected_dx}, {expected_dy})"
        )


# --------------------------------------------------------------------------
# a real `monkeyc` build: warning-free with the mask on


@pytest.mark.slow
def test_mask_compiles_warning_free_on_a_mixed_build(write_design, db, tmp_path, toolchain):
    """The real `monkeyc` build, not just Python-level codegen -- the same
    "a Python test alone cannot see a missing barrel file" lesson
    `docs/lore/codegen.md` records for `WfbColor.mc` applies here too."""
    text = MIXED_BASE + _ONE_SHOWN_CLOCK
    bag = Bag()
    result = real_build(write_design(text), output=tmp_path, bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    warnings = [d for d in bag.items if d.severity.value == "warning"]
    assert not warnings, "\n".join(d.message for d in warnings)
