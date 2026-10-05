"""`wfb studio`'s inspector, Face panel and edits: what an element offers,
what the face declares, and each edit through the gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from wfb import starters
from wfb.edit import Refused, SpanIndex
from wfb.studio.app import create_app
from wfb.studio.bundle import Bundle, from_path
from wfb.studio.document import StaleVersion, Studio
from wfb.studio.inspect import element_schema, globals_of, inspect
from wfb.studio.store import Store

ROOT = Path(__file__).resolve().parent.parent
FACES = sorted(p for p in (ROOT / "examples").rglob("face.yaml") if "dashboard" not in p.parts)
SHAPES = ROOT / "examples/features/shapes/face.yaml"
STYLES = ROOT / "examples/features/styles/face.yaml"
CHIVO = ROOT / "examples/showcase/assets/ChivoMono-Bold.ttf"
DYNALIGHT = ROOT / "examples/showcase/assets/Dynalight-Regular.ttf"


@pytest.fixture
def studio(tmp_path, db):
    s = Studio(Store(tmp_path / "state"), db, scratch=tmp_path / "scratch")
    yield s
    s.close()


@pytest.fixture
def client(studio):
    return TestClient(create_app(studio))


def new(studio, template="minimal"):
    return studio.create(Bundle("T", starters.instantiate(template, "T")), "new")


def element_path(doc, element_id):
    return next(e.path for e in SpanIndex(doc.text).elements() if e.name == element_id)


def fields(result):
    return {f["key"]: f for f in result["fields"]}


# -- the inspector ---------------------------------------------------------------------

@pytest.mark.parametrize("path", FACES, ids=lambda p: str(p.relative_to(ROOT / "examples")))
def test_every_key_an_element_has_is_a_field(path, db):
    text = path.read_text()
    for entry in SpanIndex(text).elements():
        result = inspect(text, entry.path, db.get("fr955"))
        assert result["unknown"] == [], (entry.name, result["unknown"])
        shown = {f["key"] for f in result["fields"]} | {"children", "overrides"}
        data = SpanIndex(text).data
        for step in entry.path:
            data = data[step]
        assert set(data) <= shown, (entry.name, set(data) - shown)


def test_a_shape_offers_its_own_keys_only(db):
    text = SHAPES.read_text()
    by_type = {}
    for entry in SpanIndex(text).elements():
        result = inspect(text, entry.path, None)
        by_type.setdefault(result["type"], fields(result))
    circle, rectangle = by_type["circle"], by_type["rectangle"]
    assert "radius" in circle and "size" not in circle and "points" not in circle
    assert "size" in rectangle and "corner_radius" in rectangle and "radius" not in rectangle
    assert "start_angle" in by_type["arc"] and "start_angle" not in rectangle


def test_widgets_follow_the_schema(db):
    doc_text = starters.instantiate("minimal", "W")
    clock = next(e.path for e in SpanIndex(doc_text).elements() if e.name == "clock")
    f = fields(inspect(doc_text, clock, db.get("fr955")))
    assert {k: f[k]["widget"] for k in ("type", "text", "font", "color", "align", "visible",
                                        "units", "z")} == {
        "type": "readonly", "text": "template", "font": "font", "color": "color",
        "align": "align", "visible": "expression", "units": "enum", "z": "number"}
    at = f["at"]
    assert at["widget"] == "object"
    assert {c["key"]: c["widget"] for c in at["children"]}["dy"] == "length"
    assert {c["key"]: c["widget"] for c in at["children"]}["angle"] == "angle"
    assert f["text"]["required"] and f["text"]["present"]
    assert not f["visible"]["present"]
    assert all(element_schema(t) for t in ("text", "circle", "gauge", "group", "hands"))


def test_the_inspector_reports_the_overrides_the_device_reads(db):
    text = starters.instantiate("minimal", "O").replace(
        "    at: { anchor: center }\n    color: color.text\n",
        "    at: { anchor: center }\n    color: color.text\n"
        "    overrides: { fr955: { at: { dy: 2px } }, \"shape:round\": { at: { dx: 1px } } }\n", 1)
    clock = next(e.path for e in SpanIndex(text).elements() if e.name == "clock")
    on_fr955 = inspect(text, clock, db.get("fr955"))["overrides"]
    assert on_fr955 == {"device": {"selector": "fr955", "keys": {"at": {"dy": "2px"}}},
                        "shape": {"selector": "shape:round", "keys": {"at": {"dx": "1px"}}}}
    # another round watch reads the shape's, not fr955's
    assert set(inspect(text, clock, db.get("fenix8solar47mm"))["overrides"]) == {"shape"}


# -- the Face panel ---------------------------------------------------------------------

def test_the_face_panel_lists_colours_schemes_styles_and_fonts(db):
    g = globals_of(STYLES.read_text(), db)
    assert {p["name"] for p in g["palette"]}
    assert g["styles"]["default"] and g["styles"]["entries"]
    assert g["layouts"] == ["big", "compact"]
    assert g["targets"] == ["fenix8solar47mm", "fenix8solar51mm", "fr955"]
    showcase = globals_of((ROOT / "examples/showcase/face.yaml").read_text(), db)
    assert {f["name"] for f in showcase["fonts"]} >= {"digitalclock", "dialfont"}
    assert next(p for p in showcase["palette"] if p["name"] == "black")["long"]


def test_a_colour_off_the_mip_palette_is_flagged_on_mip_targets_only(db):
    text = ("format: 2\nface: { id: 9c1d5f30-6a72-4b18-8d4e-0f2a71c93b64, name: P, version: 1.0.0 }\n"
            "build: { targets: [fr955, fenix8solar47mm] }\n"
            "resources:\n  palette:\n    ok: \"#55AAFF\"\n    off: \"#123456\"\n")
    by_name = {p["name"]: p for p in globals_of(text, db)["palette"]}
    assert by_name["ok"]["dithers_on"] == []
    assert set(by_name["off"]["dithers_on"]) == {"fr955", "fenix8solar47mm"}


# -- edits ----------------------------------------------------------------------------

def test_a_geometry_edit_goes_to_the_scope_asked_for(studio, db):
    doc = new(studio)
    clock = element_path(doc, "clock")
    doc.edit({"op": "set", "element": list(clock), "path": ["at", "dy"], "value": "-5%r",
              "scope": "device", "device": "fr955"}, doc.version)
    doc.edit({"op": "set", "element": list(clock), "path": ["at", "dy"], "value": "3%r",
              "scope": "shape", "device": "fr955"}, doc.version)
    doc.edit({"op": "set", "element": list(clock), "path": ["at", "dx"], "value": 2,
              "scope": "all"}, doc.version)
    data = SpanIndex(doc.text).data["elements"]["clock"]
    assert data["overrides"] == {"fr955": {"at": {"dy": "-5%r"}},
                                 "shape:round": {"at": {"dy": "3%r"}}}
    assert data["at"]["dx"] == 2
    placed = {item.id: item for item in doc.analysis().resolved["fr955"].items}["clock"]
    other = {item.id: item for item in doc.analysis().resolved["fenix8solar47mm"].items}
    assert placed.center != other["clock"].center
    labels = [s["label"] for s in doc.history()["states"]]
    assert labels[0] == "set elements.clock.at.dx to 2"


def test_only_geometry_can_be_overridden(studio):
    doc = new(studio)
    with pytest.raises(Refused, match="cannot be overridden"):
        doc.edit({"op": "set", "element": list(element_path(doc, "clock")), "path": ["font"],
                  "value": "FONT_SMALL", "scope": "device", "device": "fr955"}, doc.version)


def test_an_edit_the_gate_refuses_leaves_the_face_alone(studio):
    doc = new(studio)
    before = (doc.text, doc.version)
    with pytest.raises(Refused, match="color.nope"):
        doc.edit({"op": "set", "path": ["elements", "clock", "color"], "value": "color.nope"},
                 doc.version)
    with pytest.raises(Refused, match="color.bg"):
        doc.edit({"op": "remove", "path": ["resources", "palette", "bg"]}, doc.version)
    with pytest.raises(Refused, match="not a name"):
        doc.edit({"op": "rename", "path": ["resources", "palette", "bg"], "to": "1x",
                  "prefix": "color."}, doc.version)
    with pytest.raises(Refused, match="unknown edit"):
        doc.edit({"op": "explode"}, doc.version)
    with pytest.raises(Refused, match="is not set"):
        doc.edit({"op": "remove", "path": ["elements", "clock", "visible"]}, doc.version)
    with pytest.raises(StaleVersion):
        doc.edit({"op": "set", "path": ["face", "version"], "value": "2.0.0"}, 0)
    assert (doc.text, doc.version) == before


def test_a_colour_renamed_in_the_panel_is_renamed_everywhere(studio):
    doc = new(studio)
    doc.edit({"op": "rename", "path": ["resources", "palette", "text"], "to": "ink",
              "prefix": "color."}, doc.version)
    assert "color.text" not in doc.text and doc.text.count("color.ink") >= 1
    assert doc.analysis().face is not None
    doc.undo(doc.version)
    assert "color.text" in doc.text


def test_targets_and_a_style_are_edited_from_the_panel(studio):
    doc = studio.create(Bundle("S", STYLES.read_text()), "open")
    doc.edit({"op": "set", "path": ["build", "targets"], "value": ["fr955"]}, doc.version)
    assert doc.summary()["targets"] == ["fr955"]
    first = doc.summary()["globals"]["styles"]["entries"][0]
    doc.edit({"op": "set", "path": ["config", "style", "choices", "extra"],
              "value": {"layout": "compact", "scheme": first["scheme"]}}, doc.version)
    entries = {e["name"]: e for e in doc.summary()["globals"]["styles"]["entries"]}
    assert entries["extra"]["layout"] == "compact"


def test_a_font_is_added_and_its_file_replaced(studio):
    doc = new(studio)
    doc.add_asset("Chivo.ttf", CHIVO.read_bytes(), None, doc.version, font=("clockface", "20%r"))
    assert SpanIndex(doc.text).data["resources"]["fonts"]["clockface"] == {
        "source": "assets/Chivo.ttf", "size": "20%r"}
    with pytest.raises(Refused, match="already a font"):
        doc.add_asset("Other.ttf", CHIVO.read_bytes(), None, doc.version,
                      font=("clockface", "20%r"))
    doc.edit({"op": "set", "path": ["elements", "clock", "font"], "value": "font.clockface"},
             doc.version)
    doc.add_asset("Dyna.ttf", DYNALIGHT.read_bytes(), "assets/Chivo.ttf", doc.version)
    assert SpanIndex(doc.text).data["resources"]["fonts"]["clockface"]["source"] == \
        "assets/Dyna.ttf"
    # the replaced file is no longer referenced, so it left the bundle
    assert sorted(doc.head.assets) == ["assets/Dyna.ttf"]
    assert not (doc.directory / "assets/Chivo.ttf").exists()
    assert doc.analysis().face is not None


def test_a_refused_font_leaves_no_file_behind(studio):
    doc = new(studio)
    doc.add_asset("Chivo.ttf", CHIVO.read_bytes(), None, doc.version, font=("f", "20%r"))
    before = sorted(p.name for p in (doc.directory / "assets").iterdir())
    with pytest.raises(Refused):
        doc.add_asset("Bad.ttf", CHIVO.read_bytes(), None, doc.version, font=("f", "20%r"))
    assert sorted(p.name for p in (doc.directory / "assets").iterdir()) == before


# -- the endpoints ----------------------------------------------------------------------

def test_inspect_and_edit_over_http(client):
    doc = client.post("/api/documents/new?template=minimal&name=H").json()
    url = f"/api/documents/{doc['id']}"
    clock = next(n for b in doc["tree"] for n in b["children"] if n["id"] == "clock")
    result = client.get(f"{url}/inspect", params={"element": json.dumps(clock["path"]),
                                                   "device": "fr955"}).json()
    assert result["type"] == "text" and result["device"] == "fr955"
    r = client.post(f"{url}/edit?version=1", content=json.dumps(
        {"op": "set", "element": clock["path"], "path": ["font"], "value": "FONT_SMALL"}))
    assert r.status_code == 200 and r.json()["version"] == 2
    assert "font: FONT_SMALL" in r.json()["text"]
    bad = client.post(f"{url}/edit?version=2", content=json.dumps(
        {"op": "set", "element": clock["path"], "path": ["color"], "value": "color.nope"}))
    assert bad.status_code == 400 and "color.nope" in bad.json()["error"]
    assert client.post(f"{url}/edit?version=1", content="{}").status_code == 409
    assert client.post(f"{url}/edit?version=2", content="not json").status_code == 400
    assert client.post(f"{url}/edit?version=2", content=json.dumps(
        {"op": "set", "element": clock["path"], "path": ["at", "dy"], "value": 1,
         "scope": "device", "device": "nosuchwatch"})).status_code == 400
    font = client.post(f"{url}/assets?filename=C.ttf&font=big&size=30%25r&version=2",
                       content=CHIVO.read_bytes())
    assert font.status_code == 200, font.text
    assert {f["name"] for f in font.json()["globals"]["fonts"]} == {"big"}


def test_the_vocabulary_lists_sources_icons_complications_and_devices(client):
    words = client.get("/api/vocabulary").json()
    assert "activity.steps" in words["sources"]["activity"]
    assert "heart" in words["icons"] and words["complications"][0] == "auto"
    fr955 = next(d for d in words["devices"] if d["id"] == "fr955")
    assert "FONT_MEDIUM" in fr955["fonts"] and fr955["shape"] == "round"


def test_an_edit_reuses_the_gates_load_and_sees_what_a_fresh_load_sees(studio, tmp_path, db):
    from wfb.edit import gate as gate_mod

    doc = new(studio)
    doc.analysis()
    loads = []
    real = gate_mod.load_text

    def counted(path, text):
        loads.append(text)
        return real(path, text)

    import wfb.studio.document as document_mod
    gate_mod_load, doc_mod_load = gate_mod.load_text, document_mod.load_text
    gate_mod.load_text = document_mod.load_text = counted
    try:
        # an off-palette colour: a lint warning the edit adds
        doc.edit({"op": "set", "path": ["resources", "palette", "text"], "value": "#123456"},
                 doc.version)
        seeded = sorted((d["code"], d["message"]) for d in doc.diagnostics())
    finally:
        gate_mod.load_text, document_mod.load_text = gate_mod_load, doc_mod_load
    assert len(loads) == 1, "one load per edit: the gate's, reused by the analysis"
    fresh = Studio(Store(studio.store.root), db, scratch=tmp_path / "fresh").document(doc.id)
    assert sorted((d["code"], d["message"]) for d in fresh.diagnostics()) == seeded
    assert any("123456" in message for _, message in seeded)


# -- slots -------------------------------------------------------------------------------

def slots(doc):
    return {s["name"]: s for s in doc.summary()["globals"]["slots"]}


def test_a_slot_is_declared_drawn_and_its_choices_edited_from_the_panel(studio):
    doc = new(studio)
    doc.edit({"op": "set", "path": ["config", "slots", "top"],
              "value": {"default": "steps", "choices": "any"}}, doc.version)
    assert slots(doc)["top"] == {"name": "top", "label": None, "default": "steps",
                                 "choices": "any", "drawn_by": []}
    doc.structure({"op": "add", "type": "data", "block": ["elements"], "choice": "top"},
                  doc.version)
    drawer = slots(doc)["top"]["drawn_by"]
    assert len(drawer) == 1
    assert fields(doc.inspect(list(element_path(doc, drawer[0])), None))["slot"]["widget"] == "slot"
    doc.edit({"op": "set", "path": ["config", "slots", "top", "choices"],
              "value": ["steps", {"type": "heart_rate", "icon": "none"}]}, doc.version)
    doc.edit({"op": "set", "path": ["config", "slots", "top", "label"], "value": "Top"},
             doc.version)
    top = slots(doc)["top"]
    assert top["label"] == "Top"
    assert top["choices"] == [{"type": "steps", "icon": None},
                              {"type": "heart_rate", "icon": "none"}]
    assert doc.analysis().face is not None


def test_a_slot_rename_repoints_its_elements_and_nothing_else(studio):
    doc = new(studio)
    # a slot named like a complication type: `default: steps` is not a reference
    doc.edit({"op": "set", "path": ["config", "slots", "steps"],
              "value": {"default": "steps", "choices": ["steps", "calories"]}}, doc.version)
    doc.structure({"op": "add", "type": "data", "block": ["elements"], "choice": "steps"},
                  doc.version)
    doc.edit({"op": "rename", "path": ["config", "slots", "steps"], "to": "left"},
             doc.version)
    left = slots(doc)["left"]
    assert left["default"] == "steps" and len(left["drawn_by"]) == 1
    assert "slot: steps" not in doc.text and "slot: left" in doc.text
    assert doc.analysis().face is not None


def test_a_slot_edit_the_face_cannot_take_is_refused(studio):
    doc = new(studio)
    doc.edit({"op": "set", "path": ["config", "slots", "top"],
              "value": {"default": "steps", "choices": ["steps"]}}, doc.version)
    doc.structure({"op": "add", "type": "data", "block": ["elements"], "choice": "top"},
                  doc.version)
    before = doc.text
    drawer = slots(doc)["top"]["drawn_by"][0]
    with pytest.raises(Refused, match=f"{drawer} draws the slot top"):
        doc.edit({"op": "remove", "path": ["config", "slots", "top"]}, doc.version)
    with pytest.raises(Refused):      # the default left out of the list
        doc.edit({"op": "set", "path": ["config", "slots", "top", "choices"],
                  "value": ["calories"]}, doc.version)
    assert doc.text == before


def test_the_last_slot_deleted_takes_its_config_block_with_it(studio):
    doc = new(studio)
    doc.edit({"op": "set", "path": ["config", "slots", "top"],
              "value": {"default": "steps", "choices": "any"}}, doc.version)
    doc.edit({"op": "set", "path": ["config", "slots", "bottom"],
              "value": {"default": "calories", "choices": "any"}}, doc.version)
    doc.edit({"op": "remove", "path": ["config", "slots", "top"]}, doc.version)
    assert list(slots(doc)) == ["bottom"]
    doc.edit({"op": "remove", "path": ["config", "slots", "bottom"]}, doc.version)
    assert "config" not in SpanIndex(doc.text).data and doc.analysis().face is not None


def test_a_target_not_installed_and_a_value_that_is_no_colour_are_noted(db):
    text = starters.instantiate("minimal", "T").replace(
        "targets: [", "targets: [nosuchwatch, ").replace('bg: "#000000"', 'bg: "#00GG00"')
    assert "nosuchwatch" in text and "#00GG00" in text
    g = globals_of(text, db)
    assert "nosuchwatch" in g["target_problems"]
    assert set(g["target_problems"]) == {"nosuchwatch"}
    bg = next(p for p in g["palette"] if p["name"] == "bg")
    assert bg["problem"] and not bg["automatic"]
    assert all(p["problem"] is None for p in g["palette"] if p["name"] != "bg")


def test_an_installed_watch_that_cannot_be_read_is_listed_with_why(db, monkeypatch):
    from wfb.devices import DeviceError
    from wfb.studio.inspect import devices

    real = db.get
    broken = db.ids()[0]

    def get(device_id):
        if device_id == broken:
            raise DeviceError(f"{device_id}: compiler.json is not JSON")
        return real(device_id)

    monkeypatch.setattr(db, "get", get)
    listed, unreadable = devices(db)
    assert unreadable == [{"id": broken, "reason": f"{broken}: compiler.json is not JSON"}]
    assert broken not in [d["id"] for d in listed]
