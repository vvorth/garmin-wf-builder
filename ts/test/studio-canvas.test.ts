// The canvas, the layer tree and the YAML tab through the worker's
// document: drag handles, gestures, structural edits and typed text.
import assert from "node:assert/strict";
import { readdirSync, statSync } from "node:fs";
import { test } from "node:test";
import { addVertex, move, resize, toLocal, turn, vertex, View } from "../src/edit/geometry.ts";
import { indexFor, Refused } from "../src/edit/spans.ts";
import { bakeFonts, ICON_FONT } from "../src/emit/resources.ts";
import { readFontFile } from "../src/node.ts";
import { decodePng } from "../src/png.ts";
import * as starters from "../src/starters.ts";
import { bundle, readUpload } from "../src/studio/bundle.ts";
import { type Document, frameKey, StaleVersion, TEXT_MERGE_SECONDS } from "../src/studio/document.ts";
import { handles } from "../src/studio/drag.ts";
import { HAND_ANGLES } from "../src/draw/barrel.ts";
import { PlacedHands, PlacedPattern, type ResolvedPolygonPart, roundHalfAway } from "../src/layout.ts";
import { degrees } from "../src/py.ts";
import { SAMPLE } from "../src/sample.ts";
import { Client, db, dataOf, newStudio, openExample, read, readText, ROOT, SHOWCASE } from "./studio-client.ts";

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
  // a polygon: a vertex handle on each point, a segment handle on each edge's midpoint, the closing edge's too
  const chevron = byId["chevron"].handles;
  assert.deepEqual(chevron.filter((h: any) => h.kind === "vertex").map((h: any) => h.index), [0, 1, 2]);
  assert.deepEqual(chevron.filter((h: any) => h.kind === "segment").map((h: any) => h.after), [0, 1, 2]);
  const [a, b] = chevron.filter((h: any) => h.kind === "vertex");
  const edge = chevron.find((h: any) => h.kind === "segment" && h.after === 0);
  assert.deepEqual([edge.x, edge.y], [Math.floor((a.x + b.x) / 2 + 0.5), Math.floor((a.y + b.y) / 2 + 0.5)]);
  assert.ok(chevron.every((h: any) => h.live === null));
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
        else if (h.kind === "vertex") converted = vertex(view, placed.id, h.index!, 3, -2);
        else if (h.kind === "segment") converted = addVertex(view, placed.id, h.after!, h.x + 2, h.y + 3);
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

test("a this-display drag writes the display selector and moves only that display class", async () => {
  const aod = "examples/features/aod/face.yaml";
  const doc = (await newStudio()).create(readUpload("face.yaml", read(aod)), "open");
  const centerOn = (device: string): number[] => items(frameOf(doc, device))["accent_dot"].center;
  const before = { fenix847mm: centerOn("fenix847mm"), fr955: centerOn("fr955") };
  const [change, landed] = doc.drag("accent_dot", { kind: "move", dx: 0, dy: -6 }, "fenix847mm", "display", doc.version);
  assert.ok(landed);
  assert.equal(change.label, "move accent_dot by (+0, -6) px on display:amoled");
  const dot = dataOf(doc).elements.accent_dot;
  assert.deepEqual(Object.keys(dot.overrides), ["display:amoled"]);
  assert.deepEqual(Object.keys(dot.overrides["display:amoled"]), ["at"]);
  assert.ok(doc.text.includes('"display:amoled"'), "a selector with a colon is a quoted key");
  assert.deepEqual(centerOn("fenix847mm"), [before.fenix847mm[0]!, before.fenix847mm[1]! - 6]);
  assert.deepEqual(centerOn("fr955"), before.fr955);
  // auto now finds the display override on an AMOLED watch, and leaves fr955's own key alone
  doc.drag("accent_dot", { kind: "move", dx: 0, dy: -2 }, "fenix847mm", "auto", doc.version);
  assert.deepEqual(Object.keys(dot.overrides), ["display:amoled"]);
  assert.deepEqual(centerOn("fr955"), before.fr955);
  // a selection move takes the scope too
  const [all] = doc.moveAll(["accent_dot"], 3, 0, "fr955", "display", doc.version);
  assert.equal(all.label, "move accent_dot by (+3, +0) px on display:mip");
  assert.deepEqual(Object.keys(dataOf(doc).elements.accent_dot.overrides).sort(), ["display:amoled", "display:mip"]);
});

test("refused drags leave the face alone", async () => {
  const doc = await shapes();
  const before = [doc.text, doc.version];
  const drag = (id: string, gesture: Record<string, unknown>, scope = "auto", version = doc.version) => () => doc.drag(id, gesture, "fr955", scope, version);
  assert.throws(drag("chevron", { kind: "move", dx: 1, dy: 0 }, "device"), /points cannot be overridden per device/);
  assert.throws(drag("chevron", { kind: "vertex", index: 7, dx: 1, dy: 0 }), /no point 7: it has 3/);
  assert.throws(drag("chevron", { kind: "remove_vertex", index: 1 }), /needs at least 3 points/);
  assert.throws(drag("dot", { kind: "add_vertex", after: 0, x: 1, y: 1 }), /not a polygon/);
  assert.throws(drag("dot", { kind: "vertex", index: 0, dx: 1, dy: 1 }), /not a polygon/);
  assert.throws(drag("elements/dot/parts/x", { kind: "move", dx: 1, dy: 1 }), /is not a part/);
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
  const polygon = await drag(2, { element: "chevron", gesture: { kind: "move", dx: 1, dy: 0 } });
  assert.equal(polygon.status, 200, JSON.stringify(polygon.json));
  assert.equal(polygon.json.what, "move chevron by (+1, +0) px on fr955");
  assert.equal((await drag(3, { gesture: [] })).status, 400);
  const many = await drag(3, { elements: ["dot", "card"], gesture: { kind: "move", dx: 2, dy: 0 } });
  assert.equal(many.status, 200, JSON.stringify(many.json));
  assert.equal(many.json.what, "move dot, card by (+2, +0) px on fr955");
  const resized = await drag(4, { elements: ["dot", "card"], gesture: { kind: "resize", key: ["radius"], delta: 2 } });
  assert.equal(resized.status, 400);
  assert.match(resized.json.error, /only be moved together/);
  const shown = (await client.call("frame", { id, device: "fr955", scale: 1 })).json;
  assert.equal(shown.version, 4);
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

test("a type that cannot be static is added to the sibling elements block instead", async () => {
  const client = await Client.open();
  const doc = await client.create("minimal", "S");
  let version = doc.version;
  const structure = async (edit: unknown): Promise<any> => {
    const r = await client.call("structure", { id: doc.id, version, edit });
    assert.equal(r.status, 200, JSON.stringify(r.json));
    version = r.json.version;
    return r.json;
  };
  const edit = await client.call("edit", { id: doc.id, version, edit: { op: "add_slot", name: "top", default: "steps" } });
  assert.equal(edit.status, 200, JSON.stringify(edit.json));
  version = edit.json.version;
  const r = await structure({ op: "add", type: "data", block: ["static"], before: "background", choice: "top" });
  assert.equal(r.select, "new_data2");
  const d = dataOf(client.studio.document(doc.id));
  assert.deepEqual(Object.keys(d.static), ["background"]);
  assert.deepEqual(Object.keys(d.elements), ["clock", "seconds", "new_data", "new_data2"]);
  for (const [type, choice] of [["gauge", null], ["graph", "steps"], ["hands", null]] as const) {
    if (type === "hands") {
      const set = await client.call("edit", { id: doc.id, version, edit: { op: "add_hand_set", name: "dial", preset: "classic" } });
      version = set.json.version;
    }
    const added = await structure({ op: "add", type, block: ["static"], ...(choice ? { choice } : {}), ...(type === "hands" ? { choice: "dial" } : {}) });
    assert.ok(added.select in dataOf(client.studio.document(doc.id)).elements, type);
  }
  // a static type still goes where it was asked
  const shape = await structure({ op: "add", type: "rectangle", block: ["static"], before: "background" });
  assert.deepEqual(Object.keys(dataOf(client.studio.document(doc.id)).static), [shape.select, "background"]);
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
        if (h.kind === "vertex") {
          // a dragged vertex: the landed edit draws the polygon with that one point moved by the drag, and nothing else
          const tiles = new Tiles();
          const before = opsOf(view.resolved, placed.id, tiles);
          if (before === null) continue;
          for (const [dx, dy] of [[3, -2], [-5, 4]] as const) {
            const converted = vertex(view, placed.id, h.index!, dx, dy);
            if (!converted.landed) continue;
            const after = opsOf(view.place(loadText(path, converted.patch.text, exists)), placed.id, tiles);
            const predicted = before.map((op: any) => (op.op === "fillPolygon"
              ? { ...op, points: op.points.map((p: [number, number], i: number) => (i === h.index ? [p[0] + dx, p[1] + dy] : p)) } : op));
            checked++;
            if (await draw(predicted, tiles) !== await draw(after, tiles)) wrong.push(`${path}: ${placed.id} vertex ${h.index} ${JSON.stringify([dx, dy])}`);
          }
          continue;
        }
        if (h.kind === "end" || h.kind === "segment" || h.live === null || h.live === undefined) continue;
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

// -- parts and points --

const PATTERNS = "examples/features/patterns/face.yaml";
const BLADE = ["resources", "hand_sets", "vintage", "hour", "parts", "blade"];
const flat = (nodes: any[]): any[] => nodes.flatMap((n) => [n, ...flat(n.children)]);
const nodeAt = (doc: Document, id: string, kind = "element"): any => flat(doc.tree().flatMap((b) => b.children)).find((n) => n.kind === kind && n.id === id);
/** The entered frame's items by id, the entered element left out. */
const partsOf = (frame: any): Record<string, any> => Object.fromEntries(frame.items.filter((i: any) => i.path).map((i: any) => [i.id, i]));
/** A point of a part's frame on the screen: `origin` plus the point turned by `angle` degrees. */
const onScreen = ([ox, oy]: [number, number], angle: number, [x, y]: readonly [number, number]): [number, number] => {
  const t = angle * Math.PI / 180, s = Math.sin(t), c = Math.cos(t);
  return [Math.floor(ox + x * c - y * s + 0.5), Math.floor(oy + x * s + y * c + 0.5)];
};
const handsOf = (doc: Document, id: string, device = "fr955"): PlacedHands => doc.analysis().resolved.get(device)!.items.find((p) => p.id === id) as PlacedHands;
const bladeOf = (doc: Document): ResolvedPolygonPart => handsOf(doc, "roman_hands").hour!.parts.find((p) => p.id === "blade") as ResolvedPolygonPart;

test("the tree lists a hands element's hands and their parts, and a pattern's parts, by path with their lines", async () => {
  const doc = openExample(await newStudio(), SHOWCASE);
  const hands = nodeAt(doc, "roman_hands");
  assert.deepEqual(hands.children.map((h: any) => [h.kind, h.id, h.type, h.path]), [
    ["hand", "hour", "hand", ["resources", "hand_sets", "vintage", "hour"]],
    ["hand", "minute", "hand", ["resources", "hand_sets", "vintage", "minute"]],
    ["hand", "second", "hand", ["resources", "hand_sets", "vintage", "second"]],
  ]);
  const hour = hands.children[0];
  assert.deepEqual(hour.children.map((p: any) => [p.kind, p.id, p.type]), [
    ["part", "blade_bg", "polygon"], ["part", "ring_bg", "circle"], ["part", "point_bg", "polygon"], ["part", "blade", "polygon"], ["part", "ring", "circle"], ["part", "point", "polygon"],
  ]);
  const blade = hour.children.find((p: any) => p.id === "blade");
  assert.deepEqual(blade.path, BLADE);
  const lines = doc.text.split("\n");
  assert.ok(lines[blade.line - 1]!.trim().startsWith("blade:"), lines[blade.line - 1]);
  assert.ok(lines[blade.end - 1]!.includes("dy: -26%r"), lines[blade.end - 1]);
  assert.ok(hour.line < blade.line && blade.end <= hour.end);
  assert.deepEqual(blade.children, []);
  // the same hand set under another element lists the same paths
  assert.deepEqual(nodeAt(doc, "analog_hands").children.map((h: any) => h.path[2]), ["classic", "classic", "classic"]);
  // a pattern's parts, directly
  const patterns = openExample(doc.studio, PATTERNS);
  const dots = nodeAt(patterns, "week_dots");
  assert.deepEqual(dots.children.map((p: any) => [p.kind, p.id, p.type, p.path]), [
    ["part", "dot", "circle", ["elements", "week_dots", "parts", "dot"]], ["part", "ring", "circle", ["elements", "week_dots", "parts", "ring"]],
  ]);
  const ring = dots.children[1];
  assert.ok(patterns.text.split("\n")[ring.line - 1]!.trim().startsWith("ring:"));
  assert.equal(ring.line, ring.end);
  // a needle gauge's, under `needle:`
  const gauge = openExample(doc.studio, "examples/features/gauge/face.yaml");
  assert.deepEqual(nodeAt(gauge, "battery_needle").children.map((p: any) => [p.id, p.type, p.path]), [
    ["blade", "polygon", ["elements", "battery_needle", "needle", "blade"]], ["hub", "circle", ["elements", "battery_needle", "needle", "hub"]],
  ]);
  // an element without parts lists none
  assert.deepEqual(nodeAt(doc, "center_pin").children, []);
});

test("the entered frame places a hands element's parts where its hands are drawn, with handles, over a ghost of the rest", async () => {
  const doc = openExample(await newStudio(), SHOWCASE);
  const enter = nodeAt(doc, "roman_hands").path;
  const plain = doc.frame(frameKey({ device: "fr955", scale: 1, style: "roman_dark" }));
  const frame = doc.frame(frameKey({ device: "fr955", scale: 1, style: "roman_dark", enter }));
  assert.equal(plain.local, null);
  const hour = degrees(HAND_ANGLES.get("hour")!(SAMPLE.get("time.hour") as number, SAMPLE.get("time.minute") as number, 0));
  assert.deepEqual(frame.local, { element: enter, origin: [130, 130], radius: 1.3, angle: hour });
  assert.equal(hour, 304.5);
  // the items: the element itself, undrawn, and every hand's parts, nothing else
  const element = frame.items.find((i: any) => i.id === "roman_hands")!;
  assert.deepEqual([element.drawn, element.handles, element.path], [false, [], undefined]);
  const parts = partsOf(frame);
  assert.equal(Object.keys(parts).length + 1, frame.items.length);
  const hands = handsOf(doc, "roman_hands");
  const expected = (["hour", "minute", "second"] as const).flatMap((hand) => hands[hand]!.parts.map((p) => `resources/hand_sets/vintage/${hand}/parts/${p.id}`));
  assert.deepEqual(Object.keys(parts), expected);
  for (const item of Object.values(parts)) assert.ok(item.drawn && typeof item.line === "number" && item.path.join("/") === item.id);
  // a hand part's vertex handles sit where the frame draws its points: the hour hand's, turned by the hour angle about the axis
  const blade = parts["resources/hand_sets/vintage/hour/parts/blade"];
  assert.equal(blade.angle, hour);
  const resolved = bladeOf(doc);
  const vertices = blade.handles.filter((h: any) => h.kind === "vertex");
  assert.deepEqual(vertices.map((h: any) => [h.x, h.y]), resolved.points.map((p) => onScreen([130, 130], hour, p)));
  // mirror: x -- two listed points are draggable, their two reflections shown and not, each naming the point it reflects
  assert.deepEqual(vertices.map((h: any) => [h.index, h.mirrored ?? false]), [[0, false], [1, false], [1, true], [0, true]]);
  assert.deepEqual(blade.handles.filter((h: any) => h.kind === "segment").map((h: any) => h.after), [0]);
  const minute = degrees(HAND_ANGLES.get("minute")!(0, SAMPLE.get("time.minute") as number, 0));
  const ring = parts["resources/hand_sets/vintage/minute/parts/ring"];
  assert.equal(ring.angle, minute);
  assert.deepEqual(ring.handles.map((h: any) => h.kind), ["size"]);
  const second = parts["resources/hand_sets/vintage/second/parts/needle"];
  assert.deepEqual(second.handles.map((h: any) => [h.kind, h.part]), [["end", "at"], ["end", "to"]]);
  // a part's box holds its handles
  for (const item of Object.values(parts)) {
    const [x, y, w, h] = item.box;
    for (const handle of item.handles) assert.ok(handle.x >= x - 1 && handle.x <= x + w + 1 && handle.y >= y - 1 && handle.y <= y + h + 1, `${item.id} ${JSON.stringify(handle)}`);
  }
  // the ghost: the face still shows, dimmed, round the entered element, whose own pixels keep their colour
  assert.deepEqual(frame.layers.map((l: any) => l.id), ["roman_hands"]);
  const ghost = decodePng(Buffer.from(frame.frame.slice(frame.frame.indexOf(",") + 1), "base64"))!;
  const awake = decodePng(Buffer.from(plain.frame.slice(plain.frame.indexOf(",") + 1), "base64"))!;
  const at = (img: typeof ghost, x: number, y: number): number[] => [...img.pixels.subarray((y * img.width + x) * 4, (y * img.width + x) * 4 + 3)];
  const numerals = plain.items.find((i: any) => i.id === "numerals")!;
  let lit = 0, dimmed = 0;
  for (let y = numerals.box[1]; y < numerals.box[1] + numerals.box[3]; y += 2) {
    for (let x = numerals.box[0]; x < numerals.box[0] + numerals.box[2]; x += 2) {
      // the bezel's grey (24, 24, 24) is no ink
      const [r = 0, g = 0, b = 0] = at(awake, x, y);
      if (r + g + b < 100) continue;
      lit++;
      const [gr = 0, gg = 0, gb = 0] = at(ghost, x, y);
      if (gr + gg + gb < (r + g + b) * 0.6) dimmed++;
    }
  }
  assert.ok(lit > 50 && dimmed > lit * 0.8, `${dimmed} of ${lit} numeral pixels dimmed`);
  // the entered hands keep their colour: every bright pixel left as it was lies within the hands' reach
  let kept = 0;
  for (let y = 0; y < awake.height; y++) {
    for (let x = 0; x < awake.width; x++) {
      const before = at(awake, x, y);
      if (before.reduce((a, b) => a + b, 0) < 600 || !before.every((c, i) => c === at(ghost, x, y)[i])) continue;
      kept++;
      const [ex, ey, ew, eh] = element.box;
      assert.ok(x >= ex && x < ex + ew && y >= ey && y < ey + eh, `a bright pixel outside the hands at (${x}, ${y})`);
    }
  }
  assert.ok(kept > 300, `${kept} pixels of the hands kept`);
  // the frame is cached by what it draws, the entered element included
  assert.notEqual(frame.frame, plain.frame);
  assert.equal(doc.frame(frameKey({ device: "fr955", scale: 1, style: "roman_dark", enter })), frame);
});

test("a pattern entered shows its parts at the first drawn copy, and a needle gauge at the sample reading", async () => {
  const studio = await newStudio();
  const patterns = openExample(studio, PATTERNS);
  // hour_ticks skips copy 0, so copy 1, at 30 degrees, is the one shown
  const ticks = patterns.frame(frameKey({ device: "fr955", scale: 1, enter: nodeAt(patterns, "hour_ticks").path }));
  assert.deepEqual([ticks.local!.angle, ticks.local!.origin], [30, [130, 130]]);
  const tick = partsOf(ticks)["static/hour_ticks/parts/tick"];
  assert.deepEqual([tick.kind, tick.angle, tick.handles.map((h: any) => [h.kind, h.key.join("."), h.axis])], ["rectangle", 30, [["size", "size.width", "x"], ["size", "size.height", "y"]]]);
  // the tick's centre: 88%r up the frame, turned to 30 degrees
  assert.deepEqual(tick.center, onScreen([130, 130], 30, [0, -0.88 * 130]));
  // a radial pattern with `start:` shows copy 0 at that angle; an arc part's start handle is at the arc's screen angle
  const diagonals = patterns.frame(frameKey({ device: "fr955", scale: 1, enter: nodeAt(patterns, "diagonals").path }));
  assert.equal(diagonals.local!.angle, 45);
  const triangle = partsOf(diagonals)["static/diagonals/parts/triangle"];
  assert.deepEqual(triangle.handles.filter((h: any) => h.kind === "vertex").map((h: any) => h.index), [0, 1, 2]);
  assert.deepEqual(triangle.handles.filter((h: any) => h.kind === "segment").map((h: any) => h.after), [0, 1, 2]);
  const segments = partsOf(patterns.frame(frameKey({ device: "fr955", scale: 1, enter: nodeAt(patterns, "segments").path })))["static/segments/parts/segment"];
  const start = segments.handles.find((h: any) => h.key === "start_angle");
  assert.deepEqual([start.start, start.sweep, [start.cx, start.cy]], [3, 24, [130, 130]]);
  assert.deepEqual([start.x, start.y], onScreen([130, 130], 3, [0, -roundHalfAway(0.72 * 130)]));
  // a linear pattern is not turned; a text part is an item with its ink and no handles
  const numerals = partsOf(patterns.frame(frameKey({ device: "fr955", scale: 1, enter: nodeAt(patterns, "hour_numerals").path })))["static/hour_numerals/parts/numeral"];
  assert.deepEqual([numerals.kind, numerals.handles, numerals.center[0]], ["text", [], 130]);
  const dots = patterns.frame(frameKey({ device: "fr955", scale: 1, enter: nodeAt(patterns, "week_dots").path }));
  assert.equal(dots.local!.angle, 0);
  assert.notDeepEqual(dots.local!.origin, [130, 130]);
  // a needle turns to start_angle + fraction x sweep at the sample battery (68%)
  const gauge = openExample(studio, "examples/features/gauge/face.yaml");
  const needle = gauge.frame(frameKey({ device: "fr955", scale: 1, enter: nodeAt(gauge, "battery_needle").path }));
  const battery = (SAMPLE.get("system.battery") as { value: number }).value;
  assert.ok(Math.abs(needle.local!.angle - ((240 + battery / 100 * 240) % 360)) < 1e-6, String(needle.local!.angle));
  const blade = partsOf(needle)["elements/battery_needle/needle/blade"];
  assert.deepEqual([blade.kind, blade.angle, blade.handles.filter((h: any) => h.kind === "vertex").length], ["polygon", needle.local!.angle, 5]);
  // only a hands, pattern or needle element can be entered
  assert.throws(() => patterns.frame(frameKey({ device: "fr955", scale: 1, enter: ["elements", "clock"] })), /no parts to enter/);
  assert.throws(() => patterns.frame(frameKey({ device: "fr955", scale: 1, enter: ["elements", "nope"] })), /not an element/);
});

test("a hand part moved in the entered frame writes the delta turned back into the hand's frame", async () => {
  const doc = openExample(await newStudio(), SHOWCASE);
  const ring = "resources/hand_sets/vintage/hour/parts/ring";
  const before = handsOf(doc, "roman_hands").hour!.parts.find((p) => p.id === "ring") as { x: number; y: number };
  assert.deepEqual([before.x, before.y], [0, roundHalfAway(-0.32 * 130)]);
  // at 10:09:42 the hour hand is at 304.5 degrees: a screen drag of (6, -4) px is this delta along and across the hand
  const hour = 304.5;
  const [ldx, ldy] = toLocal(6, -4, hour);
  assert.ok(Math.abs(ldx - (6 * Math.cos(hour * Math.PI / 180) - 4 * Math.sin(hour * Math.PI / 180))) < 1e-9);
  assert.ok(Math.abs(ldy - (-6 * Math.sin(hour * Math.PI / 180) - 4 * Math.cos(hour * Math.PI / 180))) < 1e-9);
  const [change, landed] = doc.drag(ring, { kind: "move", dx: 6, dy: -4 }, "fr955", "auto", doc.version);
  assert.ok(landed);
  assert.equal(change.label, "move hour.ring of roman_hands by (+6, -4) px on fr955");
  const at = dataOf(doc).resources.hand_sets.vintage.hour.parts.ring.at;
  // the YAML: `at:` in %r, within the landing search's half pixel of the turned delta (1 %r is 1.3 px on fr955)
  const value = (raw: string): number => Number(raw.replace("%r", ""));
  assert.ok(at.dx.endsWith("%r") && at.dy.endsWith("%r"), JSON.stringify(at));
  assert.ok(Math.abs(value(at.dx) - ldx / 1.3) * 1.3 < 0.5, `${at.dx} vs ${ldx / 1.3}`);
  assert.ok(Math.abs(value(at.dy) - (-32 + ldy / 1.3)) * 1.3 < 0.5, `${at.dy} vs ${-32 + ldy / 1.3}`);
  // and the part lands on that pixel in its own frame
  const after = handsOf(doc, "roman_hands").hour!.parts.find((p) => p.id === "ring") as { x: number; y: number };
  assert.deepEqual([after.x, after.y], [roundHalfAway(before.x + ldx), roundHalfAway(before.y + ldy)]);
  // the same drag at another time turns by that time's angle: at 3:00 the hour hand points right, its own right side down,
  // so 13 px down the screen (10 %r) is a local dx
  doc.undo(doc.version);
  doc.drag(ring, { kind: "move", dx: 0, dy: 13 }, "fr955", "auto", doc.version, [3, 0, 0]);
  const three = dataOf(doc).resources.hand_sets.vintage.hour.parts.ring.at;
  assert.deepEqual(three, { dy: "-32%r", dx: "10%r" });
  // every hand's part: the second hand at 6 degrees a second
  const [moved] = doc.drag("resources/hand_sets/vintage/second/parts/counterweight", { kind: "move", dx: 0, dy: -13 }, "fr955", "auto", doc.version, [0, 0, 15]);
  assert.equal(moved.label, "move second.counterweight of roman_hands by (+0, -13) px on fr955");
  assert.deepEqual(dataOf(doc).resources.hand_sets.vintage.second.parts.counterweight.at, { dy: "16%r", dx: "-10%r" });
});

test("a pattern tick moved in the entered frame lands where the copy is drawn", async () => {
  const doc = openExample(await newStudio(), PATTERNS);
  const enter = nodeAt(doc, "hour_ticks").path;
  const before = partsOf(doc.frame(frameKey({ device: "fr955", scale: 1, enter })))["static/hour_ticks/parts/tick"];
  const [change, landed] = doc.drag("static/hour_ticks/parts/tick", { kind: "move", dx: 0, dy: 5 }, "fr955", "auto", doc.version);
  assert.ok(landed);
  assert.equal(change.label, "move tick of hour_ticks by (+0, +5) px on fr955");
  // copy 1 is drawn at 30 degrees: 5 px down the screen is 5 sin 30 across and 5 cos 30 along the tick's own frame
  const at = dataOf(doc).static.hour_ticks.parts.tick.at;
  const value = (raw: string): number => Number(raw.replace("%r", ""));
  assert.ok(Math.abs(value(at.dx) - 2.5 / 1.3) * 1.3 < 0.5, at.dx);
  assert.ok(Math.abs(value(at.dy) - (-88 + 5 * Math.cos(Math.PI / 6) / 1.3)) * 1.3 < 0.5, at.dy);
  const after = partsOf(doc.frame(frameKey({ device: "fr955", scale: 1, enter })))["static/hour_ticks/parts/tick"];
  assert.ok(Math.abs(after.center[0] - before.center[0]) <= 1 && Math.abs(after.center[1] - (before.center[1] + 5)) <= 1, `${before.center} -> ${after.center}`);
  // a size handle resizes the part's own size key; an arc part turns; a circle part's radius resizes
  doc.drag("static/hour_ticks/parts/tick", { kind: "resize", key: ["size", "height"], delta: 4 }, "fr955", "auto", doc.version);
  assert.equal(dataOf(doc).static.hour_ticks.parts.tick.size.height, "15%r");
  const [turned] = doc.drag("static/segments/parts/segment", { kind: "turn", key: "start_angle", degrees: 10 }, "fr955", "auto", doc.version);
  assert.equal(turned.label, "turn segment of segments.start_angle to 10° on fr955");
  assert.equal(dataOf(doc).static.segments.parts.segment.start_angle, "10deg");
  const [grown] = doc.drag("elements/week_dots/parts/dot", { kind: "resize", key: ["radius"], delta: 2 }, "fr955", "auto", doc.version);
  assert.equal(grown.label, "resize dot of week_dots.radius by +2 px on fr955");
  assert.equal(dataOf(doc).elements.week_dots.parts.dot.radius, "3.5%r");
  // a text part moves by its at:
  doc.drag("static/hour_numerals/parts/numeral", { kind: "move", dx: 0, dy: 6 }, "fr955", "auto", doc.version);
  assert.equal(dataOf(doc).static.hour_numerals.parts.numeral.at.dy, "-59.5%r");
});

test("a vertex drag on a mirror: x part keeps the mirror, and a point on the axis stays on it", async () => {
  const doc = openExample(await newStudio(), SHOWCASE);
  const before = bladeOf(doc).points;
  assert.equal(before.length, 4);
  const [ldx, ldy] = toLocal(4, -3, 304.5);
  const [change, landed] = doc.drag(BLADE.join("/"), { kind: "vertex", index: 1, dx: 4, dy: -3 }, "fr955", "auto", doc.version);
  assert.ok(landed);
  assert.equal(change.label, "move vertex 1 of hour.blade of roman_hands by (+4, -3) px on fr955");
  const after = bladeOf(doc).points;
  const moved: [number, number] = [roundHalfAway(before[1]![0] + ldx), roundHalfAway(before[1]![1] + ldy)];
  // the listed point moved by the turned delta, its reflection with it, the other pair untouched
  assert.deepEqual(after, [before[0], moved, [-moved[0], moved[1]], before[3]]);
  assert.deepEqual(dataOf(doc).resources.hand_sets.vintage.hour.parts.blade.mirror, "x");
  assert.equal(dataOf(doc).resources.hand_sets.vintage.hour.parts.blade.points.length, 2);
  // the point part's tip is on the axis (`{ dy: -40%r }`): dragged sideways it only moves along the hand
  const point = "resources/hand_sets/vintage/hour/parts/point";
  const tipBefore = (handsOf(doc, "roman_hands").hour!.parts.find((p) => p.id === "point") as ResolvedPolygonPart).points;
  assert.equal(tipBefore.length, 3);
  doc.drag(point, { kind: "vertex", index: 1, dx: 9, dy: 2 }, "fr955", "auto", doc.version);
  const tip = dataOf(doc).resources.hand_sets.vintage.hour.parts.point.points[1];
  assert.deepEqual(Object.keys(tip), ["dy"]);
  const tipAfter = (handsOf(doc, "roman_hands").hour!.parts.find((p) => p.id === "point") as ResolvedPolygonPart).points;
  assert.equal(tipAfter.length, 3);
  assert.deepEqual([tipAfter[1]![0], tipAfter[1]![1]], [0, roundHalfAway(tipBefore[1]![1] + toLocal(9, 2, 304.5)[1])]);
  // the whole mirrored part moves along its axis only
  doc.drag(BLADE.join("/"), { kind: "move", dx: 10, dy: 10 }, "fr955", "auto", doc.version);
  const whole = bladeOf(doc).points;
  assert.deepEqual(whole.map((p) => p[0]), after.map((p) => p[0]));
  assert.notDeepEqual(whole.map((p) => p[1]), after.map((p) => p[1]));
});

test("add_vertex then remove_vertex restores the text byte for byte, on a polygon element and on a part", async () => {
  const studio = await newStudio();
  const shapes = studio.create(readUpload("face.yaml", read(SHAPES)), "open");
  const original = shapes.text;
  const chevron = items(frameOf(shapes, "fr955", 1))["chevron"];
  const edge = chevron.handles.find((h: any) => h.kind === "segment" && h.after === 1);
  const [added, landed] = shapes.drag("chevron", { kind: "add_vertex", after: 1, x: edge.x, y: edge.y + 10 }, "fr955", "auto", shapes.version);
  assert.ok(landed);
  assert.equal(added.label, "add a vertex to chevron on fr955");
  const points = dataOf(shapes).elements.chevron.points;
  assert.equal(points.length, 4);
  // the new point: its neighbours' anchor and unit, landing on the dragged pixel
  assert.deepEqual(Object.keys(points[2]), ["anchor", "dx", "dy"]);
  assert.ok(points[2].dx.endsWith("%") && points[2].dy.endsWith("%"), JSON.stringify(points[2]));
  const vertices = items(frameOf(shapes, "fr955", 1))["chevron"].handles.filter((h: any) => h.kind === "vertex");
  assert.deepEqual([vertices[2].x, vertices[2].y], [edge.x, edge.y + 10]);
  assert.equal(vertices.length, 4);
  const [removed] = shapes.drag("chevron", { kind: "remove_vertex", index: 2 }, "fr955", "auto", shapes.version);
  assert.equal(removed.label, "remove vertex 2 of chevron on fr955");
  assert.equal(shapes.text, original);
  // a hand part: the new point is written in %r, as its neighbours are, in the hand's frame
  const doc = openExample(studio, SHOWCASE);
  const text = doc.text;
  const frame = doc.frame(frameKey({ device: "fr955", scale: 1, style: "roman_dark", enter: nodeAt(doc, "roman_hands").path }));
  const blade = partsOf(frame)[BLADE.join("/")];
  const segment = blade.handles.find((h: any) => h.kind === "segment");
  const [, ok] = doc.drag(BLADE.join("/"), { kind: "add_vertex", after: 0, x: segment.x + 3, y: segment.y }, "fr955", "auto", doc.version);
  assert.ok(ok);
  const written = dataOf(doc).resources.hand_sets.vintage.hour.parts.blade.points;
  assert.equal(written.length, 3);
  assert.deepEqual(Object.keys(written[1]), ["dx", "dy"]);
  assert.ok(written[1].dx.endsWith("%r"));
  const local = toLocal(segment.x + 3 - 130, segment.y - 130, 304.5);
  assert.deepEqual(bladeOf(doc).points[1], [roundHalfAway(local[0]), roundHalfAway(local[1])]);
  assert.equal(bladeOf(doc).points.length, 6);
  doc.drag(BLADE.join("/"), { kind: "remove_vertex", index: 1 }, "fr955", "auto", doc.version);
  assert.equal(doc.text, text);
});

test("the list form: a part's path ends in its index, its id is partN, and every gesture takes it", async () => {
  const text = minimal().replace("elements:\n", "elements:\n  ticks:\n    type: pattern\n    pattern: radial\n    at: { anchor: center }\n    count: 12\n"
    + "    color: color.dim\n    parts:\n      - { type: line, at: { dy: -90%r }, to: { dy: -84%r }, thickness: 1px }\n"
    + "      - type: polygon\n        points:\n          - { dx: -2%r, dy: -80%r }\n          - { dy: -84%r }\n          - { dx: 2%r, dy: -80%r }\n");
  const doc = (await newStudio()).create(bundle("L", text), "new");
  assert.ok(doc.analysis().face !== null, doc.diagnostics().map((d) => d.message).join("; "));
  const ticks = nodeAt(doc, "ticks");
  assert.deepEqual(ticks.children.map((p: any) => [p.kind, p.id, p.type, p.path, p.line, p.end]), [
    ["part", "part1", "line", ["elements", "ticks", "parts", 0], ticks.line + 7, ticks.line + 7],
    ["part", "part2", "polygon", ["elements", "ticks", "parts", 1], ticks.line + 8, ticks.line + 12],
  ]);
  const frame = doc.frame(frameKey({ device: "fr955", scale: 1, enter: ticks.path }));
  assert.deepEqual(Object.keys(partsOf(frame)), ["elements/ticks/parts/0", "elements/ticks/parts/1"]);
  const [change, landed] = doc.drag("elements/ticks/parts/1", { kind: "vertex", index: 1, dx: 0, dy: 13 }, "fr955", "auto", doc.version);
  assert.ok(landed);
  assert.equal(change.label, "move vertex 1 of part2 of ticks by (+0, +13) px on fr955");
  assert.deepEqual(dataOf(doc).elements.ticks.parts[1].points[1], { dy: "-74%r" });
  const inspected = doc.inspect(["elements", "ticks", "parts", 1], "fr955");
  assert.deepEqual([inspected.subject, inspected.id, inspected.type], ["part", "part2", "polygon"]);
  // reordering: move_item on the list, move_key refused with the way out
  doc.edit({ op: "move_item", element: ["elements", "ticks"], path: ["parts"], from: 1, to: 0 }, doc.version);
  assert.deepEqual(dataOf(doc).elements.ticks.parts.map((p: any) => p.type), ["polygon", "line"]);
  assert.throws(() => doc.edit({ op: "move_key", element: ["elements", "ticks"], path: ["parts", 0], to: 1 }, doc.version), /write the parts as a mapping to reorder them/);
});
