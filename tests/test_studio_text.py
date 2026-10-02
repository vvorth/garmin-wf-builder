"""`wfb studio`'s YAML tab: the whole text replaced as typed, its rules,
and what the pane needs from the server."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from wfb import starters
from wfb.edit import Refused
from wfb.studio.app import create_app
from wfb.studio.bundle import Bundle
from wfb.studio.document import StaleVersion, Studio
from wfb.studio.store import Store

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def studio(tmp_path, db):
    s = Studio(Store(tmp_path / "state"), db, scratch=tmp_path / "scratch")
    yield s
    s.close()


def new(studio):
    return studio.create(Bundle("T", starters.instantiate("minimal", "T")), "new")


def test_typed_text_is_recorded_as_one_change(studio):
    doc = new(studio)
    text = doc.text.replace("version: 1.0.0", "version: 2.0.0")
    change = doc.replace_text(text, doc.version)
    assert change.label == "edit the text" and doc.text == text and doc.version == 2
    assert doc.replace_text(text, doc.version) is doc.head      # the same text: nothing
    assert doc.version == 2
    doc.undo(doc.version)
    assert "version: 1.0.0" in doc.text


def test_text_that_is_not_yaml_is_refused_and_not_recorded(studio):
    doc = new(studio)
    before = (doc.text, doc.version)
    with pytest.raises(Refused, match="not valid YAML"):
        doc.replace_text(doc.text + "oops: [1, 2\n", doc.version)
    assert (doc.text, doc.version) == before


def test_text_with_errors_is_recorded_and_its_diagnostics_shown(studio):
    # the author typing passes through broken states: recorded, not refused
    doc = new(studio)
    broken = doc.text.replace("color: color.dim", "color: color.nope")
    doc.replace_text(broken, doc.version)
    assert doc.text == broken and doc.analysis().face is None
    messages = [d["message"] for d in doc.diagnostics()]
    assert any("nope" in m for m in messages)
    # and the canvas edits refuse to build on a face that does not load
    with pytest.raises(Refused):
        doc.edit({"op": "set", "path": ["elements", "clock", "color"], "value": "color.alsonope"},
                 doc.version)


def test_a_stale_text_is_refused(studio):
    doc = new(studio)
    doc.replace_text(doc.text + "\n", doc.version)
    with pytest.raises(StaleVersion):
        doc.replace_text(doc.text + "# late\n", 1)


def test_typed_text_is_loaded_once(studio, tmp_path, db, monkeypatch):
    import wfb.edit.gate as gate_mod
    import wfb.studio.document as document_mod

    doc = new(studio)
    doc.analysis()
    loads = []
    real = document_mod.load_text

    def counted(path, text):
        loads.append(text)
        return real(path, text)

    monkeypatch.setattr(document_mod, "load_text", counted)
    monkeypatch.setattr(gate_mod, "load_text", counted)
    doc.replace_text(doc.text.replace("1.0.0", "1.0.1"), doc.version)
    seeded = sorted((d["code"], d["message"]) for d in doc.diagnostics())
    assert len(loads) == 1
    monkeypatch.undo()
    fresh = Studio(Store(studio.store.root), db, scratch=tmp_path / "fresh").document(doc.id)
    assert sorted((d["code"], d["message"]) for d in fresh.diagnostics()) == seeded


def test_each_tree_node_knows_its_last_line(studio):
    doc = new(studio)
    lines = doc.text.splitlines()
    for block in doc.tree():
        for node in block["children"]:
            assert lines[node["line"] - 1].strip().startswith(f"{node['id']}:")
            last = lines[node["end"] - 1]
            assert last.strip() and last.startswith("    ")     # the element's own last line
            if node["end"] < len(lines):
                after = lines[node["end"]]
                assert not after.startswith("    ")             # the next line is not its


def test_text_and_schema_over_http(studio):
    client = TestClient(create_app(studio))
    doc = client.post("/api/documents/new?template=minimal&name=Y").json()
    url = f"/api/documents/{doc['id']}/text"
    text = doc["text"].replace("1.0.0", "1.2.3")
    r = client.post(f"{url}?version=1", content=text.encode())
    assert r.status_code == 200 and r.json()["version"] == 2
    assert client.post(f"{url}?version=1", content=text.encode()).status_code == 409
    assert client.post(f"{url}?version=2", content=b"a: [1").status_code == 400
    assert client.post(f"{url}?version=2", content=b"\xff\xfe").status_code == 400
    schema = client.get("/api/schema").json()
    assert schema["$defs"]["textElement"]["properties"]["text"]
