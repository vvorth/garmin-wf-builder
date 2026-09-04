"""Errors must point at the author's YAML, with file, line and column."""

from wfb import validate, yamlsrc
from wfb.ir import build


def load(path, bag):
    doc = yamlsrc.load(path, bag)
    if doc is None or not validate.validate(doc, bag):
        return None
    return build(doc, bag)


def test_spans_point_at_the_offending_line(write_design, bag, minimal):
    design = minimal.replace('color: palette.bg', 'color: palette.missing')
    load(write_design(design), bag)
    assert not bag.ok()
    diag = bag.errors[0]
    assert diag.span is not None
    source = design.splitlines()
    assert "palette.missing" in source[diag.span.line - 1]


def test_unknown_key_is_an_error_not_a_warning(write_design, bag, minimal):
    """A misspelled key is how a design silently loses an element (ADR 0009)."""
    load(write_design(minimal.replace("    color: palette.bg", "    colour: palette.bg")), bag)
    assert not bag.ok()
    assert any("unknown key" in d.message.lower() for d in bag.errors)


def test_unknown_format_version_is_refused_outright(write_design, bag, minimal):
    load(write_design(minimal.replace("format: 1", "format: 9")), bag)
    assert any(d.code == "format-version" for d in bag.errors)


def test_missing_format_key_is_reported(write_design, bag, minimal):
    load(write_design(minimal.replace("format: 1\n", "")), bag)
    assert not bag.ok()


def test_bad_yaml_reports_the_parse_position(write_design, bag):
    load(write_design("format: 1\nface:\n  id: [unclosed\n"), bag)
    assert any(d.code == "yaml" for d in bag.errors)
    assert bag.errors[0].span is not None


def test_duplicate_element_ids_are_rejected(write_design, bag, minimal):
    design = minimal + """
  - id: background
    type: shape
    shape: circle
    radius: 10px
    color: palette.fg
"""
    load(write_design(design), bag)
    assert any(d.code == "duplicate-id" for d in bag.errors)


def test_rendered_output_shows_the_source_line(write_design, bag, minimal):
    load(write_design(minimal.replace("palette.bg", "palette.nope")), bag)
    text = bag.render()
    assert "^" in text and "palette.nope" in text


def test_element_type_discriminates_the_schema_branch(write_design, bag, minimal):
    """A text element missing `value` must not report four unrelated errors."""
    design = minimal + """
  - id: label
    type: text
    at: {anchor: center}
"""
    load(write_design(design), bag)
    assert not bag.ok()
    assert len(bag.errors) == 1, bag.render()
    assert "value" in bag.errors[0].message
