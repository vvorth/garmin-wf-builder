// The editor's worker: bundles in and out, the history store, documents and
// the requests the page sends.
import assert from "node:assert/strict";
import { test } from "node:test";
import { unzlibSync, zipSync } from "fflate";
import { indexFor } from "../src/edit/spans.ts";
import { decodePng } from "../src/png.ts";
import * as starters from "../src/starters.ts";
import { bundle, BundleError, inside, missing, readUpload, references, toZip } from "../src/studio/bundle.ts";
import { frameKey, HISTORY_SHOWN, StaleVersion } from "../src/studio/document.ts";
import { type Change, CHANGE, MemoryBackend, replay, Store } from "../src/studio/store.ts";
import {
  ALIGN, bumped, CHIVO, Client, DYNALIGHT, minimalText, newStudio, noAssets, PROFILE, read, readText, SHOWCASE, STYLES, versionOf,
} from "./studio-client.ts";

const enc = (text: string): Uint8Array => new TextEncoder().encode(text);

/** A zip of `entries`; each name in `links` a symbolic link. */
function zipped(entries: Record<string, Uint8Array | string>, links: string[] = []): Uint8Array {
  const files: Record<string, [Uint8Array, { os?: number; attrs?: number }]> = {};
  for (const [name, data] of Object.entries(entries)) {
    files[name] = [typeof data === "string" ? enc(data) : data, links.includes(name) ? { os: 3, attrs: ((0o120777 << 16) >>> 0) } : {}];
  }
  return zipSync(files as never);
}

// -- bundles --

test("inside keeps a path in the bundle", () => {
  const cases: [string, string | null][] = [
    ["assets/a.ttf", "assets/a.ttf"], ["./assets/a.ttf", "assets/a.ttf"], ["assets/../a.ttf", "a.ttf"],
    ["../outline/assets/a.ttf", null], ["/etc/passwd", null], ["C:/fonts/a.ttf", null], ["assets\\a.ttf", null], ["", null],
  ];
  for (const [value, expected] of cases) assert.equal(inside(value), expected, value);
});

test("a yaml upload is its text named after the face", () => {
  const b = readUpload("whatever.yaml", enc(minimalText("Morning Run")));
  assert.equal(b.name, "Morning Run");
  assert.equal(b.files.size, 0);
  assert.equal(readUpload("x.yml", enc("format: 2\n")).name, "x");
});

test("a zip upload holds the face and its files", () => {
  const data = zipped({
    "face.yaml": read(SHOWCASE), "assets/ChivoMono-Bold.ttf": "ttf", "README.md": "kept", "__MACOSX/._face.yaml": "junk", ".DS_Store": "junk",
  });
  const b = readUpload("Showcase.zip", data);
  assert.equal(b.text, readText(SHOWCASE));
  assert.deepEqual([...b.files.keys()].sort(), ["README.md", "assets/ChivoMono-Bold.ttf"]);
});

test("a zipped folder is read as its contents", () => {
  const b = readUpload("myface.zip", zipped({ "myface/face.yaml": "format: 2\n", "myface/assets/a.ttf": "x" }));
  assert.equal(b.text, "format: 2\n");
  assert.deepEqual([...b.files.keys()], ["assets/a.ttf"]);
});

test("a bad bundle is refused with its reason", () => {
  const cases: [Record<string, Uint8Array | string>, string[], RegExp][] = [
    [{ "face.yaml": "a: 1", "../evil.ttf": "x" }, [], /outside the bundle/],
    [{ "face.yaml": "a: 1", "/etc/evil": "x" }, [], /outside the bundle/],
    [{ "face.yaml": "a: 1", "assets/link.ttf": "/etc/passwd" }, ["assets/link.ttf"], /link/],
    [{ "assets/a.ttf": "x", "notes.txt": "x" }, [], /no \.yaml at its root/],
    [{ "one.yaml": "a: 1", "two.yaml": "a: 1" }, [], /more than one \.yaml/],
    [{ "face.yaml": Uint8Array.from([0xff, 0xfe, 0, 0x62]) }, [], /not UTF-8/],
  ];
  for (const [entries, links, reason] of cases) assert.throws(() => readUpload("x.zip", zipped(entries, links)), (e: Error) => e instanceof BundleError && reason.test(e.message));
});

test("two root yamls are fine when one is face.yaml", () => {
  const b = readUpload("x.zip", zipped({ "face.yaml": "a: 1\n", "other.yaml": "b: 2\n" }));
  assert.equal(b.text, "a: 1\n");
  assert.deepEqual([...b.files.keys()], ["other.yaml"]);
});

test("a bundle over its limits is refused before unpacking", () => {
  const data = zipped({ "face.yaml": "a: 1", "assets/big.ttf": "0".repeat(5000) });
  assert.throws(() => readUpload("x.zip", data, { unpacked: 4000 }), /unpacks to over/);
  assert.throws(() => readUpload("x.zip", data, { unpacked: 10_000, entries: 1 }), /entries/);
});

test("an upload that is neither yaml nor zip is refused", () => {
  assert.throws(() => readUpload("face.json", enc("{}")), /neither/);
  assert.throws(() => readUpload("face.zip", enc("not a zip")), /not a readable \.zip/);
});

test("references and missing read the font sources", () => {
  const text = readText(SHOWCASE);
  assert.deepEqual(references(text).map((r) => r.value), ["assets/ChivoMono-Bold.ttf", "assets/Dynalight-Regular.ttf"]);
  assert.deepEqual(missing(text, new Set(["assets/ChivoMono-Bold.ttf"])).map((r) => r.value), ["assets/Dynalight-Regular.ttf"]);
  assert.deepEqual(references("a: [1, 2\n"), []);
});

test("a zip round trips", () => {
  const b = bundle("S", readText(SHOWCASE), new Map([["assets/a.ttf", enc("one")], ["assets/b.ttf", enc("two")]]));
  const again = readUpload("s.zip", toZip(b));
  assert.equal(again.text, b.text);
  assert.deepEqual(again.files, b.files);
});

// -- starters --

test("every new face gets its own uuid and name", () => {
  const [a, b] = [starters.instantiate("minimal", "One"), starters.instantiate("minimal", "Two")];
  const face = (t: string): Map<string, unknown> => (indexFor(t).data as Map<string, any>).get("face");
  assert.notEqual(face(a).get("id"), face(b).get("id"));
  assert.ok(!a.includes("__UUID__"));
  assert.equal(face(a).get("name"), "One");
});

test("a template is a name, never a path", () => {
  for (const name of ["../minimal", "/etc/passwd", "nope", "__proto__"]) assert.throws(() => starters.instantiate(name, "X"), starters.UnknownTemplate);
});

// -- the store and documents --

test("a new document is its first journal record", async () => {
  const studio = await newStudio();
  const doc = studio.create(bundle("T", minimalText()), "new");
  assert.deepEqual(studio.store.journal(doc.id).map((c) => [c.seq, c.label]), [[1, "new"]]);
});

test("a document survives a new store over the same records", async () => {
  const backend = new MemoryBackend();
  const first = await newStudio(backend);
  const doc = first.create(readUpload("show.zip", zipped({ "face.yaml": read(SHOWCASE), "assets/ChivoMono-Bold.ttf": read(CHIVO), "assets/Dynalight-Regular.ttf": read(DYNALIGHT) })), "open");
  doc.commit(bumped(doc, 1), new Map(Object.entries(doc.head.assets)), "one", doc.version);
  await first.store.flush();
  const second = await newStudio(backend);
  const again = second.document(doc.id);
  assert.equal(again.version, 2);
  assert.equal(again.text, doc.text);
  assert.deepEqual(again.bundle().files.get("assets/ChivoMono-Bold.ttf"), read(CHIVO));
  assert.notEqual(again.analysis().face, null);
});

test("a tab's change survives another tab's next change once that tab reloads", async () => {
  const backend = new MemoryBackend();
  const a = await newStudio(backend);
  const id = a.create(bundle("T", minimalText()), "new").id;
  await a.store.flush();
  const b = await newStudio(backend);
  const there = a.document(id);
  there.commit(bumped(there, 1), new Map(), "tab A", there.version);
  await a.store.flush();
  await b.reload(id);
  const here = b.document(id);
  here.commit(bumped(here, 2), new Map(), "tab B", here.version);
  await b.store.flush();
  const after = await newStudio(backend);
  assert.deepEqual(after.store.journal(id).map((c) => c.label), ["new", "tab A", "tab B"]);
  a.delete(id);
  await a.store.flush();
  await b.reload(id);
  assert.equal(b.store.has(id), false);
});

test("a merged change takes the place of the one before", () => {
  const change = (seq: number, kind = CHANGE, target?: number, merge = false): Change =>
    ({ seq, time: 0, label: `c${seq}`, text: "", assets: {}, kind, ...(target !== undefined ? { target } : {}), ...(merge ? { merge } : {}) });
  let line = replay([change(1), change(2), change(3, CHANGE, undefined, true), change(4, CHANGE, undefined, true)]);
  assert.deepEqual([line.states.map((c) => c.seq), line.cursor], [[1, 4], 1]);
  line = replay([change(1), change(2), change(3, CHANGE, undefined, true), change(4, "undo", 1), change(5, "redo", 3)]);
  assert.deepEqual([line.states.map((c) => c.seq), line.cursor], [[1, 3], 1]);
});

test("a long history replays in linear time", () => {
  const journal = Array.from({ length: 20000 }, (_, i): Change => ({ seq: i + 1, time: 0, label: "c", text: "", assets: {}, kind: CHANGE }));
  const start = performance.now();
  assert.equal(replay(journal).states.length, 20000);
  assert.ok(performance.now() - start < 1000);
});

test("replay moves a cursor, and a change after an undo drops the redo branch", () => {
  const c = (seq: number, kind = CHANGE, target?: number): Change => ({ seq, time: 0, label: String(seq), text: "t", assets: {}, kind, ...(target ? { target } : {}) });
  let line = replay([c(1), c(2), c(3), c(4, "undo", 2), c(5, "undo", 1), c(6, "redo", 2)]);
  assert.deepEqual([line.states.map((s) => s.seq), line.cursor], [[1, 2, 3], 1]);
  line = replay([c(1), c(2), c(3), c(4, "undo", 2), c(5)]);
  assert.deepEqual(line.states.map((s) => s.seq), [1, 2, 5]);
  assert.equal(line.cursor, 2);
});

test("a summary lists the newest changes and the history lists all", async () => {
  const client = await Client.open();
  const doc = await client.create();
  const document = client.studio.document(doc.id);
  for (let i = 0; i < HISTORY_SHOWN + 5; i++) document.commit(bumped(document, i), noAssets, `c${i}`, document.version);
  const summary = (await client.get(`/api/documents/${doc.id}`)).json.history;
  assert.equal(summary.states.length, HISTORY_SHOWN);
  assert.equal(summary.total, HISTORY_SHOWN + 6);
  assert.ok(summary.states[0].current);
  assert.equal(summary.states[0].label, `c${HISTORY_SHOWN + 4}`);
  const whole = (await client.get(`/api/documents/${doc.id}/history`)).json;
  assert.equal(whole.states.length, HISTORY_SHOWN + 6);
  assert.match(whole.states.at(-1).label, /^new/);
});

test("a change against an old version is refused", async () => {
  const studio = await newStudio();
  const doc = studio.create(bundle("T", minimalText()), "new");
  doc.commit(doc.text, noAssets, "one", 1);
  assert.throws(() => doc.commit(doc.text, noAssets, "two", 1), StaleVersion);
});

test("diagnostics name face.yaml and the bundle's own paths", async () => {
  const studio = await newStudio();
  const doc = studio.create(readUpload("face.yaml", read(SHOWCASE)), "open");
  const shown = doc.diagnostics();
  assert.ok(shown.length > 0);
  assert.deepEqual(new Set(shown.filter((d) => "file" in d).map((d) => d["file"])), new Set(["face.yaml"]));
  assert.ok(JSON.stringify(shown).includes("assets/ChivoMono-Bold.ttf"));
});

test("the tree holds blocks, layouts and groups", async () => {
  const studio = await newStudio();
  const doc = studio.create(readUpload("face.yaml", read(STYLES)), "open");
  const labels = doc.tree().map((b) => b["label"]);
  assert.deepEqual(labels.slice(0, 2), ["static", "elements"]);
  assert.ok(labels.includes("big: static"));
  const groups = studio.create(readUpload("face.yaml", read(ALIGN)), "open");
  const nested = groups.tree().flatMap((b) => b["children"] as any[]).filter((n) => n.children.length > 0);
  assert.ok(nested.length > 0, "a group's children are its tree children");
  assert.equal(nested[0].type, "group");
});

test("a frame has an item and a layer per drawn element", async () => {
  const studio = await newStudio();
  const doc = studio.create(bundle("T", minimalText()), "new");
  const frame = doc.frame(frameKey({ device: "fr955", scale: 1 })) as any;
  assert.deepEqual([frame.width, frame.height], [260, 260]);
  assert.deepEqual(frame.items.map((i: any) => i.id), ["background", "clock", "seconds"]);
  assert.deepEqual(frame.layers.map((l: any) => l.id), ["background", "clock", "seconds"]);
  assert.ok(frame.layers.every((l: any) => "ops" in l && !("image" in l)));
  const runs = frame.layers[1].ops.flatMap((op: any) => op.run ?? []);
  assert.ok(runs.length > 0, "the clock's text arrives as tiles");
  const packed = unzlibSync(Uint8Array.from(atob(frame.tiles.data), (c) => c.charCodeAt(0)));
  for (const item of runs) {
    const [offset, width, height, kind] = frame.tiles.index[item.tile];
    assert.equal(kind, "mask");
    assert.ok(offset + width * height * 4 <= packed.length);
  }
});

test("an outlined group's ring travels as its image", async () => {
  const studio = await newStudio();
  const doc = studio.create(readUpload("face.yaml", read("examples/features/rings/face.yaml")), "open");
  const frame = doc.frame(frameKey({ device: "fr955", scale: 1 })) as any;
  const ring = frame.layers.find((l: any) => l.id.startsWith("ring:"));
  const png = decodePng(Uint8Array.from(atob(ring.image.split(",", 2)[1]), (c) => c.charCodeAt(0)))!;
  assert.ok(png.width > 0 && png.pixels.some((v, i) => i % 4 === 3 && v > 0));
  assert.ok(!("ops" in ring));
  assert.equal(ring.origin.length, 2);
});

// -- the requests --

test("new from a template", async () => {
  const client = await Client.open();
  const r = await client.post("/api/documents/new?template=analog&name=Dial");
  assert.equal(r.status, 200);
  assert.equal(r.json.name, "Dial");
  assert.equal(r.json.version, 1);
  assert.ok(r.json.loads);
  assert.deepEqual(r.json.diagnostics.filter((d: any) => d.severity === "error"), []);
  assert.deepEqual((await client.get("/api/home")).json.documents.map((d: any) => d.id), [r.json.id]);
  assert.equal((await client.post("/api/documents/new?template=../x")).status, 400);
});

test("upload then download returns the same bytes", async () => {
  const client = await Client.open();
  const text = minimalText("Plain");
  const plain = await client.upload("plain.yaml", text);
  const r = await client.get(`/api/documents/${plain.id}/download`);
  assert.equal(r.filename, "plain.yaml");
  assert.equal(new TextDecoder().decode(r.body), text);
  const doc = await client.upload("show.zip", zipped({ "face.yaml": read(SHOWCASE), "assets/ChivoMono-Bold.ttf": read(CHIVO), "assets/Dynalight-Regular.ttf": read(DYNALIGHT) }));
  assert.deepEqual(doc.missing, []);
  assert.ok(doc.loads);
  const zip = await client.get(`/api/documents/${doc.id}/download`);
  assert.equal(zip.filename, "showcase.zip");
  const again = readUpload("x.zip", zip.body!);
  assert.equal(again.text, readText(SHOWCASE));
  assert.deepEqual(again.files.get("assets/ChivoMono-Bold.ttf"), read(CHIVO));
  assert.equal(new TextDecoder().decode((await client.get(`/api/documents/${doc.id}/download?form=yaml`)).body), readText(SHOWCASE));
});

test("a missing font is listed, then added and its reference patched", async () => {
  const client = await Client.open();
  const doc = await client.upload("face.yaml", read(PROFILE));
  const ref = "../outline/assets/ChivoMono-Bold.ttf";
  assert.deepEqual(doc.missing, [ref]);
  assert.ok(!doc.loads);
  const r = await client.post(`/api/documents/${doc.id}/assets?filename=Chivo.ttf&reference=${ref}&version=1`, read(CHIVO));
  assert.equal(r.status, 200, JSON.stringify(r.json));
  const after = r.json;
  assert.deepEqual(after.missing, []);
  assert.ok(after.loads);
  assert.equal(after.version, 2);
  assert.ok(after.text.includes("source: assets/Chivo.ttf"));
  const before = doc.text.split("\n"), now = after.text.split("\n");
  const changed = before.filter((line: string, i: number) => line !== now[i]);
  assert.equal(changed.length, before.filter((line: string) => line.includes(ref)).length);
});

test("an asset against an old version is refused", async () => {
  const client = await Client.open();
  const doc = await client.upload("face.yaml", read(SHOWCASE));
  const url = `/api/documents/${doc.id}/assets`;
  assert.equal((await client.post(`${url}?filename=a.ttf&reference=assets/ChivoMono-Bold.ttf&version=1`, read(CHIVO))).status, 200);
  const stale = await client.post(`${url}?filename=b.ttf&reference=assets/Dynalight-Regular.ttf&version=1`, read(DYNALIGHT));
  assert.equal(stale.status, 409);
  assert.match(stale.json.error, /version 2/);
  assert.equal((await client.post(`${url}?filename=b.ttf&reference=nope.ttf&version=2`, read(DYNALIGHT))).status, 400);
  assert.equal((await client.get(`/api/documents/${doc.id}`)).json.version, 2);
});

test("frames and refusals", async () => {
  const client = await Client.open();
  const doc = await client.create("minimal", "F");
  const url = `/api/documents/${doc.id}/frame`;
  const frame = (await client.get(`${url}?device=fenix8solar47mm&scale=1&time=12:34`)).json;
  assert.equal(frame.device, "fenix8solar47mm");
  assert.ok(frame.items.length > 0);
  for (const query of ["device=vivoactive4", "device=fr955&time=25:00", "device=fr955&date=2026-02-30", "device=fr955&date=4.10.2026", "device=fr955&scale=big"]) {
    assert.equal((await client.get(`${url}?${query}`)).status, 400, query);
  }
  assert.equal((await client.get("/api/documents/" + "0".repeat(32))).status, 404);
  assert.equal((await client.get("/api/documents/../../etc")).status, 404);
});

test("delete removes the document and its history", async () => {
  const client = await Client.open();
  const doc = await client.create();
  assert.equal((await client.delete(`/api/documents/${doc.id}`)).status, 200);
  assert.equal((await client.get(`/api/documents/${doc.id}`)).status, 404);
  assert.deepEqual((await client.get("/api/home")).json.documents, []);
  assert.deepEqual(client.events.at(-1), ["deleted", { id: doc.id }]);
});

// -- history: undo, redo, snapshots, restore --

test("undo and redo step through the changes", async () => {
  const studio = await newStudio();
  const doc = studio.create(bundle("T", minimalText()), "new");
  const first = doc.text;
  doc.commit(bumped(doc, 1), noAssets, "one", doc.version);
  doc.commit(bumped(doc, 2), noAssets, "two", doc.version);
  doc.undo(doc.version);
  assert.equal(versionOf(doc), "1.0.1");
  doc.undo(doc.version);
  assert.equal(doc.text, first);
  assert.throws(() => doc.undo(doc.version), /nothing to undo/);
  doc.redo(doc.version);
  doc.redo(doc.version);
  assert.equal(versionOf(doc), "1.0.2");
  assert.throws(() => doc.redo(doc.version), /nothing to redo/);
  // a change after an undo ends the redo line
  doc.undo(doc.version);
  doc.commit(bumped(doc, 3), noAssets, "three", doc.version);
  assert.throws(() => doc.redo(doc.version), /nothing to redo/);
  assert.deepEqual((doc.history()["states"] as any[]).map((s) => s.label), ["three", "one", "new"]);
});

test("undo against an old version is refused", async () => {
  const studio = await newStudio();
  const doc = studio.create(bundle("T", minimalText()), "new");
  doc.commit(bumped(doc, 1), noAssets, "one", doc.version);
  assert.throws(() => doc.undo(1), StaleVersion);
});

test("undo takes an added asset back out", async () => {
  const studio = await newStudio();
  const doc = studio.create(readUpload("face.yaml", read(PROFILE)), "open");
  doc.addAsset("Chivo.ttf", read(CHIVO), "../outline/assets/ChivoMono-Bold.ttf", doc.version);
  assert.ok(doc.bundle().files.has("assets/Chivo.ttf"));
  assert.notEqual(doc.analysis().face, null);
  doc.undo(doc.version);
  assert.ok(!doc.bundle().files.has("assets/Chivo.ttf"));
  assert.deepEqual(doc.missing(), ["../outline/assets/ChivoMono-Bold.ttf"]);
  doc.redo(doc.version);
  assert.deepEqual(doc.bundle().files.get("assets/Chivo.ttf"), read(CHIVO));
});

test("undo and redo survive a new store", async () => {
  const backend = new MemoryBackend();
  const first = await newStudio(backend);
  const doc = first.create(bundle("T", minimalText()), "new");
  doc.commit(bumped(doc, 1), noAssets, "one", doc.version);
  doc.commit(bumped(doc, 2), noAssets, "two", doc.version);
  doc.undo(doc.version);
  await first.store.flush();
  const again = (await newStudio(backend)).document(doc.id);
  assert.equal(versionOf(again), "1.0.1");
  const history = again.history();
  assert.ok(history["can_undo"] && history["can_redo"]);
  again.redo(again.version);
  assert.equal(versionOf(again), "1.0.2");
});

test("a write the store cannot make is reported, not acknowledged", async () => {
  const backend = new MemoryBackend();
  const client = new Client(await newStudio(backend));
  const doc = await client.create();
  backend.put = async () => {
    throw new Error("disk full");
  };
  const r = await client.post(`/api/documents/${doc.id}/edit?version=1`, { op: "set", path: ["face", "version"], value: "2.0.0" });
  assert.equal(r.status, 507);
  assert.match(r.json.error, /disk full/);
  // what was not written is not there for the next session
  assert.equal((await Store.open(backend)).head(doc.id)!.seq, 1);
});

test("the timer snapshots a changed face once per interval", async () => {
  const studio = await newStudio(new MemoryBackend(), { snapshotMinutes: 5 });
  const doc = studio.create(bundle("T", minimalText()), "new");
  const start = doc.lastSnapshot[0];
  assert.deepEqual(studio.tick(start + 60), []);
  assert.deepEqual(studio.tick(start + 301).map((t) => t.seq), [doc.version]);
  assert.deepEqual(studio.tick(start + 700), []);
  doc.commit(bumped(doc, 1), noAssets, "one", doc.version);
  assert.deepEqual(studio.tick(start + 302), []);
  assert.deepEqual(studio.tick(start + 700).map((t) => t.reason), ["timer"]);
  assert.deepEqual(studio.store.snapshots(doc.id).map((s) => s.seq), [1, 2]);
});

test("a restore is one change and can be undone", async () => {
  const studio = await newStudio();
  const doc = studio.create(bundle("T", minimalText()), "new");
  doc.commit(bumped(doc, 1), noAssets, "one", doc.version);
  const snap = doc.snapshot("manual");
  doc.commit(bumped(doc, 2), noAssets, "two", doc.version);
  doc.restore(snap.name, doc.version);
  assert.equal(versionOf(doc), "1.0.1");
  assert.match((doc.history()["states"] as any[])[0].label, /^restore the snapshot of/);
  doc.undo(doc.version);
  assert.equal(versionOf(doc), "1.0.2");
});

test("a snapshot in a dropped redo branch still restores", async () => {
  const studio = await newStudio();
  const doc = studio.create(bundle("T", minimalText()), "new");
  doc.commit(bumped(doc, 1), noAssets, "one", doc.version);
  const snap = doc.snapshot("manual");
  doc.undo(doc.version);
  doc.commit(bumped(doc, 2), noAssets, "two", doc.version);
  doc.restore(snap.name, doc.version);
  assert.equal(versionOf(doc), "1.0.1");
});

test("a snapshot opens as a copy", async () => {
  const studio = await newStudio();
  const doc = studio.create(readUpload("show.zip", zipped({ "face.yaml": read(SHOWCASE), "assets/ChivoMono-Bold.ttf": read(CHIVO), "assets/Dynalight-Regular.ttf": read(DYNALIGHT) })), "open");
  const snap = doc.snapshot("manual");
  doc.commit(bumped(doc, 7), new Map(Object.entries(doc.head.assets)), "later", doc.version);
  const copy = studio.fork(doc.id, snap.name);
  assert.notEqual(copy.id, doc.id);
  assert.equal(copy.text, studio.store.text(doc.id, snap));
  assert.ok(copy.bundle().files.has("assets/ChivoMono-Bold.ttf"));
  assert.notEqual(copy.analysis().face, null);
  assert.equal(versionOf(doc), "1.0.7");
});

test("pruning keeps every face and its newest snapshots", async () => {
  const studio = await newStudio();
  const old = studio.create(bundle("Old", minimalText()), "new");
  const keep = studio.create(bundle("Keep", minimalText()), "new");
  for (let i = 0; i < 4; i++) {
    keep.commit(bumped(keep, i), noAssets, `c${i}`, keep.version);
    keep.snapshot("manual", 1000 + i);
  }
  const removed = studio.store.prune(2);
  assert.ok(!removed.some((line) => line.includes("Old")));
  assert.ok(studio.store.has(old.id));
  assert.deepEqual(studio.store.snapshots(keep.id).map((s) => s.time), [1002, 1003]);
});

test("compaction keeps the newest changes, the version and what a snapshot needs", async () => {
  const backend = new MemoryBackend();
  const studio = await newStudio(backend);
  const doc = studio.create(bundle("T", minimalText()), "new");
  for (let i = 1; i < 4; i++) doc.commit(bumped(doc, i), noAssets, `c${i}`, doc.version);
  const snap = doc.snapshot("manual");
  doc.undo(doc.version);
  doc.commit(bumped(doc, 9), noAssets, "c9", doc.version);
  for (let i = 4; i < 7; i++) doc.commit(bumped(doc, i), noAssets, `c${i}`, doc.version);
  doc.undo(doc.version);
  const before = doc.history(null);
  const blobs = (): number => [...backend.records.keys()].filter((k) => k.startsWith(`blob/${doc.id}/`)).length;
  const count = blobs();
  assert.ok(doc.compact(3) > 0);
  await studio.store.flush();
  const again = (await newStudio(backend)).document(doc.id);
  const line = again.history(null) as any;
  assert.equal(again.version, before["version"]);
  assert.equal(versionOf(again), "1.0.5");
  assert.deepEqual(line.states.map((s: any) => s.label), ["c6", "c5", "c4"]);
  assert.deepEqual(line.states.map((s: any) => s.current), [false, true, false]);
  assert.ok(line.can_undo && line.can_redo);
  again.undo(again.version);
  assert.equal(versionOf(again), "1.0.4");
  assert.ok(!again.history(null)["can_undo"]);
  assert.ok(blobs() < count);
  again.restore(snap.name, again.version);
  assert.equal(versionOf(again), "1.0.3");
});

test("a history short enough is left alone", async () => {
  const studio = await newStudio();
  const doc = studio.create(bundle("T", minimalText()), "new");
  doc.commit(bumped(doc, 1), noAssets, "one", doc.version);
  assert.equal(doc.compact(10), 0);
});

test("the timer compacts an open face whose history has grown", async () => {
  const studio = await newStudio(new MemoryBackend(), { keepChanges: 2 });
  const doc = studio.create(bundle("T", minimalText()), "new");
  for (let i = 1; i < 5; i++) doc.commit(bumped(doc, i), noAssets, `c${i}`, doc.version);
  assert.equal(studio.store.journal(doc.id).length, 5);
  studio.tick(doc.lastSnapshot[0] + 1);
  assert.deepEqual(studio.store.journal(doc.id).map((c) => c.label), ["c3", "c4"]);
  assert.equal(doc.version, 5);
  assert.equal(versionOf(doc), "1.0.4");
});

test("pruning compacts every face", async () => {
  const studio = await newStudio();
  const doc = studio.create(bundle("T", minimalText()), "new");
  for (let i = 1; i < 6; i++) doc.commit(bumped(doc, i), noAssets, `c${i}`, doc.version);
  assert.deepEqual(studio.store.prune(5, 2), ["T: 4 old history lines, 4 unused files"]);
  assert.deepEqual(studio.store.journal(doc.id).map((c) => c.label), ["c4", "c5"]);
});

test("history through the requests", async () => {
  const client = await Client.open();
  const doc = await client.upload("face.yaml", read(SHOWCASE));
  const url = `/api/documents/${doc.id}`;
  assert.equal((await client.post(`${url}/undo?version=1`)).status, 400);
  const added = (await client.post(`${url}/assets?filename=a.ttf&reference=assets/ChivoMono-Bold.ttf&version=1`, read(CHIVO))).json;
  assert.ok(added.history.can_undo);
  assert.equal((await client.post(`${url}/undo?version=1`)).status, 409);
  const undone = (await client.post(`${url}/undo?version=2`)).json;
  assert.equal(undone.version, 3);
  assert.equal(undone.missing.length, 2);
  assert.ok(undone.history.can_redo);
  const redone = (await client.post(`${url}/redo?version=3`)).json;
  assert.equal(redone.missing.length, 1);
  const [snap] = (await client.post(`${url}/snapshots`)).json.snapshots;
  assert.equal(snap.reason, "manual");
  assert.ok(snap.current);
  await client.get(`${url}/download`);
  assert.equal((await client.get(url)).json.history.snapshots.length, 1);
  assert.equal((await client.post(`${url}/snapshots/${snap.name}/restore?version=4`)).json.version, 5);
  const copy = (await client.post(`${url}/snapshots/${snap.name}/copy`)).json;
  assert.notEqual(copy.id, doc.id);
  assert.deepEqual(copy.missing, redone.missing);
  assert.equal((await client.post(`${url}/snapshots/00000001-1/restore?version=5`)).status, 404);
  assert.equal((await client.post(`${url}/snapshots/..%2F..%2Fmeta/restore?version=5`)).status, 404);
});

test("a download snapshots a version that has none", async () => {
  const client = await Client.open();
  const doc = await client.create();
  await client.get(`/api/documents/${doc.id}/download`);
  const [snap] = (await client.get(`/api/documents/${doc.id}`)).json.history.snapshots;
  assert.equal(snap.reason, "download");
  assert.equal(snap.seq, 1);
});

test("a frame is drawn on the date asked for", async () => {
  const client = await Client.open();
  const doc = await client.create("analog");
  const url = `/api/documents/${doc.id}/frame?device=fr955&scale=1`;
  const sunday = (await client.get(`${url}&date=2026-10-04`)).json.frame;
  const saturday = (await client.get(`${url}&date=2026-03-28`)).json.frame;
  const sample = (await client.get(url)).json.frame;
  assert.equal(new Set([sunday, saturday, sample]).size, 3);
});

test("the page listens for every event the worker sends", async () => {
  const { readFileSync } = await import("node:fs");
  const sources = ["src/studio/router.ts", "src/studio/document.ts", "src/studio/worker.ts"].map((p) => readFileSync(p, "utf8")).join("\n");
  const sent = new Set([...sources.matchAll(/(?:emit|onEvent)\("(\w+)"/g)].map((m) => m[1]));
  const page = readFileSync("app/app.js", "utf8");
  const handled = new Set([...page.matchAll(/name === "(\w+)"/g)].map((m) => m[1]));
  assert.ok(sent.size > 0);
  for (const event of sent) assert.ok(handled.has(event), `the page never handles '${event}'`);
});

test("a change is announced with the tab that made it", async () => {
  const client = await Client.open();
  const doc = await client.create();
  client.tab = "tab-1";
  await client.post(`/api/documents/${doc.id}/edit?version=1`, { op: "set", path: ["face", "version"], value: "2.0.0" });
  client.tab = null;
  await client.post(`/api/documents/${doc.id}/undo?version=2`);
  assert.deepEqual(client.events.filter(([n]) => n === "changed").map(([, d]) => [d["tab"], d["version"]]), [["tab-1", 2], [null, 3]]);
});

test("goto moves to any change in one step and back", async () => {
  const client = await Client.open();
  const doc = await client.create();
  const document = client.studio.document(doc.id);
  for (let i = 0; i < 4; i++) document.commit(bumped(document, i), noAssets, `c${i}`, document.version);
  const url = `/api/documents/${doc.id}`;
  const states = (await client.get(url)).json.history.states;
  const back = (await client.post(`${url}/goto?seq=${states.at(-1).seq}&version=${document.version}`)).json;
  assert.equal(back.history.redo, "c0");
  assert.ok(!back.history.can_undo);
  assert.equal(versionOf(document), "1.0.0");
  assert.equal(back.history.states[0].label, "c3");
  const ahead = (await client.post(`${url}/goto?seq=${states[0].seq}&version=${back.version}`)).json;
  assert.equal(versionOf(document), "1.0.3");
  assert.ok(!ahead.history.can_redo);
  assert.equal(ahead.history.undo, "c3");
  const undone = (await client.post(`${url}/undo?version=${ahead.version}`)).json;
  assert.equal(versionOf(document), "1.0.2");
  assert.equal(undone.history.redo, "c3");
  const current = undone.history.states.find((s: any) => s.current).seq;
  assert.equal((await client.post(`${url}/goto?seq=${current}&version=${undone.version}`)).status, 400);
  assert.equal((await client.post(`${url}/goto?seq=999&version=${undone.version}`)).status, 400);
});

test("a face is renamed, and the library and its tabs hear", async () => {
  const backend = new MemoryBackend();
  const client = new Client(await newStudio(backend));
  const doc = await client.create();
  const url = `/api/documents/${doc.id}`;
  assert.equal((await client.post(`${url}/rename?name=%20Morning%20%20Run%20`)).json.name, "Morning Run");
  assert.equal((await client.get(url)).json.name, "Morning Run");
  assert.equal((await client.get("/api/home")).json.documents[0].name, "Morning Run");
  assert.equal((await Store.open(backend)).meta(doc.id).name, "Morning Run");
  assert.equal((await client.post(`${url}/rename?name=%20`)).status, 400);
  assert.ok(client.events.some(([n, d]) => n === "renamed" && d["name"] === "Morning Run"));
  assert.equal((await client.get(url)).json.version, doc.version);
});

test("the library shows each face on its first target", async () => {
  const client = await Client.open();
  const doc = await client.create();
  const cover = await client.get(`/api/documents/${doc.id}/cover`);
  assert.equal(cover.status, 200);
  const png = decodePng(cover.body!)!;
  assert.deepEqual([png.width, png.height], [260, 260]);
  const broken = await client.upload("b.yaml", "format: 2\n");
  assert.equal((await client.get(`/api/documents/${broken.id}/cover`)).status, 404);
});
