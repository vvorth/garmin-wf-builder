"""Generated comments name what the author wrote, never the compiler's
internal names.

The compiler reads an internal shape whose key and kind names are older than
format 2 (`wfb/lower.py`).  The generated Monkey C is read when a face
misbehaves on the wrist, so a comment quoting `when_absent:` or
`config.colors.bg` points the reader at a spelling their YAML cannot contain.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.helpers import generate_for_targets

#: An internal name that must not appear in a generated comment, each with
#: the author's spelling it stands for.
INTERNAL = re.compile(
    r"\bwhen_absent\b"                      # absent:
    r"|\bvertical_align\b"                  # align:
    r"|\bif_unavailable\b"                  # unsupported:
    r"|\bicon_(?:for|size|color|gap|position):"  # icon: {for/size/...:}
    r"|'glyph:'"                            # icon: U+XXXX
    r"|\bconfig\.colors\.|\bconfig\.(?:accent|data)_color\b"  # color.<role>
    r"|\bconfig\.data\.|\bconfig: data:"    # slot: / config: slots:
    r"|\bcolor_scheme\b"                    # theme: schemes:
    r"|`palette\.\w+`"                      # color.<swatch>
    r"|\bcomplication_slot\b"               # type: data
    r"|progress indicator"                  # type: gauge
    r"|\blow_power\b|Drawn in:"             # sleep_update:
)

#: Between them, every comment family the check covers: absence policies,
#: colour roles and swatches, slots, schemes, gauges, sleep updates and
#: dynamic icons.
DESIGNS = (
    "examples/showcase/face.yaml",
    "examples/dashboard/face.yaml",
    "examples/features/slot-gauge/face.yaml",
    "examples/features/styles/face.yaml",
    "examples/features/progress/face.yaml",
)


def internal_names(source: str) -> list[str]:
    """Each comment line of ``source`` that quotes an internal name."""
    return [line.strip() for line in source.splitlines()
            if "//" in line and INTERNAL.search(line[line.index("//"):])]


def test_the_check_sees_an_internal_name():
    assert internal_names("    // when_absent: placeholder\n")
    assert internal_names("//! Bound to `x ? config.colors.dark : palette.fg`.\n")
    assert not internal_names("    // absent: \"--\"\n")
    assert not internal_names('var x = "when_absent"; \n')


@pytest.mark.parametrize("design", DESIGNS)
def test_generated_comments_use_the_authors_names(pytestconfig, tmp_path, design):
    path = Path(pytestconfig.rootpath) / design
    generated = generate_for_targets(path, tmp_path)
    found = {name: hits for name, text in generated.files().items()
             if name.endswith(".mc") and (hits := internal_names(text))}
    assert not found, found
