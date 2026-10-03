"""The editor's patch engine (`wfb.edit`): text patches over the example
corpus, the gate that accepts or refuses them, and pixel drags written back
in the author's units to the key the viewed device reads."""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest
from ruamel.yaml.nodes import MappingNode

from tests.helpers import example
from wfb.edit import (
    Gate, Patch, Refused, SpanIndex, View, add_element, chain, delete_element,
    duplicate_element, load_text, move, move_element, parse, remove, rename_key,
    rename_reference, resize, rewrite_scalars, set_value, target, turn,
)
from wfb.edit.structure import add, element_types, group, move_to_block, ungroup
from wfb.edit.geometry import candidates, px_per_unit
from wfb.edit.patch import DEFAULTS, face_color
from wfb.edit.spans import ordered
from wfb.units import Axis, Box, Length

ROOT = Path(__file__).resolve().parent.parent
#: Every example face but the user's playground.
FACES = sorted(p for p in (ROOT / "examples").rglob("face.yaml")
               if "dashboard" not in p.parts)
TARGETS = ("fenix8solar47mm", "fenix8solar51mm", "fr955")
SHAPES = ROOT / "examples/features/shapes/face.yaml"


def changed_blocks(before: str, after: str) -> list[tuple[str, int, int, int, int]]:
    """The non-equal opcodes of a line diff: each is one contiguous change."""
    matcher = difflib.SequenceMatcher(a=before.splitlines(), b=after.splitlines(),
                                      autojunk=False)
    return [op for op in matcher.get_opcodes() if op[0] != "equal"]


def minimal(elements: str, *, static: str = "") -> str:
    return (
        "format: 2\n"
        "face: { id: 9c1d5f30-6a72-4b18-8d4e-0f2a71c93b64, name: Edit, version: 1.0.0 }\n"
        "build: { targets: [fenix8solar47mm] }\n"
        "resources:\n  palette:\n    fg: \"#FFFFFF\"\n"
        + static + elements
    )


# -- the span index -----------------------------------------------------------------

@pytest.mark.parametrize("path", FACES, ids=lambda p: str(p.relative_to(ROOT / "examples")))
def test_every_element_is_found_by_its_span(path):
    face, _ = example(path)
    index = SpanIndex(path.read_text(encoding="utf-8"))
    missing = [e.id for e in face.walk() if index.at_span(e.span) is None]
    assert not missing


def test_an_element_entry_spans_its_comments_and_stops_before_the_next_key():
    text = minimal(
        "elements:\n"
        "  # the first\n"
        "  a:\n"
        "    type: circle\n"
        "    radius: 5%r\n"
        "\n"
        "  # the second\n"
        "  b:\n"
        "    type: circle\n"
        "    radius: 6%r\n")
    index = SpanIndex(text)
    start, end = index.entry_range(index[("elements", "a")])
    assert text[start:end] == "  # the first\n  a:\n    type: circle\n    radius: 5%r\n"
    start, end = index.entry_range(index[("elements", "b")])
    assert text[start:end] == "  # the second\n  b:\n    type: circle\n    radius: 6%r\n"


# -- patches over the corpus, each through the gate ---------------------------------

def _gated(gate: Gate, patch: Patch, before: str, max_blocks: int) -> None:
    gate.check(patch)
    blocks = changed_blocks(before, patch.text)
    assert 1 <= len(blocks) <= max_blocks, (patch.what, blocks)


@pytest.mark.parametrize("path", FACES, ids=lambda p: str(p.relative_to(ROOT / "examples")))
def test_patches_over_the_corpus(path):
    text = path.read_text(encoding="utf-8")
    index = SpanIndex(text)
    gate = Gate(path, text)
    assert gate.before.face is not None
    elements = index.elements()
    first = elements[0]

    # a no-op is byte-identical, for every scalar of every `at:`
    for entry in index.entries():
        if len(entry.path) > 1 and entry.path[-2] == "at" and not isinstance(entry.value,
                                                                              MappingNode):
            assert set_value(index, entry.path, _data(index, entry.path)).text == text
    assert move_element(index, first.path, _siblings(index, first).index(first)).text == text

    # a scalar rewritten in the author's own unit changes exactly one line
    scalars = [e for e in elements if index.get(e.path + ("at", "dy")) is not None][:2]
    for entry in scalars:
        raw = _data(index, entry.path + ("at", "dy"))
        length = Length.parse(raw)
        new = length.value + 10 if not isinstance(raw, str) else f"{length.value + 10:g}{length.unit}"
        patch = set_value(index, entry.path + ("at", "dy"), new)
        _gated(gate, patch, text, 1)
        assert sum(a != b for a, b in zip(text.splitlines(), patch.text.splitlines())) == 1

    # structural patches on the first element: each one contiguous change,
    # or two for a move (the element leaves one place and lands in another)
    _gated(gate, delete_element(index, first.path), text, 1)
    _gated(gate, duplicate_element(index, first.path), text, 1)
    siblings = _siblings(index, first)
    if len(siblings) > 1:
        _gated(gate, move_element(index, first.path, 1), text, 2)
    at = index.get(first.path + ("at",))
    if (at is not None and isinstance(at.value, MappingNode)
            and index.get(first.path + ("at", "angle")) is None):
        if index.get(first.path + ("at", "dx")) is None:
            _gated(gate, set_value(index, first.path + ("at", "dx"), "1%r"), text, 1)
        if index.get(first.path + ("at", "dy")) is not None and len(at.value.value) > 1:
            _gated(gate, remove(index, first.path + ("at", "dy")), text, 1)
    if index.get(("elements",)) is not None:
        _gated(gate, add_element(index, "rectangle"), text, 1)


def _data(index: SpanIndex, path):
    data = index.data
    for step in path:
        data = data[step]
    return data


def _siblings(index: SpanIndex, entry):
    return [e for e in index.entries() if e.parent is entry.parent]


@pytest.mark.parametrize("type_", sorted(DEFAULTS))
def test_a_new_element_of_every_type_loads(type_):
    path = SHAPES
    text = path.read_text(encoding="utf-8")
    patch = add_element(SpanIndex(text), type_)
    Gate(path, text).check(patch)
    assert patch.expected["elements"][f"new_{type_}"]["color"] == "color.dim"


# -- the three rules ------------------------------------------------------------------

def test_deleting_a_blocks_only_element_removes_the_block():
    text = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n",
                   static="static:\n  bg:\n    type: circle\n    radius: 9%r\n"
                          "    color: color.fg\n")
    patch = delete_element(SpanIndex(text), ("static", "bg"))
    assert "static" not in patch.expected
    assert "static:" not in patch.text
    assert patch.text.endswith("elements:\n  a:\n    type: circle\n    radius: 5%r\n"
                               "    color: color.fg\n")


def test_a_duplicated_group_renames_every_element_inside_it():
    path = ROOT / "examples/features/rings/face.yaml"
    text = path.read_text(encoding="utf-8")
    index = SpanIndex(text)
    patch = duplicate_element(index, ("elements", "heart_rate"))
    copy = patch.expected["elements"]["heart_rate_copy"]
    assert set(copy["children"]) == {"heart_icon_copy", "heart_value_copy"}
    Gate(path, text).check(patch)


def test_a_duplicate_takes_the_first_free_suffix():
    text = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n"
                   "  a_copy:\n    type: circle\n    radius: 5%r\n    color: color.fg\n")
    patch = duplicate_element(SpanIndex(text), ("elements", "a"))
    assert list(patch.expected["elements"]) == ["a", "a_copy2", "a_copy"]


def test_an_element_is_added_to_a_face_with_no_elements_block():
    text = minimal("", static="static:\n  bg:\n    type: circle\n    radius: 9%r\n"
                              "    color: color.fg\n")
    patch = add_element(SpanIndex(text), "circle")
    assert patch.expected["elements"] == {"new_circle": {
        "type": "circle", "at": {"anchor": "center"}, "radius": "10%r", "color": "color.fg"}}


def test_a_new_element_takes_a_colour_the_face_uses():
    assert face_color(SpanIndex(minimal("elements: {}\n"))) == "color.fg"
    # the most named, not the first (the background's `color.bg`)
    assert face_color(SpanIndex(SHAPES.read_text(encoding="utf-8"))) == "color.dim"
    # each named once: a tie goes past the first, the background's
    tied = minimal("static:\n  bg:\n    type: rectangle\n    color: color.bg\n"
                   "elements:\n  a:\n    type: circle\n    color: color.fg\n")
    assert face_color(SpanIndex(tied)) == "color.fg"


def test_flow_and_block_keys_are_added_in_their_own_style():
    text = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n"
                   "    at: { anchor: center }\n")
    index = SpanIndex(text)
    assert "at: { anchor: center, dy: 3%r }\n" in set_value(
        index, ("elements", "a", "at", "dy"), "3%r").text
    assert "    color: color.fg\n    at: { anchor: center }\n    thickness: 2px\n" in set_value(
        index, ("elements", "a", "thickness"), "2px").text
    nested = set_value(index, ("elements", "a", "overrides", "fr955", "at", "dy"), "4%")
    assert '    overrides: { fr955: { at: { dy: 4% } } }\n' in nested.text


def test_a_quoted_scalar_keeps_its_quotes():
    text = minimal('elements:\n  a:\n    type: text\n    text: "Hi"\n    font: FONT_SMALL\n'
                   "    color: color.fg\n    at: { dy: '5%' }\n")
    patch = set_value(SpanIndex(text), ("elements", "a", "at", "dy"), "7%")
    assert "at: { dy: '7%' }" in patch.text


def test_a_file_without_a_final_newline_keeps_its_ending():
    text = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg")
    index = SpanIndex(text)
    for patch in (duplicate_element(index, ("elements", "a")), add_element(index, "circle"),
                  set_value(index, ("elements", "a", "thickness"), "2px")):
        assert not patch.text.endswith("\n")
        assert ordered_equal(patch)


def ordered_equal(patch: Patch) -> bool:
    from wfb.edit.gate import ordered
    from wfb.edit.spans import parse

    return bool(ordered(parse(patch.text)) == ordered(patch.expected))


# -- the gate refuses ---------------------------------------------------------------------

def test_the_gate_refuses_a_patch_that_changes_more_than_intended():
    text = SHAPES.read_text(encoding="utf-8")
    index = SpanIndex(text)
    patch = set_value(index, ("elements", "card", "at", "dy"), "-20%")
    # the same text claimed as a different change
    wrong = Patch(patch.text.replace("radius: 92%r", "radius: 91%r", 1), patch.expected,
                  patch.what)
    with pytest.raises(Refused, match="more than intended"):
        Gate(SHAPES, text).check(wrong)


def test_the_gate_refuses_a_patch_that_adds_an_error():
    text = SHAPES.read_text(encoding="utf-8")
    patch = set_value(SpanIndex(text), ("elements", "card", "at", "dy"), "lots")
    with pytest.raises(Refused, match="set elements.card.at.dy"):
        Gate(SHAPES, text).check(patch)


def test_the_gate_refuses_an_edit_that_breaks_a_reference():
    text = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n")
    patch = set_value(SpanIndex(text), ("elements", "a", "color"), "color.nope")
    with pytest.raises(Refused):
        Gate(SHAPES, text).check(patch)


def test_the_gate_ignores_errors_the_text_already_had(tmp_path):
    broken = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.no\n"
                     "  b:\n    type: circle\n    radius: 5%r\n    color: color.fg\n")
    path = tmp_path / "face.yaml"
    gate = Gate(path, broken)
    assert gate.before.errors
    # A text that did not load may be patched while it adds no error: the
    # editor fixes a face one step at a time (a missing font, then the next).
    patch = set_value(SpanIndex(broken), ("elements", "b", "radius"), "6%r")
    after = gate.check(patch)
    assert after.face is None and after.errors
    # ...and a patch that adds an error is still refused, for that error.
    worse = set_value(SpanIndex(broken), ("elements", "b", "color"), "color.nope")
    with pytest.raises(Refused, match="nope"):
        gate.check(worse)


@pytest.mark.parametrize("path", FACES, ids=lambda p: str(p.relative_to(ROOT / "examples")))
def test_the_index_data_is_exactly_what_the_text_parses_to(path):
    # one scan builds the nodes and the data; a folded scalar is where the
    # round-trip composer's values and the parser's disagree
    text = path.read_text()
    assert ordered(SpanIndex(text).data) == ordered(parse(text))


def test_invalid_yaml_is_refused_not_raised():
    with pytest.raises(Refused, match="not valid YAML"):
        SpanIndex("a: [1, 2\n")


def test_diagnostics_name_the_design_not_a_scratch_file(tmp_path):
    path = tmp_path / "face.yaml"
    loaded = load_text(path, minimal("elements:\n  a:\n    type: circle\n    color: color.no\n"))
    assert loaded.errors
    assert all(d.span is None or d.span.path == path for d in loaded.errors)


# -- unit conversion -----------------------------------------------------------------------

def test_pixels_per_unit():
    screen = Box(0, 0, 260, 280)
    assert px_per_unit("px", axis=Axis.X, parent=screen, minor_radius=130) == 1
    assert px_per_unit("%r", axis=Axis.X, parent=screen, minor_radius=130) == 1.3
    assert px_per_unit("%", axis=Axis.Y, parent=screen, minor_radius=130) == 2.8
    assert px_per_unit("%", axis=Axis.MINOR, parent=screen, minor_radius=130) == 2.6
    assert px_per_unit("pt", axis=Axis.X, parent=screen, minor_radius=130, font_px=20) == 20
    with pytest.raises(Refused, match="pt"):
        px_per_unit("pt", axis=Axis.X, parent=screen, minor_radius=130)


def test_candidates_run_coarse_to_fine_and_stay_within_half_a_pixel():
    # 4 px at 1.3 px per %r is 3.0769%r: 10 and 5 are too far, 1 lands
    # within 0.1 px, then each finer step once
    assert candidates(4 / 1.3, (10, 5, 1, 0.5, 0.1, 0.05, 0.01), 1.3) == [3, 3.1, 3.08]
    # the finest is kept even when it is half a pixel out, as the last resort
    assert candidates(0.5, (1,), 1.0) == [0]


# -- drags on the three verification devices ------------------------------------------------

@pytest.fixture(scope="module")
def shapes_views(db):
    text = SHAPES.read_text(encoding="utf-8")
    return {d: View(SHAPES, text, db.get(d)) for d in TARGETS}


def _placed_on(db, path: Path, text: str, device: str, element: str):
    return View(path, text, db.get(device)).placed(element)


@pytest.mark.parametrize("device", TARGETS)
def test_a_move_lands_on_the_dragged_pixel(shapes_views, device):
    view = shapes_views[device]
    gate = Gate(SHAPES, view.index.text)
    for element in view.face.walk():
        if element.id == "chevron":  # a polygon: refused, below
            continue
        before = view.placed(element.id)
        converted = move(view, element.id, 3, -4)
        assert converted.landed, (element.id, converted.patch.what)
        loaded = gate.check(converted.patch)
        assert loaded.face is not None
        after = view.placed(element.id, view.place(loaded))
        assert after.center == (before.center[0] + 3, before.center[1] - 4)


@pytest.mark.parametrize("device", TARGETS)
def test_a_resize_lands_on_the_dragged_pixel(shapes_views, device):
    view = shapes_views[device]
    done = 0
    for element, key in (("card", ("size", "width")), ("card", ("size", "height")),
                         ("outer_arc", ("radius",)), ("outer_arc", ("thickness",)),
                         ("dot", ("radius",))):
        if view.index.get(view.author_path(element) + key) is None:
            continue
        converted = resize(view, element, key, -2)
        assert converted.landed, (element, key, converted.patch.what)
        done += 1
    assert done >= 4


def test_a_move_keeps_the_authors_unit(shapes_views):
    view = shapes_views["fenix8solar47mm"]
    patch = move(view, "card", 0, 5).patch
    # `card` writes `dy: -22%`; `%` of 260 px is 2.6 px, so +5 px is about
    # +1.9%, rounded to the coarsest step that still lands
    assert "at: { anchor: center, dy: -20% }" in patch.text
    patch = move(view, "outer_arc", 7, 0).patch
    # an absent `dx` with no sibling is written in %r
    assert "at: { anchor: center, dx: 5.5%r }" in patch.text


def test_a_polygon_move_is_refused(shapes_views):
    with pytest.raises(Refused, match="polygon"):
        move(shapes_views["fenix8solar47mm"], "chevron", 1, 1)


@pytest.mark.parametrize("device", TARGETS)
def test_a_polar_move_rewrites_angle_and_radius(db, device):
    path = ROOT / "examples/features/align/face.yaml"
    view = View(path, path.read_text(encoding="utf-8"), db.get(device))
    for element in ("ne_card", "se_card", "nw_card", "top_accent"):
        converted = move(view, element, 4, 3)
        assert converted.landed, (element, converted.patch.what)
        data = _data(SpanIndex(converted.patch.text), view.author_path(element) + ("at",))
        assert set(data) == {"anchor", "angle", "radius"}
        assert data["angle"].endswith("deg") and data["radius"].endswith("%r")


@pytest.mark.parametrize("device", TARGETS)
def test_a_group_and_its_child_move(db, device):
    path = ROOT / "examples/features/rings/face.yaml"
    view = View(path, path.read_text(encoding="utf-8"), db.get(device))
    for element in ("heart_rate", "heart_value"):
        assert move(view, element, -2, 3).landed, element


def test_the_static_block_is_not_an_element(db):
    path = ROOT / "examples/features/align/face.yaml"
    view = View(path, path.read_text(encoding="utf-8"), db.get("fenix8solar47mm"))
    with pytest.raises(Refused, match="block"):
        move(view, "static", 3, 0)


# -- the override target ---------------------------------------------------------------------

def _with_fr955_override(text: str) -> str:
    index = SpanIndex(text)
    return set_value(index, ("elements", "card", "overrides", "fr955", "at", "dy"), "-17%").text


def test_the_target_is_the_most_specific_source(db):
    text = _with_fr955_override(SHAPES.read_text(encoding="utf-8"))
    index = SpanIndex(text)
    card = ("elements", "card")
    fr955, fenix = db.get("fr955"), db.get("fenix8solar47mm")
    assert target(index, card, ("at", "dy"), fr955) == card + ("overrides", "fr955", "at", "dy")
    assert target(index, card, ("at", "dy"), fenix) == card + ("at", "dy")
    # the override has no dx: it merges key by key, so dx is the element's own
    assert target(index, card, ("at", "dx"), fr955) == card + ("at", "dx")
    assert target(index, card, ("at", "dy"), fr955, "all") == card + ("at", "dy")
    assert target(index, card, ("at", "dy"), fenix, "shape") == card + (
        "overrides", "shape:round", "at", "dy")


@pytest.mark.parametrize("device", TARGETS)
def test_a_drag_moves_exactly_the_devices_that_read_the_patched_key(db, device):
    text = _with_fr955_override(SHAPES.read_text(encoding="utf-8"))
    view = View(SHAPES, text, db.get(device))
    patch = move(view, "card", 0, 6).patch
    reads_shared = {"fenix8solar47mm", "fenix8solar51mm"}
    moved = {d for d in TARGETS
             if _placed_on(db, SHAPES, patch.text, d, "card").center
             != _placed_on(db, SHAPES, text, d, "card").center}
    assert moved == ({"fr955"} if device == "fr955" else reads_shared)


def test_a_this_device_drag_creates_the_override(db):
    text = SHAPES.read_text(encoding="utf-8")
    view = View(SHAPES, text, db.get("fenix8solar51mm"))
    converted = move(view, "card", 0, 6, scope="device")
    assert converted.landed
    card = converted.patch.expected["elements"]["card"]
    assert card["at"] == {"anchor": "center", "dy": "-22%"}
    assert set(card["overrides"]) == {"fenix8solar51mm"}
    moved = {d for d in TARGETS
             if _placed_on(db, SHAPES, converted.patch.text, d, "card").center
             != _placed_on(db, SHAPES, text, d, "card").center}
    assert moved == {"fenix8solar51mm"}


# -- block values, renames and references ----------------------------------------------

@pytest.mark.parametrize("path", FACES, ids=lambda p: str(p.relative_to(ROOT / "examples")))
def test_a_list_replaces_targets_in_its_own_style(path):
    text = path.read_text()
    index = SpanIndex(text)
    targets = list(index.data["build"]["targets"])
    patch = set_value(index, ("build", "targets"), list(reversed(targets)) + ["fenix7"])
    Gate(path, text).check(patch)
    after = SpanIndex(patch.text)
    assert after.data["build"]["targets"] == list(reversed(targets)) + ["fenix7"]
    entry = index[("build", "targets")]
    block = not getattr(entry.value, "flow_style", False)
    assert block == (not getattr(after[("build", "targets")].value, "flow_style", False))
    # nothing outside the key's line and its value changed
    head = text[:text.rfind("\n", 0, entry.key.start_mark.index) + 1]
    tail = text[index.value_end(entry):]
    assert patch.text.startswith(head) and patch.text.endswith(tail)
    assert len(patch.text) > len(head) + len(tail)


def test_a_block_mapping_is_replaced_at_its_indent_keeping_the_key_line():
    text = ("format: 2\nresources:\n  palette:  # the swatches\n    a: \"#000000\"\n"
            "    # a comment inside goes with the old value\n    b: \"#FFFFFF\"\nelements: {}\n")
    patch = set_value(SpanIndex(text), ("resources", "palette"), {"a": "#000000", "c": "#555555"})
    assert patch.text == ("format: 2\nresources:\n  palette:  # the swatches\n"
                          "    a: \"#000000\"\n    c: \"#555555\"\nelements: {}\n")
    assert parse(patch.text) == patch.expected
    emptied = set_value(SpanIndex(text), ("resources", "palette"), {})
    assert parse(emptied.text)["resources"]["palette"] == {}


@pytest.mark.parametrize("path", FACES, ids=lambda p: str(p.relative_to(ROOT / "examples")))
def test_every_colour_renames_with_its_references_and_back(path):
    text = path.read_text()
    index = SpanIndex(text)
    palette = (index.data.get("resources") or {}).get("palette") or {}
    gate = Gate(path, text)
    for name in palette:
        patch = rename_reference(index, ("resources", "palette", name), f"{name}_x", "color.")
        gate.check(patch)
        assert f"color.{name}_x" in patch.text or f"color.{name}" not in text
        back = rename_reference(SpanIndex(patch.text), ("resources", "palette", f"{name}_x"),
                                name, "color.")
        assert back.text == text


def test_a_rename_reaches_into_expressions_but_not_longer_names():
    text = ("resources:\n  palette:\n    a: \"#000000\"\n    ab: \"#FFFFFF\"\n"
            "elements:\n  x:\n    color: \"cond ? color.a : color.ab\"\n"
            "    choices: [color.a, color.ab]\n    text: 'color.a'\n")
    patch = rename_reference(SpanIndex(text), ("resources", "palette", "a"), "z", "color.")
    data = parse(patch.text)
    assert list(data["resources"]["palette"]) == ["z", "ab"]
    assert data["elements"]["x"] == {"color": "cond ? color.z : color.ab",
                                     "choices": ["color.z", "color.ab"], "text": "color.z"}
    assert "text: 'color.z'" in patch.text           # its own quoting kept


def test_a_rename_onto_an_existing_name_is_refused():
    text = "resources:\n  palette:\n    a: \"#000000\"\n    b: \"#FFFFFF\"\n"
    with pytest.raises(Refused, match="already exists"):
        rename_key(SpanIndex(text), ("resources", "palette", "a"), "b")


def test_rewrite_leaves_keys_and_block_scalars_alone():
    text = "color.a: color.a\nnote: |\n  color.a\nlist: [color.a]\n"
    patch = rewrite_scalars(SpanIndex(text), lambda s: s.replace("color.a", "color.b"), "x")
    assert patch.text == "color.a: color.b\nnote: |\n  color.a\nlist: [color.b]\n"


def test_a_chain_checks_its_first_step():
    index = SpanIndex("a: 1\n")
    lying = Patch("a: 2\n", {"a": 1}, "lie")
    with pytest.raises(Refused, match="more than intended"):
        chain(lying, lambda i: set_value(i, ("a",), 3))


@pytest.mark.parametrize("device", TARGETS)
def test_a_lines_ends_move_apart_and_land(shapes_views, device):
    view = shapes_views[device]
    lines = [e.id for e in view.face.walk()
             if getattr(e, "shape", None) == "line"]
    assert lines, "the shapes face has a line"
    for line in lines:
        before = view.placed(line)
        start = move(view, line, 4, -3, part="at")
        assert start.landed
        placed = view.placed(line, view.place(load_text(SHAPES, start.patch.text)))
        assert placed.center == (before.center[0] + 4, before.center[1] - 3)
        assert placed.end == before.end                  # the other end stays
        end = move(view, line, -5, 2, part="to")
        assert end.landed
        placed = view.placed(line, view.place(load_text(SHAPES, end.patch.text)))
        assert placed.end == (before.end[0] - 5, before.end[1] + 2)
        assert placed.center == before.center
    with pytest.raises(Refused, match="not a line"):
        move(view, "card", 1, 1, part="to")


@pytest.mark.parametrize("device", TARGETS)
def test_an_arcs_angles_turn_in_the_authors_unit(shapes_views, device):
    view = shapes_views[device]
    before = view.placed("outer_arc")
    turned = turn(view, "outer_arc", "sweep", float(before.sweep) - 23)
    assert turned.landed
    data = SpanIndex(turned.patch.text).data
    assert data["elements"]["outer_arc"]["sweep"] == f"{before.sweep - 23:g}deg"
    rotated = turn(view, "outer_arc", "start_angle", 33.3)
    assert rotated.landed
    assert SpanIndex(rotated.patch.text).data["elements"]["outer_arc"]["start_angle"] == "33deg"
    with pytest.raises(Refused, match="no start_angle"):
        turn(view, "card", "start_angle", 10)
    with pytest.raises(Refused, match="not start_angle or sweep"):
        turn(view, "outer_arc", "radius", 10)


# -- structure: blocks, groups, every type ------------------------------------------------

def _blocks(index):
    out = {}
    for e in index.elements():
        out.setdefault(e.path[:-1], []).append(e)
    return out


def _placements(path, text, device):
    from wfb.build import resolve_all
    from wfb.diagnostics import Bag

    loaded = load_text(path, text)
    resolved, _ = resolve_all(loaded.face, [device], Bag())
    return {p.id: (p.box, p.center) for p in resolved[device.id].items}


@pytest.mark.parametrize("path", FACES, ids=lambda p: str(p.relative_to(ROOT / "examples")))
def test_grouping_moves_nothing_and_ungrouping_gives_the_text_back(path, db):
    text = path.read_text()
    index = SpanIndex(text)
    gate = Gate(path, text)
    device = db.get("fr955")
    before = None
    for block, entries in _blocks(index).items():
        if len(entries) < 2 or entries[0].is_flow or entries[1].is_flow:
            continue
        try:
            patch = group(index, [entries[0].path, entries[1].path])
            gate.check(patch)
        except Refused as exc:
            assert "subscreen" in str(exc)          # only a top-level element may use it
            continue
        before = before or _placements(path, text, device)
        after = _placements(path, patch.text, device)
        assert all(after[k] == v for k, v in before.items() if k in after), block
        made = SpanIndex(patch.text)
        new = next(e for e in made.elements() if e.name not in index.element_ids())
        assert ungroup(made, new.path).text == text


def test_an_element_moves_between_blocks_creating_and_emptying_them():
    text = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n"
                   "  # b's own comment travels with it\n"
                   "  b:\n    type: circle\n    radius: 6%r\n    color: color.fg\n")
    index = SpanIndex(text)
    moved = move_to_block(index, ("elements", "b"), ("static",))
    data = parse(moved.text)
    assert list(data["static"]) == ["b"] and list(data["elements"]) == ["a"]
    assert "  # b's own comment travels with it\n  b:\n" in moved.text
    back = move_to_block(SpanIndex(moved.text), ("static", "b"), ("elements",))
    assert parse(back.text)["elements"] == parse(text)["elements"]
    assert "static" not in parse(back.text)          # the emptied block went
    # into a group's children, before one of them, re-indented
    grouped = group(SpanIndex(text), [("elements", "a")], "g")
    into = move_to_block(SpanIndex(grouped.text), ("elements", "b"), ("elements", "g", "children"),
                         before="a")
    assert list(parse(into.text)["elements"]["g"]["children"]) == ["b", "a"]
    assert "      b:\n        type: circle\n" in into.text


def test_structure_refuses_what_it_cannot_do():
    text = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n"
                   "  g:\n    type: group\n    at: { anchor: center, dy: 5%r }\n"
                   "    children:\n      c:\n        type: circle\n        radius: 2%r\n"
                   "        color: color.fg\n")
    index = SpanIndex(text)
    with pytest.raises(Refused, match="already in"):
        move_to_block(index, ("elements", "a"), ("elements",))
    with pytest.raises(Refused, match="into itself"):
        move_to_block(index, ("elements", "g"), ("elements", "g", "children"))
    with pytest.raises(Refused, match="not an element block"):
        move_to_block(index, ("elements", "a"), ("resources",))
    with pytest.raises(Refused, match="not a group"):
        move_to_block(index, ("elements", "g", "children", "c"), ("elements", "a", "children"))
    with pytest.raises(Refused, match="side by side in one block"):
        group(index, [("elements", "a"), ("elements", "g", "children", "c")])
    with pytest.raises(Refused, match="has at"):
        ungroup(index, ("elements", "g"))
    with pytest.raises(Refused, match="needs its series"):
        add(index, "graph")
    with pytest.raises(Refused, match="no element type"):
        add(index, "teapot")


@pytest.mark.parametrize("type_", sorted(set(element_types()) - {"data", "hands"}))
def test_every_type_can_be_added(type_):
    text = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n")
    patch = add(SpanIndex(text), type_, choice="steps" if type_ == "graph" else None)
    Gate(SHAPES, text).check(patch)
    assert parse(patch.text)["elements"][f"new_{type_}"]["type"] == type_


def test_a_data_element_can_be_added_on_a_declared_slot():
    text = minimal("config:\n  slots:\n    top: { default: steps, choices: any }\n"
                   "elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n")
    patch = add(SpanIndex(text), "data", choice="top")
    Gate(SHAPES, text).check(patch)
    assert parse(patch.text)["elements"]["new_data"]["slot"] == "top"
