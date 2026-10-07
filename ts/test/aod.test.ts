// `aod:`: one block shape, each key cascading element > group > `defaults:`.
import assert from "node:assert/strict";
import { test } from "node:test";
import { errors, face, MINIMAL, view } from "./designs.ts";

const AMOLED = MINIMAL.replace("targets: [fenix8solar47mm]", "targets: [fenix847mm]");

const design = (defaults: string, elements: string): string =>
  AMOLED.replace("resources:", `defaults:\n  aod: ${defaults}\nresources:`) + elements;

const text = (id: string, aod: string): string =>
  `  ${id}:\n    type: text\n    text: "{time.clock:%H:%M}"\n    color: color.fg\n    aod: ${aod}\n`;

test("dim cascades key by key, and dim: 1 stops an inherited one", () => {
  const f = face(design("{dim: 0.5}",
    "  g:\n    type: group\n    aod: {dim: 0.25}\n    children:\n" + text("inner", "{visible: true}").replace(/^(?=.)/gm, "    ")
    + text("plain", "{visible: true}") + text("bright", "{dim: 1}")));
  const byId = new Map<string, (typeof f.elements)[number]>();
  const walk = (items: typeof f.elements): void => items.forEach((e) => { byId.set(e.id, e); walk(e.children()); });
  walk(f.elements);
  assert.deepEqual(byId.get("plain")!.aod!.dim, [500, 1000]);
  assert.deepEqual(byId.get("inner")!.aod!.dim, [250, 1000]);
  assert.equal(byId.get("bright")!.aod!.dim, null);
  assert.equal(byId.get("background")!.aod, null, "defaults: {aod:} without visible: true hides the silent");
});

test("an override colour is dimmed too, unless the element says dim: 1", () => {
  const dimmed = view(design("{dim: 0.5}", text("clock", '{color: "#FFFFFF"}')));
  assert.match(dimmed, /_aod \? 0x808080 :/);
  const full = view(design("{dim: 0.5}", text("clock", '{color: "#FFFFFF", dim: 1}')));
  assert.match(full, /_aod \? 0xFFFFFF :/);
  assert.doesNotMatch(full, /0x808080/);
});

test("visible: false hides, sticky on a group; the old words name the new spelling", () => {
  const f = face(design("{visible: true}",
    "  g:\n    type: group\n    aod: {visible: false}\n    children:\n" + text("inner", "{visible: true}").replace(/^(?=.)/gm, "    ")));
  assert.equal(f.elements.find((e) => e.id === "g")!.children()[0]!.aod, null);

  const word = errors(design("{visible: true}", text("clock", "hide")));
  assert.ok(word.some((d) => d.notes.some((n) => n.includes("'aod: hide' is written 'aod: {visible: false}'"))));
  const top = errors(AMOLED + "aod:\n  dim: 0.5\n");
  assert.ok(top.some((d) => d.notes.some((n) => n.includes("moved into 'defaults: {aod:"))));
});
