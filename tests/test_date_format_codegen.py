"""`date.today` `format:` codegen: `%m` needs a second reader.

The bug (found 2026-09-23): under `FORMAT_MEDIUM` (the `date` reader),
`Gregorian.Info.month` is a localised String ("Sep"), with no numeric form at
all -- `%b` relies on exactly that String, but the previous implementation
emitted `%m` (the zero-padded *Number* month) as `date.month.format("%02d")`
too, which fails every real `monkeyc` build using it
(`Cannot find symbol ':format' on type '$.Toybox.Lang.String'`). The fix
reads `%m` off `date_short` (FORMAT_SHORT) instead, cast `as Number`, the
same way `date.weekday` already reads `dateShort.day_of_week`
(`tests/test_patterns.py::test_a_date_reading_is_declared_once_before_the_loop`)
-- and `wfb.emit.monkeyc.readplan.ReadPlan` has to know to declare that
second reader and thread it into the element's own generated method as a
parameter, exactly the same "fake path" mechanism it already uses for
`time.clock`/`device.is_24_hour` on a time format.

`tests/test_formatting.py` covers `formatting.emit`/`date_extra_paths` at
the unit level; this covers the read plan actually wiring the extra reader
through a real generated `View.mc`, and a real `monkeyc` build exercising
every `DATE_CODES`/`TIME_CODES` entry at once (no existing test compiled
every date code, which is why this bug was never caught).
"""

from __future__ import annotations

import pytest

from tests.test_build import toolchain  # noqa: F401  -- a fixture, used by name
from tests.test_diagnostics import load
from wfb.build import build as real_build
from wfb.diagnostics import Bag
from wfb.emit import generate
from wfb.emit.resources import bake_fonts

BASE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
"""

AOD_BASE = """
format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix847mm]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
"""


def _view_text(text, write_design, bag, db, device_id="fenix8solar47mm"):
    face = load(write_design(text), bag)
    assert face is not None, bag.render()
    device = db.get(device_id)
    baked = {device.id: bake_fonts(face, device)}
    project = generate(face, [device], write_design("").parent / "build", baked)
    return next(v for k, v in project.files().items() if k.endswith("View.mc"))


# --------------------------------------------------------------------------
# fast codegen: the read plan wires up the second reader


def test_numeric_month_reads_the_short_reader(write_design, bag, db):
    text = BASE + """
elements:
  - id: today
    type: text
    value: date.today
    format: "{:%Y-%m-%d}"
    font: FONT_TINY
    color: palette.fg
"""
    view = _view_text(text, write_design, bag, db)
    # the fix: %m reads off dateShort, cast as Number
    assert '(dateShort.month as Number).format("%02d")' in view
    # the bug: %m must never read .month.format off the FORMAT_MEDIUM `date`
    # local again -- that String has no .format(String) overload at all.
    assert "date.month.format" not in view
    # the extra reader is actually declared and threaded as a parameter --
    # not just referenced in the draw method with nothing supplying it.
    assert "var dateShort = Gregorian.info(Time.now(), Time.FORMAT_SHORT);" in view
    assert "dateShort as Gregorian.Info" in view
    method = view.split("private function drawToday")[1].split("\n    }")[0]
    assert "dateShort" in method


def test_a_spec_without_percent_m_never_declares_the_short_reader(write_design, bag, db):
    """Byte-identical-output guarantee: a face that never uses `%m` must not
    grow a `dateShort`/FORMAT_SHORT reader it does not need."""
    text = BASE + """
elements:
  - id: today
    type: text
    value: date.today
    format: "{:%a %e %b}"
    font: FONT_TINY
    color: palette.fg
"""
    view = _view_text(text, write_design, bag, db)
    assert "dateShort" not in view
    assert "FORMAT_SHORT" not in view


def test_aod_format_override_can_need_the_short_reader_on_its_own(write_design, bag, db):
    """An `aod: {format: ...}` override (plan 14) is not validated against
    the value's own codes, and can use `%m` even when the awake `format:`
    never does -- the read plan has to check both specs, or this element's
    AOD ternary reads an undeclared `dateShort` local."""
    text = AOD_BASE + """
elements:
  - id: today
    type: text
    value: date.today
    format: "{:%a}"
    font: FONT_TINY
    color: palette.fg
    aod: {format: "{:%m}"}
"""
    view = _view_text(text, write_design, bag, db, device_id="fenix847mm")
    assert "var dateShort = Gregorian.info(Time.now(), Time.FORMAT_SHORT);" in view
    assert "dateShort as Gregorian.Info" in view
    method = view.split("private function drawToday")[1].split("\n    }")[0]
    assert '(dateShort.month as Number).format("%02d")' in method
    assert "_aod ?" in method


# --------------------------------------------------------------------------
# real monkeyc: every DATE_CODES / TIME_CODES entry, once


_ALL_DATE_CODES = "{:%a %d %e %b %m %Y %y %%}"
_ALL_TIME_CODES = "{:%H %I %l %h %M %S %p %%}"

_SLOW_FACE = f"""
format: 1
face:
  id: db49d4b7-d510-49f2-90ed-8c2421ee4580
  name: AllDateCodes
targets: [fenix8solar47mm]

palette:
  black: "#000000"
  white: "#FFFFFF"

fonts:
  dial:
    # device-resident, scalable -- fenix8solar47mm publishes BionicSemiBold
    # (examples/features/vector-text/face.yaml).
    face: [BionicSemiBold, RobotoCondensedBold]
    size: 8%r

elements:
  - id: background
    type: shape
    shape: rectangle
    at: {{anchor: center}}
    size: {{width: 100%, height: 100%}}
    color: palette.black

  # Plain text, every DATE_CODES entry at once.
  - id: all_date_codes
    type: text
    value: date.today
    format: "{_ALL_DATE_CODES}"
    font: FONT_TINY
    color: palette.white
    at: {{anchor: center, dy: -30%}}
    lint:
      allow: [text-overflow, off-screen, safe-area]
      reason: "deliberately exercises every DATE_CODES entry in one string
        to catch a compile bug in any of them; not meant to actually fit
        the screen"

  # Curved text with a face: (vector) font, every DATE_CODES entry at once
  # -- rotated.py's own formatting.emit call site plus shapes.py's vector
  # draw path, both at once. A curved element skips the text-overflow lint
  # entirely (wfb/lint.py check_text_fit), so no allow needed here.
  - id: all_date_codes_curved
    type: text
    value: date.today
    format: "{_ALL_DATE_CODES}"
    font: font.dial
    color: palette.white
    at: {{anchor: center}}
    curve: {{style: angled, angle: 0deg}}

  # Cheap to add: every TIME_CODES entry too, since nothing else exercises
  # %I/%l/%h/%p/%S all at once either.
  - id: all_time_codes
    type: text
    value: time.clock
    format: "{_ALL_TIME_CODES}"
    font: FONT_TINY
    color: palette.white
    at: {{anchor: center, dy: 30%}}
    lint:
      allow: [text-overflow, off-screen, safe-area]
      reason: "deliberately exercises every TIME_CODES entry in one string
        to catch a compile bug in any of them; not meant to actually fit
        the screen"
"""


@pytest.mark.slow
def test_every_date_and_time_code_compiles_warning_free(write_design, db, tmp_path, toolchain):
    """The real `monkeyc` build, not just Python-level codegen -- this is
    the test that would have caught the `%m` bug before it shipped: no
    existing test compiled every `DATE_CODES` entry in one face, so a
    single broken code (`%m`) never got exercised by the fast suite or by
    any of the example builds."""
    bag = Bag()
    result = real_build(write_design(_SLOW_FACE), output=tmp_path, bag=bag, db=db,
                        toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    warnings = [d for d in bag.items if d.severity.value == "warning"]
    assert not warnings, "\n".join(d.message for d in warnings)
