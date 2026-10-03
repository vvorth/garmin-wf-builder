"""Does the editor accept a cross-site 'simple request' (text/plain POST, foreign Origin and Host)?"""
import sys, tempfile, json
from pathlib import Path
sys.path.insert(0, ".")
from starlette.testclient import TestClient
from wfb.devices import DeviceDatabase
from wfb.studio.store import Store
from wfb.studio.document import Studio
from wfb.studio.app import create_app

studio = Studio(Store(Path(tempfile.mkdtemp())), DeviceDatabase.discover(None))
app = create_app(studio)
evil = {"Origin": "http://evil.example", "Host": "evil.example:8765", "Content-Type": "text/plain"}
with TestClient(app, base_url="http://evil.example:8765") as c:
    r = c.post("/api/documents/new?template=minimal&name=Planted", headers=evil)
    print("new        ", r.status_code, r.json().get("id", r.text)[:40])
    doc = r.json()
    home = c.get("/api/home", headers=evil).json()
    print("home lists ", [d["name"] for d in home["documents"]])
    body = json.dumps({"op": "set", "path": ["face", "name"], "value": "Defaced"})
    r = c.post(f"/api/documents/{doc['id']}/edit?version={doc['version']}", content=body, headers=evil)
    print("edit       ", r.status_code, r.json().get("name", r.text)[:60])
    r = c.get(f"/api/documents/{doc['id']}/download?form=yaml", headers=evil)
    print("download   ", r.status_code, len(r.content), "bytes readable")
studio.close()
