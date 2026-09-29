"""The mapping form of an element list (`wfb/desugar.py`).

Format 2 is mapping-only, and `desugar` rewrites it into the list the IR
builder reads.  What is pinned here is the two ways that could go quietly
wrong: a span that stops pointing at the author's line, and a key or body
that cannot be an element slipping through.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from wfb.build import load
from wfb import desugar, yamlsrc
from wfb.diagnostics import Bag

ROOT = Path(__file__).resolve().parent.parent

HEAD = """format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [fenix8solar47mm, fenix8solar51mm, fr955]
resources:
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
    accent: "#FF5500"
"""

#: Top-level elements and a group's children, both in the mapping form.
MAPPING_FORM = HEAD + """elements:
  background:
    type: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: color.bg
  panel:
    type: group
    at: {anchor: center}
    size: {width: 60%, height: 60%}
    children:
      clock:
        type: text
        text: "{time.clock:%H:%M}"
        font: FONT_NUMBER_MEDIUM
        at: {anchor: center}
        color: color.fg
      steps:
        type: text
        text: "{activity.steps:d}"
        font: FONT_XTINY
        at: {anchor: center, dy: 30%}
        color: color.accent
        absent: "--"
  data:
    type: text
    text: "{activity.calories:d}"
    font: FONT_SMALL
    at: {anchor: center, dy: 34%}
    color: color.fg
    absent: {value: "0"}
"""


def _document(write_design, text: str, bag: Bag):
    """Load and desugar without validating, so a rewrite can be inspected raw."""
    doc = yamlsrc.load(write_design(text), bag)
    assert doc is not None, bag.render()
    ok = desugar.desugar(doc, bag)
    return doc, ok


# -- the rewrite ----------------------------------------------------------------


def test_the_real_example_still_desugars(pytestconfig, bag):
    """`examples/features/complications/` is the mapping form in anger -- so the same
    rewrite runs over a real design, not only over a fixture written to
    order."""
    design = pytestconfig.rootpath / "examples" / "features" / "complications" / "face.yaml"
    if not design.exists():
        pytest.skip("the example is missing")
    doc = yamlsrc.load(design, bag)
    assert doc is not None and desugar.desugar(doc, bag), bag.render()
    assert isinstance(doc.data["elements"], list)
    assert all("id" in e for e in doc.data["elements"])


# -- spans --------------------------------------------------------------------


def test_every_element_points_at_the_key_that_named_it(write_design, bag):
    doc, ok = _document(write_design, MAPPING_FORM, bag)
    assert ok, bag.render()
    lines = MAPPING_FORM.splitlines()

    def key_line(node, index_path):
        span = doc.span(node, "id")
        assert span is not None, "the injected id carries no span"
        assert doc.span_for_path(index_path) == span, (
            "span_for_path and span(node, 'id') disagree"
        )
        return lines[span.line - 1], span.col

    for path, expected in (
        (["elements", 0], "background"),
        (["elements", 1], "panel"),
        (["elements", 2], "data"),
    ):
        node = doc.data["elements"][path[1]]
        text, col = key_line(node, path)
        assert text.strip() == f"{expected}:"
        assert text[col - 1:].startswith(expected), "the column misses the key"

    children = doc.data["elements"][1]["children"]
    for index, expected in enumerate(("clock", "steps")):
        text, col = key_line(children[index], ["elements", 1, "children", index])
        assert text.strip() == f"{expected}:"
        assert text[col - 1:].startswith(expected)


def test_a_semantic_error_inside_a_mapping_form_element_still_points_at_it(
        write_design, bag):
    """The rewrite must not cost the author the spans the list form gives."""
    design = MAPPING_FORM.replace("color: color.fg\n    absent: {value: \"0\"}",
                                  "color: color.missing\n    absent: {value: \"0\"}")
    assert load(write_design(design), bag) is None
    diag = next(d for d in bag.errors if d.code == "color")
    assert diag.span is not None
    assert "color.missing" in design.splitlines()[diag.span.line - 1]


# -- errors -------------------------------------------------------------------


def test_id_inside_a_mapping_form_body_is_an_error(write_design, bag):
    design = MAPPING_FORM.replace("  background:\n", "  background:\n    id: bg\n")
    assert load(write_design(design), bag) is None
    diag = next(d for d in bag.errors if d.code == "schema")
    assert "unknown key ('id' was unexpected)" in diag.message
    assert "format 2 writes the element's key" in " ".join(diag.notes)
    assert diag.span is not None
    assert design.splitlines()[diag.span.line - 1].strip() == "id: bg"


def test_a_key_that_is_not_an_identifier_is_an_error(write_design, bag):
    design = MAPPING_FORM.replace("  background:\n", "  back-ground:\n")
    assert load(write_design(design), bag) is None
    diag = next(d for d in bag.errors if d.code == "schema")
    assert "'back-ground' is not a valid name" in diag.message
    assert diag.span is not None
    assert design.splitlines()[diag.span.line - 1].strip() == "back-ground:"


def test_a_duplicate_key_is_a_clear_diagnostic(write_design, bag):
    """ruamel's round-trip loader raises `DuplicateKeyError` itself, so this
    never reaches `desugar` -- but the author must still get a clear error
    against the second key, which is what this pins down.
    """
    design = MAPPING_FORM.replace("  panel:\n", "  background:\n")
    assert load(write_design(design), bag) is None
    diag = bag.errors[0]
    assert diag.code == "yaml"
    assert 'duplicate key "background"' in diag.message
    assert diag.span is not None
    assert design.splitlines()[diag.span.line - 1].strip() == "background:"


def test_an_alias_shared_by_two_keys_is_an_error(write_design, bag):
    """One node cannot carry two ids.  Without this the second `insert` would
    silently move the id and produce two elements called the same thing."""
    design = HEAD + """elements:
  first: &body
    type: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: color.bg
  second: *body
"""
    assert load(write_design(design), bag) is None
    diag = next(d for d in bag.errors if d.code == "element-mapping")
    assert "same node" in diag.message


# -- the identifier pattern ---------------------------------------------------


def test_the_identifier_pattern_is_the_schema_s_own(repo_root):
    """`desugar.IDENTIFIER` rejects exactly what `#/$defs/identifier` rejects.
    Reading it out of the schema rather than repeating it is what stops the
    two drifting the day the schema's pattern changes."""
    schema = json.loads(
        (repo_root / "schema" / "wfb-face-2.schema.json").read_text(encoding="utf-8"))
    pattern = schema["$defs"]["identifier"]["pattern"]
    assert desugar.IDENTIFIER.pattern == pattern
    schema_re = re.compile(pattern)
    for candidate in ("clock", "_x", "a1", "Big_Ring", "1clock", "a-b", "", "a b"):
        assert bool(schema_re.match(candidate)) == bool(
            desugar.IDENTIFIER.match(candidate)), candidate
