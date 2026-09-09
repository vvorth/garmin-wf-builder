"""The mapping form of an element list (`wfb/desugar.py`).

The gate that actually matters is
:func:`test_the_two_forms_generate_byte_identical_output`: two spellings that
are meant to mean the same thing are only proved to mean the same thing when
the compiler's own output for them is identical, byte for byte, on every
target.  Everything else here is about the two ways this could go quietly
wrong -- a span that stops pointing at the author's line, and a carousel's
`items:` being mistaken for a list of elements.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.test_diagnostics import load
from wfb import desugar, yamlsrc
from wfb.diagnostics import Bag

ROOT = Path(__file__).resolve().parent.parent

HEAD = """format: 1
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
targets: [fenix8solar47mm, fenix8solar51mm, fr955]
palette:
  bg: "#000000"
  fg: "#FFFFFF"
  accent: "#FF5500"
"""

#: The same design twice.  Element order, every key and every value match; only
#: the shape of the two element lists differs.
LIST_FORM = HEAD + """elements:
  - id: background
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
  - id: panel
    type: group
    at: {anchor: center}
    size: {width: 60%, height: 60%}
    children:
      - id: clock
        type: text
        value: time.clock
        format: "{:%H:%M}"
        font: FONT_NUMBER_MEDIUM
        at: {anchor: center}
        color: palette.fg
      - id: steps
        type: text
        value: activity.steps
        format: "{:d}"
        font: FONT_XTINY
        at: {anchor: center, dy: 30%}
        color: palette.accent
        when_absent: placeholder
        placeholder: "--"
  - id: data
    type: carousel
    at: {anchor: center, dy: 30%}
    size: {width: 52%, height: 20%}
    pitch: 22%r
    icon_size: 9%r
    color: palette.accent
    inactive_color: palette.fg
    value_font: FONT_SMALL
    value_color: palette.fg
    value_offset: {anchor: center, dy: 34%}
    items:
      - value: activity.calories
        format: "{:d}"
        when_absent: fallback
        fallback: "0"
      - value: system.battery
        format: "{:.0f}%"
"""

MAPPING_FORM = HEAD + """elements:
  background:
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
  panel:
    type: group
    at: {anchor: center}
    size: {width: 60%, height: 60%}
    children:
      clock:
        type: text
        value: time.clock
        format: "{:%H:%M}"
        font: FONT_NUMBER_MEDIUM
        at: {anchor: center}
        color: palette.fg
      steps:
        type: text
        value: activity.steps
        format: "{:d}"
        font: FONT_XTINY
        at: {anchor: center, dy: 30%}
        color: palette.accent
        when_absent: placeholder
        placeholder: "--"
  data:
    type: carousel
    at: {anchor: center, dy: 30%}
    size: {width: 52%, height: 20%}
    pitch: 22%r
    icon_size: 9%r
    color: palette.accent
    inactive_color: palette.fg
    value_font: FONT_SMALL
    value_color: palette.fg
    value_offset: {anchor: center, dy: 34%}
    items:
      # NOT rewritten: a carousel's items are slots, not elements.  They have
      # no id, and nothing here is keyed.
      - value: activity.calories
        format: "{:d}"
        when_absent: fallback
        fallback: "0"
      - value: system.battery
        format: "{:.0f}%"
"""


def _document(write_design, text: str, bag: Bag):
    """Load and desugar without validating, so a rewrite can be inspected raw."""
    doc = yamlsrc.load(write_design(text), bag)
    assert doc is not None, bag.render()
    ok = desugar.desugar(doc, bag)
    return doc, ok


# -- the gate -----------------------------------------------------------------


def _write_pair(tmp_path) -> tuple[Path, Path]:
    """Both forms under the *same* filename, in sibling directories.

    The generated header names the design file, so two different filenames
    would make this gate fail for a reason that has nothing to do with the
    rewrite.
    """
    out = []
    for name, text in (("list", LIST_FORM), ("map", MAPPING_FORM)):
        directory = tmp_path / name
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "face.yaml"
        path.write_text(text, encoding="utf-8")
        out.append(path)
    return out[0], out[1]


def _generate(design: Path, db, tmp_path):
    from wfb.emit import generate
    from wfb.emit.resources import bake_fonts

    bag = Bag()
    face = load(design, bag)
    assert face is not None, bag.render()
    devices = [db.get(d) for d in face.targets if d in db.ids()]
    assert len(devices) == 3, "this gate is about all three targets"
    reference = min(d.minor_radius for d in devices)
    baked = {d.id: bake_fonts(face, d, reference) for d in devices}
    return generate(face, devices, tmp_path, baked).files()


def test_the_two_forms_generate_byte_identical_output(write_design, db, tmp_path):
    """The strongest available proof that the mapping form is pure sugar.

    Every generated file -- Monkey C, the per-device resource XML and .fnt,
    the manifest, the jungle, the strings -- for all three targets, compared
    byte for byte between a design written both ways.
    """
    as_list, as_map = _write_pair(tmp_path / "src")
    from_list = _generate(as_list, db, tmp_path / "l")
    from_map = _generate(as_map, db, tmp_path / "m")
    assert sorted(from_list) == sorted(from_map)
    differing = [name for name in from_list if from_list[name] != from_map[name]]
    assert not differing, f"generated files differ between the two forms: {differing}"
    # A guard nobody has watched fail is not a guard: the corpus must be real.
    assert any(name.endswith("View.mc") for name in from_list)
    assert "manifest.xml" in from_list and "monkey.jungle" in from_list


def test_a_carousel_keeps_its_items_a_plain_list(write_design, bag):
    """`items:` are slots with no id.  Rewriting them would mangle the row."""
    doc, ok = _document(write_design, MAPPING_FORM, bag)
    assert ok, bag.render()
    carousel = doc.data["elements"][2]
    assert carousel["id"] == "data"
    items = carousel["items"]
    assert isinstance(items, list) and len(items) == 2
    assert [item.get("value") for item in items] == [
        "activity.calories", "system.battery",
    ]
    assert not any("id" in item for item in items)


#: A carousel whose `items:` are written as a mapping.  Nonsense -- a slot has
#: no id -- and the point is that it is *rejected*, not silently rewritten into
#: a list of elements carrying invented ids.
CAROUSEL_ITEMS_AS_MAPPING = MAPPING_FORM.replace("""    items:
      # NOT rewritten: a carousel's items are slots, not elements.  They have
      # no id, and nothing here is keyed.
      - value: activity.calories
        format: "{:d}"
        when_absent: fallback
        fallback: "0"
      - value: system.battery
        format: "{:.0f}%"
""", """    items:
      calories:
        value: activity.calories
        format: "{:d}"
        when_absent: fallback
        fallback: "0"
      battery:
        value: system.battery
        format: "{:.0f}%"
""")


def test_a_carousel_items_mapping_is_rejected_not_rewritten(write_design, bag):
    """The discriminating test for "not a carousel's items".

    A `carousel` and a `group` both own a list of mappings; only the group's
    are elements.  If this pass ever started rewriting `items:` too, the
    mangling would be silent -- ids invented for slots that have none -- so
    what is asserted here is that the mapping survives untouched and the schema
    then says plainly that `items:` must be a list.
    """
    assert CAROUSEL_ITEMS_AS_MAPPING != MAPPING_FORM, "the fixture did not apply"
    doc, ok = _document(write_design, CAROUSEL_ITEMS_AS_MAPPING, bag)
    assert ok, bag.render()
    items = doc.data["elements"][2]["items"]
    assert isinstance(items, dict), "a carousel's items were rewritten"
    assert not any("id" in body for body in items.values())

    assert load(write_design(CAROUSEL_ITEMS_AS_MAPPING), bag) is None
    assert any(d.code == "schema" for d in bag.errors), bag.render()


def test_the_real_example_still_holds_its_carousel(pytestconfig, bag):
    """`examples/complications/` is the mapping form in anger, and it carries a
    carousel -- so the same rewrite runs over a real design with both shapes in
    it, not only over a fixture written to order."""
    design = pytestconfig.rootpath / "examples" / "complications" / "face.yaml"
    if not design.exists():
        pytest.skip("the example is missing")
    doc = yamlsrc.load(design, bag)
    assert doc is not None and desugar.desugar(doc, bag), bag.render()
    assert isinstance(doc.data["elements"], list)
    carousel = [e for e in doc.data["elements"] if e.get("type") == "carousel"]
    assert len(carousel) == 1
    assert not any("id" in item for item in carousel[0]["items"])


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
    design = MAPPING_FORM.replace("color: palette.accent\n    inactive_color",
                                  "color: palette.missing\n    inactive_color")
    assert load(write_design(design), bag) is None
    diag = next(d for d in bag.errors if d.code == "expression")
    assert diag.span is not None
    assert "palette.missing" in design.splitlines()[diag.span.line - 1]


# -- errors -------------------------------------------------------------------


def test_id_inside_a_mapping_form_body_is_an_error(write_design, bag):
    design = MAPPING_FORM.replace("  background:\n", "  background:\n    id: bg\n")
    assert load(write_design(design), bag) is None
    diag = next(d for d in bag.errors if d.code == "element-mapping")
    assert "must not also declare 'id:'" in diag.message
    assert diag.span is not None
    assert design.splitlines()[diag.span.line - 1].strip() == "id: bg"


def test_a_key_that_is_not_an_identifier_is_an_error(write_design, bag):
    design = MAPPING_FORM.replace("  background:\n", "  back-ground:\n")
    assert load(write_design(design), bag) is None
    diag = next(d for d in bag.errors if d.code == "element-mapping")
    assert "not a valid element id" in diag.message
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
    type: shape
    shape: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: palette.bg
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
        (repo_root / "schema" / "wfb-face-1.schema.json").read_text(encoding="utf-8"))
    pattern = schema["$defs"]["identifier"]["pattern"]
    assert desugar.IDENTIFIER.pattern == pattern
    schema_re = re.compile(pattern)
    for candidate in ("clock", "_x", "a1", "Big_Ring", "1clock", "a-b", "", "a b"):
        assert bool(schema_re.match(candidate)) == bool(
            desugar.IDENTIFIER.match(candidate)), candidate


# -- the list form is untouched ----------------------------------------------


def test_a_list_form_document_is_left_exactly_as_it_was(write_design, bag):
    doc, ok = _document(write_design, LIST_FORM, bag)
    assert ok, bag.render()
    ids = [e["id"] for e in doc.data["elements"]]
    assert ids == ["background", "panel", "data"]
    # The list form's own spans are what they always were: the element body.
    span = doc.span_for_path(["elements", 0])
    assert span is not None
    assert LIST_FORM.splitlines()[span.line - 1].strip() == "- id: background"


# -- through the real toolchain -----------------------------------------------


@pytest.mark.slow
def test_the_two_forms_compile_to_identical_prg_files(tmp_path, db):
    """The same gate again, but through `monkeyc` rather than the generator.

    Both forms are built from the *same* design filename into the *same* output
    directory, one after the other, because the compiled `.prg` carries the
    paths it was built from -- two output directories would differ for a reason
    that has nothing to do with the rewrite.  The build must also be clean, not
    merely successful: `wfb/build.py` turns each `WARNING:` line `monkeyc`
    prints into a diagnostic, so `bag.ok()` is an assertion about the Garmin
    compiler's own output.
    """
    from wfb.build import Toolchain, build

    toolchain = Toolchain.discover()
    if toolchain is None or not toolchain.key.exists():
        pytest.skip("no Connect IQ SDK or developer key")

    design = tmp_path / "src" / "face.yaml"
    design.parent.mkdir(parents=True)
    out = tmp_path / "out"
    products: dict[str, dict[str, bytes]] = {}
    for name, text in (("list", LIST_FORM), ("map", MAPPING_FORM)):
        design.write_text(text, encoding="utf-8")
        bag = Bag()
        result = build(design, output=out, bag=bag, db=db, toolchain=toolchain)
        assert result is not None, bag.render()
        assert bag.ok(), bag.render()
        assert len(result.products) == 3, "all three targets must have been built"
        products[name] = {
            device: path.read_bytes() for device, path in result.products.items()
        }
    assert products["list"].keys() == products["map"].keys()
    for device in sorted(products["list"]):
        assert products["list"][device] == products["map"][device], (
            f"{device}: the two forms compiled to different .prg files"
        )
