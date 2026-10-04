"""Author text into generated Monkey C (`wfb.mcsource`): a quote, a
backslash or a line break in drawn text, a label or a widest rendering
keeps the source well formed, and a line break in drawn text is refused
on the author's own line instead."""

from __future__ import annotations

import pytest

from helpers import generate_for_targets, load_errors
from wfb.build import build as real_build
from wfb.diagnostics import Bag
from wfb.draw.printer import str_code
from wfb.draw.program import StrLit
from wfb.mcsource import comment_text, control_character, string_literal

FACE = """
format: 2
face:
  id: 5d0f2a61-3c4b-4e7a-9b18-6a2e4c9d1f03
  name: Quoted
build:
  targets: [fr955]
resources:
  palette:
    fg: "#FFFFFF"
elements:
  label:
    type: text
    text: {label}
    font: FONT_SMALL
    at: {{ anchor: center }}
    color: color.fg
  numerals:
    type: pattern
    pattern: radial
    at: {{ anchor: center }}
    count: 4
    color: color.fg
    parts:
      - type: text
        text: {part}
        font: FONT_XTINY
        at: {{ dy: -60%r }}
"""

#: `say "hi" \ ok`, and a pattern part `a"b\c`, as YAML single-quoted strings.
QUOTED = FACE.format(label="'say \"hi\" \\ ok'", part="'a\"b\\c'")


def test_a_string_literal_escapes_what_would_end_or_break_it():
    assert string_literal('say "hi" \\ ok') == '"say \\"hi\\" \\\\ ok"'
    assert string_literal("a\nb\tc\rd\x01") == '"a\\nb\\tc\\rd\\u0001"'
    assert string_literal("é ✓") == '"é ✓"'


def test_a_comment_stays_on_its_line():
    assert comment_text('widest "a\nb"') == 'widest "a\\nb"'
    assert "\n" not in comment_text("x\r\n\ty")
    assert control_character("fine") is None
    assert control_character("a\tb") == "\\t"


def test_a_printed_string_is_escaped():
    assert str_code(StrLit('a"b\\c')) == '"a\\"b\\\\c"'


def test_quoted_text_is_escaped_once_in_the_generated_view(write_design, tmp_path):
    """The text's own literal and the pattern part's: escaped once each, not
    left raw (a quote ends the literal) and not twice (the part used to be
    escaped before the printer escaped it again)."""
    project = generate_for_targets(write_design(QUOTED), tmp_path / "out")
    view = next(s.text for s in project.sources if s.path.endswith("View.mc"))
    assert '"say \\"hi\\" \\\\ ok"' in view
    assert '"a\\"b\\\\c"' in view
    assert '"a\\"b\\\\\\\\c"' not in view


@pytest.mark.parametrize("where, design", [
    ("text", FACE.format(label='"one\\ntwo"', part="'x'")),
    ("text", FACE.format(label="'x'", part='"tab\\there"')),
    ("absent", FACE.format(label='"{heart_rate.current}"', part="'x'").replace(
        "    font: FONT_SMALL\n", "    font: FONT_SMALL\n    absent: \"-\\n-\"\n", 1)),
], ids=["text", "pattern-part", "absent"])
def test_a_line_break_in_drawn_text_is_refused_where_it_is_written(where, design, write_design):
    errors = load_errors(design, write_design)
    assert [e.code for e in errors] == ["format"], [e.message for e in errors]
    assert errors[0].message.startswith(f"{where}: a text is drawn on one line")
    line = errors[0].span.line
    assert design.splitlines()[line - 1].strip().startswith(f"{where}:")


@pytest.mark.slow
def test_quoted_text_builds_warning_free(write_design, db, tmp_path, toolchain):
    """The real `monkeyc`: a quote and a backslash in a text and in a
    pattern part used to end the generated literal (`no viable alternative
    at input`)."""
    bag = Bag()
    result = real_build(write_design(QUOTED), output=tmp_path, bag=bag, db=db,
                        toolchain=toolchain)
    assert result is not None and result.products, bag.render()
    warnings = [d for d in bag.items if d.severity.value in ("warning", "error")]
    assert not warnings, "\n".join(d.message for d in warnings)
