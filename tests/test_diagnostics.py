"""Errors must point at the author's YAML, with file, line and column."""

from wfb.build import load


def test_spans_point_at_the_offending_line(write_design, bag, minimal):
    design = minimal.replace('color: color.bg', 'color: color.missing')
    load(write_design(design), bag)
    assert not bag.ok()
    diag = bag.errors[0]
    assert diag.span is not None
    source = design.splitlines()
    assert "color.missing" in source[diag.span.line - 1]


def test_unknown_key_is_an_error_not_a_warning(write_design, bag, minimal):
    """A misspelled key is how a design silently loses an element (ADR 0009)."""
    load(write_design(minimal.replace("    color: color.bg", "    colour: color.bg")), bag)
    assert not bag.ok()
    assert any("unknown key" in d.message.lower() for d in bag.errors)


def test_unknown_format_version_is_refused_outright(write_design, bag, minimal):
    load(write_design(minimal.replace("format: 2", "format: 9")), bag)
    assert any(d.code == "format-version" for d in bag.errors)


def test_missing_format_key_is_reported(write_design, bag, minimal):
    load(write_design(minimal.replace("""format: 2
""", "")), bag)
    assert not bag.ok()


def test_bad_yaml_reports_the_parse_position(write_design, bag):
    load(write_design("format: 2\nface:\n  id: [unclosed\n"), bag)
    assert any(d.code == "yaml" for d in bag.errors)
    assert bag.errors[0].span is not None


def test_duplicate_element_ids_are_rejected(write_design, bag, minimal):
    """A mapping cannot repeat a key, but a group's child can repeat an id
    from another level."""
    design = minimal + """
  panel:
    type: group
    children:
      background:
        type: circle
        radius: 10px
        color: color.fg
"""
    load(write_design(design), bag)
    assert any(d.code == "duplicate-id" for d in bag.errors)


def test_rendered_output_shows_the_source_line(write_design, bag, minimal):
    load(write_design(minimal.replace("color.bg", "color.nope")), bag)
    text = bag.render()
    assert "^" in text and "color.nope" in text


def test_element_type_discriminates_the_schema_branch(write_design, bag, minimal):
    """A text element missing `text` must not report four unrelated errors."""
    design = minimal + """
  label:
    type: text
    at: {anchor: center}
"""
    load(write_design(design), bag)
    assert not bag.ok()
    assert len(bag.errors) == 1, bag.render()
    assert "missing required key 'text'" in bag.errors[0].message
