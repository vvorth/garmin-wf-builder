"""`outline:` beyond text, compiled for real (research 19): the
Python-level tests read the generated source text, which cannot see a Monkey
C typing or scoping error in it (`slow`: runs `monkeyc`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from wfb.build import build as real_build
from wfb.diagnostics import Bag

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.slow
@pytest.mark.parametrize("fixture", ["outline_shapes", "outline_hands", "outline_group",
                                     "outline_pattern_gauge"])
def test_outline_fixture_compiles_warning_free(fixture, db, tmp_path, toolchain):
    """Every outlined kind in the fixture, on all three verification
    targets: warning-free is the build bar (root CLAUDE.md §7)."""
    bag = Bag()
    result = real_build(FIXTURES / fixture / "face.yaml", output=tmp_path, bag=bag, db=db,
                        toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
    warnings = [d for d in bag.items if d.severity.value == "warning"]
    assert not warnings, "\n".join(d.message for d in warnings)


_SHARED_GUARD = """
format: 2
face: { id: 0b7e4a19-2c5d-4e93-8f16-9d3a7c1e5b44, name: AodTwo, version: 1.0.0 }
build: { targets: [fenix847mm] }
defaults: { aod: show }
resources: { palette: { bg: "#000000", fg: "#FFFFFF" } }
elements:
  a: { type: circle, at: { anchor: center }, radius: 5px, color: color.fg, aod: { visible: "time.second > 1" } }
  b: { type: circle, at: { anchor: center, dx: 20px }, radius: 5px, color: color.fg, aod: { visible: "time.second > 2" } }
"""

_LAYOUT_GUARDS = """
format: 2
face: { id: 0b7e4a19-2c5d-4e93-8f16-9d3a7c1e5b45, name: AodLayouts, version: 1.0.0 }
build: { targets: [fenix847mm] }
defaults: { aod: show }
resources: { palette: { bg: "#000000", fg: "#FFFFFF" } }
config:
  style:
    default: one
    choices:
      one: { label: "One", layout: one }
      two: { label: "Two", layout: two }
layouts:
  one:
    elements:
      a: { type: circle, at: { anchor: center }, radius: 5px, color: color.fg, aod: { visible: "time.second > 1" } }
  two:
    elements:
      b: { type: circle, at: { anchor: center, dx: 20px }, radius: 5px, color: color.fg, aod: { visible: "time.second > 2" } }
"""


@pytest.mark.slow
@pytest.mark.parametrize("design", [_SHARED_GUARD, _LAYOUT_GUARDS], ids=["shared", "layouts"])
def test_aod_guards_reading_one_source_compile(design, write_design, db, tmp_path, toolchain):
    """Two `aod: {visible: ...}` guards reading one source declare its
    local once per scope: once in the shared frame body (a second `var` is
    a `Redefinition of variable`), and afresh in each `_configLayout`
    block (a local from another block is an `Undefined symbol`).  An
    outlined group's member meets the first case with its own ring."""
    bag = Bag()
    result = real_build(write_design(design), output=tmp_path, bag=bag, db=db,
                        toolchain=toolchain)
    assert result is not None, bag.render()
    assert bag.ok(), bag.render()
