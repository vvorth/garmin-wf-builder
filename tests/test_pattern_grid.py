"""`pattern: grid` -- a template in rows of `columns:`, `count:` copies in
all, so the last row may be partial.

Copy `i` is column `i % columns`, row `i // columns`, offset by `step:`'s
`dx` per column and `dy` per row. The tests pin that one rule in the
generated loop, in the preview's pixels (a drawn cell and the partial
row's missing one), in the extent, and in each refusal.
"""

from __future__ import annotations

import pytest

from wfb import lint
from wfb.build import build as real_build
from wfb.build import load
from wfb.diagnostics import Bag
from wfb.emit import generate
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve
from wfb.preview import PreviewOptions, render

BASE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
  accent: "#FFAA00"
elements:
"""

GRID = """
  - id: month
    type: pattern
    pattern: grid
    at: {anchor: center, dx: -30%r, dy: -20%r}
    count: 10
    columns: 4
    step: {dx: 20px, dy: 16px}
    color: palette.fg
    parts:
      - {shape: circle, radius: 4px}
"""


def _face(text, write_design, bag):
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    return face


def _resolved(text, write_design, bag, db):
    face = _face(text, write_design, bag)
    device = db.get("fenix8solar47mm")
    return resolve(face, device, bake_fonts(face, device))


def _placed(resolved):
    return next(p for p in resolved.items if p.id == "month")


def test_the_loop_splits_the_copy_index_into_column_and_row(write_design, bag, db):
    face = _face(BASE + GRID, write_design, bag)
    device = db.get("fenix8solar47mm")
    files = generate(face, [device], write_design("").parent / "build",
                     {device.id: bake_fonts(face, device)}).files()
    view = next(v for k, v in files.items() if k.endswith("View.mc"))
    assert "var ox = Layout.MONTH_X + (i % 4) * Layout.MONTH_DX;" in view
    assert "var oy = Layout.MONTH_Y + (i / 4) * Layout.MONTH_DY;" in view
    assert "for (var i = 0; i < 10; i++)" in view


def test_copies_fill_rows_and_leave_the_last_one_partial(write_design, bag, db):
    """10 copies in rows of 4: row 2 holds copies 8 and 9 only. Must fail
    against a linear layout (one long row) or a column-major one."""
    resolved = _resolved(BASE + GRID, write_design, bag, db)
    placed = _placed(resolved)
    x0, y0 = placed.center
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))
    assert placed.transform(5)[:2] == (x0 + 20, y0 + 16)
    assert image.getpixel((x0 + 1 * 20, y0 + 2 * 16)) == (255, 255, 255)   # copy 9
    assert image.getpixel((x0 + 2 * 20, y0 + 2 * 16)) == (0, 0, 0)         # no copy 10
    assert image.getpixel((x0 + 3 * 20, y0)) == (255, 255, 255)            # copy 3


def test_the_extent_covers_every_row(write_design, bag, db):
    """The ink of four columns and three rows of 4 px dots: 3 x 20 + 8 wide,
    2 x 16 + 8 tall -- not one 10-copy row, not one 4-copy row."""
    placed = _placed(_resolved(BASE + GRID, write_design, bag, db))
    x0, y0 = placed.center
    assert (placed.box.x, placed.box.y, placed.box.width, placed.box.height) == \
        (x0 - 4, y0 - 4, 3 * 20 + 8, 2 * 16 + 8)


def test_copy_and_skip_keep_their_meaning(write_design, bag, db):
    text = BASE + GRID.replace("    color: palette.fg\n",
                               "    color: \"copy == 5 ? palette.accent : palette.fg\"\n"
                               "    skip: [0]\n")
    resolved = _resolved(text, write_design, bag, db)
    placed = _placed(resolved)
    x0, y0 = placed.center
    image = render(resolved, PreviewOptions(scale=1, mask_shape=False, quantise=False))
    assert image.getpixel((x0, y0)) == (0, 0, 0)                        # copy 0 skipped
    assert image.getpixel((x0 + 20, y0 + 16)) == (0xFF, 0xAA, 0x00)     # copy 5


# -- refusals ----------------------------------------------------------------------


def _errors(text, write_design, bag):
    assert load(write_design(text), bag) is None
    return bag.errors


def test_a_grid_without_columns_is_an_error(write_design, bag):
    [error] = _errors(BASE + GRID.replace("    columns: 4\n", ""), write_design, bag)
    assert "needs 'columns:'" in error.message


def test_columns_on_a_linear_pattern_is_an_error(write_design, bag):
    [error] = _errors(BASE + GRID.replace("pattern: grid", "pattern: linear"), write_design, bag)
    assert "read only by 'pattern: grid'" in error.message


def test_an_angle_step_on_a_grid_is_an_error(write_design, bag):
    [error] = _errors(BASE + GRID.replace("step: {dx: 20px, dy: 16px}", "step: 30deg"),
                      write_design, bag)
    assert "'pattern: grid' takes {dx, dy}" in error.message


def test_a_row_step_that_rounds_away_is_an_error_naming_the_rows(write_design, bag, db):
    resolved = _resolved(BASE + GRID.replace("dy: 16px", "dy: 0.1%"), write_design, bag, db)
    lint.run(resolved, bag)
    [error] = [d for d in bag.errors if d.code == "pattern-step"]
    assert "every row lands on the first" in error.message
    assert "column" not in error.message


# -- a real build ------------------------------------------------------------------


@pytest.mark.slow
def test_a_grid_compiles_warning_free(write_design, db, tmp_path, toolchain):
    text = BASE.replace("targets: [fenix8solar47mm]", "targets: [fenix8solar47mm, fr955]") + \
        GRID.replace("    color: palette.fg\n",
                     "    color: \"copy == date.day - 1 ? palette.accent : palette.fg\"\n") + """
  - id: labels
    type: pattern
    pattern: grid
    at: {anchor: center, dx: -20%r, dy: 40%r}
    count: 6
    columns: 3
    step: {dx: 20%r, dy: 14%r}
    color: palette.fg
    parts:
      - {shape: text, value: "copy + 1", font: FONT_XTINY}
"""
    bag = Bag()
    result = real_build(write_design(text), output=tmp_path, bag=bag, db=db, toolchain=toolchain)
    assert result is not None, bag.render()
    assert not [d for d in bag.items if d.severity.value in ("warning", "error")], bag.render()
