"""ADR 0008 checks, and the confidence each one is allowed to claim."""

import pytest

from tests.test_diagnostics import load
from wfb import lint
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve

BASE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
{palette}
elements:
  - id: background
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.bg
{extra}
"""


@pytest.fixture
def check(write_design, bag, db):
    def _check(extra: str = "", palette: str = '  bg: "#000000"\n  fg: "#FFFFFF"'):
        face = load(write_design(BASE.format(palette=palette, extra=extra)), bag)
        assert face is not None, bag.render()
        device = db.get("fenix8solar47mm")
        resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
        lint.run(resolved, bag)
        return bag

    return _check


def codes(bag):
    return {d.code for d in bag.items}


# -- check 3 ---------------------------------------------------------------


def test_a_dithered_colour_warns_with_the_nearest_legal_one(check):
    bag = check(palette='  bg: "#000000"\n  fg: "#123456"')
    warning = next(d for d in bag.items if d.code == "palette-dither")
    assert "dither" in warning.message
    assert any("#005555" in note or "nearest" in note for note in warning.notes)
    assert "exact" in warning.confidence


def test_a_legal_palette_is_silent(check):
    assert "palette-dither" not in codes(check())


# -- check 4 ---------------------------------------------------------------


def test_a_full_bleed_background_is_not_flagged(check):
    """It is *meant* to run under the bezel; warning on every build is noise."""
    bag = check()
    assert "safe-area" not in codes(bag)
    assert "off-screen" not in codes(bag)


def test_an_element_off_the_framebuffer_is_an_error(check):
    bag = check("""
  - id: stray
    type: shape
    shape: circle
    at: {anchor: center, dx: 200%}
    radius: 10px
    color: palette.fg
""")
    assert "off-screen" in {d.code for d in bag.errors}


def test_an_element_under_the_bezel_warns(check):
    bag = check("""
  - id: corner
    type: shape
    shape: circle
    at: {anchor: top_left, dx: 6px, dy: 6px}
    radius: 5px
    color: palette.fg
""")
    assert "safe-area" in codes(bag)


def test_suppression_needs_a_reason_and_then_silences(check):
    bag = check("""
  - id: corner
    type: shape
    shape: circle
    at: {anchor: top_left, dx: 6px, dy: 6px}
    radius: 5px
    color: palette.fg
    lint:
      allow: [safe-area]
      reason: "deliberately tucked behind the bezel"
""")
    assert "safe-area" not in codes(bag)


# -- check 6 ---------------------------------------------------------------


def test_a_glyph_missing_from_a_subsetted_font_is_an_error(write_design, bag, db, repo_root):
    ttf = repo_root / "examples/slice/assets/OpenSans-Regular.ttf"
    design = f"""
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  fg: "#FFFFFF"
fonts:
  clock:
    source: {ttf}
    size: 40
    glyphs: "0123456789"
elements:
  - id: clock
    type: text
    value: time.clock
    format: "{{:%H:%M}}"
    font: font.clock
    at: {{anchor: center}}
    color: palette.fg
"""
    face = load(write_design(design), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    lint.run(resolved, bag)
    missing = next(d for d in bag.errors if d.code == "missing-glyph")
    assert "':'" in missing.message
    assert "exact" in missing.confidence


# -- check 10 --------------------------------------------------------------


def test_low_contrast_warns_and_labels_the_threshold_as_a_judgement(check):
    bag = check(
        """
  - id: label
    type: text
    text: "hi"
    at: {anchor: center}
    color: palette.dim
""",
        palette='  bg: "#000000"\n  fg: "#FFFFFF"\n  dim: "#555555"',
    )
    warning = next(d for d in bag.items if d.code == "contrast")
    assert "judgement call" in warning.confidence


# -- check 9 ---------------------------------------------------------------


def test_the_power_budget_check_says_it_is_a_heuristic(check):
    """Garmin does not publish the number, so the message must not imply one."""
    bag = check("""
  - id: wide
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 90%, height: 60%}
    color: palette.fg
    modes: [active, low_power]
""")
    warning = next(d for d in bag.items if d.code == "partial-update-budget")
    assert "HEURISTIC" in warning.confidence
    assert "onPowerBudgetExceeded" in " ".join(warning.notes)


def test_a_tight_low_power_clip_does_not_warn(check):
    bag = check("""
  - id: small
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 20%, height: 10%}
    color: palette.fg
    modes: [active, low_power]
""")
    assert "partial-update-budget" not in codes(bag)


# -- check 7 ---------------------------------------------------------------


BUILD_STATS = """
Build Stats:
  Device: fenix8solar47mm
  Data:
    Foreground: 879 bytes
  Code:
    Foreground: 1982 bytes
  Total PRG Size: 96748 bytes
BUILD SUCCESSFUL
"""


def test_memory_is_measured_and_says_so(device, bag):
    stats = lint.check_memory(device, BUILD_STATS, bag)
    assert stats == {"data": 879, "code": 1982, "total": 2861, "limit": 131072, "prg": 96748}
    diag = next(d for d in bag.items if d.code == "memory")
    assert diag.confidence == "measured"
    assert "not measured here" in " ".join(diag.notes)


def test_memory_over_the_limit_is_an_error(device, bag):
    over = BUILD_STATS.replace("1982 bytes", "200000 bytes")
    lint.check_memory(device, over, bag)
    assert any(d.code == "memory" for d in bag.errors)


def test_unparseable_build_output_returns_nothing_rather_than_guessing(device, bag):
    assert lint.check_memory(device, "BUILD SUCCESSFUL", bag) is None
    assert not bag.items


# -- permissions ------------------------------------------------------------


def test_a_permission_a_watch_face_cannot_hold_is_an_error(write_design, bag, monkeypatch):
    """`monkeyc` rejects the manifest, but never names the binding responsible.

    Since this compiler *derives* the permission set, the author has no line to
    look at unless the check points at the source that implied it.
    """
    from wfb import catalog

    monkeypatch.setitem(
        catalog.CATALOG,
        "hr.raw",
        catalog.Source(
            path="hr.raw", type=catalog.Type.NUMBER, reader="activity_info",
            field_name="currentHeartRate", nullable=True, tier=catalog.Tier.FRAME,
            permissions=("Sensor",),
        ),
    )
    face = load(write_design(BASE.format(
        palette='  bg: "#000000"\n  fg: "#FFFFFF"',
        extra="""
  - id: hr
    type: text
    value: hr.raw
    format: "{:d}"
    at: {anchor: center}
    color: palette.fg
    when_absent: hide
""")), bag)
    assert face is not None, bag.render()
    lint.check_permissions(face, bag)
    diag = next(d for d in bag.errors if d.code == "permission")
    assert "Sensor" in diag.message
    assert "hr" in diag.message
    assert "exact" in diag.confidence


def test_the_permissions_a_watch_face_may_hold_match_the_sdk_table(bag):
    from wfb import catalog

    assert catalog.WATCHFACE_PERMISSIONS == {
        "Background", "Communications", "ComplicationSubscriber",
        "Positioning", "UserProfile",
    }


def test_heart_rate_needs_no_permission():
    """Read off Activity.getActivityInfo(), which is absent from the table.

    Toybox.Sensor would need a permission a watch face may not declare -- which
    is exactly why the catalogue does not route heart rate through it.
    """
    from wfb import catalog

    assert catalog.get("heart_rate.current").permissions == ()
