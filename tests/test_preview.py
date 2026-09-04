"""The host-side preview renderer."""

import pytest

from tests.test_diagnostics import load
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render
from wfb.palette import MIP64_LEVELS


@pytest.fixture
def resolved(repo_root, db, bag):
    design = repo_root / "examples" / "slice" / "face.yaml"
    if not design.exists():
        pytest.skip("the example design is missing")
    face = load(design, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device, device.minor_radius))


def test_preview_is_the_devices_own_size(resolved):
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False))
    assert image.size == (resolved.device.width, resolved.device.height)


def test_scale_multiplies_both_axes(resolved):
    image = render(resolved, PreviewOptions(scale=3, mask_shape=False))
    assert image.size == (resolved.device.width * 3, resolved.device.height * 3)


def test_quantising_snaps_to_the_devices_own_palette(resolved):
    """A dithered colour should look wrong in the preview the way it will on the wrist."""
    image = render(resolved, PreviewOptions(scale=1, quantise=True, mask_shape=False))
    channels = {value for pixel in image.get_flattened_data() for value in pixel}
    assert channels <= set(MIP64_LEVELS)


def test_the_face_actually_draws_something(resolved):
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False))
    colors = {pixel for pixel in image.get_flattened_data()}
    assert len(colors) > 2, "the preview is blank"


def test_sample_readings_drive_the_bound_elements(resolved):
    """Different step counts must produce different pixels, or nothing is bound."""
    low = render(resolved, PreviewOptions(scale=1, mask_shape=False,
                                          sample={"activity.steps": 100}))
    high = render(resolved, PreviewOptions(scale=1, mask_shape=False,
                                           sample={"activity.steps": 9900}))
    assert list(low.get_flattened_data()) != list(high.get_flattened_data())


def test_an_absent_reading_hides_a_hidden_element(resolved):
    present = render(resolved, PreviewOptions(scale=1, mask_shape=False))
    absent = render(resolved, PreviewOptions(scale=1, mask_shape=False,
                                             sample={"activity.steps": None}))
    assert list(present.get_flattened_data()) != list(absent.get_flattened_data())


def test_preview_and_codegen_read_the_same_geometry(resolved):
    """The anti-drift guarantee: both consume the resolved IR, not two layouts."""
    from wfb.emit.monkeyc import emit_layout

    layout = emit_layout(resolved).text
    ring = next(p for p in resolved.items if p.id == "step_ring")
    assert f"const STEP_RING_RADIUS as Number = {ring.radius};" in layout
    assert f"const STEP_RING_CX as Number = {ring.center[0]};" in layout
