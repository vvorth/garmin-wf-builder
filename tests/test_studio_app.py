"""The editor's whole page (`app.js`) rendered in Node with preact over the
minimal DOM (`tests/studio_dom.mjs`), against a stand-in server that
answers from a real face's summary: the home screen and the editor
render, and their menus open and send what the server expects. Nothing is
drawn or laid out; how the page looks is still checked by hand."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from wfb import starters
from wfb.studio.bundle import Bundle
from wfb.studio.document import Studio
from wfb.studio.inspect import vocabulary
from wfb.studio.store import Store

HERE = Path(__file__).resolve().parent
STATIC = HERE.parent / "wfb/studio/static"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture
def face(tmp_path, db):
    """A face with three changes and an error, its summary and the home list."""
    studio = Studio(Store(tmp_path / "state"), db, scratch=tmp_path / "scratch")
    try:
        doc = studio.create(Bundle("Morning", starters.instantiate("minimal", "Morning")), "new")
        for v in ("1.0.1", "1.0.2"):
            doc.edit({"op": "set", "path": ["face", "version"], "value": v}, doc.version)
        doc.replace_text(doc.text.replace("color: color.dim", "color: color.nope"), doc.version)
        return {"summary": doc.summary(), "home": {
            "templates": [{"name": "minimal", "blurb": ""}], "store": "/state", "shared": True,
            "documents": studio.store.documents()}}
    finally:
        studio.close()


def page(face: dict, route: str, body: str) -> list:
    """Load the page at ``route`` over a stand-in server, run ``body`` and
    return what it prints, one JSON value a line. Every request the page
    makes is in `requests`."""
    script = f"""
      import {{ install }} from {json.dumps((HERE / 'studio_dom.mjs').as_uri())};
      const document = install();
      const app = document.createElement("div");
      document.getElementById = () => app;
      document.querySelector = () => null;
      document.documentElement = document.createElement("html");   // CodeMirror reads it on import
      globalThis.window = globalThis;
      // the page's own listeners on the window, so a test can press keys
      const listeners = {{}};
      globalThis.addEventListener = (t, f) => {{ (listeners[t] ||= []).push(f); }};
      globalThis.removeEventListener = (t, f) => {{ listeners[t] = (listeners[t] || []).filter((g) => g !== f); }};
      const press = (key, mods = {{}}) => {{
        const event = {{ key, ...mods, target: {{ closest: () => null }}, prevented: false,
                         preventDefault() {{ this.prevented = true; }} }};
        for (const f of listeners.keydown || []) f(event);
        return event.prevented;
      }};
      globalThis.location = {{ hash: {json.dumps(route)}, href: "http://studio/", reload() {{}} }};
      globalThis.EventSource = class {{ addEventListener() {{}} close() {{}} }};
      const summary = {json.dumps(face["summary"])};
      const answers = {{
        "/api/home": {json.dumps(face["home"])},
        "/api/vocabulary": {json.dumps({**vocabulary(), "devices": []})},
      }};
      answers[`/api/documents/${{summary.id}}`] = summary;
      const requests = [];
      globalThis.fetch = async (url, options = {{}}) => {{
        const path = url.split("?")[0];
        requests.push([options.method || "GET", url]);
        let body = answers[path];
        if (path.endsWith("/goto")) body = summary;
        if (path.endsWith("/rename")) body = {{ id: summary.id, name: new URLSearchParams(url.split("?")[1]).get("name") }};
        if (body === undefined) return new Promise(() => {{}});      // a frame: never drawn here
        return {{ ok: true, status: 200, statusText: "OK", headers: {{ get: () => "application/json" }},
                  json: async () => body }};
      }};
      await import({json.dumps((STATIC / 'app.js').as_uri())});
      const settle = () => new Promise((r) => setTimeout(r, 10));
      await settle(); await settle();
      const cls = (e) => e.attributes.class || "";
      const find = (pred) => app.all(pred);
      const button = (text) => find((e) => e.localName === "button" && e.textContent.trim().startsWith(text))[0];
      const click = async (e) => {{ e.click(); await settle(); }};
      const out = (v) => console.log(JSON.stringify(v));
      {body}
    """
    done = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-2000:]
    return [json.loads(line) for line in done.stdout.splitlines()]


def test_the_library_shows_each_face_with_its_picture_and_renames_it(face):
    printed = page(face, "#/", """
      const img = find((e) => e.localName === "img" && e.parentNode && cls(e.parentNode) === "cover")[0];
      out(img.attributes.src.split("?")[0].endsWith("/cover"));
      await click(button("Rename"));
      const input = find((e) => e.localName === "input" && cls(e).startsWith("inline-name"))[0];
      out(input.attributes.value);
      input.value = "Evening"; input.dispatch("input", { target: input }); await settle();
      input.dispatch("keydown", { key: "Enter", target: input }); await settle();
      out(requests.filter(([m]) => m === "POST").map(([m, u]) => u.split("/").pop()));
    """)
    assert printed[0] is True
    assert printed[1] == "Morning"
    assert printed[2] == ["rename?name=Evening"]


def test_the_editor_folds_its_controls_away_and_names_what_undo_takes_back(face):
    doc = face["summary"]
    printed = page(face, f"#/face/{doc['id']}", """
      const text = app.textContent;
      // the toolbar keeps the device and zoom; the rest is behind Preview
      out([text.includes("Device"), text.includes("Zoom"), text.includes("asleep")]);
      await click(button("Preview"));
      out(app.textContent.includes("asleep") && app.textContent.includes("AOD"));
      out(button("↶ Undo").attributes.title);
      // the history menu lists the changes and goes to one in one step
      await click(find((e) => e.localName === "button" && e.textContent === "▾" && e.attributes.title.startsWith("Go back"))[0]);
      const states = find((e) => e.localName === "button" && cls(e) === "state");
      out(states.map((b) => b.textContent.split(/\\d/)[0].trim()));
      await click(states[states.length - 1]);
      out(requests.filter(([m]) => m === "POST").map(([m, u]) => u.split("/").pop().split("&")[0]));
      // one keyboard listener for the editor's life: Ctrl+Z undoes, an
      // arrow with nothing selected is the browser's
      out([(listeners.keydown || []).length, press("z", { ctrlKey: true }), press("ArrowLeft")]);
      await settle();
      out(requests.filter(([m]) => m === "POST").map(([m, u]) => u.split("/").pop().split("?")[0]));
      // the error count opens Diagnostics on the errors
      await click(find((e) => e.localName === "button" && cls(e) === "errors")[0]);
      out(app.textContent.includes("errors only"));
      // the Properties section folds away
      await click(find((e) => e.localName === "h3" && cls(e) === "fold")[0]);
      out(cls(find((e) => cls(e).startsWith("panel right"))[0]));
    """)
    assert printed[0] == [True, True, False]
    assert printed[1] is True
    assert printed[2] == "Undo: edit the text (Ctrl+Z)"
    assert printed[3][0] == "edit the text" and printed[3][-1].startswith("new")
    seq = doc["history"]["states"][-1]["seq"]
    assert printed[4] == [f"goto?seq={seq}"]
    _, undo_prevented, arrow_prevented = printed[5]
    assert undo_prevented is True and arrow_prevented is False
    # one Ctrl+Z is one undo: a listener left behind by a render would send two
    assert printed[6] == ["goto", "undo"]
    assert printed[7] is True
    assert "props-folded" in printed[8]


def _deferred_fetch() -> str:
    """Script wrapping the stand-in server so a test holds back the answer to
    each POST until it calls `release(i, status)` (200 answers the face one
    version on, anything else refuses)."""
    return """
      const held = [];
      const serve = globalThis.fetch;
      globalThis.fetch = (url, options = {}) => {
        if ((options.method || "GET") !== "POST") return serve(url, options);
        requests.push(["POST", url]);
        return new Promise((resolve) => held.push((status) => resolve({
          ok: status === 200, status, statusText: "", headers: { get: () => "application/json" },
          json: async () => status === 200 ? { ...summary, version: summary.version + 1 }
                                           : { error: "refused for the test" } })));
      };
      const release = async (i, status = 200) => { held[i](status); await settle(); await settle(); };
    """


def test_an_answer_for_a_face_left_behind_never_replaces_the_face_opened(face):
    doc = face["summary"]
    printed = page(face, f"#/face/{doc['id']}", _deferred_fetch() + """
      const other = { ...summary, id: "b".repeat(32), name: "Evening", version: 1 };
      answers[`/api/documents/${other.id}`] = other;
      press("z", { ctrlKey: true }); await settle();        // face A's undo, on its way
      location.hash = `#/face/${other.id}`;
      for (const f of listeners.hashchange || []) f();
      await settle(); await settle();
      const name = () => find((e) => cls(e).startsWith("name renamable"))[0].textContent;
      out(name());
      await release(0);                                     // A's answer arrives late
      out(name());
      // the next change is aimed at B's version, not A's
      press("z", { ctrlKey: true }); await settle();
      out(requests.filter(([m]) => m === "POST").map(([m, u]) => u.split("/api/documents/")[1]));
    """)
    assert printed[0] == "Evening"
    assert printed[1] == "Evening"
    assert printed[2] == [f"{doc['id']}/undo?version={doc['version']}", f"{'b' * 32}/undo?version=1"]


def test_a_refused_change_says_how_many_queued_behind_it_were_not_sent(face):
    doc = face["summary"]
    printed = page(face, f"#/face/{doc['id']}", _deferred_fetch() + """
      press("z", { ctrlKey: true }); press("z", { ctrlKey: true }); press("z", { ctrlKey: true });
      await settle();
      await release(0, 400);
      out(find((e) => cls(e).startsWith("toast"))[0].textContent);
      out(requests.filter(([m]) => m === "POST").length);
    """)
    assert printed[0] == "refused for the test (2 later changes were not sent)"
    assert printed[1] == 1
