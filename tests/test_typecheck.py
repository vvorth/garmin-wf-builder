"""`mypy --strict` over `wfb/`, against `tests/mypy-baseline.txt`.

The sweep itself is the `typecheck` test set, which runs only when selected
(`pytest -m typecheck`, `tests/conftest.py`): it fails on an error the
baseline does not hold, and on a baseline entry that is no longer reported,
so the baseline only ever shrinks. The comparison logic
(`tools/typecheck.py`) is tested here too, without mypy, in the ordinary
fast suite.
"""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("wfb_typecheck_tool", ROOT / "tools" / "typecheck.py")
typecheck = importlib.util.module_from_spec(_spec)
# `dataclasses.dataclass` looks its own module up in `sys.modules`.
sys.modules[_spec.name] = typecheck
_spec.loader.exec_module(typecheck)

OUTPUT = """\
wfb/a.py:10: error: Function is missing a return type annotation  [no-untyped-def]
wfb/a.py:10: note: Use "-> None" if function does not return a value
wfb/a.py:20:5: error: Function is missing a return type annotation  [no-untyped-def]
wfb/b.py:3: error: "None" not callable  [misc]
wfb/b.py:7: error: Something without a code
"""


def test_parse_keeps_errors_and_drops_notes():
    errors = typecheck.parse(OUTPUT)
    assert [(e.path, e.line, e.code) for e in errors] == [
        ("wfb/a.py", 10, "no-untyped-def"), ("wfb/a.py", 20, "no-untyped-def"),
        ("wfb/b.py", 3, "misc"), ("wfb/b.py", 7, "misc")]
    assert errors[0].key == "wfb/a.py: [no-untyped-def] Function is missing a return type annotation"


def test_a_moved_error_matches_its_baseline_entry():
    """Line numbers are not part of an entry: editing a file above an
    existing error must not fail the check."""
    before = typecheck.parse(OUTPUT)
    after = typecheck.parse(OUTPUT.replace("wfb/b.py:3:", "wfb/b.py:40:"))
    new, fixed = typecheck.compare(after, Counter(e.key for e in before))
    assert new == [] and not fixed


def test_a_second_occurrence_of_a_known_error_is_new():
    """The count is compared, not just the kind: one more missing annotation
    in the same file fails, and names every occurrence of that kind."""
    errors = typecheck.parse(OUTPUT)
    baseline = Counter(e.key for e in errors)
    extra = typecheck.parse(OUTPUT + "wfb/b.py:9: error: \"None\" not callable  [misc]\n")
    new, fixed = typecheck.compare(extra, baseline)
    assert [e.line for e in new] == [3, 9] and not fixed
    assert "baseline allows 1" in typecheck.report(new, fixed, baseline)


def test_a_fixed_error_is_reported_so_the_baseline_shrinks():
    errors = typecheck.parse(OUTPUT)
    baseline = Counter(e.key for e in errors)
    new, fixed = typecheck.compare(errors[1:], baseline)
    assert new == []
    assert fixed == Counter({errors[0].key: 1})
    assert "--update" in typecheck.report(new, fixed, baseline)


def test_the_baseline_round_trips(tmp_path):
    errors = typecheck.parse(OUTPUT)
    path = tmp_path / "baseline.txt"
    path.write_text(typecheck.format_baseline(errors, {"mypy": "9.9.9", "pillow": "1.0"}))
    assert typecheck.load_baseline(path) == Counter(e.key for e in errors)
    assert typecheck.baseline_versions(path) == {"mypy": "9.9.9", "pillow": "1.0"}
    assert "mypy 9.9.9 -> " in typecheck.version_note(path)


@pytest.mark.typecheck
def test_mypy_strict_reports_nothing_the_baseline_does_not_hold():
    errors = typecheck.run()
    # Empty is the goal; missing would lose the versions `version_note` names.
    assert typecheck.BASELINE.exists(), "tests/mypy-baseline.txt is missing"
    baseline = typecheck.load_baseline()
    new, fixed = typecheck.compare(errors, baseline)
    message = "\n".join(filter(None, [typecheck.report(new, fixed, baseline),
                                       typecheck.version_note()]))
    assert not new and not fixed, message
