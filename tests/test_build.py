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
    path = repo_root / "examples" / "slice" / "face.yaml"
    if not path.exists():
        pytest.skip("the example design is missing")
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


def test_a_device_outside_the_designs_targets_is_rejected(slice_design, tmp_path, db):
    bag = Bag()
    result = build(slice_design, output=tmp_path, bag=bag, db=db,
                   devices_only=["fenix7pro"], compile_prg=False)
    assert result is None
    assert any(d.code == "target" for d in bag.errors)


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
    ttf = repo_root / "examples" / "slice" / "assets" / "OpenSans-Regular.ttf"
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
    ttf = repo_root / "examples" / "slice" / "assets" / "OpenSans-Regular.ttf"
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
    # compiled (verified: present for examples/config, absent for
    # examples/graph), interleaved with diagnostics this project has
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
