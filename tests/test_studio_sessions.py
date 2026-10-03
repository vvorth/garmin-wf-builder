"""`wfb studio`'s sessions: each browser a principal owning its faces, the
links that join a browser to one, the `Host` allowlist, and the single-user
mode (`wfb.studio.sessions`)."""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from starlette.testclient import TestClient

from wfb import starters
from wfb.studio import allowed_hosts
from wfb.studio.app import Events, create_app
from wfb.studio.bundle import Bundle
from wfb.studio.builder import Build
from wfb.studio.document import Studio
from wfb.studio.sessions import COOKIE, Sessions
from wfb.studio.store import OWNER, Store


@pytest.fixture
def studio(tmp_path, db):
    s = Studio(Store(tmp_path / "state"), db, scratch=tmp_path / "scratch")
    yield s
    s.close()


@pytest.fixture
def sessions(tmp_path):
    return Sessions(tmp_path / "state", keep_days=30)


def browser(app) -> TestClient:
    """A client that has loaded the editor's page, so it has a session."""
    client = TestClient(app)
    page = client.get("/")
    assert page.status_code == 200 and COOKIE in client.cookies
    return client


def new_face(client, name="F"):
    got = client.post(f"/api/documents/new?template=minimal&name={name}")
    assert got.status_code == 200, got.text
    return got.json()


def test_the_page_starts_a_session_with_a_cookie_only_this_site_sends(studio, sessions):
    client = TestClient(create_app(studio, sessions=sessions))
    page = client.get("/")
    cookie = page.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
    assert f"Max-Age={30 * 86400}" in cookie
    # the store keeps only the token's hash
    token = client.cookies[COOKIE]
    stored = list((sessions.root / "sessions").glob("*.json"))
    assert len(stored) == 1 and token not in stored[0].name and token not in stored[0].read_text()
    # visiting again keeps the session and renews the cookie
    again = client.get("/")
    assert again.headers["set-cookie"].startswith(f"{COOKIE}={token};")


def test_a_request_with_no_session_is_refused_and_leaves_nothing(studio, sessions):
    client = TestClient(create_app(studio, sessions=sessions))
    for got in (client.get("/api/home"), client.post("/api/documents/new?template=minimal"),
                client.get("/api/events"), client.get("/api/builds/x")):
        assert got.status_code == 401 and "open the editor's page" in got.json()["error"]
    assert list((sessions.root / "sessions").glob("*.json")) == []
    assert sessions.principals() == [OWNER]


def test_each_browser_sees_only_its_own_faces(studio, sessions):
    app = create_app(studio, sessions=sessions)
    alice, bob = browser(app), browser(app)
    mine = new_face(alice, "Mine")
    new_face(bob, "Theirs")
    assert [d["name"] for d in alice.get("/api/home").json()["documents"]] == ["Mine"]
    assert [d["name"] for d in bob.get("/api/home").json()["documents"]] == ["Theirs"]
    doc = f"/api/documents/{mine['id']}"
    version = mine["version"]
    # someone else's face is as unknown as one that never existed
    for got in (bob.get(doc), bob.get(f"{doc}/frame?device=fr955"),
                bob.get(f"{doc}/download"), bob.get(f"{doc}/handset?name=x&device=fr955"),
                bob.post(f"{doc}/edit?version={version}",
                         content=json.dumps({"op": "set", "path": ["face", "name"], "value": "x"})),
                bob.post(f"{doc}/undo?version={version}"), bob.post(f"{doc}/snapshots"),
                bob.delete(doc)):
        assert got.status_code == 404, got.request.url
        assert got.json()["error"] == "there is no such face; it may have been deleted"
    assert alice.get(doc).status_code == 200


def test_a_build_downloads_only_for_its_faces_owner(studio, sessions, tmp_path, monkeypatch):
    prg = tmp_path / "f.prg"
    prg.write_bytes(b"prg")
    done = Build("b1", "fr955", 1, True, "ok", prg=prg, name="f-fr955.prg")
    monkeypatch.setattr(studio.builder, "run", lambda *a, **k: done)
    monkeypatch.setattr(studio.builder, "get", lambda build_id: done if build_id == "b1" else None)
    app = create_app(studio, sessions=sessions)
    alice, bob = browser(app), browser(app)
    face = new_face(alice)
    built = alice.post(f"/api/documents/{face['id']}/build?device=fr955&version={face['version']}")
    assert built.status_code == 200 and built.json()["download"] == "/api/builds/b1"
    assert alice.get("/api/builds/b1").content == b"prg"
    assert bob.get("/api/builds/b1").status_code == 404


def test_a_claim_link_opens_a_browsers_faces_in_another_once(studio, sessions):
    app = create_app(studio, sessions=sessions)
    alice, bob = browser(app), browser(app)
    new_face(alice, "Mine")
    link = alice.post("/api/claims").json()
    assert link["url"].startswith("/claim/") and link["seconds"] == 600
    joined = bob.get(link["url"], follow_redirects=False)
    assert joined.status_code == 303 and joined.headers["location"] == "/"
    assert [d["name"] for d in bob.get("/api/home").json()["documents"]] == ["Mine"]
    carol = browser(app)
    assert carol.get(link["url"]).status_code == 410
    assert carol.get("/api/home").json()["documents"] == []


def test_an_expired_claim_is_refused(studio, sessions, monkeypatch):
    app = create_app(studio, sessions=sessions)
    alice, bob = browser(app), browser(app)
    link = alice.post("/api/claims").json()["url"]
    later = time.time() + 601
    monkeypatch.setattr("wfb.studio.sessions.time.time", lambda: later)
    assert bob.get(link).status_code == 410


def test_the_startup_link_gives_the_faces_made_before_owners(studio, sessions):
    legacy = studio.create(Bundle("Old", starters.instantiate("minimal", "Old")), "old")
    meta = studio.store.root / legacy.id / "meta.json"
    data = json.loads(meta.read_text())
    del data["owner"]                                       # as written before sessions
    meta.write_text(json.dumps(data))
    studio._open.clear()
    app = create_app(studio, sessions=sessions)
    stranger = browser(app)
    assert stranger.get("/api/home").json()["documents"] == []
    me = TestClient(app)
    code = sessions.startup_claim()
    assert me.get(f"/?claim={code}", follow_redirects=False).status_code == 303
    assert [d["name"] for d in me.get("/api/home").json()["documents"]] == ["Old"]
    assert TestClient(app).get(f"/?claim={code}").status_code == 410


def test_single_user_shares_every_face(tmp_path, studio):
    shared = Sessions(tmp_path / "state", keep_days=30, single_user=True)
    app = create_app(studio, sessions=shared)
    one, two = TestClient(app), TestClient(app)
    new_face(one, "Ours")
    assert [d["name"] for d in two.get("/api/home").json()["documents"]] == ["Ours"]
    assert two.get("/api/home").json()["shared"] is True
    assert two.post("/api/claims").status_code == 400
    assert COOKIE not in two.get("/").headers.get("set-cookie", "")


def test_only_the_allowed_host_names_are_answered(studio):
    """A page that points its own name at this address (DNS rebinding) sends
    its own name as Host: the editor answers it only when told to."""
    hosts = allowed_hosts("127.0.0.1", [])
    assert hosts == ["127.0.0.1", "localhost", "[::1]"]
    assert allowed_hosts("0.0.0.0", ["studio.lan"]) == hosts + ["studio.lan"]
    assert allowed_hosts("::1", []) == hosts
    guarded = create_app(studio, allowed_hosts=hosts)
    for name in ("127.0.0.1:8765", "localhost:8765", "[::1]:8765"):
        assert TestClient(guarded).get("/api/home", headers={"Host": name}).status_code == 200
    evil = {"Host": "evil.example:8765", "Origin": "http://evil.example"}
    assert TestClient(guarded).get("/api/home", headers=evil).status_code == 400
    assert TestClient(guarded).post("/api/documents/new?template=minimal",
                                    headers=evil).status_code == 400
    # the contrast: without the allowlist, the same request is served
    assert TestClient(create_app(studio)).get("/api/home", headers=evil).status_code == 200


def test_a_stream_hears_only_of_its_principals_faces():
    owners = {"a1": "alice", "b1": "bob"}

    async def run() -> list[str]:
        events = Events(owners.get)
        alice, everyone = events.stream("alice"), events.stream()
        for stream in (alice, everyone):
            await stream.__anext__()
        events.publish("changed", {"id": "b1", "version": 2})
        events.publish("changed", {"id": "a1", "version": 3})
        heard = [await asyncio.wait_for(alice.__anext__(), 1)]
        heard += [await asyncio.wait_for(everyone.__anext__(), 1) for _ in range(2)]
        for stream in (alice, everyone):
            await stream.aclose()
        return heard

    heard = asyncio.run(run())
    assert ['"a1"' in m for m in heard] == [True, False, True]


def test_pruning_drops_stale_sessions_and_principals_with_nothing(tmp_path, studio):
    sessions = Sessions(tmp_path / "state", keep_days=1)
    kept, token = sessions.new_browser()
    stale, _ = sessions.new_browser()
    owner_of_a_face, _ = sessions.new_browser()
    later = time.time() + 2 * 86400
    sessions.principal_of(token)                   # seen now: kept
    path = next(p for p in (sessions.root / "sessions").glob("*.json")
                if json.loads(p.read_text())["principal"] == kept)
    data = json.loads(path.read_text())
    data["last_seen"] = later
    path.write_text(json.dumps(data))
    removed = sessions.prune({owner_of_a_face}, now=later)
    assert sum(r.startswith("session ") for r in removed) == 2
    assert set(sessions.principals()) == {OWNER, kept, owner_of_a_face}
