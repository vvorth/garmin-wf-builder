"""`wfb studio`'s structural edits: the Layers panel's add, delete,
duplicate, reorder, move between blocks, group and ungroup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from wfb import starters
from wfb.edit import Refused, SpanIndex
from wfb.studio.app import create_app
from wfb.studio.bundle import Bundle, read_upload
from wfb.studio.document import StaleVersion, Studio
from wfb.studio.store import Store

ROOT = Path(__file__).resolve().parent.parent
STYLES = ROOT / "examples/features/styles/face.yaml"


@pytest.fixture
def studio(tmp_path, db):
    s = Studio(Store(tmp_path / "state"), db, scratch=tmp_path / "scratch")
    yield s
    s.close()


def new(studio):
    return studio.create(Bundle("T", starters.instantiate("minimal", "T")), "new")


def ids(doc, block=("elements",)):
    data = SpanIndex(doc.text).data
    for step in block:
        data = data[step]
    return list(data)


def test_add_duplicate_reorder_delete(studio):
    doc = new(studio)
    _, made = doc.structure({"op": "add", "type": "circle", "block": ["elements"],
                             "before": "seconds"}, doc.version)
    assert made == "new_circle" and ids(doc) == ["clock", "new_circle", "seconds"]
    _, copy = doc.structure({"op": "duplicate", "path": ["elements", "clock"]}, doc.version)
    assert copy == "clock_copy" and ids(doc)[:2] == ["clock", "clock_copy"]
    doc.structure({"op": "move", "path": ["elements", "seconds"], "block": ["elements"],
                   "before": "clock"}, doc.version)
    assert ids(doc)[0] == "seconds"
    doc.structure({"op": "move", "path": ["elements", "seconds"], "block": ["elements"]},
                  doc.version)
    assert ids(doc)[-1] == "seconds"
    doc.structure({"op": "delete", "path": ["elements", "clock_copy"]}, doc.version)
    assert "clock_copy" not in ids(doc)
    labels = [s["label"] for s in doc.history()["states"]][:5]
    assert labels[-1] == "add new_circle" and labels[0] == "delete clock_copy"


def test_static_and_dynamic_and_the_gate(studio):
    doc = new(studio)
    doc.structure({"op": "add", "type": "rectangle", "block": ["elements"]}, doc.version)
    doc.structure({"op": "move", "path": ["elements", "new_rectangle"], "block": ["static"]},
                  doc.version)
    assert ids(doc, ("static",)) == ["background", "new_rectangle"]
    with pytest.raises(Refused, match="time.clock"):
        doc.structure({"op": "move", "path": ["elements", "clock"], "block": ["static"]},
                      doc.version)


def test_moves_across_layouts(studio):
    doc = studio.create(read_upload("face.yaml", STYLES.read_bytes()), "open")
    labels = [b["label"] for b in doc.tree()]
    assert {"big: static", "big: elements", "compact: static", "compact: elements"} <= set(labels)
    source = next(b for b in doc.tree() if b["label"] == "big: static" and b["children"])
    element = source["children"][0]
    doc.structure({"op": "move", "path": element["path"],
                   "block": ["layouts", "compact", "static"]}, doc.version)
    assert element["id"] in ids(doc, ("layouts", "compact", "static"))


def test_group_and_ungroup_select_and_restore(studio):
    doc = new(studio)
    original = doc.text
    _, made = doc.structure({"op": "group", "paths": [["elements", "clock"],
                                                      ["elements", "seconds"]]}, doc.version)
    assert made == "group" and ids(doc) == ["group"]
    doc.structure({"op": "ungroup", "path": ["elements", "group"]}, doc.version)
    assert doc.text == original


def test_an_empty_block_is_listed_and_filled(studio):
    text = starters.instantiate("minimal", "E")
    without_static = text[:text.index("static:")] + text[text.index("elements:"):]
    doc = studio.create(Bundle("E", without_static), "new")
    static = next(b for b in doc.tree() if b["path"] == ["static"])
    assert static["line"] is None and static["children"] == []
    doc.structure({"op": "add", "type": "rectangle", "block": ["elements"]}, doc.version)
    doc.structure({"op": "move", "path": ["elements", "new_rectangle"], "block": ["static"]},
                  doc.version)
    assert ids(doc, ("static",)) == ["new_rectangle"]


def test_refusals_leave_the_face_alone(studio):
    doc = new(studio)
    before = (doc.text, doc.version)
    with pytest.raises(Refused, match="unknown structural edit"):
        doc.structure({"op": "explode"}, doc.version)
    with pytest.raises(Refused, match="needs its slot"):
        doc.structure({"op": "add", "type": "data"}, doc.version)
    with pytest.raises(Refused, match="not in"):
        doc.structure({"op": "move", "path": ["elements", "clock"], "block": ["elements"],
                       "before": "nope"}, doc.version)
    with pytest.raises(Refused, match="list of paths"):
        doc.structure({"op": "group", "paths": "clock"}, doc.version)
    with pytest.raises(StaleVersion):
        doc.structure({"op": "delete", "path": ["elements", "clock"]}, 0)
    assert (doc.text, doc.version) == before


def node(doc, element_id):
    def walk(nodes):
        for n in nodes:
            if n["kind"] == "element" and n["id"] == element_id:
                return n
            found = walk(n.get("children", []))
            if found:
                return found
        return None
    return walk(doc.tree())


@pytest.mark.parametrize("face, element, reason", [
    # the layout's only element: the emptied layout goes with it, and a
    # style still names it
    ("analog", "sport_hands", "unknown layout 'sport'"),
    # a group's only child: a group with no children is not a group
    ("aod", "date_text", "missing required key 'children'"),
])
def test_a_delete_that_would_leave_a_dangling_name_is_refused(studio, face, element, reason):
    doc = studio.create(read_upload(
        "face.yaml", (ROOT / f"examples/features/{face}/face.yaml").read_bytes()), "open")
    before = (doc.text, doc.version)
    with pytest.raises(Refused, match=reason):
        doc.structure({"op": "delete", "path": node(doc, element)["path"]}, doc.version)
    assert (doc.text, doc.version) == before


def test_structure_over_http(tmp_path, studio):
    client = TestClient(create_app(studio))
    doc = client.post("/api/documents/new?template=minimal&name=S").json()
    url = f"/api/documents/{doc['id']}/structure"
    r = client.post(f"{url}?version=1", content=json.dumps(
        {"op": "add", "type": "graph", "choice": "steps"}))
    assert r.status_code == 200, r.text
    assert r.json()["select"] == "new_graph" and r.json()["version"] == 2
    assert client.post(f"{url}?version=1", content="{}").status_code == 409
    assert client.post(f"{url}?version=2", content=json.dumps(
        {"op": "add", "type": "teapot"})).status_code == 400
    words = client.get("/api/vocabulary").json()
    assert "graph" in words["types"] and "steps" in words["series"]
    assert "hand_sets" in r.json()["globals"] and "slots" in r.json()["globals"]
