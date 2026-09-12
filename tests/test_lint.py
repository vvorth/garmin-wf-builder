"""ADR 0008 checks, and the confidence each one is allowed to claim."""

import re

import pytest

from tests.test_diagnostics import load
from wfb import build, lint
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


def test_a_dithered_colour_names_an_unused_entry_as_unsuppressible(check):
    """The note must not claim a suppression mechanism that does not exist.

    Nothing in this design uses palette.fg, so there is nowhere to hang
    'lint: {allow: [palette-dither]}' -- the note has to say that honestly
    rather than repeat instructions that would silently do nothing (Bug 1).
    """
    bag = check(palette='  bg: "#000000"\n  fg: "#123456"')
    warning = next(d for d in bag.items if d.code == "palette-dither")
    assert any("nowhere to put" in note for note in warning.notes)


def test_a_dithered_colour_can_be_suppressed_on_the_element_that_uses_it(check):
    """The note this warning prints must be something that actually works.

    Before this fix, following the note's own instructions -- adding
    'lint: {allow: [palette-dither], reason: ...}' to the element that draws
    the dithered colour -- did nothing: `check_palette` warns per palette
    entry, which has no element of its own to hang a suppression on, and the
    warning bypassed `_emit`/`_suppressed` entirely.
    """
    bag = check(
        """
  - id: dot
    type: shape
    shape: circle
    at: {anchor: center}
    radius: 5px
    color: palette.fg
    lint:
      allow: [palette-dither]
      reason: "probing"
""",
        palette='  bg: "#000000"\n  fg: "#123456"',
    )
    assert "palette-dither" not in codes(bag)


def test_a_dithered_track_color_can_also_be_suppressed(check):
    """`track_color:` (Progress) is the other field check_palette must honour,
    not just `color:` -- both are named in the warning's own note."""
    bag = check(
        """
  - id: ring
    type: progress
    style: arc
    value: 5
    max: 10
    at: {anchor: center}
    radius: 40%r
    thickness: 4px
    start_angle: 0deg
    sweep: 360deg
    color: palette.bg
    track_color: palette.fg
    lint:
      allow: [palette-dither]
      reason: "probing"
""",
        palette='  bg: "#000000"\n  fg: "#123456"',
    )
    assert "palette-dither" not in codes(bag)


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


def test_the_power_budget_warning_can_be_suppressed_on_a_low_power_element(check):
    """Like palette-dither, this check is about a face-wide clip rectangle,
    not one element, so there was nowhere to hang `_emit`/`_suppressed`'s
    per-element suppression -- the check called `bag.warning` directly and
    ignored `lint: {allow: ...}` entirely, the same shape of bug as Bug 1's
    palette-dither case, on the other check `SUPPRESSIBLE` already claimed
    could be silenced.
    """
    bag = check("""
  - id: wide
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 90%, height: 60%}
    color: palette.fg
    modes: [active, low_power]
    lint:
      allow: [partial-update-budget]
      reason: "probing"
""")
    assert "partial-update-budget" not in codes(bag)


def test_no_low_power_elements_means_no_partial_update_diagnostics(check):
    bag = check()  # BASE's own background is `active` only
    assert "partial-update-budget" not in codes(bag)
    assert "partial-update" not in codes(bag)


def test_a_small_weather_binding_in_low_power_warns_even_with_a_tiny_clip(check):
    """Bug 2: gating the whole check on `fraction > 0.25` misses the case its
    own notes claim it covers -- a small low-power element that reads
    `Weather.getCurrentConditions()`/a `Complications` lookup every second.
    Before this trigger existed, this exact design linted clean (see the
    orchestrator's session notes: reproduced with `old_check`, a stand-in for
    the pre-fix clip-fraction-only body, which emits nothing here).
    """
    bag = check("""
  - id: temp
    type: text
    value: weather.temperature
    format: "{:d}"
    when_absent: hide
    at: {anchor: center}
    modes: [active, low_power]
    color: palette.fg
""")
    warning = next(d for d in bag.items if d.code == "partial-update-budget")
    assert "temp" in warning.message
    assert "weather.temperature" in warning.message
    assert "HEURISTIC" in warning.confidence


def test_the_expensive_source_warning_names_the_element_and_can_be_suppressed(check):
    bag = check("""
  - id: temp
    type: text
    value: weather.temperature
    format: "{:d}"
    when_absent: hide
    at: {anchor: center}
    modes: [active, low_power]
    color: palette.fg
    lint:
      allow: [partial-update-budget]
      reason: "known and accepted"
""")
    assert "partial-update-budget" not in codes(bag)


def test_a_low_power_graph_element_warns_regardless_of_clip_size(check):
    bag = check("""
  - id: hr_graph
    type: graph
    series: heart_rate
    range: 1h
    style: line
    thickness: 2px
    color: palette.fg
    at: {anchor: center}
    size: {width: 20%, height: 10%}
    modes: [active, low_power]
""")
    warning = next(d for d in bag.items if d.code == "partial-update-budget")
    assert "hr_graph" in warning.message
    assert "graph" in warning.message


def test_clip_fraction_and_expensive_source_do_not_both_fire(check):
    """One diagnostic per face: once the clip-fraction branch has already
    fired for a face, an expensive-source element sharing that same clip
    must not also get the per-source warning."""
    bag = check("""
  - id: wide
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 90%, height: 60%}
    color: palette.fg
    modes: [active, low_power]
  - id: temp
    type: text
    value: weather.temperature
    format: "{:d}"
    when_absent: hide
    at: {anchor: center}
    modes: [active, low_power]
    color: palette.fg
""")
    warnings = [d for d in bag.items if d.code == "partial-update-budget"]
    assert len(warnings) == 1
    assert "clip" in warnings[0].message


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
            field_name="currentHeartRate", nullable=True,
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


# -- lint: allow -------------------------------------------------------------

#: One element carrying a `lint:` block, appended to BASE the same way the
#: geometry checks above append 'corner'.  The code under test varies.
_ALLOW_ELEMENT = """
  - id: corner
    type: shape
    shape: circle
    at: {{anchor: top_left, dx: 6px, dy: 6px}}
    radius: 5px
    color: palette.fg
    lint:
      allow: [{code}]
      reason: "{reason}"
"""


def _face_allowing(write_design, bag, code: str, reason: str = "probing"):
    face = load(write_design(BASE.format(
        palette='  bg: "#000000"\n  fg: "#FFFFFF"',
        extra=_ALLOW_ELEMENT.format(code=code, reason=reason),
    )), bag)
    assert face is not None, bag.render()
    return face


def test_an_unknown_lint_code_is_reported_with_a_suggestion(write_design, bag):
    """A typo in 'allow:' used to do nothing at all (Bug 2) -- the warning it
    was meant to silence just kept firing, with no sign of whether the code
    was misspelled or the check refuses suppression on purpose.
    """
    face = _face_allowing(write_design, bag, "safearea")
    lint.check_lint_allow(face, bag)
    diag = next(d for d in bag.errors if d.code == "lint-allow")
    assert "'safearea'" in diag.message
    assert "not a diagnostic code" in diag.message
    assert any("safe-area" in note for note in diag.notes)


def test_an_unknown_lint_code_is_never_offered_a_misleading_suggestion(write_design, bag):
    """A near-miss suggestion has to be *right*, not merely close.

    'overlap' is the case that pins this down. An earlier draft of the check
    suggested 'text-overflow' for it at a looser cutoff, which is a different
    check entirely and would have sent the author somewhere useless. Since
    then `tap-overlap` has been built, so a suggestion *is* now available and
    is a genuinely good one -- what must never come back is a suggestion that
    is not a real code, or the misleading 'text-overflow' match.
    """
    face = _face_allowing(write_design, bag, "overlap")
    lint.check_lint_allow(face, bag)
    diag = next(d for d in bag.errors if d.code == "lint-allow")
    assert "'overlap'" in diag.message
    suggestions = [n for n in diag.notes if "did you mean" in n]
    assert not any("text-overflow" in n for n in suggestions), suggestions
    for note in suggestions:
        named = note.split("did you mean")[-1].strip().rstrip("?").lstrip(":").strip()
        for part in named.split(","):
            assert part.strip().strip("'\"") in lint.ALL_CODES, note


def test_a_real_but_unsuppressible_code_is_reported_with_the_reason(write_design, bag):
    """`off-screen` is a real code that fires all the time -- but SUPPRESSIBLE
    excludes it on purpose, because silencing a hard platform limit produces a
    face that does not work.  'allow: [off-screen]' must be refused with that
    reason stated, not treated as a plain typo.
    """
    face = _face_allowing(write_design, bag, "off-screen")
    lint.check_lint_allow(face, bag)
    diag = next(d for d in bag.errors if d.code == "lint-allow")
    assert "not" in diag.message and "suppressible" in diag.message
    assert any("does not work" in note for note in diag.notes)
    assert not any("did you mean" in note for note in diag.notes)


def test_a_suppressible_code_used_correctly_raises_nothing(write_design, bag):
    face = _face_allowing(write_design, bag, "safe-area")
    lint.check_lint_allow(face, bag)
    assert "lint-allow" not in codes(bag)


def test_lint_allow_runs_once_per_build_regardless_of_target_count(write_design, db):
    """Device-independent, like check_permissions -- `resolve_all` must call it
    exactly once, or a single typo would be reported once per target device
    instead of once against the author's one line of YAML.
    """
    from wfb.diagnostics import Bag

    design = BASE.format(
        palette='  bg: "#000000"\n  fg: "#FFFFFF"',
        extra=_ALLOW_ELEMENT.format(code="safearea", reason="typo for safe-area"),
    ).replace(
        "targets: [fenix8solar47mm]",
        "targets: [fenix8solar47mm, fenix8solar51mm, fr955]",
    )
    bag = Bag()
    face = build.load(write_design(design), bag)
    assert face is not None, bag.render()
    devices = build.select_devices(face, db, bag)
    assert len(devices) == 3
    build.resolve_all(face, devices, bag)
    assert sum(1 for d in bag.items if d.code == "lint-allow") == 1


# -- the diagnostic-code registry ---------------------------------------------

#: Matches the code literal in `bag.error("code", ...)` / `.warning(...)` /
#: `.note(...)`, across all of `self.bag` and a plain `bag`.
_BAG_CALL_RE = re.compile(r'(?:bag|self\.bag)\.(?:error|warning|note)\(\s*"([a-zA-Z0-9_-]+)"')
#: Same call shape, but the code is `<expr> or "fallback"` rather than a bare
#: literal -- `wfb/ir.py`'s `_expression` forwards `expr.ExprError.code` when
#: the raiser set one and falls back to a literal default otherwise
#: (`exc.code or "expression"`). Still finds the literal fallback.
_BAG_CALL_FALLBACK_RE = re.compile(
    r'(?:bag|self\.bag)\.(?:error|warning|note)\(\s*[\w.]+\s+or\s+"([a-zA-Z0-9_-]+)"'
)
#: Matches the code literal in a directly-constructed `Diagnostic(Severity.X, "code", ...)`
#: -- `check_geometry`, `check_text_fit` and `check_contrast` build these to pass
#: through `_emit` rather than call `bag.*` directly.
_DIAGNOSTIC_RE = re.compile(r'Diagnostic\(\s*Severity\.\w+,\s*"([a-zA-Z0-9_-]+)"')
#: Matches a code carried on an `expr.ExprError` (e.g. `source-renamed`,
#: raised in `wfb/expr.py` for a moved catalogue path) -- it never calls
#: `bag.error` itself, `wfb/ir.py`'s `_expression` does that once it catches
#: the exception, forwarding `exc.code` (see `_BAG_CALL_FALLBACK_RE` above),
#: so this is the only place the literal actually appears in source.
_EXPR_ERROR_CODE_RE = re.compile(r'code="([a-zA-Z0-9_-]+)"')


def test_all_codes_registry_matches_every_code_the_compiler_actually_emits(repo_root):
    """`lint.ALL_CODES` is what lets `check_lint_allow` tell a misspelled code
    apart from a real one that is simply not suppressible (Bug 2) -- so it
    must itself stay honest about what this compiler emits.  Rather than trust
    a hand-maintained list not to drift, this re-runs the same grep it was
    built from and fails the day a new `bag.error/warning/note` or
    `Diagnostic(...)` call introduces a code nobody registered.
    """
    found: set[str] = set()
    for path in (repo_root / "wfb").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        found.update(_BAG_CALL_RE.findall(text))
        found.update(_BAG_CALL_FALLBACK_RE.findall(text))
        found.update(_DIAGNOSTIC_RE.findall(text))
        found.update(_EXPR_ERROR_CODE_RE.findall(text))
    assert found == lint.ALL_CODES, (
        f"missing from ALL_CODES: {found - lint.ALL_CODES}; "
        f"registered but never emitted: {lint.ALL_CODES - found}"
    )


def test_every_target_delivers_a_hold_so_nothing_is_reported(write_design, bag, db):
    """The regression this pins down is a *removed* diagnostic.

    Until `docs/research/07-carousel-interaction.md`, `fr955` drew a note
    saying its targets "are reached by touch and hold instead" -- true, and
    actively misleading, because it implied the fēnix 8s got taps. They do
    not: `WatchFaceDelegate.onTap` is documented "Only available in WatchFace
    config mode" and never fires during normal display, on any device. Hold is
    the only gesture, all three targets have `onPress`, so a design with an
    `on_hold:` is uniformly fine and the linter should now say nothing at all.
    """
    from tests.test_semantics import HELD, design
    from wfb.diagnostics import Bag
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    face = load(write_design(design(HELD)), bag)
    assert face is not None, bag.render()
    for device_id in ("fenix8solar47mm", "fenix8solar51mm", "fr955"):
        device = db.get(device_id)
        quiet = Bag()
        lint.run(resolve(face, device, bake_fonts(face, device, device.minor_radius)), quiet)
        assert not [d for d in quiet.items
                    if d.code in ("hold-unsupported", "hold-overlap")], quiet.render()


def test_a_device_without_onpress_is_reported_from_its_own_symbol_table(
        write_design, bag, db, monkeypatch):
    """ADR 0008's check 2, still the one place it is used for real.

    No device this project vendors lacks `onPress` -- but 100-odd Connect IQ
    products have no touchscreen at all, and for those an `on_hold:` can never
    fire. The answer has to come from the device's own api.debug.xml rather
    than an API level: `onPress` is documented since 4.2.0, and its sibling
    `onTap` is documented since 5.1.0 yet absent on `fr955` at 5.2.0, so a
    level comparison proves nothing here.
    """
    from tests.test_semantics import HELD, design
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    face = load(write_design(design(HELD)), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    baked = bake_fonts(face, device, device.minor_radius)
    resolved = resolve(face, device, baked)
    monkeypatch.setattr(type(device), "has_symbol", lambda self, symbol: False)
    lint.check_hold_targets(resolved, bag)
    hits = [d for d in bag.items if d.code == "hold-unsupported"]
    assert hits, bag.render()
    assert "onPress" in hits[0].message
    assert any("no tap to fall back to" in note for note in hits[0].notes), hits[0].notes


# -- carousel zones ---------------------------------------------------------


CAROUSEL_DESIGN = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
elements:
  - id: data
    type: carousel
    at: {anchor: center, dy: DY}
    size: {width: WIDTH, height: 22%}
    pitch: 22%r
    icon_size: 9%r
    color: palette.fg
    items:
      - value: activity.steps
        format: "{:d}"
        when_absent: hide
      - icon: battery
        value: system.battery
        format: "{:.0f}%"
      - icon: flame
        value: activity.calories
        format: "{:d}"
        when_absent: hide
"""


def _carousel(write_design, bag, db, width: str, dy: str = "0%"):
    from wfb.emit.resources import bake_fonts
    from wfb.layout import resolve

    src = CAROUSEL_DESIGN.replace("WIDTH", width).replace("DY", dy)
    face = load(write_design(src), bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device, device.minor_radius))


def test_a_generous_carousel_box_is_not_a_safe_area_warning(write_design, bag, db):
    """A carousel's box is its *touch target*, deliberately larger than what it
    paints, so `check_geometry` reads `content_box` instead.  Sizing the target
    generously must not read as a layout mistake -- the reachability question
    is asked separately, by `check_carousel_zones`."""
    resolved = _carousel(write_design, bag, db, "62%")
    lint.run(resolved, bag)
    assert not [d for d in bag.items if d.code in ("safe-area", "carousel-zone")], \
        bag.render()


def test_a_narrow_carousel_warns_that_its_zones_are_hard_to_hit(write_design, bag, db):
    """The box is split into thirds, so a narrow one gives three slivers."""
    resolved = _carousel(write_design, bag, db, "30%")
    lint.check_carousel_zones(resolved, bag)
    hits = [d for d in bag.items if d.code == "carousel-zone"]
    assert hits, bag.render()
    assert "hold zone" in hits[0].message
    assert "judgement" in (hits[0].confidence or ""), hits[0].confidence


def test_a_carousel_whose_outer_zones_are_under_the_bezel_warns(write_design, bag, db):
    """A hold can only land where the wearer can see and touch, so a zone past
    the bezel of a round screen is dead however wide it measures."""
    resolved = _carousel(write_design, bag, db, "96%", dy="30%")
    lint.check_carousel_zones(resolved, bag)
    hits = [d for d in bag.items if d.code == "carousel-zone"]
    assert hits, bag.render()
    assert "bezel" in hits[0].message
    assert hits[0].confidence.startswith("exact"), hits[0].confidence


# -- complication gating (F3) -------------------------------------------------
#
# `complication.sleep_score` -> `COMPLICATION_TYPE_SLEEP_SCORE` needs
# ConnectIQ 6.0.2 (wfb/complications.py). fenix8solar47mm/51mm sit at 6.0.2,
# fr955 tops out at 5.2.0 (CLAUDE.md's own hand-derived numbers, and
# docs/review/2026-09-architecture-review.md's F3 confirms `Device.api_level`
# reproduces them). `Device.has_symbol` cannot answer this at all --
# COMPLICATION_TYPE_* are constants, not <functionEntry> symbols, and are
# simply absent from every device's api.debug.xml (the review confirmed this
# by grep, including for COMPLICATION_TYPE_BATTERY, the one type every target
# supports unconditionally) -- so `check_complication_availability` compares
# `since` against `Device.api_level` instead.

COMPLICATION_DATA_DESIGN = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm, fenix8solar51mm, fr955]
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
  - id: score
    type: text
    value: complication.sleep_score
    format: "{:d}"
    when_absent: hide
    color: palette.fg
    at: {anchor: center}
"""

COMPLICATION_HOLD_DESIGN = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm, fenix8solar51mm, fr955]
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
  - id: hr
    type: icon
    icon: heart
    size: 14%r
    at: {anchor: center}
    color: palette.fg
    on_hold: sleep_score
"""


def _resolved_for(write_design, bag, db, src: str, device_id: str, name: str = "face.yaml"):
    face = load(write_design(src, name), bag)
    assert face is not None, bag.render()
    device = db.get(device_id)
    return resolve(face, device, bake_fonts(face, device, device.minor_radius))


def test_a_complication_above_the_devices_ceiling_warns_on_that_device(write_design, bag, db):
    resolved = _resolved_for(write_design, bag, db, COMPLICATION_DATA_DESIGN, "fr955")
    lint.check_complication_availability(resolved, bag)
    hits = [d for d in bag.items if d.code == "complication-gated"]
    assert hits, bag.render()
    assert "score" in hits[0].message and "sleep_score" in hits[0].message
    assert "6.0.2" in hits[0].message and "5.2.0" in hits[0].message
    assert "fr955" in hits[0].message
    assert any("null" in note for note in hits[0].notes), hits[0].notes
    assert hits[0].confidence.startswith("exact"), hits[0].confidence


def test_the_same_complication_is_silent_on_a_device_that_supports_it(write_design, bag, db):
    """fenix8solar47mm sits at ConnectIQ 6.0.2, exactly `sleep_score`'s
    `since` -- so the same binding that warns on fr955 must be silent here,
    in the same design."""
    resolved = _resolved_for(write_design, bag, db, COMPLICATION_DATA_DESIGN, "fenix8solar47mm")
    lint.check_complication_availability(resolved, bag)
    assert not [d for d in bag.items if d.code == "complication-gated"], bag.render()


def test_an_ordinary_complication_type_never_fires_anywhere(write_design, bag, db):
    """Only the three types above the 4.2.0 floor (wheelchair_pushes 4.2.3,
    last_golf_round_score 5.0.0, sleep_score 6.0.2 -- wfb/complications.py)
    can ever trigger this. `body_battery` (4.2.0) is fine on every device
    this project vendors, fr955 included."""
    from wfb.diagnostics import Bag

    design = COMPLICATION_DATA_DESIGN.replace(
        "complication.sleep_score", "complication.body_battery")
    for device_id in ("fenix8solar47mm", "fenix8solar51mm", "fr955"):
        quiet = Bag()
        resolved = _resolved_for(write_design, quiet, db, design, device_id)
        lint.check_complication_availability(resolved, quiet)
        assert not [d for d in quiet.items if d.code == "complication-gated"], \
            (device_id, quiet.render())


def test_a_hold_target_above_the_devices_ceiling_warns_and_says_it_is_a_no_op(
        write_design, bag, db):
    """The `on_hold:`/`launch:` direction: distinct message text from the data
    direction, and it must say the hold is a no-op, not a crash --
    `WfbComplications.mc`'s `subscribe()` already absorbs both ways a device
    can decline a type."""
    resolved = _resolved_for(write_design, bag, db, COMPLICATION_HOLD_DESIGN, "fr955")
    lint.check_complication_availability(resolved, bag)
    hits = [d for d in bag.items if d.code == "complication-gated"]
    assert hits, bag.render()
    assert "holding to launch" in hits[0].message
    assert "sleep_score" in hits[0].message
    assert "6.0.2" in hits[0].message and "5.2.0" in hits[0].message
    assert any("no-op" in note for note in hits[0].notes), hits[0].notes
    assert not any("null" in note for note in hits[0].notes), hits[0].notes


def test_a_carousel_launch_item_above_the_devices_ceiling_also_warns(write_design, bag, db):
    """Same mechanism, the carousel item's own `launch:` rather than an
    element-level `on_hold:` -- a carousel cannot take `on_hold:` itself
    (`carousel-on-hold`), so this is the only way the hold direction reaches
    a carousel."""
    design = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm, fr955]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
  dim: "#555555"
elements:
  - id: background
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
  - id: data
    type: carousel
    at: {anchor: center}
    size: {width: 62%, height: 22%}
    pitch: 22%r
    icon_size: 9%r
    color: palette.fg
    inactive_color: palette.dim
    items:
      - value: activity.steps
        format: "{:d}"
        when_absent: hide
        launch: sleep_score
      - value: activity.calories
        format: "{:d}"
        when_absent: hide
"""
    resolved = _resolved_for(write_design, bag, db, design, "fr955")
    lint.check_complication_availability(resolved, bag)
    hits = [d for d in bag.items if d.code == "complication-gated"]
    assert hits, bag.render()
    assert "holding to launch" in hits[0].message


def test_complication_gated_is_suppressible_on_the_bound_element(write_design, bag, db):
    design = COMPLICATION_DATA_DESIGN.replace(
        "    color: palette.fg\n    at: {anchor: center}\n",
        "    color: palette.fg\n    at: {anchor: center}\n"
        "    lint:\n      allow: [complication-gated]\n      reason: \"probing\"\n",
    )
    resolved = _resolved_for(write_design, bag, db, design, "fr955")
    lint.check_complication_availability(resolved, bag)
    assert not [d for d in bag.items if d.code == "complication-gated"], bag.render()


def test_complication_availability_degrades_honestly_without_an_api_level(
        write_design, bag, db, monkeypatch):
    """`Device.api_level` never raises -- it falls back to a `"0.0.0"`
    sentinel when `compiler.json` carries no usable `connectIQVersion`. That
    must read as "not checked", not as "this device supports nothing",
    the same discipline ADR 0008 and `check_hold_targets` already apply."""
    from wfb.diagnostics import Severity

    resolved = _resolved_for(write_design, bag, db, COMPLICATION_DATA_DESIGN, "fr955")
    monkeypatch.setattr(type(resolved.device), "api_level", property(lambda self: "0.0.0"))
    lint.check_complication_availability(resolved, bag)
    warnings = [d for d in bag.items
                if d.code == "complication-gated" and d.severity == Severity.WARNING]
    assert not warnings, bag.render()
    notes = [d for d in bag.items
             if d.code == "complication-gated" and d.confidence
             and d.confidence.startswith("not checked")]
    assert notes and "complication" in notes[0].message.lower(), bag.render()


def test_format_doc_lists_every_suppressible_code():
    """`docs/format.md` names the suppressible codes; `lint.SUPPRESSIBLE` is
    the real list.

    These drifted once already -- the prose said "exactly five" long after
    `carousel-zone`, `hold-overlap` and `hold-unsupported` had joined -- so
    the claim is pinned here rather than trusted. Prose is a deliverable in
    this repo, and a doc that quietly lists the wrong set is worse than one
    that lists none: an author who reads it and writes an `allow:` for a code
    it omits gets a build error the doc says they should not.
    """
    import pathlib

    doc = pathlib.Path(__file__).resolve().parent.parent / "docs" / "format.md"
    text = doc.read_text(encoding="utf-8")
    missing = [code for code in sorted(lint.SUPPRESSIBLE) if f"`{code}`" not in text]
    assert not missing, (
        "docs/format.md does not mention these suppressible codes: "
        + ", ".join(missing)
    )
