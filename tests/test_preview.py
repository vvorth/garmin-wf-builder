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


def test_a_progress_fallback_renders_the_same_fraction_the_device_draws(
        write_design, db, bag, tmp_path):
    """Preview and device must agree about an absent reading, not just a present
    one.

    `when_absent: fallback` used to be honoured here and silently dropped by
    codegen, so the two renderers disagreed in exactly the case the policy
    exists for. They now substitute the same fill fraction, so a half-full
    fallback ring is half full in both -- distinguishable here from the 0.0 an
    unhandled absence would produce.
    """
    from tests.test_semantics import RING, design

    path = write_design(design(RING.replace("__FALLBACK__", "0.5")))
    face = load(path, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    # No reading for either bound source: the fallback is the only thing left.
    options = PreviewOptions(scale=1, mask_shape=False,
                             sample={"activity.steps": None, "activity.step_goal": None})
    filled = render(resolved, options)
    empty = render(resolved, PreviewOptions(
        scale=1, mask_shape=False,
        sample={"activity.steps": 0, "activity.step_goal": 1000}))
    lit = sum(1 for p in filled.get_flattened_data() if p != (0, 0, 0))
    dark = sum(1 for p in empty.get_flattened_data() if p != (0, 0, 0))
    assert lit > dark, "the fallback fraction drew nothing"


def test_the_preview_draws_a_carousel_as_the_device_first_will(repo_root, bag, db):
    """Item 0 centred, neighbours dimmed.

    Not a guess: `Application.Storage` starts empty, `WfbCarousel.restore`
    returns 0, so item 0 is exactly what the watch draws on first launch --
    which is what keeps this image and the generated code in agreement, the
    only reason the two share resolved geometry at all.
    """
    from wfb.emit.resources import bake_fonts
    from wfb.layout import PlacedCarousel, resolve
    from wfb.preview import PreviewOptions, render

    design = repo_root / "examples" / "carousel" / "face.yaml"
    face = load(design, bag)
    assert face is not None, bag.render()
    device = db.get("fenix8solar47mm")
    resolved = resolve(face, device, bake_fonts(face, device, device.minor_radius))
    carousel = next(p for p in resolved.items if isinstance(p, PlacedCarousel))

    image = render(resolved, PreviewOptions(scale=1, mask_shape=False))
    accent = face.palette["accent"]
    dim = face.palette["dim"]

    def ink(cx: int) -> set:
        return {image.getpixel((x, y))
                for x in range(cx - carousel.icon_px // 2, cx + carousel.icon_px // 2)
                for y in range(carousel.row_center[1] - carousel.icon_px // 2,
                               carousel.row_center[1] + carousel.icon_px // 2)}

    centre = carousel.row_center[0]
    assert (accent.r, accent.g, accent.b) in ink(centre), "the selected item is accented"
    assert (dim.r, dim.g, dim.b) in ink(centre - carousel.pitch), "neighbours are dimmed"
    assert (dim.r, dim.g, dim.b) in ink(centre + carousel.pitch)
