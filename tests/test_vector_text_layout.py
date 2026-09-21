"""Vector fonts and `curve:` (plan 11 slice 1) -- step 2: per-device face
resolution (gates 1-3), the `if_unavailable:` policy (including the
cross-device `error`/`hide` aggregate in `wfb.lint.check_vector_font_
availability`, wired into `wfb.build.resolve_all`), and the angled/radial
lint boxes.  `tests/test_vector_fonts.py` covers step 1 (the IR alone) and
is not repeated here.

Real installed devices throughout, per the task brief: `fenix8solar47mm`/
`fr955` HAVE vector fonts, `fenix6`/`fr245`/`fr255` do not.

**Why `resolve_all`'s own font baking is stubbed out** (`_stub_baking`):
`wfb.emit.resources.bake_fonts` iterates every `face.fonts` entry and calls
`bake(spec.source, ...)` unconditionally -- for a `face:` (vector) `FontSpec`
`spec.source` is `None`, so a real, unmodified `wfb build` of any design
with a vector font fails today with a confusing `cannot open resource`
`font` error, before layout or this step's own lint ever run. That is a
pre-existing gap in `wfb/emit/resources.py` (font baking -- codegen, a
later slice, plan 11 §5), not something this step introduces or is asked to
fix -- so these tests monkeypatch `bake_fonts` to skip baking (an empty
`dict`, exactly the "resolved layout with no baked fonts" shape `wfb.layout.
Resolver._unbaked_font_size` already documents as a normal caller) purely to
exercise `wfb.build.resolve_all`'s own per-device loop and the new
cross-device check wired into it, without tripping over that unrelated bug.
"""

from __future__ import annotations

import math

import pytest

from wfb import build, lint
from wfb.layout import PlacedText, arc_bbox, resolve

# -- design templates ---------------------------------------------------------

_SINGLE_FONT = """\
  bezel:
    face: RobotoCondensedBold
    size: 6%r
"""

_CANDIDATE_FONT = """\
  bezel:
    face: [NotARealFace, RobotoCondensedBold]
    size: 6%r
"""

_UNPUBLISHED_FONT = """\
  bezel:
    face: NotARealFace
    size: 6%r
"""

_HIDE_FONT = """\
  bezel:
    face: RobotoCondensedBold
    size: 6%r
    if_unavailable: hide
"""


def _design(fonts: str, elements: str, *, targets: str = "[fenix8solar47mm]") -> str:
    return f"""
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}}
targets: {targets}
palette: {{bg: "#000000", fg: "#FFFFFF"}}
fonts:
{fonts}
elements:
{elements}"""


def _text(element_id: str, extra: str = "", *, font: str = "font.bezel") -> str:
    return f"""\
  - id: {element_id}
    type: text
    text: "GARMIN"
    color: palette.fg
    at: {{anchor: center}}
    font: {font}
{extra}"""


def _placed(resolved, element_id: str) -> PlacedText:
    for p in resolved.items:
        if p.id == element_id:
            assert isinstance(p, PlacedText), f"{element_id} is a {type(p)}, not PlacedText"
            return p
    raise AssertionError(f"{element_id!r} was not placed")


def _stub_baking(monkeypatch) -> None:
    """See the module docstring: sidesteps the unrelated `bake_fonts` bug so
    `wfb.build.resolve_all` can be exercised end to end for its own per-device
    loop and cross-device check."""
    monkeypatch.setattr("wfb.emit.resources.bake_fonts", lambda face, device: {})


def _load(write_design, bag, design: str):
    face = build.load(write_design(design), bag)
    assert face is not None, bag.render()
    return face


# -- face resolution (gates 1-3), per device -----------------------------------


def test_vector_face_resolves_to_the_first_published_candidate(write_design, bag, db):
    """`face: [NotARealFace, RobotoCondensedBold]` -- the first candidate is
    never published by any device, so this only passes if resolution really
    walks the list in author order rather than, say, always taking the
    first entry regardless (plan 11 §2.1)."""
    face = _load(write_design, bag, _design(_CANDIDATE_FONT, _text("brand")))
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})
    placed = _placed(resolved, "brand")
    assert placed.font_is_vector is True
    assert placed.font_available is True
    assert placed.font_face == "RobotoCondensedBold"


def test_vector_face_unavailable_on_a_gate1_device(write_design, bag, db):
    """fenix6 has no `Graphics.getVectorFont` at all -- gate 1 fails before
    the candidate list is even consulted."""
    face = _load(write_design, bag, _design(_SINGLE_FONT, _text("brand")))
    device = db.get("fenix6")
    resolved = resolve(face, device, {})
    placed = _placed(resolved, "brand")
    assert placed.font_is_vector is True
    assert placed.font_available is False
    assert placed.font_face == ""


def test_vector_face_unavailable_when_no_candidate_is_published(write_design, bag, db):
    """fenix8solar47mm passes gate 1, but publishes no face named
    'NotARealFace' -- a gate 2/3 failure, distinct from gate 1's."""
    face = _load(write_design, bag, _design(_UNPUBLISHED_FONT, _text("brand")))
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})
    placed = _placed(resolved, "brand")
    assert placed.font_available is False
    assert placed.font_face == ""


def test_gate1_alone_blocks_resolution_even_when_the_face_is_published(write_design, bag, db):
    """Isolates gate 1 from gates 2/3: on every currently installed device
    the three move together (a device either has none of `getVectorFont`/
    `scalable_faces` or all of them), so `font_available` alone cannot tell
    "gate 1 failed" apart from "gates 2/3 failed" using only real devices --
    both give the same `False`. This constructs the case no installed
    device can: fenix6's own symbol table (genuinely missing
    `Graphics.getVectorFont`, `has_symbol` unmodified) paired with a
    `scalable_faces` that -- if gate 1 were skipped -- would resolve just
    fine, so a resolution that still fails here proves gate 1 is checked on
    its own, not merely inferred from gates 2/3 happening to agree."""
    from wfb.devices import Device

    face = _load(write_design, bag, _design(_SINGLE_FONT, _text("brand")))
    fenix6 = db.get("fenix6")
    assert fenix6.has_symbol(Device.VECTOR_FONT_SYMBOL) is False
    patched = Device(id=fenix6.id, root=fenix6.root, compiler=fenix6.compiler,
                     simulator=fenix6.simulator)
    patched.scalable_faces = ("RobotoCondensedBold",)
    assert patched.has_symbol(Device.VECTOR_FONT_SYMBOL) is False

    resolved = resolve(face, patched, {})
    placed = _placed(resolved, "brand")
    assert placed.font_available is False
    assert placed.font_face == ""


def test_baked_font_text_is_never_marked_vector(write_design, bag, db, repo_root):
    """Contrast against the vector-font tests above: an ordinary baked font
    must not be swept up by the same flags."""
    source = repo_root / "tests" / "fixtures" / "slice" / "assets" / "OpenSans-Regular.ttf"
    design = _design(
        f"  clock:\n    source: {source}\n    size: 18%r\n",
        _text("brand", font="font.clock"),
    )
    face = _load(write_design, bag, design)
    device = db.get("fenix8solar47mm")
    from wfb.emit.resources import bake_fonts
    resolved = resolve(face, device, bake_fonts(face, device))
    placed = _placed(resolved, "brand")
    assert placed.font_is_vector is False
    assert placed.font_available is True
    assert placed.font_face == ""


# -- gate-1 vs gate-2/3 failure reasons ----------------------------------------


def test_error_mode_gate1_failure_names_the_missing_symbol(write_design, bag, db, monkeypatch):
    face = _load(write_design, bag, _design(_SINGLE_FONT, _text("brand"), targets="[fenix6]"))
    devices = build.select_devices(face, db, bag)
    _stub_baking(monkeypatch)
    build.resolve_all(face, devices, bag)
    assert not bag.ok()
    errors = [d for d in bag.errors if d.code == "font-unavailable"]
    assert errors, bag.render()
    text = " ".join(errors[0].notes)
    assert "gate 1" in text
    assert "getVectorFont" in text
    assert "gates 2/3" not in text


def test_error_mode_gate23_failure_names_the_unpublished_face(write_design, bag, db, monkeypatch):
    face = _load(
        write_design, bag,
        _design(_UNPUBLISHED_FONT, _text("brand"), targets="[fenix8solar47mm]"),
    )
    devices = build.select_devices(face, db, bag)
    _stub_baking(monkeypatch)
    build.resolve_all(face, devices, bag)
    assert not bag.ok()
    errors = [d for d in bag.errors if d.code == "font-unavailable"]
    assert errors, bag.render()
    text = " ".join(errors[0].notes)
    assert "gates 2/3" in text
    assert "publishes" in text
    assert "gate 1" not in text


# -- error fails the build, hide does not --------------------------------------


def test_if_unavailable_error_fails_the_build_when_any_target_lacks_the_face(
    write_design, bag, db, monkeypatch,
):
    face = _load(
        write_design, bag,
        _design(_SINGLE_FONT, _text("brand"), targets="[fenix8solar47mm, fenix6]"),
    )
    devices = build.select_devices(face, db, bag)
    _stub_baking(monkeypatch)
    build.resolve_all(face, devices, bag)
    assert not bag.ok()
    assert any(d.code == "font-unavailable" for d in bag.errors)


def test_if_unavailable_hide_does_not_fail_the_build(write_design, bag, db, monkeypatch):
    face = _load(
        write_design, bag,
        _design(_HIDE_FONT, _text("brand"), targets="[fenix8solar47mm, fenix6]"),
    )
    devices = build.select_devices(face, db, bag)
    _stub_baking(monkeypatch)
    build.resolve_all(face, devices, bag)
    assert bag.ok(), bag.render()
    assert any(d.code == "font-unavailable" for d in bag.items)


def test_hide_warning_names_every_unavailable_device_and_not_the_available_one(
    write_design, bag, db, monkeypatch,
):
    face = _load(
        write_design, bag,
        _design(_HIDE_FONT, _text("brand"), targets="[fenix8solar47mm, fenix6, fr245]"),
    )
    devices = build.select_devices(face, db, bag)
    _stub_baking(monkeypatch)
    build.resolve_all(face, devices, bag)
    assert bag.ok(), bag.render()
    warnings = [d for d in bag.items if d.code == "font-unavailable"]
    assert len(warnings) == 1, bag.render()  # one aggregate warning, not one per device
    msg = warnings[0].message
    assert "fenix6" in msg
    assert "fr245" in msg
    assert "fenix8solar47mm" not in msg


def test_hide_warning_is_suppressible(write_design, bag, db, monkeypatch):
    element = _text("brand", "    lint: {allow: [font-unavailable], reason: known gap}\n")
    face = _load(
        write_design, bag,
        _design(_HIDE_FONT, element, targets="[fenix8solar47mm, fenix6]"),
    )
    devices = build.select_devices(face, db, bag)
    _stub_baking(monkeypatch)
    build.resolve_all(face, devices, bag)
    assert bag.ok(), bag.render()
    assert not any(d.code == "font-unavailable" for d in bag.items)


# -- element overrides the font's own if_unavailable ---------------------------


def test_element_if_unavailable_error_overrides_the_fonts_own_hide(
    write_design, bag, db, monkeypatch,
):
    element = _text("brand", "    if_unavailable: error\n")
    face = _load(
        write_design, bag,
        _design(_HIDE_FONT, element, targets="[fenix8solar47mm, fenix6]"),
    )
    devices = build.select_devices(face, db, bag)
    _stub_baking(monkeypatch)
    build.resolve_all(face, devices, bag)
    assert not bag.ok(), "the element's own 'error' must win over the font's 'hide'"
    assert any(d.code == "font-unavailable" for d in bag.errors)


def test_element_if_unavailable_hide_overrides_the_fonts_own_error(
    write_design, bag, db, monkeypatch,
):
    element = _text("brand", "    if_unavailable: hide\n")
    face = _load(
        write_design, bag,
        _design(_SINGLE_FONT, element, targets="[fenix8solar47mm, fenix6]"),
    )
    devices = build.select_devices(face, db, bag)
    _stub_baking(monkeypatch)
    build.resolve_all(face, devices, bag)
    assert bag.ok(), "the element's own 'hide' must win over the font's default 'error'"
    assert any(d.code == "font-unavailable" for d in bag.items)


# -- angled / radial boxes ------------------------------------------------------


def test_angled_box_is_the_rotated_bounding_box(write_design, bag, db):
    """`angled`'s `angle:` is a rotation from upright (0 = level), not a
    position, so `0deg` alone would draw the *unrotated* box and could not
    prove anything got rotated at all. `angle: 90deg` is a full quarter
    turn instead (`wfb.layout.garmin_curve_angle`: `(-90) % 360 == 270`),
    so the rotated box's width/height are the *upright* box's height/width,
    swapped -- proving the box is actually rotated, not a no-op copy of the
    unrotated one (CLAUDE.md §7: a test must exercise the contrast it
    claims)."""
    elements = (
        _text("upright") + "\n"
        + _text("angled", "    curve: {style: angled, angle: 90deg}\n")
    )
    face = _load(write_design, bag, _design(_SINGLE_FONT, elements))
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})
    upright = _placed(resolved, "upright")
    angled = _placed(resolved, "angled")

    assert angled.curve_style == "angled"
    assert angled.curve_angle_degrees == pytest.approx(90.0)
    assert angled.curve_angle_garmin == pytest.approx(270.0)
    assert upright.box.width > upright.box.height, (
        "the fixture assumes 'GARMIN' measures wider than one line is tall"
    )
    assert abs(angled.box.width - upright.box.height) <= 1
    assert abs(angled.box.height - upright.box.width) <= 1


def test_radial_box_is_a_tight_arc_not_the_old_square(write_design, bag, db):
    """2026-09-21 follow-up to plan 11 §4: the old box was a SQUARE, centre
    +/- (radius + line_height) -- on a round screen its corners sit at
    (radius + line_height) * sqrt(2) from centre, comfortably outside the
    panel even when the run itself sits nowhere near the edge (the false
    positive on `examples/features/vector-text/face.yaml`'s `wordmark`/
    `left_cw`/`top_ccw`/`top_cw`, confirmed not to overflow on the real
    simulator: `docs/research/probes/vector-fonts/
    radial-facing-both-directions.png`). The fix bounds the annulus sector
    the run actually sweeps (`radial_text_angle_span` + `arc_bbox`), which
    must be strictly smaller in area than that square for an ordinary
    (sub-360-degree) run -- CLAUDE.md §7: a test must exercise the contrast
    it claims, not just re-assert whatever the code already does."""
    element = _text("radial", "    curve: {style: radial, angle: 0deg, radius: 40%r}\n")
    face = _load(write_design, bag, _design(_SINGLE_FONT, element))
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})
    placed = _placed(resolved, "radial")

    assert placed.curve_style == "radial"
    assert placed.curve_direction == "clockwise"
    expected_radius = round(0.40 * device.minor_radius)
    assert placed.curve_radius_px == expected_radius

    # A synthetic vector-font `FontMetric` never carries `height_px`, so
    # `wfb.fonts.fallback.line_height` falls back to `metric.size_px` --
    # which is exactly `font_px` (`Resolver._vector_font_metric`).
    old_reach = expected_radius + placed.font_px
    old_square_area = (2 * old_reach) ** 2
    new_area = placed.box.width * placed.box.height
    assert new_area < old_square_area, (
        "the tight arc box must be smaller than the square it replaced"
    )
    # And it must still be centred on the circle's own centre, radially
    # bounded by radius -/+ line_height (font_px, per the note above) --
    # never reaching all the way out to the old square's full reach on
    # every side at once.
    cx, cy = placed.center
    assert placed.box.x > cx - old_reach or placed.box.y > cy - old_reach


def test_radial_text_that_genuinely_overflows_still_warns(write_design, bag, db):
    """The tight arc box must never UNDER-report: a radial run whose own
    radius already sits right at the bezel margin, further widened by the
    +line_height ink band, must still trip 'safe-area' -- proving the fix
    tightened the box rather than quietly turning the check off
    (CLAUDE.md §7)."""
    element = _text("radial", "    curve: {style: radial, angle: 0deg, radius: 93%r}\n")
    face = _load(write_design, bag, _design(_SINGLE_FONT, element))
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})
    lint.check_geometry(resolved, bag)
    assert any(d.code == "safe-area" for d in bag.items), (
        "a radial run this close to the bezel must still warn"
    )


# -- arc_bbox: the shared annulus-sector bounding box ----------------------


def test_arc_bbox_axis_crossing_finds_the_true_extreme_not_just_the_corners():
    """The classic arc-bbox bug: a sector that sweeps through 90 Garmin
    degrees (screen convention `py = cy - r*sin(theta)`, so this is the
    point directly ABOVE centre) has its topmost point mid-sweep, at
    neither of its two corners (45/135 degrees). Using only the four
    corner points would put the box's top at `r_outer * cos(45deg) ~=
    7.07`, not the true `r_outer == 10` -- a real under-report, which is
    exactly the "missing the axis-extreme point" failure mode plan 11's
    follow-up calls out."""
    box = arc_bbox(0.0, 0.0, 5.0, 10.0, 45.0, 135.0)
    half_diag_outer = 10.0 * math.sqrt(2.0) / 2.0
    half_diag_inner = 5.0 * math.sqrt(2.0) / 2.0
    assert box.y == pytest.approx(-10.0)          # the axis-crossing extreme, not a corner
    assert box.x == pytest.approx(-half_diag_outer)      # x-extent still comes from the corners
    assert box.x + box.width == pytest.approx(half_diag_outer)
    # The bottom edge comes from the two INNER corners (both sit closer to
    # centre in y than the axis extreme is), not the outer ones -- the two
    # 45-degree corners of the outer radius are further "up" (more negative
    # y) than the inner ones, so they never set the box's bottom.
    assert box.y + box.height == pytest.approx(-half_diag_inner)


def test_arc_bbox_with_no_axis_crossing_uses_only_the_corners():
    """The contrast case for the test above: a sector entirely inside one
    quadrant (10-30 degrees) never reaches any of the four axis-aligned
    extremes, so the box is exactly the four corner points -- proving the
    axis-crossing logic is conditional, not "always add all four."""
    box = arc_bbox(0.0, 0.0, 5.0, 10.0, 10.0, 30.0)
    xs, ys = [], []
    for theta_deg in (10.0, 30.0):
        theta = math.radians(theta_deg)
        for r in (5.0, 10.0):
            xs.append(r * math.cos(theta))
            ys.append(-r * math.sin(theta))
    assert box.x == pytest.approx(min(xs))
    assert box.y == pytest.approx(min(ys))
    assert box.x + box.width == pytest.approx(max(xs))
    assert box.y + box.height == pytest.approx(max(ys))


def test_arc_bbox_full_turn_is_the_whole_annulus():
    box = arc_bbox(0.0, 0.0, 5.0, 10.0, 0.0, 360.0)
    assert box.x == pytest.approx(-10.0)
    assert box.y == pytest.approx(-10.0)
    assert box.x + box.width == pytest.approx(10.0)
    assert box.y + box.height == pytest.approx(10.0)


def test_upright_vector_font_text_measures_like_any_other_estimated_text(write_design, bag, db):
    """A `face:` font with no `curve:` at all must still work -- plain
    `Dc.drawText`, measured the same estimated way a system font already is."""
    face = _load(write_design, bag, _design(_SINGLE_FONT, _text("brand")))
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, {})
    placed = _placed(resolved, "brand")
    assert placed.curve_style is None
    assert placed.font_is_vector is True
    assert placed.font_available is True
    assert placed.width_is_estimated is True
    assert placed.measured_width > 0
    assert placed.box.width > 0 and placed.box.height > 0
