// The canvas, the layer tree and the YAML tab through the worker's
// document: drag handles, gestures, structural edits and typed text.
import assert from "node:assert/strict";
import { readdirSync, statSync } from "node:fs";
import { test } from "node:test";
import { move, resize, turn, View } from "../src/edit/geometry.ts";
import { indexFor, Refused } from "../src/edit/spans.ts";
import { bakeFonts, ICON_FONT } from "../src/emit/resources.ts";
import { readFontFile } from "../src/node.ts";
import { decodePng } from "../src/png.ts";
import * as starters from "../src/starters.ts";
import { bundle, readUpload } from "../src/studio/bundle.ts";
import { type Document, frameKey, StaleVersion, TEXT_MERGE_SECONDS } from "../src/studio/document.ts";
import { handles } from "../src/studio/drag.ts";
import { Client, db, dataOf, newStudio, read, readText, ROOT } from "./studio-client.ts";

const SHAPES = "examples/features/shapes/face.yaml";
const items = (frame: any): Record<string, any> => Object.fromEntries(frame.items.map((i: any) => [i.id, i]));
const frameOf = (doc: Document, device = "fr955", scale = 2): any => doc.frame(frameKey({ device, scale }));
const shapes = async (): Promise<Document> => (await newStudio()).create(readUpload("face.yaml", read(SHAPES)), "open");
const minimal = (): string => starters.instantiate("minimal", "T");

// -- handles --

test("each kind gets its own handles", async () => {
  const byId = items(frameOf(await shapes(), "fr955", 1));
  const kinds = (id: string): string[] => byId[id].handles.map((h: any) => `${h.kind}:${h.key ? [h.key].flat().join(".") : h.part}`);
  assert.ok(kinds("dot").includes("size:radius"));
  assert.ok(kinds("card").includes("size:size.width") && kinds("card").includes("size:size.height"));
  assert.ok(kinds("outer_arc").includes("angle:start_angle") && kinds("outer_arc").includes("angle:sweep"));
  const line = Object.keys(byId).find((id) => byId[id].handles.some((h: any) => h.kind === "end"))!;
  assert.deepEqual(new Set(byId[line].handles.map((h: any) => h.part)), new Set(["at", "to"]));
  assert.deepEqual(byId["chevron"].handles, []);
});

test("a size handle sits on the edge that moves", async () => {
  const studio = await newStudio();
  for (const [align, side, gain] of [["top_left", "right", 1], ["center", "right", 2], ["right", "left", -1]] as const) {
    const text = minimal().replace("static:\n", "static:\n  box:\n    type: rectangle\n    at: { anchor: center }\n"
      + `    size: { width: 40px, height: 20px }\n    align: ${align}\n    color: color.dim\n`);
    const box = items(frameOf(studio.create(bundle("H", text), "new"), "fr955", 1))["box"];
    const width = box.handles.find((h: any) => JSON.stringify(h.key) === '["size","width"]');
    const [x, , w] = box.box;
    assert.equal(width.gain, gain, align);
    assert.equal(width.x, side === "right" ? x + w : x, align);
  }
});

test("every handle offered is a drag that lands", () => {
  const device = db.get("fr955");
  for (const name of ["shapes", "rings", "align", "progress", "gauge"]) {
    const path = `examples/features/${name}/face.yaml`;
    const exists = (p: string): boolean => { try { read(p); return true; } catch { return false; } };
    const view = new View(path, readText(path), device, exists, (face, d) => bakeFonts(face, d, (p) => readFontFile(p === ICON_FONT ? p : `${ROOT}/${p}`)));
    let tried = 0;
    for (const placed of view.resolved.items) {
      for (const h of handles(placed)) {
        let converted;
        if (h.kind === "end") converted = move(view, placed.id, 3, -2, "auto", h.part);
        else if (h.kind === "size") converted = resize(view, placed.id, h.key as string[], 2);
        else converted = turn(view, placed.id, h.key as string, Number(h.key === "start_angle" ? h.start : h.sweep) - 12);
        assert.ok(converted.landed, `${name}: ${placed.id} ${JSON.stringify(h)}`);
        tried++;
      }
    }
    assert.ok(tried > 0, name);
  }
});

// -- frames and thumbnails --

test("the frame is the render with its items and layers", async () => {
  const doc = await shapes();
  const frame = frameOf(doc);
  assert.equal(frame.minor_radius, 130);
  for (const i of frame.items) for (const key of ["id", "kind", "box", "center", "handles", "drawn", "line"]) assert.ok(key in i, key);
  const drawn = new Set(frame.items.filter((i: any) => i.drawn).map((i: any) => i.id));
  assert.deepEqual(new Set(frame.layers.filter((l: any) => !l.id.startsWith("ring:")).map((l: any) => l.id)), drawn);
  const png = decodePng(doc.thumbnail(frameKey({ device: "fenix8solar51mm", scale: 1 })))!;
  assert.deepEqual([png.width, png.height], [280, 280]);
});

test("a group is an item even though it draws nothing", async () => {
  const doc = (await newStudio()).create(readUpload("face.yaml", read("examples/features/align/face.yaml")), "open");
  const groups = frameOf(doc).items.filter((i: any) => i.kind === "group");
  assert.ok(groups.length > 0 && !groups.some((g: any) => g.drawn));
});

// -- drags --

test("a drag moves the element by the dragged pixels", async () => {
  const doc = await shapes();
  const before = items(frameOf(doc))["dot"].center;
  const [change, landed] = doc.drag("dot", { kind: "move", dx: 5, dy: -3 }, "fr955", "auto", doc.version);
  assert.ok(landed);
  assert.equal(change.label, "move dot by (+5, -3) px on fr955");
  assert.deepEqual(items(frameOf(doc))["dot"].center, [before[0] + 5, before[1] - 3]);
  doc.undo(doc.version);
  assert.deepEqual(items(frameOf(doc))["dot"].center, before);
});

test("a drag on one device can leave the others alone", async () => {
  const doc = await shapes();
  const other = items(frameOf(doc, "fenix8solar47mm"))["dot"].center;
  doc.drag("dot", { kind: "move", dx: 4, dy: 0 }, "fr955", "device", doc.version);
  assert.ok("fr955" in dataOf(doc).elements.dot.overrides);
  assert.deepEqual(items(frameOf(doc, "fenix8solar47mm"))["dot"].center, other);
  doc.drag("dot", { kind: "move", dx: 1, dy: 0 }, "fr955", "auto", doc.version);
  assert.deepEqual(items(frameOf(doc, "fenix8solar47mm"))["dot"].center, other);
});

test("refused drags leave the face alone", async () => {
  const doc = await shapes();
  const before = [doc.text, doc.version];
  const drag = (id: string, gesture: Record<string, unknown>, scope = "auto", version = doc.version) => () => doc.drag(id, gesture, "fr955", scope, version);
  assert.throws(drag("chevron", { kind: "move", dx: 1, dy: 0 }), /polygon/);
  assert.throws(drag("dot", { kind: "spin" }), /unknown gesture/);
  assert.throws(drag("dot", { kind: "move", dx: 1 }), /needs its values/);
  assert.throws(drag("dot", { kind: "move", dx: 1, dy: 1, part: "to" }), /not a line/);
  assert.throws(drag("dot", { kind: "move", dx: 1, dy: 1 }, "everywhere"), /scope/);
  assert.throws(drag("dot", { kind: "move", dx: 1, dy: 1 }, "auto", 0), StaleVersion);
  assert.deepEqual([doc.text, doc.version], before);
});

test("a selection moves together as one change", async () => {
  const doc = await shapes();
  const before = items(frameOf(doc));
  const version = doc.version;
  const [change, landed] = doc.moveAll(["dot", "card"], 5, -3, "fr955", "auto", doc.version);
  assert.ok(landed);
  assert.equal(change.label, "move dot, card by (+5, -3) px on fr955");
  assert.equal(doc.version, version + 1);
  const after = items(frameOf(doc));
  for (const id of ["dot", "card"]) assert.deepEqual(after[id].center, [before[id].center[0] + 5, before[id].center[1] - 3]);
  assert.deepEqual(after["label"].center, before["label"].center);
  doc.undo(doc.version);
  const undone = items(frameOf(doc));
  for (const id of ["dot", "card"]) assert.deepEqual(undone[id].center, before[id].center);
});

test("a group and its member selected together move once", async () => {
  const doc = await shapes();
  const block = doc.tree().find((b) => JSON.stringify(b["path"]) === '["elements"]')!;
  const paths = (block["children"] as any[]).filter((n) => n.id === "dot" || n.id === "card").map((n) => n.path);
  const [, groupId] = doc.structure({ op: "group", paths }, doc.version);
  assert.ok(groupId);
  const before = items(frameOf(doc));
  const [, landed] = doc.moveAll([groupId!, "dot"], 4, 2, "fr955", "auto", doc.version);
  assert.ok(landed);
  const after = items(frameOf(doc));
  for (const id of ["dot", "card"]) assert.deepEqual(after[id].center, [before[id].center[0] + 4, before[id].center[1] + 2], id);
});

test("drags through the requests", async () => {
  const client = await Client.open();
  const doc = await client.upload("face.yaml", read(SHAPES));
  const id = doc.id;
  const drag = (version: number, args: Record<string, unknown>) => client.call("drag", { id, version, device: "fr955", ...args });
  const arc = items((await client.call("frame", { id, device: "fr955", scale: 1 })).json)["outer_arc"];
  const sweep = arc.handles.find((h: any) => h.key === "sweep");
  const r = await drag(1, { element: "outer_arc", gesture: { kind: "turn", key: "sweep", degrees: sweep.sweep - 30 } });
  assert.equal(r.status, 200, JSON.stringify(r.json));
  assert.ok(r.json.landed);
  assert.match(r.json.what, /^turn outer_arc\.sweep to/);
  assert.equal((await drag(1, { element: "dot", gesture: { kind: "move", dx: 1, dy: 0 } })).status, 409);
  assert.equal((await drag(2, { element: "chevron", gesture: { kind: "move", dx: 1, dy: 0 } })).status, 400);
  assert.equal((await drag(2, { gesture: [] })).status, 400);
  const many = await drag(2, { elements: ["dot", "card"], gesture: { kind: "move", dx: 2, dy: 0 } });
  assert.equal(many.status, 200, JSON.stringify(many.json));
  assert.equal(many.json.what, "move dot, card by (+2, +0) px on fr955");
  const resized = await drag(3, { elements: ["dot", "card"], gesture: { kind: "resize", key: ["radius"], delta: 2 } });
  assert.equal(resized.status, 400);
  assert.match(resized.json.error, /only be moved together/);
  const shown = (await client.call("frame", { id, device: "fr955", scale: 1 })).json;
  assert.equal(shown.version, 3);
  assert.ok(shown.layers.length > 0);
  assert.equal((await client.call("layers", { id, device: "fr955" })).status, 400);
  assert.equal((await client.call("thumbnail", { id, device: "fr955" })).type, "image/png");
});

test("a gesture without its values and a refused gesture say different things", async () => {
  const doc = (await newStudio()).create(bundle("T", minimal()), "new");
  assert.throws(() => doc.drag("clock", { kind: "move", dx: "far" }, "fr955", "auto", doc.version), /needs its values/);
  assert.throws(() => doc.drag("no_such_element", { kind: "move", dx: 1, dy: 0 }, "fr955", "auto", doc.version), (e: Error) => e instanceof Refused && !e.message.includes("needs its values"));
  assert.throws(() => doc.drag("clock", { kind: "spin" }, "fr955", "auto", doc.version), /unknown gesture/);
});

// -- structure --

function ids(doc: Document, block: string[] = ["elements"]): string[] {
  let data = dataOf(doc);
  for (const step of block) data = data[step];
  return Object.keys(data);
}

function node(doc: Document, id: string): any {
  const walk = (nodes: any[]): any => {
    for (const n of nodes) {
      if (n.kind === "element" && n.id === id) return n;
      const found = walk(n.children ?? []);
      if (found) return found;
    }
    return null;
  };
  return walk(doc.tree());
}

test("add, duplicate, reorder, delete", async () => {
  const doc = (await newStudio()).create(bundle("T", minimal()), "new");
  const [, made] = doc.structure({ op: "add", type: "circle", block: ["elements"], before: "seconds" }, doc.version);
  assert.equal(made, "new_circle");
  assert.deepEqual(ids(doc), ["clock", "new_circle", "seconds"]);
  const [, copy] = doc.structure({ op: "duplicate", path: ["elements", "clock"] }, doc.version);
  assert.equal(copy, "clock_copy");
  assert.deepEqual(ids(doc).slice(0, 2), ["clock", "clock_copy"]);
  doc.structure({ op: "move", path: ["elements", "seconds"], block: ["elements"], before: "clock" }, doc.version);
  assert.equal(ids(doc)[0], "seconds");
  doc.structure({ op: "move", path: ["elements", "seconds"], block: ["elements"] }, doc.version);
  assert.equal(ids(doc).at(-1), "seconds");
  doc.structure({ op: "delete", path: ["elements", "clock_copy"] }, doc.version);
  assert.ok(!ids(doc).includes("clock_copy"));
  const labels = (doc.history()["states"] as any[]).map((s) => s.label).slice(0, 5);
  assert.equal(labels.at(-1), "add new_circle");
  assert.equal(labels[0], "delete clock_copy");
});

test("static and dynamic, and the gate", async () => {
  const doc = (await newStudio()).create(bundle("T", minimal()), "new");
  doc.structure({ op: "add", type: "rectangle", block: ["elements"] }, doc.version);
  doc.structure({ op: "move", path: ["elements", "new_rectangle"], block: ["static"] }, doc.version);
  assert.deepEqual(ids(doc, ["static"]), ["background", "new_rectangle"]);
  assert.throws(() => doc.structure({ op: "move", path: ["elements", "clock"], block: ["static"] }, doc.version), /time\.clock/);
});

test("moves across layouts", async () => {
  const doc = (await newStudio()).create(readUpload("face.yaml", read("examples/features/styles/face.yaml")), "open");
  const labels = new Set(doc.tree().map((b) => b["label"]));
  for (const l of ["big: static", "big: elements", "compact: static", "compact: elements"]) assert.ok(labels.has(l), l);
  const source = doc.tree().find((b) => b["label"] === "big: static" && (b["children"] as any[]).length > 0)!;
  const element = (source["children"] as any[])[0];
  doc.structure({ op: "move", path: element.path, block: ["layouts", "compact", "static"] }, doc.version);
  assert.ok(ids(doc, ["layouts", "compact", "static"]).includes(element.id));
});

test("group and ungroup select and restore", async () => {
  const doc = (await newStudio()).create(bundle("T", minimal()), "new");
  const original = doc.text;
  const [, made] = doc.structure({ op: "group", paths: [["elements", "clock"], ["elements", "seconds"]] }, doc.version);
  assert.equal(made, "group");
  assert.deepEqual(ids(doc), ["group"]);
  doc.structure({ op: "ungroup", path: ["elements", "group"] }, doc.version);
  assert.equal(doc.text, original);
});

test("an empty block is listed and filled", async () => {
  const text = starters.instantiate("minimal", "E");
  const withoutStatic = text.slice(0, text.indexOf("static:")) + text.slice(text.indexOf("elements:"));
  const doc = (await newStudio()).create(bundle("E", withoutStatic), "new");
  const block = doc.tree().find((b) => JSON.stringify(b["path"]) === '["static"]')!;
  assert.equal(block["line"], null);
  assert.deepEqual(block["children"], []);
  doc.structure({ op: "add", type: "rectangle", block: ["elements"] }, doc.version);
  doc.structure({ op: "move", path: ["elements", "new_rectangle"], block: ["static"] }, doc.version);
  assert.deepEqual(ids(doc, ["static"]), ["new_rectangle"]);
});

test("structural refusals leave the face alone", async () => {
  const doc = (await newStudio()).create(bundle("T", minimal()), "new");
  const before = [doc.text, doc.version];
  assert.throws(() => doc.structure({ op: "explode" }, doc.version), /unknown structural edit/);
  assert.throws(() => doc.structure({ op: "add", type: "data" }, doc.version), /needs its slot/);
  assert.throws(() => doc.structure({ op: "move", path: ["elements", "clock"], block: ["elements"], before: "nope" }, doc.version), /not in/);
  assert.throws(() => doc.structure({ op: "group", paths: "clock" }, doc.version), /list of paths/);
  assert.throws(() => doc.structure({ op: "delete", path: ["elements", "clock"] }, 0), StaleVersion);
  assert.deepEqual([doc.text, doc.version], before);
});

test("a delete that would leave a dangling name is refused", async () => {
  const studio = await newStudio();
  for (const [face, element, reason] of [["analog", "sport_hands", /unknown layout 'sport'/], ["aod", "date_text", /missing required key 'children'/]] as const) {
    const doc = studio.create(readUpload("face.yaml", read(`examples/features/${face}/face.yaml`)), "open");
    const before = [doc.text, doc.version];
    assert.throws(() => doc.structure({ op: "delete", path: node(doc, element).path }, doc.version), reason);
    assert.deepEqual([doc.text, doc.version], before);
  }
});

test("structure through the requests", async () => {
  const client = await Client.open();
  const doc = await client.create("minimal", "S");
  const structure = (version: number, edit: unknown) => client.call("structure", { id: doc.id, version, edit });
  const r = await structure(1, { op: "add", type: "graph", choice: "steps" });
  assert.equal(r.status, 200, JSON.stringify(r.json));
  assert.equal(r.json.select, "new_graph");
  assert.equal(r.json.version, 2);
  assert.equal((await structure(1, {})).status, 409);
  assert.equal((await structure(2, { op: "add", type: "teapot" })).status, 400);
  const words = (await client.call("vocabulary")).json;
  assert.ok(words.types.includes("graph") && words.series.includes("steps"));
  assert.ok("hand_sets" in r.json.globals && "slots" in r.json.globals);
});

test("a selection of several is deleted as one change", async () => {
  const doc = (await newStudio()).create(bundle("T", minimal()), "new");
  const [original, version] = [doc.text, doc.version];
  doc.structure({ op: "group", paths: [["elements", "clock"]] }, doc.version);
  const grouped = doc.version;
  doc.structure({ op: "delete", paths: [["elements", "group", "children", "clock"], ["elements", "group"], ["elements", "seconds"], ["static", "background"]] }, doc.version);
  assert.equal(doc.version, grouped + 1);
  const d = dataOf(doc);
  assert.ok(!("static" in d) && (!d.elements || Object.keys(d.elements).length === 0));
  assert.equal((doc.history()["states"] as any[])[0].label, "delete group, seconds, background");
  doc.undo(doc.version);
  doc.undo(doc.version);
  assert.equal(doc.text, original);
  assert.ok(doc.version > version);
  assert.throws(() => doc.structure({ op: "delete", paths: "clock" }, doc.version), /list of paths/);
});

test("elements copied from one face paste into another and are selected", async () => {
  const studio = await newStudio();
  const [source, target] = [studio.create(bundle("T", minimal()), "new"), studio.create(bundle("T", minimal()), "new")];
  const clock = node(source, "clock");
  const lines = source.text.split(/(?<=\n)/).slice(clock.line - 1, clock.end);
  const indent = lines[0]!.length - lines[0]!.trimStart().length;
  const clip = lines.map((l) => l.slice(indent)).join("");
  const [, select] = target.structure({ op: "paste", text: clip, block: ["elements"], before: "seconds" }, target.version);
  assert.equal(select, "clock2");
  assert.deepEqual(ids(target), ["clock", "clock2", "seconds"]);
  assert.equal((target.history()["states"] as any[])[0].label, "paste clock2");
  assert.throws(() => target.structure({ op: "paste", text: "  " }, target.version), /nothing to paste/);
});

// -- typed text --

test("typed text is recorded as one change", async () => {
  const doc = (await newStudio()).create(bundle("T", minimal()), "new");
  const text = doc.text.replace("version: 1.0.0", "version: 2.0.0");
  const change = doc.replaceText(text, doc.version);
  assert.equal(change.label, "edit the text");
  assert.equal(doc.text, text);
  assert.equal(doc.version, 2);
  assert.equal(doc.replaceText(text, doc.version), doc.head);
  assert.equal(doc.version, 2);
  doc.undo(doc.version);
  assert.ok(doc.text.includes("version: 1.0.0"));
});

test("text that is not YAML is refused and not recorded", async () => {
  const doc = (await newStudio()).create(bundle("T", minimal()), "new");
  const before = [doc.text, doc.version];
  assert.throws(() => doc.replaceText(doc.text + "oops: [1, 2\n", doc.version), /not valid YAML/);
  assert.deepEqual([doc.text, doc.version], before);
});

test("text with errors is recorded and its diagnostics shown", async () => {
  const doc = (await newStudio()).create(bundle("T", minimal()), "new");
  const broken = doc.text.replace("color: color.dim", "color: color.nope");
  doc.replaceText(broken, doc.version);
  assert.equal(doc.text, broken);
  assert.equal(doc.analysis().face, null);
  assert.ok(doc.diagnostics().some((d) => String(d["message"]).includes("nope")));
  assert.throws(() => doc.edit({ op: "set", path: ["elements", "clock", "color"], value: "color.alsonope" }, doc.version), Refused);
});

test("a stale text is refused", async () => {
  const doc = (await newStudio()).create(bundle("T", minimal()), "new");
  doc.replaceText(doc.text + "\n", doc.version);
  assert.throws(() => doc.replaceText(doc.text + "# late\n", 1), StaleVersion);
});

test("each tree node knows its last line", async () => {
  const doc = (await newStudio()).create(bundle("T", minimal()), "new");
  const lines = doc.text.split("\n");
  if (lines.at(-1) === "") lines.pop();
  for (const block of doc.tree()) {
    for (const n of block["children"] as any[]) {
      assert.ok(lines[n.line - 1]!.trim().startsWith(`${n.id}:`));
      const last = lines[n.end - 1]!;
      assert.ok(last.trim() && last.startsWith("    "));
      if (n.end < lines.length) assert.ok(!lines[n.end]!.startsWith("    "));
    }
  }
});

test("text through the requests", async () => {
  const client = await Client.open();
  const doc = await client.create("minimal", "Y");
  const put = (version: number, text: unknown) => client.call("text", { id: doc.id, version, text });
  const text = doc.text.replace("1.0.0", "1.2.3");
  const r = await put(1, text);
  assert.equal(r.status, 200);
  assert.equal(r.json.version, 2);
  assert.equal((await put(1, text)).status, 409);
  assert.equal((await put(2, "a: [1")).status, 400);
  assert.equal((await put(2, 7)).status, 400);
});

test("a burst of typing is one step to undo", async () => {
  const studio = await newStudio();
  const doc = studio.create(bundle("T", minimal()), "new");
  for (let n = 1; n < 4; n++) doc.replaceText(doc.text.replace(`version: 1.0.${n - 1}`, `version: 1.0.${n}`), doc.version);
  assert.equal(doc.version, 4);
  assert.deepEqual(studio.store.timeline(doc.id).states.map((c) => c.label), ["new", "edit the text"]);
  const realNow = Date.now;
  const later = (studio.store.head(doc.id)!.time + TEXT_MERGE_SECONDS + 1) * 1000;
  Date.now = () => later;
  try {
    doc.replaceText(doc.text + "# later\n", doc.version);
  } finally {
    Date.now = realNow;
  }
  assert.deepEqual(studio.store.timeline(doc.id).states.map((c) => c.label), ["new", "edit the text", "edit the text"]);
  doc.undo(doc.version);
  assert.ok(doc.text.includes("version: 1.0.3") && !doc.text.includes("# later"));
  doc.undo(doc.version);
  assert.ok(doc.text.includes("version: 1.0.0"));
});

test("typing after an undo or another edit is not merged into it", async () => {
  const studio = await newStudio();
  const doc = studio.create(bundle("T", minimal()), "new");
  doc.replaceText(doc.text + "# a\n", doc.version);
  doc.undo(doc.version);
  doc.replaceText(doc.text + "# b\n", doc.version);
  doc.edit({ op: "set", path: ["face", "version"], value: "9.9.9" }, doc.version);
  doc.replaceText(doc.text + "# c\n", doc.version);
  assert.deepEqual(studio.store.timeline(doc.id).states.map((c) => c.label), ["new", "edit the text", "set face.version to 9.9.9", "edit the text"]);
});

// -- live handles --

test("every live handle predicts the edit", async () => {
  // A handle a kind declares live, on every example face (fr955, native):
  // the element's ops before, changed by the browser's `liveOps`, draw
  // exactly what the engine's own landed edit draws, grown and shrunk by
  // even and odd amounts, and turned to whole degrees either way.
  const { join } = await import("node:path");
  const { createHash } = await import("node:crypto");
  const { loadText } = await import("../src/edit/gate.ts");
  const { Tiles, toJson } = await import("../src/draw/jsonform.ts");
  const preview = await import("../src/preview.ts");
  const { REPO_ROOT } = await import("../src/devices/node.ts");
  const raster = await import("../src/raster/canvas.ts");
  const device = db.get("fr955");
  const opsOf = (resolved: any, id: string, tiles: InstanceType<typeof Tiles>): any => {
    const options = preview.previewOptions();
    const values = preview.sampleValues(resolved, options, null);
    const placed = preview.frameItems(resolved, options, null).find((p) => p.id === id);
    if (placed === undefined) return null;
    const r = preview.newRenderer(resolved, options, values, [0, 0, 0]);
    return r.shows(placed) ? toJson(r, placed, tiles)[0] : null;
  };
  const draw = async (ops: any, tiles: InstanceType<typeof Tiles>): Promise<string> => {
    const [packed, index] = tiles.pack();
    const inflated = await raster.inflateTiles({ data: Buffer.from(packed).toString("base64"), index });
    const im = raster.image(260, 260, [0, 0, 0]);
    raster.drawOps(im, ops, inflated, 1);
    return createHash("md5").update(im.data).digest("hex");
  };
  const exists = (p: string): boolean => { try { read(p); return true; } catch { return false; } };
  const bake = (face: any, d: any): any => bakeFonts(face, d, (p) => readFontFile(p === ICON_FONT ? p : join(REPO_ROOT, p)));
  const wrong: string[] = [];
  let checked = 0;
  const walk = (dir: string, out: string[] = []): string[] => {
    for (const name of readdirSync(join(REPO_ROOT, dir)).sort()) {
      const p = `${dir}/${name}`;
      if (statSync(join(REPO_ROOT, p)).isDirectory()) walk(p, out);
      else if (name === "face.yaml" && !p.includes("/dashboard/")) out.push(p);
    }
    return out;
  };
  for (const path of walk("examples")) {
    const view = new View(path, readText(path), device, exists, bake);
    for (const placed of view.resolved.items) {
      for (const h of handles(placed)) {
        if (h.kind === "end" || h.live === null || h.live === undefined) continue;
        const tiles = new Tiles();
        const before = opsOf(view.resolved, placed.id, tiles);
        if (before === null) continue;
        const changes = h.kind === "size" ? [6, -4, 3, -1].map((delta) => ({ delta }))
          : [12, -30, 7].map((d) => ({ degrees: Math.round(Number(h.key === "start_angle" ? h.start : h.sweep)) + d }));
        for (const change of changes) {
          let converted;
          try {
            converted = "delta" in change ? resize(view, placed.id, h.key as string[], change.delta) : turn(view, placed.id, h.key as string, change.degrees);
          } catch (error) {
            if (error instanceof Refused) continue;
            throw error;
          }
          if (!converted.landed) continue;
          const after = opsOf(view.place(loadText(path, converted.patch.text, exists)), placed.id, tiles);
          checked++;
          if (await draw(raster.liveOps(before, h.live, change), tiles) !== await draw(after, tiles)) {
            wrong.push(`${path}: ${placed.id} ${JSON.stringify(h.key)} ${JSON.stringify(change)}`);
          }
        }
      }
    }
  }
  assert.ok(checked > 0);
  assert.deepEqual(wrong, []);
});
