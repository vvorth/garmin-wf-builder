"""`wfb studio`'s Build, its skins and the devices the editor offers: the
build runner with a stand-in command, the endpoints, and one real build
(`slow`)."""

from __future__ import annotations

import base64
import io
import json
import sys
import threading
from pathlib import Path

import pytest
from PIL import Image
from starlette.testclient import TestClient

from wfb import starters
from wfb.studio.app import create_app
from wfb.studio.bundle import Bundle
from wfb.studio.builder import Builder, BuildBusy
from wfb.studio.document import Studio
from wfb.studio.store import Store

#: Stands in for `wfb build`: writes the .prg where it would and prints the
#: line it would, or fails as asked.
FAKE = """
import sys, pathlib
face, device, out = sys.argv[1], sys.argv[2], pathlib.Path(sys.argv[3])
if "FAIL" in pathlib.Path(face).read_text():
    print("error: the face is broken", file=sys.stderr); sys.exit(1)
if "SLEEP" in pathlib.Path(face).read_text():
    import time; time.sleep(5)
if "NOPRG" in pathlib.Path(face).read_text():
    print("build succeeded"); sys.exit(0)
target = out / "my-face" / f"my-face-{device}.prg"
target.parent.mkdir(parents=True)
target.write_bytes(b"PRG" + device.encode())
print(f"built      my-face-{device}.prg  1,234 B / 131,072 B (0.9%)")
"""


def fake(face: Path, device: str, output: Path) -> list[str]:
    return [sys.executable, "-c", FAKE, str(face), device, str(output)]


@pytest.fixture
def studio(tmp_path, db):
    s = Studio(Store(tmp_path / "state"), db, scratch=tmp_path / "scratch",
               builder=Builder(fake, timeout=2))
    yield s
    s.close()


def staged(tmp_path, text="format: 2\n"):
    source = tmp_path / "face"
    source.mkdir()
    (source / "face.yaml").write_text(text)
    return source


def test_a_build_leaves_its_prg_and_its_memory_line(tmp_path):
    builder = Builder(fake)
    work = builder.stage(staged(tmp_path))
    done = builder.run(work, "fr955", 3, "my-face")
    assert done.ok and done.prg is not None and done.prg.read_bytes() == b"PRGfr955"
    assert done.name == "my-face-fr955.prg" and done.version == 3
    assert done.memory == "1,234 B / 131,072 B (0.9%)"
    assert builder.get(done.id) is done
    builder.close()


def test_a_failed_or_hung_build_says_why(tmp_path):
    builder = Builder(fake, timeout=1)
    failed = builder.run(builder.stage(staged(tmp_path, "FAIL\n")), "fr955", 1, "x")
    assert not failed.ok and failed.prg is None and "the face is broken" in failed.log
    other = tmp_path / "other"
    other.mkdir()
    hung = builder.run(builder.stage(staged(other, "SLEEP\n")), "fr955", 1, "x")
    assert not hung.ok and "was stopped" in hung.log
    third = tmp_path / "third"
    third.mkdir()
    empty = builder.run(builder.stage(staged(third, "NOPRG\n")), "fr955", 1, "x")
    assert not empty.ok and "left no .prg" in empty.log
    builder.close()


def test_one_build_at_a_time(tmp_path):
    builder = Builder(fake)
    builder._running.acquire()
    outcome: list[object] = []

    def second() -> None:
        try:
            builder.run(builder.stage(staged(tmp_path)), "fr955", 1, "x")
            outcome.append("built")
        except BuildBusy as exc:
            outcome.append(exc)

    # in a thread with a deadline: a broken guard waits, it does not fail
    attempt = threading.Thread(target=second, daemon=True)
    attempt.start()
    attempt.join(5)
    builder._running.release()
    attempt.join(5)
    assert outcome and isinstance(outcome[0], BuildBusy), outcome
    builder.close()


def test_build_over_http_downloads_the_prg(studio):
    client = TestClient(create_app(studio))
    doc = client.post("/api/documents/new?template=minimal&name=My Face").json()
    url = f"/api/documents/{doc['id']}/build"
    r = client.post(f"{url}?device=fr955&version=1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["device"] == "fr955" and body["memory"].startswith("1,234 B")
    prg = client.get(body["download"])
    assert prg.status_code == 200 and prg.content == b"PRGfr955"
    assert 'filename="my-face-fr955.prg"' in prg.headers["content-disposition"]
    # a watch beyond the face's targets builds too (`wfb build -d` takes any)
    assert client.post(f"{url}?device=fenix8solar51mm&version=1").json()["ok"]
    assert client.post(f"{url}?device=nosuchwatch&version=1").status_code == 400
    assert client.post(f"{url}?device=fr955&version=0").status_code == 409
    assert client.get("/api/builds/" + "0" * 32).status_code == 404


def test_a_face_that_does_not_load_is_not_built(studio):
    doc = studio.create(Bundle("B", starters.instantiate("minimal", "B")), "new")
    doc.replace_text(doc.text.replace("color: color.dim", "color: color.nope"), doc.version)
    client = TestClient(create_app(studio))
    r = client.post(f"/api/documents/{doc.id}/build?device=fr955&version={doc.version}")
    assert r.status_code == 400 and "does not load" in r.json()["error"]


def test_a_skin_is_the_watch_round_its_screen(studio):
    client = TestClient(create_app(studio))
    r = client.get("/api/skin?device=fr955&scale=2")
    assert r.status_code == 200, r.text
    skin = r.json()
    image = Image.open(io.BytesIO(base64.b64decode(skin["image"].split(",", 1)[1])))
    assert image.size == (skin["width"], skin["height"])
    # the screen (260 px at scale 2) sits inside it, where the skin is clear
    x, y = skin["x"], skin["y"]
    assert x + 520 <= skin["width"] and y + 520 <= skin["height"]
    assert image.getpixel((x + 260, y + 260))[3] == 0
    assert client.get("/api/skin?device=nosuchwatch").status_code == 400


def test_the_editor_offers_each_watchs_density_and_skin(studio):
    client = TestClient(create_app(studio))
    devices = {d["id"]: d for d in client.get("/api/vocabulary").json()["devices"]}
    fr955 = devices["fr955"]
    assert fr955["ppi"] == 200 and fr955["skin"] and (fr955["width"], fr955["height"]) == (260, 260)
    assert any(d["ppi"] is None for d in devices.values()), "some watches' files give no ppi"


@pytest.mark.slow
def test_a_real_build_from_the_editor(tmp_path, db):
    s = Studio(Store(tmp_path / "state"), db, scratch=tmp_path / "scratch")
    try:
        client = TestClient(create_app(s))
        doc = client.post("/api/documents/new?template=minimal&name=Real").json()
        body = client.post(f"/api/documents/{doc['id']}/build?device=fr955&version=1").json()
        assert body["ok"], body["log"]
        assert "warning" not in body["log"].lower()
        assert client.get(body["download"]).content[:4]
    finally:
        s.close()
