"""The end-to-end pipeline, including the real `monkeyc` build when available."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from wfb.build import Toolchain, build
from wfb.devices import DeviceDatabase
from wfb.diagnostics import Bag


@pytest.fixture
def toolchain():
    found = Toolchain.discover()
    if found is None:
        pytest.skip("no Connect IQ SDK; set CIQ_SDK or run ./tools/setup-env.sh")
    if not found.key.exists():
        pytest.skip("no developer key")
    return found


@pytest.fixture
def slice_design(repo_root):
    path = repo_root / "tests" / "fixtures" / "slice" / "face.yaml"
    assert path.exists(), path
    return path


def test_generation_needs_no_toolchain(slice_design, tmp_path, db):
    """Stages 1-3 must work in CI, where the toolchain is unavailable."""
    bag = Bag()
    result = build(slice_design, output=tmp_path, bag=bag, db=db, compile_prg=False)
    assert result is not None
    assert bag.ok(), bag.render()
    root = result.output_dir
    assert (root / "manifest.xml").exists()
    assert (root / "monkey.jungle").exists()
    assert (root / "source" / "SliceView.mc").exists()
    assert (root / "runtime-lib" / "WfbArc.mc").exists()
    for device in result.devices:
        assert (root / f"source-{device.id}" / "Layout.mc").exists()
        assert (root / f"resources-{device.id}" / "fonts" / "clock.fnt").exists()
        assert (root / f"resources-{device.id}" / "fonts" / "clock.png").exists()
        assert (root / f"resources-{device.id}" / "drawables" / "launcher_icon.png").exists()


def test_an_unparseable_build_stats_section_is_reported_not_silently_dropped(
        slice_design, tmp_path, db, monkeypatch,
):
    """`wfb.lint.check_memory` returns `None` when it cannot find the
    `--build-stats` section in monkeyc's own output (a future SDK reformats
    it, say). Memory is *measured, never estimated* (ADR 0008) -- a build
    that quietly skips the check on such a `None` would silently stop
    catching an over-budget design the moment the SDK's own output changed
    shape, with nothing in the diagnostics to say so. No real toolchain is
    needed: `subprocess.run` is faked to "succeed" (writes the `.prg`,
    returns code 0) with output that carries no `--build-stats` section at
    all, which is exactly the case `_STATS_RE` fails to match.
    """
    import subprocess as sp

    from wfb.build import Toolchain

    def fake_run(command, cwd, capture_output, text, check):
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_bytes(b"fake-prg")
        return sp.CompletedProcess(command, 0, stdout="BUILD SUCCESSFUL\n", stderr="")

    monkeypatch.setattr("wfb.build.subprocess.run", fake_run)

    toolchain = Toolchain(sdk=Path("/fake/sdk"), key=Path("/fake/key.der"))
    bag = Bag()
    result = build(slice_design, output=tmp_path, bag=bag, db=db, toolchain=toolchain)

    assert result is not None, bag.render()
    assert result.products, "the fake build should still have 'succeeded'"
    assert not result.memory, "there was nothing to measure -- stats never parsed"
    memory_warnings = [
        d for d in bag.items
        if d.code == "memory" and d.severity.value == "warning"
    ]
    assert memory_warnings, (
        "an unparseable --build-stats section must be reported, not silently "
        "dropped:\n" + bag.render()
    )


def test_an_off_screen_low_power_element_builds_and_clamps_the_clip(
    write_design, tmp_path, db, bag,
):
    """End-to-end: drawing off the framebuffer is now a suppressible
    warning, not a build error (`wfb.lint.check_geometry`), so a design with
    an off-screen `low_power` element must still generate rather than abort
    at the lint stage. The low-power clip rectangle it feeds
    (`wfb.layout.ResolvedFace.clip_for`) must clamp to the framebuffer, not
    emit a negative-width/height `dc.setClip(...)` call
    (`wfb.emit.monkeyc.view._emit_on_partial_update`).
    """
    design = write_design("""
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
    at: {anchor: center, dx: 500%}
    radius: 10px
    color: palette.fg
    modes: [active, low_power]
    lint:
      allow: [off-screen]
      reason: "probing"
""")
    result = build(design, output=tmp_path, bag=bag, db=db, compile_prg=False)
    assert result is not None
    assert bag.ok(), bag.render()
    layout_mc = (result.output_dir / "source-fenix8solar47mm" / "Layout.mc").read_text()
    for name in ("LOW_POWER_CLIP_WIDTH", "LOW_POWER_CLIP_HEIGHT"):
        line = next(l for l in layout_mc.splitlines() if f"{name} as Number" in l)
        value = int(line.split("=")[1].strip().rstrip(";"))
        assert value >= 0, line


def test_launcher_icons_are_generated_at_each_devices_own_size(slice_design, tmp_path, db):
    """Shipping one icon and letting the compiler scale it warns on every build."""
    from PIL import Image

    bag = Bag()
    result = build(slice_design, output=tmp_path, bag=bag, db=db, compile_prg=False)
    for device in result.devices:
        wanted = device.compiler.get("launcherIcon")
        icon = Image.open(result.output_dir / f"resources-{device.id}" / "drawables"
                          / "launcher_icon.png")
        assert icon.size == (wanted["width"], wanted["height"])


def test_font_sheets_scale_with_the_screen(slice_design, tmp_path, db):
    """A sheet baked for 260x260 is wrong on the 280x280 fenix 8 Solar 51 mm."""
    bag = Bag()
    result = build(slice_design, output=tmp_path, bag=bag, db=db, compile_prg=False)
    sizes = {
        device.id: result.project.resolved[device.id].fonts["clock"].size
        for device in result.devices
    }
    assert sizes["fenix8solar51mm"] > sizes["fenix8solar47mm"]
    assert sizes["fr955"] == sizes["fenix8solar47mm"]


def test_building_one_device_only(slice_design, tmp_path, db):
    bag = Bag()
    result = build(slice_design, output=tmp_path, bag=bag, db=db,
                   devices_only=["fr955"], compile_prg=False)
    assert [d.id for d in result.devices] == ["fr955"]


def _installed(db, device_id):
    if device_id not in db.ids():
        pytest.skip(f"{device_id} is not installed")


def test_a_device_outside_the_designs_targets_builds_with_a_note(slice_design, tmp_path, db):
    """`-d` may name any installed device, not only a listed target: trying a
    face on another watch must not need an edit to the design.  The product
    list comes from the devices asked for, so the manifest names that device
    and none of the targets that were not asked for."""
    _installed(db, "fenix7pro")
    bag = Bag()
    result = build(slice_design, output=tmp_path, bag=bag, db=db,
                   devices_only=["fenix7pro"], compile_prg=False)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    assert [d.id for d in result.devices] == ["fenix7pro"]
    notes = [d for d in bag.items if d.code == "target"]
    assert len(notes) == 1 and notes[0].severity.value == "note", bag.render()
    assert "fenix7pro" in notes[0].message
    manifest = (result.output_dir / "manifest.xml").read_text(encoding="utf-8")
    assert 'id="fenix7pro"' in manifest
    assert 'id="fr955"' not in manifest
    assert (result.output_dir / "source-fenix7pro" / "Layout.mc").exists()


def test_a_listed_target_asked_for_by_name_draws_no_note(slice_design, tmp_path, db):
    bag = Bag()
    build(slice_design, output=tmp_path, bag=bag, db=db,
          devices_only=["fr955"], compile_prg=False)
    assert not [d for d in bag.items if d.code == "target"], bag.render()


def test_a_device_below_the_manifest_floor_is_a_friendly_build_error(slice_design, tmp_path, db):
    """A device whose own ConnectIQ ceiling sits below `BASE_API_LEVEL`
    cannot build at all -- every generated manifest declares one shared
    `minApiLevel` (`wfb/emit/manifest.py`), so a device below that floor
    fails outright regardless of what the design actually uses. This must
    surface as a clear, targeted build error naming the device and its
    level (`wfb.build.select_devices`), not the raw `monkeyc` failure
    ("Device '<id>' does not support API Level '<floor>'") a build would
    otherwise hit deep inside the toolchain stage.

    No installed device is actually below 3.1.0 (`fenix5`/`fenix5x`, this
    project's lowest installed ceiling, are 3.1.6), so this constructs a
    synthetic device fixture in a throwaway device root -- the same
    "construct what no installed device can" move
    `tests/test_vector_text_layout.py::
    test_gate1_alone_blocks_resolution_even_when_the_face_is_published`
    already uses for gate 1.
    """
    import json

    device_root = tmp_path / "fake-devices" / "ancientwatch"
    device_root.mkdir(parents=True)
    (device_root / "compiler.json").write_text(json.dumps({
        "deviceFamily": "fake-100x100",
        "resolution": {"width": 100, "height": 100},
        "appTypes": [{"type": "watchFace", "memoryLimit": 65536}],
        "partNumbers": [{"connectIQVersion": "3.0.0"}],
    }), encoding="utf-8")
    (device_root / "simulator.json").write_text("{}", encoding="utf-8")
    fake_db = DeviceDatabase(root=tmp_path / "fake-devices")

    bag = Bag()
    result = build(slice_design, output=tmp_path / "out", bag=bag, db=fake_db,
                   devices_only=["ancientwatch"], compile_prg=False)
    assert result is None
    hits = [d for d in bag.items if d.code == "target"]
    assert len(hits) == 1 and hits[0].severity.value == "error", bag.render()
    assert "ancientwatch" in hits[0].message
    assert "3.0.0" in hits[0].message
    assert "3.1.0" in hits[0].message


def test_an_unknown_device_is_one_error_and_no_note(slice_design, tmp_path, db):
    bag = Bag()
    result = build(slice_design, output=tmp_path, bag=bag, db=db,
                   devices_only=["nosuchwatch"], compile_prg=False)
    assert result is None
    hits = [d for d in bag.items if d.code == "target"]
    assert len(hits) == 1 and hits[0].severity.value == "error", bag.render()


def test_a_device_named_twice_is_built_once(slice_design, tmp_path, db):
    bag = Bag()
    result = build(slice_design, output=tmp_path, bag=bag, db=db,
                   devices_only=["fr955", "fr955"], compile_prg=False)
    assert [d.id for d in result.devices] == ["fr955"]


# --------------------------------------------------------------------------
# the build proof: every installed, watch-face-capable device at or above
# the shared manifest floor (root CLAUDE.md constraint 2's "136 of 164
# devices can run a watch face", narrowed to BASE_API_LEVEL) gets a real,
# warning-free monkeyc build.


def _build_proof_device_ids() -> list[str]:
    """Collected once, at import time, the same way `tests/test_templates.
    py`'s own `EXAMPLES` list is built from a directory scan -- so a missing
    `~/.Garmin/ConnectIQ/Devices` collects zero parametrised cases (each
    reported "no tests ran" for this file, not a collection error) rather
    than failing collection for the whole test session.

    Filters `db.ids()` (every installed device) down to the ones this
    compiler can actually target: `Device.supports_watchface` (constraint
    2 -- 28 of 164 devices cannot run a watch face at all) and an own
    ConnectIQ ceiling at or above `BASE_API_LEVEL` (the shared manifest
    floor every generated build declares, `wfb/emit/manifest.py`) -- a
    device below that floor is `wfb.build.select_devices`'s own friendly
    `target` build error, covered separately by
    `test_a_device_below_the_manifest_floor_is_a_friendly_build_error`
    above, not this proof.
    """
    from wfb.devices import DeviceDatabase, DeviceError, version_key
    from wfb.emit.manifest import BASE_API_LEVEL

    try:
        database = DeviceDatabase.discover()
    except DeviceError:
        return []
    floor = version_key(BASE_API_LEVEL)
    return sorted(
        device_id for device_id in database.ids()
        if database.get(device_id).supports_watchface
        and version_key(database.get(device_id).api_level) >= floor
    )


_BUILD_PROOF_DEVICE_IDS = _build_proof_device_ids()

#: One face exercising: text bound to `time.clock` and `date.today` with a
#: `%m`-using `format:` (`docs/lore/codegen.md`'s "date.today's format: bug"
#: finding -- the numeric month needs a second, `date_short` reader, which
#: is exactly the kind of extra codegen path a per-device build proof needs
#: to actually compile, not just generate), a `shape` element, a `progress`
#: `style: arc` bound to `system.battery` (CLAUDE.md's own "progress arc on
#: battery"), and an `antialias: true` primitive (`_emit_antialias_helper`'s
#: `dc has :setAntiAlias` guard, `wfb/emit/monkeyc/view.py`) -- a small but
#: non-trivial face. On `fenix5`/`fenix5x` (ConnectIQ 3.1.6) this only
#: compiles once the manifest floor is at or below 3.1.0: at the previous
#: 3.2.0 floor `fenix5` sits *below* the floor and the build fails outright
#: (`test_a_device_below_the_manifest_floor_is_a_friendly_build_error`
#: covers that failure mode in isolation, with a synthetic device, since no
#: installed device is below the *current* 3.1.0 floor to demonstrate it
#: directly) -- this test is the complementary proof: a real, warning-free
#: `monkeyc` run for a design that actually uses these features, on every
#: device the new floor makes buildable, not just a friendly-error stub.
_BUILD_PROOF_FACE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f61
  name: BuildProof
targets: [{device_id}]
aod:
  lint: {{allow: [aod-empty], reason: "build-proof fixture, not a real design -- irrelevant on a MIP target too"}}
palette:
  bg: "#000000"
  fg: "#FFFFFF"
  accent: "#00AAFF"
  dim: "#555555"
elements:
  - id: background
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.bg
    antialias: true
    lint: {{allow: [antialias-dither], reason: "build-proof fixture, not a real design"}}
  - id: clock
    type: text
    value: time.clock
    format: "{{:%H:%M}}"
    font: FONT_MEDIUM
    color: palette.fg
    at: {{anchor: center, dy: -20%r}}
  - id: today
    type: text
    value: date.today
    format: "{{:%Y-%m-%d}}"
    font: FONT_TINY
    color: palette.fg
    at: {{anchor: center, dy: 20%r}}
  - id: battery_arc
    type: progress
    style: arc
    at: {{anchor: center, angle: 187deg, radius: 46%r}}
    radius: 6%r
    thickness: 3px
    start_angle: 20deg
    sweep: 320deg
    value: system.battery
    max: 100
    color: palette.accent
    track_color: palette.dim
"""


@pytest.mark.slow
@pytest.mark.parametrize("device_id", _BUILD_PROOF_DEVICE_IDS)
def test_every_installed_device_at_the_floor_or_above_builds_warning_free(
        device_id, write_design, tmp_path, db, toolchain):
    """The build proof: a real `monkeyc` build, warning-free, for every
    installed device at or above `BASE_API_LEVEL` -- parametrised per
    device, so a failure names the device rather than reporting one lump
    "some target failed". Before the floor was lowered to 3.1.0 this failed
    outright on `fenix5`/`fenix5x` with monkeyc's own `Device 'fenix5' does
    not support API Level '3.2.0'`, confirmed by hand
    (`wfb.build.select_devices` did not yet exist to turn that into a
    friendly error either, at the time -- the manifest floor was simply too
    high for the device to build under any circumstance).
    """
    design = write_design(_BUILD_PROOF_FACE.format(device_id=device_id))
    bag = Bag()
    result = build(design, output=tmp_path / "out", bag=bag, db=db,
                   toolchain=toolchain, devices_only=[device_id])
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    warnings = [d for d in bag.items if d.severity.value == "warning"]
    assert not warnings, "\n".join(d.message for d in warnings)
    assert device_id in result.products
    prg = result.products[device_id]
    assert prg.exists() and prg.stat().st_size > 0
    stats = result.memory[device_id]
    assert 0 < stats["total"] < stats["limit"]


@pytest.mark.slow
def test_a_device_outside_the_targets_compiles(slice_design, tmp_path, db, toolchain):
    """The end-to-end promise of `-d` on an unlisted device: an older, smaller
    watch than any target (fenix6: 240x240, API 3.x, 114,688 B for a face)
    gets a signed .prg from the unchanged design."""
    _installed(db, "fenix6")
    bag = Bag()
    result = build(slice_design, output=tmp_path, bag=bag, db=db, toolchain=toolchain,
                   devices_only=["fenix6"])
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    assert set(result.products) == {"fenix6"}


@pytest.mark.slow
def test_the_slice_compiles_cleanly_for_every_target(slice_design, tmp_path, db, toolchain):
    """The Phase 2 promise: one command, YAML to a signed .prg, no warnings."""
    bag = Bag()
    result = build(slice_design, output=tmp_path, bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    warnings = [d for d in bag.items if d.severity.value == "warning"]
    assert not warnings, "\n".join(d.message for d in warnings)
    assert set(result.products) == {d.id for d in result.devices}
    for device_id, prg in result.products.items():
        assert prg.exists() and prg.stat().st_size > 0
        stats = result.memory[device_id]
        assert 0 < stats["total"] < stats["limit"]


@pytest.mark.slow
def test_a_length_font_size_compiles_cleanly_for_every_target(
        write_design, repo_root, tmp_path, db, toolchain):
    """`size: 18%r` through the real toolchain, warning-free on all three.

    A `Length` size changes only a number in the baked sheet and its `fonts.xml`
    comment, so the generated Monkey C is the same shape a bare number produces
    -- which is exactly the reasoning that makes a test worth having rather than
    assuming: nothing about "it should be identical" is checked by `wfb
    validate`, and `wfb.build` turns each `WARNING:` line `monkeyc` prints into
    a bag diagnostic, so this asserts warning-free rather than merely
    successful.
    """
    ttf = repo_root / "tests" / "fixtures" / "slice" / "assets" / "OpenSans-Regular.ttf"
    design = write_design(f"""
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: FontLen}}
targets: [fenix8solar47mm, fenix8solar51mm, fr955]
palette: {{bg: "#000000", fg: "#FFFFFF"}}
fonts:
  clock:
    source: {ttf}
    size: 18%r
elements:
  - id: background
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.bg
  - id: clock
    type: text
    value: time.clock
    format: "{{:%H:%M}}"
    font: font.clock
    at: {{anchor: center}}
    color: palette.fg
""")
    bag = Bag()
    result = build(design, output=tmp_path / "out", bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    warnings = [d for d in bag.items if d.severity.value == "warning"]
    assert not warnings, "\n".join(d.message for d in warnings)
    sizes = {
        device.id: result.project.resolved[device.id].fonts["clock"].size
        for device in result.devices
    }
    # 18% of each device's own minor radius: 130 -> 23.4, 140 -> 25.2.
    assert sizes == {"fenix8solar47mm": 23, "fenix8solar51mm": 25, "fr955": 23}


@pytest.mark.slow
def test_a_monospaced_font_compiles_cleanly_for_every_target(
        write_design, repo_root, tmp_path, db, toolchain):
    """A monospaced bake through the real toolchain, warning-free on all three.

    Nothing in the generated Monkey C changes -- only the advances and offsets
    inside the `.fnt` -- which is precisely why this is worth building rather
    than assuming: the resource compiler parses that file, and a bad advance or
    a negative offset would be its problem to reject, not `wfb validate`'s.
    `wfb.build` turns each `WARNING:` line into a bag diagnostic, so this
    asserts warning-free rather than merely successful.
    """
    ttf = repo_root / "tests" / "fixtures" / "slice" / "assets" / "OpenSans-Regular.ttf"
    design = write_design(f"""
format: 1
face: {{id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Mono}}
targets: [fenix8solar47mm, fenix8solar51mm, fr955]
palette: {{bg: "#000000", fg: "#FFFFFF"}}
fonts:
  clock:
    source: {ttf}
    size: 22%r
    monospace: true
  label:
    source: {ttf}
    size: 8%r
    monospace: true
    align: right
elements:
  - id: background
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.bg
  - id: clock
    type: text
    value: time.clock
    format: "{{:%H:%M}}"
    font: font.clock
    at: {{anchor: center}}
    color: palette.fg
  - id: steps
    type: text
    value: activity.steps
    font: font.label
    at: {{anchor: center, dy: 20%r}}
    color: palette.fg
    when_absent: placeholder
    placeholder: "--"
""")
    bag = Bag()
    result = build(design, output=tmp_path / "out", bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    warnings = [d for d in bag.items if d.severity.value == "warning"]
    assert not warnings, "\n".join(d.message for d in warnings)
    for device in result.devices:
        font = result.project.resolved[device.id].fonts["clock"]
        assert font.monospace
        assert {g.xadvance for g in font.glyphs.values()} == {font.cell_width}


@pytest.mark.slow
def test_conditional_visibility_compiles_cleanly_for_every_target(
        write_design, tmp_path, db, toolchain):
    """`visible:` through the real toolchain, warning-free on all three targets.

    Worth a real build rather than a text assertion for one specific reason:
    the guard `if (x == null || !(cond)) { return; }` asks `monkeyc` to narrow
    a nullable local *across* the `||`, so that the condition on the right may
    dereference it.  Nothing in the generated text tells you whether strict
    typechecking accepts that -- only the compiler does, and `wfb.build` turns
    each `WARNING:` line it prints into a bag diagnostic, so this asserts
    warning-free rather than merely successful.

    The design covers each shape the emitter produces: a non-nullable
    condition, a nullable one, a group condition pushed into a subtree, and a
    nested group whose condition composes with both the outer group's and the
    leaf's own.
    """
    design = write_design("""
format: 1
face: {id: 3b7d5c11-08a2-4f6e-9c33-5d1e77a04b28, name: Visible}
targets: [fenix8solar47mm, fenix8solar51mm, fr955]
palette: {bg: "#000000", fg: "#FFFFFF", accent: "#FF5500"}
elements:
  - id: background
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
  - id: seconds
    type: text
    value: time.second
    format: "{:d}"
    font: FONT_SMALL
    at: {anchor: center, dy: -30%r}
    color: palette.fg
    visible: "time.second < 30"
  - id: step_note
    type: text
    text: "GO"
    font: FONT_SMALL
    at: {anchor: center, dy: -15%r}
    color: palette.accent
    visible: "activity.steps > 500"
  - id: night_panel
    type: group
    at: {anchor: center}
    size: {width: 70%, height: 40%}
    visible: "time.hour >= 18 or time.hour < 6"
    children:
      - id: night_label
        type: text
        text: "NIGHT"
        font: FONT_SMALL
        at: {anchor: top}
        color: palette.fg
      - id: night_inner
        type: group
        at: {anchor: center}
        size: {width: 100%, height: 50%}
        visible: "not device.do_not_disturb"
        children:
          - id: night_steps
            type: text
            value: activity.steps
            format: "{:d}"
            font: FONT_SMALL
            at: {anchor: center}
            color: palette.accent
            when_absent: placeholder
            placeholder: "--"
          - id: night_icon
            type: icon
            icon: heart
            at: {anchor: bottom}
            size: 8%r
            color: palette.fg
            visible: "system.battery > 20"
""")
    bag = Bag()
    result = build(design, output=tmp_path / "out", bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    warnings = [d for d in bag.items if d.severity.value == "warning"]
    assert not warnings, "\n".join(d.message for d in warnings)
    assert set(result.products) == {d.id for d in result.devices}
    view = (result.output_dir / "source" / "VisibleView.mc").read_text(encoding="utf-8")
    assert "if (activitySteps == null || !(activitySteps > 500))" in view
    # The leaf's guard carries the outer group's condition, the inner group's,
    # and its own -- and the group itself emits no method at all.
    assert ("if (!(((timeHour >= 18) || (timeHour < 6)) "
            "&& ((!deviceDoNotDisturb) && (systemBattery > 20))))") in view
    assert "drawNightPanel" not in view


# --------------------------------------------------------------------------
# the toolchain-output noise filter
#
# `_strip_noise` is the only thing between `monkeyc`'s raw output and the
# diagnostics `wfb build` reports, and this project's whole "warning-free, not
# merely successful" bar rests on every real `WARNING:` line becoming a bag
# diagnostic (CLAUDE.md records a feature that shipped with a real warning
# precisely because nothing put it through the real toolchain).  A filter that
# drifted wider would silence that bar silently, so the two halves are pinned
# here rather than trusted: the JVM notice must go, and real diagnostics must
# survive untouched.


def test_the_noise_filter_strips_the_jvm_notice_and_keeps_real_diagnostics():
    from wfb.build import _strip_noise

    # The JVM's four-line deprecated-reflective-access notice, printed
    # verbatim by this SDK whenever a <watchface-config> resource is
    # compiled (verified: present for examples/features/config, absent for
    # examples/features/graph), interleaved with diagnostics this project has
    # actually hit before -- the delegate's unused `_view` field and the
    # `setAntiAlias` indirect-lookup warning.
    raw = "\n".join([
        "Picked up JAVA_TOOL_OPTIONS: -Dhttp.proxyHost=example",
        "WARNING: A terminally deprecated method in sun.misc.Unsafe has been called",
        "WARNING: sun.misc.Unsafe::arrayBaseOffset has been called by "
        "com.google.protobuf.UnsafeUtil$MemoryAccessor (file:/x/monkeybrains.jar)",
        "WARNING: Please consider reporting this to the maintainers of class "
        "com.google.protobuf.UnsafeUtil$MemoryAccessor",
        "WARNING: sun.misc.Unsafe::arrayBaseOffset will be removed in a future release",
        "WARNING: fr955: /x/ConfigView.mc:8: Member variable '_view' is not used.",
        "WARNING: fenix8solar47mm: The private symbol 'setAntiAlias' will not be "
        "found when using the indirect lookup syntax",
        "ERROR: fr955: /x/Foo.mc:3,4: Undefined symbol ':bar' detected.",
        "BUILD SUCCESSFUL",
    ])

    kept = [line for line in _strip_noise(raw).splitlines() if line.strip()]

    assert not [line for line in kept if "Unsafe" in line], (
        "the JVM notice reached the diagnostics:\n" + "\n".join(kept))
    assert not [line for line in kept if "JAVA_TOOL_OPTIONS" in line]
    # The half that matters most: a filter is only allowed to remove noise.
    assert any("Member variable '_view' is not used" in line for line in kept)
    assert any("indirect lookup syntax" in line for line in kept)
    assert any("Undefined symbol" in line for line in kept)
    assert any("BUILD SUCCESSFUL" in line for line in kept)
