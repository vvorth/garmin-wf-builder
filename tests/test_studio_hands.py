"""`wfb studio`'s hand sets: added from a preset in the face's colours,
duplicated, renamed with every `set:`, deleted while unused, and drawn
alone for the Face panel (`wfb.edit.hands`)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image
from starlette.testclient import TestClient

from wfb import starters
from wfb.edit import Refused, SpanIndex
from wfb.edit.hands import presets
from wfb.studio.app import create_app
from wfb.studio.bundle import Bundle, from_path
from wfb.studio.document import Studio
from wfb.studio.inspect import inspect
from wfb.studio.store import Store

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def studio(tmp_path, db):
    s = Studio(Store(tmp_path / "state"), db, scratch=tmp_path / "scratch")
    yield s
    s.close()


def new(studio, template="minimal"):
    return studio.create(Bundle("T", starters.instantiate(template, "T")), "new")


def edit(doc, **op):
    doc.edit(op, doc.version)


def sets(doc):
    return SpanIndex(doc.text).data["resources"]["hand_sets"]


def hands_elements(doc):
    data = SpanIndex(doc.text).data
    return {k: v for k, v in data["elements"].items() if v.get("type") == "hands"}


def test_the_presets_are_the_four_decided():
    assert list(presets()) == ["classic", "baton", "dauphine", "subdial"]


@pytest.mark.parametrize("preset", ["classic", "baton", "dauphine", "subdial"])
def test_each_preset_loads_into_a_face_in_its_colours(studio, preset):
    doc = new(studio)
    edit(doc, op="add_hand_set", name="dial", preset=preset)
    assert doc.analysis().face is not None and not doc.analysis().bag.errors
    colors = {h["color"] for h in sets(doc)["dial"].values()}
    assert colors <= {"color.text"}                 # the minimal face's main colour
    assert hands_elements(doc) == {"new_hands": {"type": "hands", "at": {"anchor": "center"},
                                                 "set": "dial"}}


def test_a_second_set_is_not_placed_again_and_points_are_one_a_line(studio):
    doc = new(studio)
    edit(doc, op="add_hand_set", name="dial", preset="dauphine")
    edit(doc, op="add_hand_set", name="small", preset="subdial")
    assert list(hands_elements(doc)) == ["new_hands"]
    assert "          - type: polygon\n            points:\n              - { dy: 5%r }\n" in doc.text


def test_the_accent_is_used_where_the_face_has_one(studio):
    doc = new(studio, "analog")
    edit(doc, op="add_hand_set", name="dial", preset="baton")
    assert sets(doc)["dial"]["second"]["color"] == "color.accent"


def test_a_set_is_duplicated_renamed_with_its_elements_and_deleted_when_unused(studio):
    doc = new(studio)
    edit(doc, op="add_hand_set", name="dial", preset="classic")
    edit(doc, op="duplicate_hand_set", name="dial")
    assert sets(doc)["dial_copy"] == sets(doc)["dial"]
    edit(doc, op="rename_hand_set", name="dial", to="main")
    assert hands_elements(doc)["new_hands"]["set"] == "main"
    edit(doc, op="delete_hand_set", name="dial_copy")
    assert set(sets(doc)) == {"main"}


def test_hand_set_refusals_leave_the_face_alone(studio):
    doc = new(studio)
    edit(doc, op="add_hand_set", name="dial", preset="classic")
    before = (doc.text, doc.version)
    with pytest.raises(Refused, match="new_hands places the hand set dial"):
        edit(doc, op="delete_hand_set", name="dial")
    with pytest.raises(Refused, match="already"):
        edit(doc, op="add_hand_set", name="dial", preset="baton")
    with pytest.raises(Refused, match="no preset called"):
        edit(doc, op="add_hand_set", name="other", preset="nope")
    with pytest.raises(Refused, match="not a hand set name"):
        edit(doc, op="rename_hand_set", name="dial", to="1x")
    with pytest.raises(Refused, match="no hand set called"):
        edit(doc, op="duplicate_hand_set", name="nope")
    assert (doc.text, doc.version) == before


def test_the_panel_lists_each_set_with_its_lines_and_users(studio):
    bundle, moved = from_path(ROOT / "examples/showcase/face.yaml")
    doc = studio.create(bundle, "open", moved)
    by_name = {h["name"]: h for h in doc.summary()["globals"]["hands"]}
    assert set(by_name) == {"classic", "vintage"}
    classic = by_name["classic"]
    lines = doc.text.splitlines()
    assert lines[classic["line"] - 1].strip() == "classic:"
    assert lines[classic["end"] - 1].strip()               # the set's own last line
    assert next(l for l in lines[classic["end"]:]
                if l.strip() and not l.strip().startswith("#")).strip() == "vintage:"
    assert set(classic["hands"]) == {"hour", "minute", "second"}
    assert classic["placed_by"]


def test_a_hands_elements_set_is_a_choice_of_the_declared_sets(studio):
    doc = new(studio)
    edit(doc, op="add_hand_set", name="dial", preset="classic")
    path = next(e.path for e in SpanIndex(doc.text).elements() if e.name == "new_hands")
    fields = {f["key"]: f for f in inspect(doc.text, path, None)["fields"]}
    assert fields["set"]["widget"] == "handset"


def test_a_set_is_drawn_alone_over_http(studio):
    doc = new(studio)
    edit(doc, op="add_hand_set", name="dial", preset="baton")
    client = TestClient(create_app(studio))
    got = client.get(f"/api/documents/{doc.id}/handset",
                     params={"name": "dial", "device": "fr955", "scale": 2})
    assert got.status_code == 200 and got.headers["content-type"] == "image/png"
    image = Image.open(io.BytesIO(got.content))
    assert image.mode == "RGBA" and image.getchannel("A").getbbox() == (0, 0, *image.size)
    # cropped to the hands, not the screen: the sample time spreads them
    assert image.width < 2 * 260 and image.height < 2 * 260
    missing = client.get(f"/api/documents/{doc.id}/handset",
                         params={"name": "nope", "device": "fr955"})
    assert missing.status_code == 400 and "no hand set called nope" in missing.json()["error"]
    # the throwaway file it loads beside the face is gone again
    assert not (doc.directory / ".hand-set.yaml").exists()


@pytest.mark.slow
@pytest.mark.parametrize("preset", ["classic", "baton", "dauphine", "subdial"])
def test_each_preset_builds_warning_free_on_every_target(studio, preset, write_design, tmp_path,
                                                         toolchain):
    """The preset added by the editor, placed by the `hands` element it adds,
    compiled by the real `monkeyc` for the verification devices."""
    from wfb.build import build as real_build
    from wfb.diagnostics import Bag

    doc = new(studio)
    edit(doc, op="add_hand_set", name="dial", preset=preset)
    bag = Bag()
    result = real_build(write_design(doc.text), output=tmp_path / "out", bag=bag, db=studio.db,
                        toolchain=toolchain)
    assert result is not None, bag.render()
    warnings = [d for d in bag.items if d.severity.value == "warning"]
    assert bag.ok() and not warnings, bag.render()
