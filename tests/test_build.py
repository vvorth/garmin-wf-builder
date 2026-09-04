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
