"""`outline:` beyond text, compiled for real (research 19, plan 23): the
Python-level tests read the generated source text, which cannot see a Monkey
C typing or scoping error in it (`slow`: runs `monkeyc`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from wfb.build import build as real_build
from wfb.diagnostics import Bag

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.slow
@pytest.mark.parametrize("fixture", ["outline_shapes"])
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
