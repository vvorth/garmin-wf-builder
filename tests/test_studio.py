"""`wfb studio`: bundles in and out, the history store, documents and the
HTTP endpoints, through Starlette's test client."""

from __future__ import annotations

import asyncio
import io
import json
import os
import stat
import zipfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from wfb import starters
from wfb.edit import Refused, SpanIndex, set_value
from wfb.emit.resources import BakeMemo
from wfb.studio import bundle as bundle_mod
from wfb.studio.app import Events, create_app
from wfb.studio.bundle import (
    Bundle, BundleError, from_path, inside, missing, read_upload, references, to_zip,
)
from wfb.studio.document import FrameKey, StaleVersion, Studio
from wfb.studio.store import Store

ROOT = Path(__file__).resolve().parent.parent
SHOWCASE = ROOT / "examples/showcase/face.yaml"
PROFILE = ROOT / "examples/features/profile/face.yaml"
STYLES = ROOT / "examples/features/styles/face.yaml"
ALIGN = ROOT / "examples/features/align/face.yaml"
CHIVO = ROOT / "examples/showcase/assets/ChivoMono-Bold.ttf"
DYNALIGHT = ROOT / "examples/showcase/assets/Dynalight-Regular.ttf"


def zipped(entries: dict[str, bytes], links: tuple[str, ...] = ()) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name)
            if name in links:
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, data)
    return out.getvalue()


@pytest.fixture
def studio(tmp_path, db):
    s = Studio(Store(tmp_path / "state"), db, scratch=tmp_path / "scratch")
    yield s
    s.close()


@pytest.fixture
def client(studio):
    return TestClient(create_app(studio))


def minimal_text(name: str = "T") -> str:
    return starters.instantiate("minimal", name)


# -- bundles --------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("assets/a.ttf", "assets/a.ttf"),
    ("./assets/a.ttf", "assets/a.ttf"),
    ("assets/../a.ttf", "a.ttf"),
    ("../outline/assets/a.ttf", None),
    ("/etc/passwd", None),
    ("C:/fonts/a.ttf", None),
    ("assets\\a.ttf", None),
    ("", None),
])
def test_inside_keeps_a_path_in_the_bundle(value, expected):
    assert inside(value) == expected


def test_a_yaml_upload_is_its_text_named_after_the_face():
    b = read_upload("whatever.yaml", minimal_text("Morning Run").encode())
    assert b.name == "Morning Run" and b.files == {}
    assert read_upload("x.yml", b"format: 2\n").name == "x"


def test_a_zip_upload_holds_the_face_and_its_files():
    data = zipped({"face.yaml": SHOWCASE.read_bytes(), "assets/ChivoMono-Bold.ttf": b"ttf",
                   "README.md": b"kept", "__MACOSX/._face.yaml": b"junk", ".DS_Store": b"junk"})
    b = read_upload("Showcase.zip", data)
    assert b.text == SHOWCASE.read_text()
    assert set(b.files) == {"assets/ChivoMono-Bold.ttf", "README.md"}


def test_a_zipped_folder_is_read_as_its_contents():
    data = zipped({"myface/face.yaml": b"format: 2\n", "myface/assets/a.ttf": b"x"})
    b = read_upload("myface.zip", data)
    assert b.text == "format: 2\n" and set(b.files) == {"assets/a.ttf"}


@pytest.mark.parametrize("entries, links, reason", [
    ({"face.yaml": b"a: 1", "../evil.ttf": b"x"}, (), "outside the bundle"),
    ({"face.yaml": b"a: 1", "/etc/evil": b"x"}, (), "outside the bundle"),
    ({"face.yaml": b"a: 1", "assets/link.ttf": b"/etc/passwd"}, ("assets/link.ttf",), "link"),
    ({"assets/a.ttf": b"x", "notes.txt": b"x"}, (), "no .yaml at its root"),
    ({"one.yaml": b"a: 1", "two.yaml": b"a: 1"}, (), "more than one .yaml"),
    ({"face.yaml": b"\xff\xfe\x00bad"}, (), "not UTF-8"),
])
def test_a_bad_bundle_is_refused_with_its_reason(entries, links, reason):
    with pytest.raises(BundleError, match=reason):
        read_upload("x.zip", zipped(entries, links))


def test_two_root_yamls_are_fine_when_one_is_face_yaml():
    b = read_upload("x.zip", zipped({"face.yaml": b"a: 1\n", "other.yaml": b"b: 2\n"}))
    assert b.text == "a: 1\n" and set(b.files) == {"other.yaml"}


def test_a_bundle_over_its_limits_is_refused_before_unpacking(monkeypatch):
    data = zipped({"face.yaml": b"a: 1", "assets/big.ttf": b"0" * 5000})
    monkeypatch.setattr(bundle_mod, "MAX_UNPACKED_BYTES", 4000)
    with pytest.raises(BundleError, match="unpacks to over"):
        read_upload("x.zip", data)
    monkeypatch.setattr(bundle_mod, "MAX_UNPACKED_BYTES", 10_000)
    monkeypatch.setattr(bundle_mod, "MAX_ENTRIES", 1)
    with pytest.raises(BundleError, match="entries"):
        read_upload("x.zip", data)


def test_an_upload_that_is_neither_yaml_nor_zip_is_refused():
    with pytest.raises(BundleError, match="neither"):
        read_upload("face.json", b"{}")
    with pytest.raises(BundleError, match="not a readable .zip"):
        read_upload("face.zip", b"not a zip")


def test_references_and_missing_read_the_font_sources():
    text = SHOWCASE.read_text()
    assert [r.value for r in references(text)] == [
        "assets/ChivoMono-Bold.ttf", "assets/Dynalight-Regular.ttf"]
    assert [r.value for r in missing(text, {"assets/ChivoMono-Bold.ttf": b""})] == [
        "assets/Dynalight-Regular.ttf"]
    assert references("a: [1, 2\n") == []


def test_from_path_gathers_a_file_outside_the_face_into_assets():
    b, moved = from_path(PROFILE)
    assert moved == {"../outline/assets/ChivoMono-Bold.ttf": "assets/ChivoMono-Bold.ttf"}
    assert b.files["assets/ChivoMono-Bold.ttf"] == (
        ROOT / "examples/features/outline/assets/ChivoMono-Bold.ttf").read_bytes()


def test_a_zip_round_trips():
    b = Bundle("S", SHOWCASE.read_text(), {"assets/a.ttf": b"one", "assets/b.ttf": b"two"})
    again = read_upload("s.zip", to_zip(b))
    assert (again.text, again.files) == (b.text, b.files)


# -- starters -------------------------------------------------------------------------

def test_every_new_face_gets_its_own_uuid_and_name():
    a, b = starters.instantiate("minimal", "One"), starters.instantiate("minimal", "Two")
    ids = [SpanIndex(t).data["face"]["id"] for t in (a, b)]
    assert ids[0] != ids[1] and "__UUID__" not in a
    assert SpanIndex(a).data["face"]["name"] == "One"


@pytest.mark.parametrize("name", ["../minimal", "/etc/passwd", "nope"])
def test_a_template_is_a_name_never_a_path(name):
    with pytest.raises(starters.UnknownTemplate):
        starters.instantiate(name, "X")


# -- the font-bake memo ----------------------------------------------------------------

def test_the_bake_memo_reuses_a_sheet_until_the_file_changes(tmp_path):
    font = tmp_path / "f.ttf"
    font.write_bytes(CHIVO.read_bytes())
    memo = BakeMemo()
    first = memo.bake(font, name="f", size=20, glyphs="0123")
    assert memo.bake(font, name="f", size=20, glyphs="0123") is first
    assert memo.bake(font, name="f", size=21, glyphs="0123") is not first
    os.utime(font, ns=(1, 1))
    assert memo.bake(font, name="f", size=20, glyphs="0123") is not first


def test_a_memoised_resolve_draws_the_same_pixels(db):
    from wfb.build import load, resolve_all, select_devices
    from wfb.diagnostics import Bag
    from wfb.preview import PreviewOptions, render

    bag = Bag()
    face = load(SHOWCASE, bag)
    devices = select_devices(face, db, bag, ["fr955"])
    memo = BakeMemo()
    plain, _ = resolve_all(face, devices, Bag())
    resolve_all(face, devices, Bag(), memo)
    warm, _ = resolve_all(face, devices, Bag(), memo)
    options = PreviewOptions(scale=1)
    assert render(plain["fr955"], options).tobytes() == render(warm["fr955"], options).tobytes()


# -- the store and documents -------------------------------------------------------------

def test_a_new_document_is_its_first_journal_line(studio):
    doc = studio.create(Bundle("T", minimal_text()), "new")
    journal = studio.store.journal(doc.id)
    assert [(c.seq, c.label) for c in journal] == [(1, "new")]
    assert doc.path.read_text() == doc.text


def test_a_document_survives_a_new_server_over_the_same_store(tmp_path, db):
    first = Studio(Store(tmp_path / "state"), db, scratch=tmp_path / "a")
    b, moved = from_path(PROFILE)
    doc_id = first.create(b, "open", moved).id
    text = first.document(doc_id).text
    first.close()

    second = Studio(Store(tmp_path / "state"), db, scratch=tmp_path / "b")
    doc = second.document(doc_id)
    assert doc.version == 2 and doc.text == text
    assert (doc.directory / "assets/ChivoMono-Bold.ttf").read_bytes() == b.files[
        "assets/ChivoMono-Bold.ttf"]
    assert doc.analysis().face is not None


def test_a_journal_line_cut_short_by_a_crash_is_not_the_head(studio):
    doc = studio.create(Bundle("T", minimal_text()), "new")
    with open(studio.store.root / doc.id / "journal.jsonl", "a") as out:
        out.write('{"seq": 2, "time": 1')
    assert studio.store.head(doc.id).seq == 1


def test_the_directory_is_rebuilt_when_it_goes_missing(studio):
    import shutil

    doc = studio.create(Bundle("T", minimal_text()), "new")
    shutil.rmtree(doc.directory)
    assert doc.analysis().face is not None


def test_an_edit_keeps_an_untouched_asset_file_as_it_was(studio):
    # Its modification time keys the bake memo: rewriting it on every edit
    # would re-bake every font on every edit.
    b, moved = from_path(PROFILE)
    doc = studio.create(b, "open", moved)
    font = doc.directory / "assets/ChivoMono-Bold.ttf"
    before = font.stat().st_mtime_ns
    os.utime(font, ns=(before - 10**9, before - 10**9))
    before = font.stat().st_mtime_ns
    text = set_value(SpanIndex(doc.text), ("face", "version"), "9.9.9").text
    doc.commit(text, dict(doc.head.assets), "edit", doc.version)
    assert font.stat().st_mtime_ns == before
    assert doc.path.read_text() == text


def test_a_change_against_an_old_version_is_refused(studio):
    doc = studio.create(Bundle("T", minimal_text()), "new")
    doc.commit(doc.text, {}, "one", 1)
    with pytest.raises(StaleVersion):
        doc.commit(doc.text, {}, "two", 1)


def test_opening_a_design_on_disk_never_writes_to_it(studio):
    before = (PROFILE.read_bytes(), PROFILE.stat().st_mtime_ns)
    b, moved = from_path(PROFILE)
    doc = studio.create(b, "open", moved)
    doc.analysis()
    assert (PROFILE.read_bytes(), PROFILE.stat().st_mtime_ns) == before
    # the copy's reference was moved into the bundle, the original's was not
    assert "../outline/assets" in PROFILE.read_text()
    assert "../outline/assets" not in doc.text


def test_diagnostics_name_face_yaml_never_the_temporary_directory(studio):
    doc = studio.create(read_upload("face.yaml", SHOWCASE.read_bytes()), "open")
    shown = doc.diagnostics()
    assert shown and {d["file"] for d in shown if "file" in d} == {"face.yaml"}
    flat = json.dumps(shown)
    assert str(studio.scratch) not in flat and str(studio.scratch.resolve()) not in flat
    assert "assets/ChivoMono-Bold.ttf" in flat


def test_the_tree_holds_blocks_layouts_and_groups(studio):
    doc = studio.create(read_upload("face.yaml", STYLES.read_bytes()), "open")
    labels = [b["label"] for b in doc.tree()]
    assert labels[:2] == ["static", "elements"] and "big: static" in labels
    groups = studio.create(read_upload("face.yaml", ALIGN.read_bytes()), "open")
    nested = [n for b in groups.tree() for n in b["children"] if n["children"]]
    assert nested, "a group's children are its tree children"
    assert nested[0]["type"] == "group"


def test_a_frame_has_an_item_and_a_layer_per_drawn_element(studio):
    doc = studio.create(Bundle("T", minimal_text()), "new")
    key = FrameKey("fr955", scale=1)
    frame = doc.frame(key)
    assert (frame["width"], frame["height"]) == (260, 260)
    assert [i["id"] for i in frame["items"]] == ["background", "clock", "seconds"]
    layers = doc.layers(key)["layers"]
    assert [layer["id"] for layer in layers] == ["background", "clock", "seconds"]
    assert all(layer["image"].startswith("data:image/png;base64,") for layer in layers)
    # each layer carries its ink only, placed by its origin, inside its box
    from PIL import Image
    import base64
    clock = layers[1]
    image = Image.open(io.BytesIO(base64.b64decode(clock["image"].split(",", 1)[1])))
    assert image.size[0] < 260 and image.size[1] < 260
    x, y = clock["origin"]
    bx, by, bw, bh = frame["items"][1]["box"]
    assert bx - 2 <= x and x + image.size[0] <= bx + bw + 2


# -- the endpoints ----------------------------------------------------------------------

def test_new_from_a_template_over_http(client):
    r = client.post("/api/documents/new?template=analog&name=Dial")
    assert r.status_code == 200
    doc = r.json()
    assert doc["name"] == "Dial" and doc["version"] == 1 and doc["loads"]
    assert not [d for d in doc["diagnostics"] if d["severity"] == "error"]
    home = client.get("/api/home").json()
    assert [d["id"] for d in home["documents"]] == [doc["id"]]
    assert client.post("/api/documents/new?template=../x").status_code == 400


def test_upload_then_download_returns_the_same_bytes(client):
    text = minimal_text("Plain")
    doc = client.post("/api/documents/upload?filename=plain.yaml",
                      content=text.encode()).json()
    r = client.get(f"/api/documents/{doc['id']}/download")
    assert r.headers["content-disposition"] == 'attachment; filename="plain.yaml"'
    assert r.content == text.encode()

    data = zipped({"face.yaml": SHOWCASE.read_bytes(),
                   "assets/ChivoMono-Bold.ttf": CHIVO.read_bytes(),
                   "assets/Dynalight-Regular.ttf": DYNALIGHT.read_bytes()})
    doc = client.post("/api/documents/upload?filename=show.zip", content=data).json()
    assert doc["missing"] == [] and doc["loads"]
    r = client.get(f"/api/documents/{doc['id']}/download")
    assert r.headers["content-disposition"] == 'attachment; filename="showcase.zip"'
    again = read_upload("x.zip", r.content)
    assert again.text == SHOWCASE.read_text()
    assert again.files["assets/ChivoMono-Bold.ttf"] == CHIVO.read_bytes()
    assert client.get(f"/api/documents/{doc['id']}/download?form=yaml").content == (
        SHOWCASE.read_bytes())


def test_a_missing_font_is_listed_then_added_and_its_reference_patched(client):
    doc = client.post("/api/documents/upload?filename=face.yaml",
                      content=PROFILE.read_bytes()).json()
    assert doc["missing"] == ["../outline/assets/ChivoMono-Bold.ttf"] and not doc["loads"]
    url = f"/api/documents/{doc['id']}/assets"
    ref = "../outline/assets/ChivoMono-Bold.ttf"
    r = client.post(f"{url}?filename=Chivo.ttf&reference={ref}&version=1",
                    content=CHIVO.read_bytes())
    assert r.status_code == 200, r.text
    after = r.json()
    assert after["missing"] == [] and after["loads"] and after["version"] == 2
    assert "source: assets/Chivo.ttf" in after["text"]
    # only the reference's characters changed
    changed = [(a, b) for a, b in zip(doc["text"].splitlines(), after["text"].splitlines())
               if a != b]
    assert len(changed) == len([1 for line in doc["text"].splitlines() if ref in line])


def test_an_asset_against_an_old_version_is_refused(client):
    doc = client.post("/api/documents/upload?filename=face.yaml",
                      content=SHOWCASE.read_bytes()).json()
    url = f"/api/documents/{doc['id']}/assets"
    ok = client.post(f"{url}?filename=a.ttf&reference=assets/ChivoMono-Bold.ttf&version=1",
                     content=CHIVO.read_bytes())
    assert ok.status_code == 200, ok.text
    stale = client.post(f"{url}?filename=b.ttf&reference=assets/Dynalight-Regular.ttf"
                        "&version=1", content=DYNALIGHT.read_bytes())
    assert stale.status_code == 409 and "version 2" in stale.json()["error"]
    nothing = client.post(f"{url}?filename=b.ttf&reference=nope.ttf&version=2",
                          content=DYNALIGHT.read_bytes())
    assert nothing.status_code == 400
    assert client.get(f"/api/documents/{doc['id']}").json()["version"] == 2


def test_frames_and_refusals_over_http(client):
    doc = client.post("/api/documents/new?template=minimal&name=F").json()
    url = f"/api/documents/{doc['id']}/frame"
    frame = client.get(f"{url}?device=fenix8solar47mm&scale=1&time=12:34").json()
    assert frame["device"] == "fenix8solar47mm" and frame["items"]
    assert client.get(f"{url}?device=vivoactive4").status_code == 400
    assert client.get(f"{url}?device=fr955&time=25:00").status_code == 400
    assert client.get(f"{url}?device=fr955&scale=big").status_code == 400
    assert client.get("/api/documents/" + "0" * 32).status_code == 404
    assert client.get("/api/documents/../../etc").status_code == 404


def test_delete_removes_the_document_and_its_history(client, studio):
    doc = client.post("/api/documents/new?template=minimal&name=D").json()
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 200
    assert not (studio.store.root / doc["id"]).exists()
    assert client.get(f"/api/documents/{doc['id']}").status_code == 404
    assert client.get("/api/home").json()["documents"] == []


def test_the_front_end_is_served(client):
    assert "app.js" in client.get("/").text
    assert client.get("/static/vendor/preact-htm.module.js").status_code == 200


def test_events_reach_every_stream():
    async def run() -> list[str]:
        events = Events()
        stream = events.stream()
        assert await stream.__anext__() == ": connected\n\n"
        events.publish("changed", {"id": "x", "version": 2})
        message = await asyncio.wait_for(stream.__anext__(), 1)
        await stream.aclose()
        return [message]

    (message,) = asyncio.run(run())
    assert message == 'event: changed\ndata: {"id": "x", "version": 2}\n\n'


# -- history: undo, redo, snapshots, restore ------------------------------------------

def bumped(doc, n: int) -> str:
    """The document's text with `face.version` set to 1.0.<n>: one line changed."""
    return set_value(SpanIndex(doc.text), ("face", "version"), f"1.0.{n}").text


def versions(doc) -> str:
    return SpanIndex(doc.text).data["face"]["version"]


def test_replay_moves_a_cursor_and_a_change_after_undo_drops_the_redo_branch():
    from wfb.studio.store import Change, replay

    def c(seq, kind="change", target=None):
        return Change(seq, 0.0, str(seq), "t", {}, kind, target)

    line = replay([c(1), c(2), c(3), c(4, "undo", 2), c(5, "undo", 1), c(6, "redo", 2)])
    assert [s.seq for s in line.states] == [1, 2, 3] and line.cursor == 1
    assert line.can_undo and line.can_redo
    line = replay([c(1), c(2), c(3), c(4, "undo", 2), c(5)])
    assert [s.seq for s in line.states] == [1, 2, 5] and not line.can_redo


def test_undo_and_redo_step_through_the_changes(studio):
    doc = studio.create(Bundle("T", minimal_text()), "new")
    first = doc.text
    doc.commit(bumped(doc, 1), {}, "one", doc.version)
    doc.commit(bumped(doc, 2), {}, "two", doc.version)
    doc.undo(doc.version)
    assert versions(doc) == "1.0.1" and doc.path.read_text() == doc.text
    doc.undo(doc.version)
    assert doc.text == first
    with pytest.raises(Refused, match="nothing to undo"):
        doc.undo(doc.version)
    doc.redo(doc.version)
    doc.redo(doc.version)
    assert versions(doc) == "1.0.2"
    with pytest.raises(Refused, match="nothing to redo"):
        doc.redo(doc.version)
    # a change after an undo ends the redo line
    doc.undo(doc.version)
    doc.commit(bumped(doc, 3), {}, "three", doc.version)
    with pytest.raises(Refused, match="nothing to redo"):
        doc.redo(doc.version)
    labels = [s["label"] for s in doc.history()["states"]]
    assert labels == ["three", "one", "new"]


def test_undo_against_an_old_version_is_refused(studio):
    doc = studio.create(Bundle("T", minimal_text()), "new")
    doc.commit(bumped(doc, 1), {}, "one", doc.version)
    with pytest.raises(StaleVersion):
        doc.undo(1)


def test_undo_removes_an_added_asset_from_the_directory(studio):
    doc = studio.create(read_upload("face.yaml", PROFILE.read_bytes()), "open")
    doc.add_asset("Chivo.ttf", CHIVO.read_bytes(), "../outline/assets/ChivoMono-Bold.ttf",
                  doc.version)
    assert (doc.directory / "assets/Chivo.ttf").is_file() and doc.analysis().face is not None
    doc.undo(doc.version)
    assert not (doc.directory / "assets/Chivo.ttf").exists()
    assert doc.missing() == ["../outline/assets/ChivoMono-Bold.ttf"]
    doc.redo(doc.version)
    assert (doc.directory / "assets/Chivo.ttf").read_bytes() == CHIVO.read_bytes()


def test_undo_and_redo_survive_a_new_server(tmp_path, db):
    first = Studio(Store(tmp_path / "state"), db, scratch=tmp_path / "a")
    doc = first.create(Bundle("T", minimal_text()), "new")
    doc.commit(bumped(doc, 1), {}, "one", doc.version)
    doc.commit(bumped(doc, 2), {}, "two", doc.version)
    doc.undo(doc.version)
    doc_id = doc.id
    first.close()

    again = Studio(Store(tmp_path / "state"), db, scratch=tmp_path / "b").document(doc_id)
    assert versions(again) == "1.0.1"
    history = again.history()
    assert history["can_undo"] and history["can_redo"]
    again.redo(again.version)
    assert versions(again) == "1.0.2"


def test_a_change_the_store_cannot_record_is_not_applied(studio, monkeypatch):
    from wfb.studio.store import StoreError

    doc = studio.create(Bundle("T", minimal_text()), "new")
    before = (doc.text, doc.version, doc.path.read_text())

    def broken(fd):
        raise OSError("disk full")

    monkeypatch.setattr(os, "fsync", broken)
    # a new text: its blob cannot be written
    with pytest.raises(StoreError, match="disk full"):
        doc.commit(bumped(doc, 1), {}, "one", doc.version)
    # the same text: its blob is stored already, so the journal append fails
    with pytest.raises(StoreError, match="disk full"):
        doc.commit(doc.text, {}, "again", doc.version)
    monkeypatch.undo()
    assert (doc.text, doc.version, doc.path.read_text()) == before
    assert [c.label for c in studio.store.journal(doc.id)] == ["new"]


def test_the_timer_snapshots_a_changed_face_once_per_interval(tmp_path, db):
    s = Studio(Store(tmp_path / "state"), db, scratch=tmp_path / "s", snapshot_minutes=5)
    doc = s.create(Bundle("T", minimal_text()), "new")
    start = doc.last_snapshot[0]
    assert s.tick(start + 60) == []                       # too soon
    taken = s.tick(start + 301)
    assert [t.seq for t in taken] == [doc.version]        # the new face, unchanged since
    assert s.tick(start + 700) == []                      # unchanged since that one
    doc.commit(bumped(doc, 1), {}, "one", doc.version)
    assert s.tick(start + 302) == []                      # changed, but too soon
    assert [t.reason for t in s.tick(start + 700)] == ["timer"]
    assert [x.seq for x in s.store.snapshots(doc.id)] == [1, 2]
    s.close()


def test_a_restore_is_one_change_and_can_be_undone(studio):
    doc = studio.create(Bundle("T", minimal_text()), "new")
    doc.commit(bumped(doc, 1), {}, "one", doc.version)
    snap = doc.snapshot("manual")
    doc.commit(bumped(doc, 2), {}, "two", doc.version)
    doc.restore(snap.name, doc.version)
    assert versions(doc) == "1.0.1"
    assert doc.history()["states"][0]["label"].startswith("restore the snapshot of")
    doc.undo(doc.version)
    assert versions(doc) == "1.0.2"


def test_a_snapshot_in_a_dropped_redo_branch_still_restores(studio):
    doc = studio.create(Bundle("T", minimal_text()), "new")
    doc.commit(bumped(doc, 1), {}, "one", doc.version)
    snap = doc.snapshot("manual")
    doc.undo(doc.version)
    doc.commit(bumped(doc, 2), {}, "two", doc.version)   # drops "one" from the line
    doc.restore(snap.name, doc.version)
    assert versions(doc) == "1.0.1"


def test_a_snapshot_opens_as_a_copy(studio):
    b, moved = from_path(PROFILE)
    doc = studio.create(b, "open", moved)
    snap = doc.snapshot("manual")
    doc.commit(bumped(doc, 7), dict(doc.head.assets), "later", doc.version)
    copy = studio.fork(doc.id, snap.name)
    assert copy.id != doc.id and copy.text == studio.store.text(doc.id, snap)
    assert (copy.directory / "assets/ChivoMono-Bold.ttf").is_file()
    assert copy.analysis().face is not None
    assert versions(doc) == "1.0.7"


def test_pruning_removes_old_faces_and_old_snapshots(studio):
    store = studio.store
    old = studio.create(Bundle("Old", minimal_text()), "new")
    keep = studio.create(Bundle("Keep", minimal_text()), "new")
    for i in range(4):
        keep.commit(bumped(keep, i), {}, f"c{i}", keep.version)
        keep.snapshot("manual", now=1000.0 + i)
    now = store.head(keep.id).time + 1
    # `old` is made to look 31 days untouched
    journal = store.root / old.id / "journal.jsonl"
    journal.write_text(journal.read_text().replace(
        f'"time": {store.head(old.id).time}', f'"time": {now - 31 * 86400}'))
    removed = store.prune(keep_days=30, keep_snapshots=2, now=now)
    assert any("Old" in line for line in removed)
    assert not (store.root / old.id).exists()
    assert [s.time for s in store.snapshots(keep.id)] == [1002.0, 1003.0]


def test_history_over_http(client):
    doc = client.post("/api/documents/upload?filename=face.yaml",
                      content=SHOWCASE.read_bytes()).json()
    url = f"/api/documents/{doc['id']}"
    assert client.post(f"{url}/undo?version=1").status_code == 400     # nothing to undo
    added = client.post(f"{url}/assets?filename=a.ttf&reference=assets/ChivoMono-Bold.ttf"
                        "&version=1", content=CHIVO.read_bytes()).json()
    assert added["history"]["can_undo"]
    assert client.post(f"{url}/undo?version=1").status_code == 409     # stale
    undone = client.post(f"{url}/undo?version=2").json()
    assert undone["version"] == 3 and len(undone["missing"]) == 2
    assert undone["history"]["can_redo"]
    redone = client.post(f"{url}/redo?version=3").json()
    assert len(redone["missing"]) == 1

    history = client.post(f"{url}/snapshots").json()
    (snap,) = history["snapshots"]
    assert snap["reason"] == "manual" and snap["current"]
    # a download of a version that already has a snapshot adds none
    client.get(f"{url}/download")
    assert len(client.get(url).json()["history"]["snapshots"]) == 1
    restored = client.post(f"{url}/snapshots/{snap['name']}/restore?version=4").json()
    assert restored["version"] == 5
    copy = client.post(f"{url}/snapshots/{snap['name']}/copy").json()
    assert copy["id"] != doc["id"] and copy["missing"] == redone["missing"]
    assert client.post(f"{url}/snapshots/00000001-1/restore?version=5").status_code == 404
    assert client.post(f"{url}/snapshots/..%2F..%2Fmeta/restore?version=5").status_code == 404


def test_a_download_snapshots_a_version_that_has_none(client):
    doc = client.post("/api/documents/new?template=minimal&name=D").json()
    url = f"/api/documents/{doc['id']}"
    client.get(f"{url}/download")
    (snap,) = client.get(url).json()["history"]["snapshots"]
    assert snap["reason"] == "download" and snap["seq"] == 1


def test_the_cli_defaults_are_the_studio_defaults():
    from wfb.cli import _parser
    from wfb.studio import KEEP_DAYS, KEEP_SNAPSHOTS
    from wfb.studio.document import SNAPSHOT_MINUTES

    args = _parser().parse_args(["studio"])
    assert (args.snapshot_minutes, args.keep_days, args.keep_snapshots) == (
        SNAPSHOT_MINUTES, KEEP_DAYS, KEEP_SNAPSHOTS)
