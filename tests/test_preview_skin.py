"""`wfb preview --skin`: the render set into the device's simulator skin
(`wfb.preview.frame_in_skin`), and the bare screen when the device files
lack the skin -- the skin is optional, so its absence is a warning, never a
failure."""

import shutil

import pytest
from PIL import Image

from tests.helpers import run_cli
from wfb.build import load
from wfb.devices import DeviceDatabase
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import (
    PreviewOptions, frame_in_skin, has_skin, render, render_all_styles, render_aod_heatmap,
    skin_missing_warning,
)

DEVICE = "fenix8solar47mm"

#: A white panel: any pixel the skin lets through is white, any bezel pixel
#: is the skin's own colour.
DESIGN = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  fg: "#FFFFFF"
elements:
  - id: fill
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.fg
"""

PLAIN = dict(mask_shape=False, quantise=False)


@pytest.fixture
def resolved_on(write_design, bag):
    def _resolve(database: DeviceDatabase, design: str = DESIGN):
        face = load(write_design(design), bag)
        assert face is not None, bag.render()
        device = database.get(DEVICE)
        return resolve(face, device, bake_fonts(face, device))

    return _resolve


@pytest.fixture
def skinless_db(db, tmp_path):
    """A device root holding `DEVICE` with its skin PNG removed -- device
    files as a partial install or a hand-copied definition would leave them."""
    root = tmp_path / "devices"
    source = db.root / DEVICE
    shutil.copytree(source, root / DEVICE)
    skin = db.get(DEVICE).skin_path
    assert skin is not None, f"{DEVICE}'s own files ship a skin"
    (root / DEVICE / skin.name).unlink()
    return DeviceDatabase(root)


@pytest.mark.parametrize("scale", [1, 2])
def test_the_panel_sits_at_its_display_location_inside_the_skin(db, resolved_on, scale):
    resolved = resolved_on(db)
    device = resolved.device
    x, y, width, height = device.display_location
    with Image.open(device.skin_path) as opened:
        skin = opened.convert("RGBA")

    framed = render(resolved, PreviewOptions(scale=scale, skin=True, **PLAIN))

    assert framed.mode == "RGBA"
    assert framed.size == (skin.width * scale, skin.height * scale)
    # The panel's centre shows through the glass...
    centre = ((x + width // 2) * scale, (y + height // 2) * scale)
    assert framed.getpixel(centre) == (255, 255, 255, 255)
    # ...the panel's own corner is under the opaque bezel, so it is the
    # skin's colour, not the white render...
    corner = (x * scale + 1, y * scale + 1)
    assert framed.getpixel(corner)[:3] != (255, 255, 255)
    # ...and outside the watch is the skin's own background, not drawn on.
    assert framed.getpixel((0, 0)) == skin.getpixel((0, 0))


def test_without_skin_the_render_is_unchanged(db, resolved_on):
    resolved = resolved_on(db)
    bare = render(resolved, PreviewOptions(scale=1, **PLAIN))
    assert bare.size == (resolved.device.width, resolved.device.height)
    assert bare.mode == "RGB"


def test_a_device_without_a_skin_renders_the_bare_screen(skinless_db, resolved_on):
    resolved = resolved_on(skinless_db)
    device = resolved.device
    assert not has_skin(device)
    assert frame_in_skin(Image.new("RGB", (device.width, device.height)), device, 1) is None

    skinned = render(resolved, PreviewOptions(scale=2, skin=True, **PLAIN))
    bare = render(resolved, PreviewOptions(scale=2, **PLAIN))
    assert skinned.tobytes() == bare.tobytes()


def test_the_warning_names_only_the_devices_without_a_skin(db, skinless_db):
    with_skin, without = db.get(DEVICE), skinless_db.get(DEVICE)
    assert has_skin(with_skin)
    warning = skin_missing_warning([with_skin, without], skin=True)
    assert warning is not None and DEVICE in warning
    assert skin_missing_warning([with_skin], skin=True) is None
    assert skin_missing_warning([without], skin=False) is None


def test_all_styles_frames_every_panel(db, resolved_on):
    from tests.test_preview import LAYOUT_STYLE_DESIGN

    resolved = resolved_on(db, LAYOUT_STYLE_DESIGN)
    one = render(resolved, PreviewOptions(scale=1, skin=True, style="style_a", **PLAIN))
    composed = render_all_styles(resolved, PreviewOptions(scale=1, skin=True, **PLAIN))
    assert composed.width == one.width * 2 + 1


def test_the_heatmap_is_framed_once(db, resolved_on):
    resolved = resolved_on(db)
    heat, _ = render_aod_heatmap(resolved, PreviewOptions(scale=1, skin=True), minutes=[0])
    with Image.open(resolved.device.skin_path) as skin:
        assert heat.size == skin.size


def test_cli_writes_a_skin_suffixed_png(write_design, tmp_path):
    out = tmp_path / "out"
    result = run_cli("preview", str(write_design(DESIGN)), "--skin", "-o", str(out))
    assert result.returncode == 0, result.stderr
    with Image.open(out / f"{DEVICE}--skin.png") as image:
        assert image.mode == "RGBA"
    assert "skin" not in result.stderr


def test_cli_without_a_skin_writes_the_bare_png_and_warns(write_design, skinless_db, tmp_path):
    out = tmp_path / "out"
    result = run_cli("preview", str(write_design(DESIGN)), "--skin", "-o", str(out),
                     "--devices-dir", str(skinless_db.root))
    assert result.returncode == 0, result.stderr
    assert (out / f"{DEVICE}.png").is_file()
    assert not (out / f"{DEVICE}--skin.png").exists()
    assert "no simulator skin" in result.stderr and DEVICE in result.stderr
