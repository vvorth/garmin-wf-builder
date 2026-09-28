"""2-colour panels (the Instinct family): the `palette-mono` lint and the
preview's black-and-white snap (plan 20 slice 3, research 16 §5)."""

import copy

import pytest

from PIL import Image

from tests.helpers import lint_text, resolve_text
from wfb import lint
from wfb.diagnostics import Bag
from wfb.palette import Color
from wfb.preview import PreviewOptions, _quantise, mono_guess_warning, render

MONO = "instinct2"
MIP = "fenix8solar47mm"

#: `#FF0000` is legal on a 64-colour panel, so it can only be flagged by the
#: 2-colour rule; `#FF8000` is off both grids, so it shows which code fires.
DESIGN = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [instinct2, fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
  red: "#FF0000"
  orange: "#FF8000"
  navy: "#5555AA"
elements:
  - {id: back, type: shape, shape: rectangle, at: {anchor: center}, size: {width: 100%, height: 100%}, color: palette.bg}
  - {id: red_dot, type: shape, shape: circle, at: {anchor: center, dx: -20%}, radius: 10px, color: palette.red}
  - {id: orange_dot, type: shape, shape: circle, at: {anchor: center}, radius: 10px, color: palette.orange}
  - {id: navy_dot, type: shape, shape: circle, at: {anchor: center, dx: 20%}, radius: 10px, color: palette.navy}
  - {id: white_dot, type: shape, shape: circle, at: {anchor: center, dy: 20%}, radius: 10px, color: palette.fg}
"""


def _need(db, *device_ids):
    for device_id in device_ids:
        if device_id not in db.ids():
            pytest.skip(f"{device_id} not installed")


def _codes(bag: Bag, *codes: str) -> dict[str, list[str]]:
    return {code: [d.message for d in bag.items if d.code == code] for code in codes}


def test_a_colour_legal_on_mip_is_palette_mono_on_the_instinct(write_design, db):
    _need(db, MONO, MIP)
    mono = _codes(lint_text(DESIGN, write_design, db, MONO), "palette-mono", "palette-dither")
    mip = _codes(lint_text(DESIGN, write_design, db, MIP), "palette-mono", "palette-dither")
    assert mono["palette-dither"] == []
    assert sorted(m.split(" ", 1)[0] for m in mono["palette-mono"]) == [
        "color.navy", "color.orange", "color.red"]
    assert mip["palette-mono"] == []
    assert [m.split(" ", 1)[0] for m in mip["palette-dither"]] == ["color.orange"]


def test_palette_mono_names_the_nearest_and_says_the_mapping_is_a_guess(write_design, db):
    _need(db, MONO)
    bag = lint_text(DESIGN, write_design, db, MONO)
    by_token = {d.message.split(" ", 1)[0]: d for d in bag.items if d.code == "palette-mono"}
    red, navy = by_token["color.red"], by_token["color.navy"]
    assert red.severity.value == "warning"
    assert "only black and white are safe" in red.message
    assert "nearest legal colour: #FFFFFF" in red.notes
    assert "nearest legal colour: #000000" in navy.notes
    assert "unverified" in " ".join(red.notes)


def test_palette_mono_is_suppressible_on_an_element_that_draws_it(write_design, db):
    _need(db, MONO)
    allowed = DESIGN.replace(
        "color: palette.red}",
        "color: palette.red, lint: {allow: [palette-mono], reason: deliberate}}")
    bag = lint_text(allowed, write_design, db, MONO)
    flagged = [d.message.split(" ", 1)[0] for d in bag.items if d.code == "palette-mono"]
    assert "color.red" not in flagged and "color.navy" in flagged


def test_a_config_colour_goes_through_the_same_rule(write_design, db):
    _need(db, MONO)
    design = DESIGN.replace("elements:", """config:
  accent_color:
    default: "#AAAAAA"
    choices: any
elements:""").replace("color: palette.fg}", "color: config.accent_color}")
    bag = lint_text(design, write_design, db, MONO)
    assert any("config.accent_color" in d.message for d in bag.items if d.code == "palette-mono")


def test_a_palette_size_without_a_rule_is_reported_not_checked(write_design, bag, db):
    """8- and 14-colour panels exist (12 face-capable devices) but none is
    installed, so one is simulated: the note must name the size."""
    _need(db, MONO)
    _, resolved = resolve_text(DESIGN, write_design, bag, db, MONO)
    device = copy.copy(resolved.device)
    device.__dict__["_scraped"] = {"normalized": {"display_colors": 14}}
    fourteen = copy.copy(resolved)
    object.__setattr__(fourteen, "device", device)
    out = Bag()
    lint.check_palette(fourteen, out)
    notes = [d.message for d in out.items if d.code == "palette-dither"]
    assert notes and "14 colours, which has no known rule" in notes[0]
    assert all(d.severity.value == "note" for d in out.items)


# -- preview -----------------------------------------------------------------


def _pixel(image, device, dx_percent: float, dy_percent: float = 0.0):
    x = round(device.width / 2 + device.width * dx_percent)
    y = round(device.height / 2 + device.height * dy_percent)
    return image.getpixel((x, y))


def test_the_preview_snaps_to_black_and_white_on_a_2_colour_panel(write_design, bag, db):
    _need(db, MONO)
    _, resolved = resolve_text(DESIGN, write_design, bag, db, MONO)
    device = resolved.device
    snapped = render(resolved, PreviewOptions(scale=1)).convert("RGB")
    assert _pixel(snapped, device, -0.2) == (255, 255, 255)   # red -> white
    assert _pixel(snapped, device, 0.2) == (0, 0, 0)          # navy -> black
    raw = render(resolved, PreviewOptions(scale=1, quantise=False)).convert("RGB")
    assert _pixel(raw, device, -0.2) == (255, 0, 0)


def test_the_preview_says_once_that_the_snap_is_a_guess(db):
    _need(db, MONO, MIP)
    mono, mip = db.get(MONO), db.get(MIP)
    warning = mono_guess_warning([mono, mip], quantise=True)
    assert warning is not None and MONO in warning and MIP not in warning
    assert "unverified" in warning
    assert mono_guess_warning([mip], quantise=True) is None
    assert mono_guess_warning([mono], quantise=False) is None


def _colour_grid() -> Image.Image:
    """Every red and green in steps of 3 against 16 blues: dense enough to
    straddle the black/white crossover many times over (#006CFF is one)."""
    colours = [(r, g, b) for b in range(0, 256, 17)
               for g in range(0, 256, 3) for r in range(0, 256, 3)]
    image = Image.new("RGB", (86 * 86, 16))
    image.putdata(colours)
    return image


@pytest.mark.parametrize("colors", [2, 64])
def test_the_preview_snaps_every_colour_where_the_lint_says(colors):
    """The preview is the evidence for `palette-mono`/`palette-dither`'s
    "nearest" colour, so the two must be one rule, not two that agree on
    the easy cases."""
    grid = _colour_grid()
    snapped = _quantise(grid, colors).convert("RGB")
    disagree = [
        (Color(*rgb), got)
        for rgb, got in zip(grid.getdata(), snapped.getdata())
        if Color(*got) != Color(*rgb).nearest_legal(colors)
    ]
    assert not disagree, f"{len(disagree)} colours, e.g. {disagree[:3]}"
