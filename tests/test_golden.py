"""Golden-file tests over the generated project.

ADR 0003 makes these the primary compiler test, because they run with **no
Garmin toolchain** -- only the device files, which the fixtures skip on if they
are missing.  A change to codegen shows up as a diff a human can read, which is
also how the "generated Monkey C must be readable" requirement stays honest.

Regenerate after an intentional change:

    pytest tests/test_golden.py --update-golden
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import compare_golden, generate_for_targets


@pytest.fixture(scope="module")
def slice_design(pytestconfig) -> Path:
    # A fixture, so missing is a failure, never a skip: a skip here once
    # silently turned off every golden test when the design was deleted.
    path = pytestconfig.rootpath / "tests" / "fixtures" / "slice" / "face.yaml"
    assert path.exists(), path
    return path


@pytest.fixture(scope="module")
def generated(pytestconfig, slice_design, tmp_path_factory):
    return generate_for_targets(slice_design, tmp_path_factory.mktemp("build"))


@pytest.mark.parametrize("name", [
    "manifest.xml",
    "monkey.jungle",
    "source/SliceApp.mc",
    "source/SliceView.mc",
    "source/Palette.mc",
    "source-fenix8solar47mm/Layout.mc",
    "source-fenix8solar51mm/Layout.mc",
    "source-fr955/Layout.mc",
    "resources-fenix8solar47mm/fonts/fonts.xml",
])
def test_generated_file_matches_golden(pytestconfig, generated, name):
    files = generated.files()
    if name not in files:
        pytest.skip(f"{name} was not generated for this device set")
    compare_golden(pytestconfig, name.replace("/", "__"), files[name])


# -- properties the golden files should never silently lose ----------------


def test_the_view_names_every_element(generated):
    view = generated.files()["source/SliceView.mc"]
    for element in generated.face.walk():
        assert f"`{element.id}`" in view, f"{element.id} has no comment tying it to the YAML"


def test_layout_constants_are_named_not_inlined(generated):
    """No bare pixel numbers in drawing calls -- ADR 0003's readability contract."""
    import re

    view = generated.files()["source/SliceView.mc"]
    for line in view.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("dc.fill", "dc.draw", "WfbArc.")):
            continue
        # Format strings and justify flags are fine; positional integers are not.
        without_strings = re.sub(r'"[^"]*"', '""', stripped)
        assert not re.search(r"\(\s*-?\d", without_strings), stripped


def test_every_nullable_read_is_guarded(generated):
    view = generated.files()["source/SliceView.mc"]
    assert "activitySteps == null" in view or "activitySteps != null" in view


def test_the_manifest_declares_a_language(generated):
    """No declared language makes the compiler carry a much larger resource table."""
    assert "<iq:language>eng</iq:language>" in generated.files()["manifest.xml"]


def test_permissions_are_empty_for_a_design_that_needs_none(generated):
    assert "<iq:permissions/>" in generated.files()["manifest.xml"]


def test_each_device_gets_its_own_resolved_layout(generated):
    files = generated.files()
    layouts = {name for name in files if name.endswith("Layout.mc")}
    assert len(layouts) == len(generated.devices)
    small = files["source-fenix8solar47mm/Layout.mc"]
    large = files["source-fenix8solar51mm/Layout.mc"]
    assert small != large


def test_only_the_barrel_files_the_face_uses_are_copied(generated):
    assert set(generated.barrel) == {"WfbArc.mc", "WfbMath.mc", "WfbTime.mc"}
    # Not WfbIcons.mc: an icon draws its baked glyph via dc.drawText, the same
    # mechanism any other bound text uses, so there is no barrel function for
    # it to pull in (see wfb/icons.py).


def test_the_generated_header_cites_the_source(generated):
    for name, text in generated.files().items():
        if name.endswith((".mc",)):
            assert "garmin-wf-builder" in text
            assert "face.yaml" in text
