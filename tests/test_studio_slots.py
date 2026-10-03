"""`wfb studio`'s slots: complication types with names and groups, a slot
added with the element that draws it, the face drawn showing any one of a
slot's choices, and a data element's own keys in the inspector."""

from __future__ import annotations

from pathlib import Path

import pytest

from wfb import complications, starters
from wfb.edit import Refused, SpanIndex
from wfb.studio.bundle import Bundle, from_path
from wfb.studio.document import FrameKey, Studio
from wfb.studio.inspect import inspect, vocabulary
from wfb.studio.store import Store

ROOT = Path(__file__).resolve().parent.parent
SLOT_GAUGE = ROOT / "examples/features/slot-gauge/face.yaml"


@pytest.fixture
def studio(tmp_path, db):
    s = Studio(Store(tmp_path / "state"), db, scratch=tmp_path / "scratch")
    yield s
    s.close()


def open_example(studio, path):
    bundle, moved = from_path(path)
    return studio.create(bundle, "open", moved)


def layers(doc, **key):
    frame = doc.frame(FrameKey("fr955", **key))
    return {layer["id"]: layer for layer in frame["layers"]}, frame


def test_every_type_has_a_name_for_people_and_a_group():
    assert set(complications.PRESENTATION) == set(complications.TYPES)
    labels = [complications.label(n) for n in complications.TYPES]
    assert len(set(labels)) == len(labels)
    assert {complications.category(n) for n in complications.TYPES} == set(complications.CATEGORIES)
    assert complications.label("floors_climbed") == "Floors climbed"


def test_the_vocabulary_offers_each_type_with_its_icon_and_sample():
    types = {t["name"]: t for t in vocabulary()["complication_types"]}
    assert len(types) == 42
    assert types["heart_rate"] == {"name": "heart_rate", "label": "Heart rate",
                                   "category": "health", "icon": "heart", "sample": "72"}
    assert types["wheelchair_pushes"]["sample"] is None        # no sample reading
    assert vocabulary()["icon_glyphs"]["heart"] == 0xF02D1


def test_a_slot_is_added_with_a_data_element_drawing_it(studio):
    doc = studio.create(Bundle("T", starters.instantiate("minimal", "T")), "new")
    doc.edit({"op": "add_slot", "name": "top", "default": "heart_rate"}, doc.version)
    data = SpanIndex(doc.text).data
    assert data["config"]["slots"] == {"top": {"default": "heart_rate", "choices": "any"}}
    assert data["elements"]["new_data"]["slot"] == "top"
    assert "config:\n  slots:\n    top:\n      default: heart_rate\n" in doc.text
    before = (doc.text, doc.version)
    with pytest.raises(Refused, match="already"):
        doc.edit({"op": "add_slot", "name": "top", "default": "steps"}, doc.version)
    with pytest.raises(Refused, match="not a complication type"):
        doc.edit({"op": "add_slot", "name": "other", "default": "nope"}, doc.version)
    assert (doc.text, doc.version) == before


def test_the_face_is_drawn_showing_a_slots_pick(studio):
    doc = open_example(studio, SLOT_GAUGE)
    default, frame = layers(doc)
    battery, picked = layers(doc, picks=(("top", "battery"),))
    assert picked["frame"] != frame["frame"]
    # the ring fills against battery's own 0-100 scale, the reading is battery's
    assert battery["top_ring"]["ops"] != default["top_ring"]["ops"]
    assert battery["top_reading"]["ops"] != default["top_reading"]["ops"]
    # a pick the slot may not show is ignored: the default is drawn
    _, ignored = layers(doc, picks=(("top", "sunrise"),))
    assert ignored["frame"] == frame["frame"]


def test_a_slot_shown_with_no_scale_draws_no_gauge(studio):
    doc = open_example(studio, SLOT_GAUGE)
    default, _ = layers(doc)
    scaled, _ = layers(doc, picks=(("right", "battery"),))
    # `date` has no scale, so its gauge draws nothing; battery has one
    assert default["right_needle"]["ops"] != scaled["right_needle"]["ops"]


def test_a_data_elements_icon_is_edited_and_format_is_not_offered(studio):
    doc = open_example(studio, ROOT / "examples/showcase/face.yaml")
    path = next(e.path for e in SpanIndex(doc.text).elements() if e.name == "left_register")
    fields = {f["key"]: f for f in inspect(doc.text, path, None)["fields"]}
    assert fields["icon"]["widget"] == "object"
    assert {c["key"]: c["widget"] for c in fields["icon"]["children"]} == {
        "size": "length", "position": "enum", "gap": "length", "color": "color"}
    assert "format" not in fields
