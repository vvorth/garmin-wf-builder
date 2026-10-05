"""`wfb studio`'s canvas: the fast frame, its items and handles, layers,
thumbnails, drags through the gate, and the compressed history."""

from __future__ import annotations

import io
import json
import zlib
from pathlib import Path

import pytest
from PIL import Image
from starlette.testclient import TestClient

from wfb import starters
from wfb.edit import Refused, SpanIndex, View, move, resize, turn
from wfb.studio.app import create_app
from wfb.studio.bundle import Bundle, read_upload
from wfb.studio.document import FrameKey, StaleVersion, Studio
from wfb.studio.drag import handles
from wfb.studio.store import Store

ROOT = Path(__file__).resolve().parent.parent
SHAPES = ROOT / "examples/features/shapes/face.yaml"
#: The faces with the most kinds of handle between them.
HANDLED = [ROOT / f"examples/features/{name}/face.yaml"
           for name in ("shapes", "rings", "align", "progress", "gauge")]


@pytest.fixture
def studio(tmp_path, db):
    s = Studio(Store(tmp_path / "state"), db, scratch=tmp_path / "scratch")
    yield s
    s.close()


@pytest.fixture
def client(studio):
    return TestClient(create_app(studio))


def shapes(studio):
    return studio.create(read_upload("face.yaml", SHAPES.read_bytes()), "open")


def items(frame):
    return {i["id"]: i for i in frame["items"]}


# -- handles ----------------------------------------------------------------------------

def test_each_kind_gets_its_own_handles(studio):
    doc = shapes(studio)
    by_id = items(doc.frame(FrameKey("fr955", scale=1)))
    kinds = {i: sorted({(h["kind"], tuple(h.get("key", ())) or h.get("part")) for h in it["handles"]},
                       key=str) for i, it in by_id.items()}
    assert ("size", ("radius",)) in kinds["dot"]
    assert ("size", ("size", "width")) in kinds["card"] and ("size", ("size", "height")) in kinds["card"]
    assert {("angle", "start_angle"), ("angle", "sweep")} <= {
        (h["kind"], h["key"]) for h in by_id["outer_arc"]["handles"] if h["kind"] == "angle"}
    line = next(i for i, it in by_id.items() if any(h["kind"] == "end" for h in it["handles"]))
    assert {h["part"] for h in by_id[line]["handles"]} == {"at", "to"}
    assert by_id["chevron"]["handles"] == []          # a polygon is edited in the text


@pytest.mark.parametrize("align, side, gain", [
    ("top_left", "right", 1), ("center", "right", 2), ("right", "left", -1)])
def test_a_size_handle_sits_on_the_edge_that_moves(studio, align, side, gain):
    text = starters.instantiate("minimal", "H").replace(
        "static:\n", "static:\n  box:\n    type: rectangle\n    at: { anchor: center }\n"
        f"    size: {{ width: 40px, height: 20px }}\n    align: {align}\n"
        "    color: color.dim\n", 1)
    doc = studio.create(Bundle("H", text), "new")
    box = items(doc.frame(FrameKey("fr955", scale=1)))["box"]
    width = next(h for h in box["handles"] if h["key"] == ["size", "width"])
    x, _, w, _ = box["box"]
    assert width["gain"] == gain and width["x"] == (x + w if side == "right" else x)


@pytest.mark.parametrize("path", HANDLED, ids=lambda p: p.parent.name)
def test_every_handle_offered_is_a_drag_that_lands(path, db):
    """A handle never offers a drag the engine refuses."""
    text = path.read_text()
    device = db.get("fr955")
    view = View(path, text, device)
    tried = 0
    for placed in view.resolved.items:
        for h in handles(placed):
            if h["kind"] == "end":
                converted = move(view, placed.id, 3, -2, part=h["part"])
            elif h["kind"] == "size":
                converted = resize(view, placed.id, tuple(h["key"]), 2)
            else:
                current = float(h["start"] if h["key"] == "start_angle" else h["sweep"])
                converted = turn(view, placed.id, h["key"], current - 12)
            assert converted.landed, (placed.id, h)
            tried += 1
    assert tried


# -- frames, layers, thumbnails ------------------------------------------------------------

def test_the_frame_is_the_render_with_items_and_its_layers(studio):
    doc = shapes(studio)
    key = FrameKey("fr955", scale=2)
    frame = doc.frame(key)
    assert frame["minor_radius"] == 130
    assert all(set(i) >= {"id", "kind", "box", "center", "handles", "drawn", "line"}
               for i in frame["items"])
    drawn = {i["id"] for i in frame["items"] if i["drawn"]}
    assert {l["id"] for l in frame["layers"] if not l["id"].startswith("ring:")} == drawn
    png = doc.thumbnail(FrameKey("fenix8solar51mm", scale=1))
    assert Image.open(io.BytesIO(png)).size == (280, 280)


def test_a_group_is_an_item_even_though_it_draws_nothing(studio):
    doc = studio.create(read_upload("face.yaml",
                                    (ROOT / "examples/features/align/face.yaml").read_bytes()),
                        "open")
    groups = [i for i in doc.frame(FrameKey("fr955"))["items"] if i["kind"] == "group"]
    assert groups and not any(g["drawn"] for g in groups)


# -- drags -------------------------------------------------------------------------------

def test_a_drag_moves_the_element_by_the_dragged_pixels(studio):
    doc = shapes(studio)
    before = items(doc.frame(FrameKey("fr955")))["dot"]["center"]
    change, landed = doc.drag("dot", {"kind": "move", "dx": 5, "dy": -3}, "fr955", "auto",
                              doc.version)
    assert landed and change.label == "move dot by (+5, -3) px on fr955"
    after = items(doc.frame(FrameKey("fr955")))["dot"]["center"]
    assert after == [before[0] + 5, before[1] - 3]
    doc.undo(doc.version)
    assert items(doc.frame(FrameKey("fr955")))["dot"]["center"] == before


def test_a_drag_on_one_device_can_leave_the_others_alone(studio):
    doc = shapes(studio)
    other = items(doc.frame(FrameKey("fenix8solar47mm")))["dot"]["center"]
    doc.drag("dot", {"kind": "move", "dx": 4, "dy": 0}, "fr955", "device", doc.version)
    assert "fr955" in SpanIndex(doc.text).data["elements"]["dot"]["overrides"]
    assert items(doc.frame(FrameKey("fenix8solar47mm")))["dot"]["center"] == other
    # "auto" now writes where fr955 reads: its override
    doc.drag("dot", {"kind": "move", "dx": 1, "dy": 0}, "fr955", "auto", doc.version)
    assert items(doc.frame(FrameKey("fenix8solar47mm")))["dot"]["center"] == other


def test_a_drag_loads_the_face_once(studio, monkeypatch):
    import wfb.edit.gate as gate_mod
    import wfb.edit.geometry as geometry_mod

    doc = shapes(studio)
    doc.analysis()
    loads = []

    def counted(path, text):
        loads.append(text)
        return gate_mod_load(path, text)

    gate_mod_load = gate_mod.load_text
    monkeypatch.setattr(gate_mod, "load_text", counted)
    monkeypatch.setattr(geometry_mod, "load_text", counted)
    doc.drag("dot", {"kind": "move", "dx": 2, "dy": 2}, "fr955", "auto", doc.version)
    assert len(loads) == 1, "the engine's load of the landing text is the gate's"


def test_refused_drags_leave_the_face_alone(studio):
    doc = shapes(studio)
    before = (doc.text, doc.version)
    with pytest.raises(Refused, match="polygon"):
        doc.drag("chevron", {"kind": "move", "dx": 1, "dy": 0}, "fr955", "auto", doc.version)
    with pytest.raises(Refused, match="unknown gesture"):
        doc.drag("dot", {"kind": "spin"}, "fr955", "auto", doc.version)
    with pytest.raises(Refused, match="needs its values"):
        doc.drag("dot", {"kind": "move", "dx": 1}, "fr955", "auto", doc.version)
    with pytest.raises(Refused, match="not a line"):
        doc.drag("dot", {"kind": "move", "dx": 1, "dy": 1, "part": "to"}, "fr955", "auto",
                 doc.version)
    with pytest.raises(Refused, match="scope"):
        doc.drag("dot", {"kind": "move", "dx": 1, "dy": 1}, "fr955", "everywhere", doc.version)
    with pytest.raises(StaleVersion):
        doc.drag("dot", {"kind": "move", "dx": 1, "dy": 1}, "fr955", "auto", 0)
    assert (doc.text, doc.version) == before


def test_a_selection_moves_together_as_one_change(studio):
    doc = shapes(studio)
    before = items(doc.frame(FrameKey("fr955")))
    version = doc.version
    change, landed = doc.move_all(["dot", "card"], 5, -3, "fr955", "auto", doc.version)
    assert landed and change.label == "move dot, card by (+5, -3) px on fr955"
    assert doc.version == version + 1, "one change, so one undo"
    after = items(doc.frame(FrameKey("fr955")))
    for element in ("dot", "card"):
        assert after[element]["center"] == [before[element]["center"][0] + 5,
                                            before[element]["center"][1] - 3]
    assert after["label"]["center"] == before["label"]["center"]
    doc.undo(doc.version)
    undone = items(doc.frame(FrameKey("fr955")))
    assert undone["dot"]["center"] == before["dot"]["center"]
    assert undone["card"]["center"] == before["card"]["center"]


def test_a_group_and_its_member_selected_together_move_once(studio):
    doc = shapes(studio)
    block = next(b for b in doc.tree() if b["path"] == ["elements"])
    paths = [n["path"] for n in block["children"] if n["id"] in ("dot", "card")]
    _, group_id = doc.structure({"op": "group", "paths": paths}, doc.version)
    assert group_id
    before = items(doc.frame(FrameKey("fr955")))
    _, landed = doc.move_all([group_id, "dot"], 4, 2, "fr955", "auto", doc.version)
    after = items(doc.frame(FrameKey("fr955")))
    assert landed
    for element in ("dot", "card"):
        assert after[element]["center"] == [before[element]["center"][0] + 4,
                                            before[element]["center"][1] + 2], element


def test_drags_over_http(client):
    doc = client.post("/api/documents/upload?filename=face.yaml",
                      content=SHAPES.read_bytes()).json()
    url = f"/api/documents/{doc['id']}"
    frame = client.get(f"{url}/frame?device=fr955&scale=1").json()
    arc = items(frame)["outer_arc"]
    sweep = next(h for h in arc["handles"] if h.get("key") == "sweep")
    r = client.post(f"{url}/drag?version=1", content=json.dumps({
        "element": "outer_arc", "device": "fr955",
        "gesture": {"kind": "turn", "key": "sweep", "degrees": sweep["sweep"] - 30}}))
    assert r.status_code == 200, r.text
    assert r.json()["landed"] and r.json()["what"].startswith("turn outer_arc.sweep to")
    assert client.post(f"{url}/drag?version=1", content=json.dumps({
        "element": "dot", "device": "fr955",
        "gesture": {"kind": "move", "dx": 1, "dy": 0}})).status_code == 409
    assert client.post(f"{url}/drag?version=2", content=json.dumps({
        "element": "chevron", "device": "fr955",
        "gesture": {"kind": "move", "dx": 1, "dy": 0}})).status_code == 400
    assert client.post(f"{url}/drag?version=2", content="[]").status_code == 400
    r = client.post(f"{url}/drag?version=2", content=json.dumps({
        "elements": ["dot", "card"], "device": "fr955",
        "gesture": {"kind": "move", "dx": 2, "dy": 0}}))
    assert r.status_code == 200, r.text
    assert r.json()["what"] == "move dot, card by (+2, +0) px on fr955"
    # handles act on one element: several cannot be resized together
    r = client.post(f"{url}/drag?version=3", content=json.dumps({
        "elements": ["dot", "card"], "device": "fr955",
        "gesture": {"kind": "resize", "key": ["radius"], "delta": 2}}))
    assert r.status_code == 400 and "only be moved together" in r.text
    shown = client.get(f"{url}/frame?device=fr955&scale=1").json()
    assert shown["version"] == 3 and shown["layers"]
    assert client.get(f"{url}/layers?device=fr955").status_code == 404
    thumb = client.get(f"{url}/thumbnail?device=fr955")
    assert thumb.headers["content-type"] == "image/png"


# -- the compressed history -------------------------------------------------------------

def test_text_versions_are_stored_compressed_and_old_blobs_still_read(studio):
    doc = shapes(studio)
    store = studio.store
    blobs = store.root / doc.id / "blobs"
    head = store.head(doc.id)
    packed = blobs / f"{head.text}.z"
    assert packed.exists() and not (blobs / head.text).exists()
    assert zlib.decompress(packed.read_bytes()).decode() == doc.text
    assert packed.stat().st_size < len(doc.text.encode()) / 2
    # a store written before compression: a plain blob, still read
    plain = store.put(doc.id, b"plain bytes")
    assert (blobs / plain).exists() and store.get(doc.id, plain) == b"plain bytes"


def test_a_gesture_without_its_values_and_a_refused_gesture_say_different_things(studio):
    doc = studio.create(Bundle("T", starters.instantiate("minimal", "T")), "new")
    with pytest.raises(Refused, match="needs its values"):
        doc.drag("clock", {"kind": "move", "dx": "far"}, "fr955", "auto", doc.version)
    # a refusal from the move itself keeps its own reason
    with pytest.raises(Refused) as refused:
        doc.drag("no_such_element", {"kind": "move", "dx": 1, "dy": 0}, "fr955", "auto",
                 doc.version)
    assert "needs its values" not in str(refused.value)
    with pytest.raises(Refused, match="unknown gesture"):
        doc.drag("clock", {"kind": "spin"}, "fr955", "auto", doc.version)
