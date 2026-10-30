// The patch engine over the example corpus and its own edge cases: spans,
// patches through the gate, renames, structure and paste.
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { resolveAll } from "../src/build.ts";
import { REPO_ROOT } from "../src/devices/node.ts";
import { Bag } from "../src/diagnostics.ts";
import { Gate, loadText } from "../src/edit/gate.ts";
import { move, turn, View } from "../src/edit/geometry.ts";
import {
  addElement, chain, dataAt, DEFAULTS, deleteElement, duplicateElement, faceColor, insertItem, listSpan, moveElement, moveItem, type Patch,
  patch as makePatch, remove, removeItem, renameKey, renameReference, rewriteScalars, setScalars, setValue, child, deleteChild, flow,
  setChild, ShapeError,
} from "../src/edit/patch.ts";
import { type Entry, parse, type Path, Refused, sameData, SpanIndex, type Step } from "../src/edit/spans.ts";
import { type Data } from "../src/edit/yaml.ts";
import { deepCopy } from "../src/py.ts";
import { add, elementTypes, group, moveToBlock, paste, ungroup } from "../src/edit/structure.ts";
import { bakeFonts, ICON_FONT } from "../src/emit/resources.ts";
import { isSubmodule, readFontFile, repoFileExists } from "../src/node.ts";
import { Length } from "../src/units.ts";
import { db } from "./designs.ts";

const SHAPES = "examples/features/shapes/face.yaml";
const TARGETS = ["fenix8solar47mm", "fenix8solar51mm", "fr955"];
const read = (p: string): string => readFileSync(join(REPO_ROOT, p), "utf8");
const bake = (face: any, d: any): any => bakeFonts(face, d, (p) => readFontFile(p === ICON_FONT ? p : join(REPO_ROOT, p)));
const gate = (path: string, text: string): Gate => new Gate(path, text, repoFileExists);

/** Every design under `examples/` but the user's playground; `FACES` the faces among them. */
const DESIGNS: string[] = (() => {
  const out: string[] = [];
  const walk = (dir: string): void => {
    for (const name of readdirSync(join(REPO_ROOT, dir)).sort()) {
      const rel = `${dir}/${name}`;
      if (statSync(join(REPO_ROOT, rel)).isDirectory()) { if (!isSubmodule(rel)) walk(rel); }
      else if (name.endsWith(".yaml")) out.push(rel);
    }
  };
  walk("examples");
  return out;
})();
const FACES: string[] = DESIGNS.filter((p) => p.endsWith("/face.yaml"));

const minimal = (elements: string, staticBlock = ""): string =>
  "format: 2\nface: { id: 9c1d5f30-6a72-4b18-8d4e-0f2a71c93b64, name: Edit, version: 1.0.0 }\nbuild: { targets: [fenix8solar47mm] }\n"
  + "resources:\n  palette:\n    fg: \"#FFFFFF\"\n" + staticBlock + elements;

const data = (text: string): any => JSON.parse(JSON.stringify(parse(text), (_, v) => (v instanceof Map ? Object.fromEntries(v) : v)));
const at = (index: SpanIndex, path: Path): unknown => path.reduce<unknown>((d, step) => (d instanceof Map ? d.get(step) : (d as unknown[])[step as number]), index.data);

/** How many separate places two texts differ in, by line. */
function changedBlocks(before: string, after: string): number {
  const a = before.split("\n"), b = after.split("\n");
  let start = 0;
  while (start < a.length && a[start] === b[start]) start++;
  let endA = a.length - 1, endB = b.length - 1;
  while (endA >= start && endB >= start && a[endA] === b[endB]) endA--, endB--;
  if (start > endA && start > endB) return 0;
  // a change in two places shows as a span with equal lines inside it
  const inner = a.slice(start, endA + 1), innerB = b.slice(start, endB + 1);
  const common = inner.filter((line) => innerB.includes(line)).length;
  return common > 0 && inner.length > 1 && innerB.length > 1 ? 2 : 1;
}

function gated(g: Gate, p: Patch, before: string, maxBlocks: number): void {
  g.check(p);
  const n = changedBlocks(before, p.text);
  assert.ok(n >= 1 && n <= maxBlocks, `${p.what}: ${n} changes`);
}

const siblings = (index: SpanIndex, entry: Entry): Entry[] => index.entries().filter((e) => e.parent === entry.parent);

// -- the span index --

test("every element is found by its span", () => {
  for (const path of FACES) {
    const text = read(path);
    const loaded = loadText(path, text, repoFileExists);
    const index = new SpanIndex(text);
    const missing = loaded.face!.walk().filter((e) => index.atSpan(e.span) === undefined).map((e) => e.id);
    assert.deepEqual(missing, [], path);
  }
});

test("an element entry spans its comments and stops before the next key", () => {
  const text = minimal("elements:\n  # the first\n  a:\n    type: circle\n    radius: 5%r\n\n  # the second\n  b:\n    type: circle\n    radius: 6%r\n");
  const index = new SpanIndex(text);
  for (const [name, want] of [["a", "  # the first\n  a:\n    type: circle\n    radius: 5%r\n"], ["b", "  # the second\n  b:\n    type: circle\n    radius: 6%r\n"]]) {
    const [s, e] = index.entryRange(index.at(["elements", name!]));
    assert.equal(text.slice(s, e), want);
  }
});

test("the index data is exactly what the text parses to", () => {
  for (const path of FACES) {
    const text = read(path);
    assert.ok(sameData(new SpanIndex(text).data, parse(text)), path);
  }
  assert.throws(() => new SpanIndex("a: [1, 2\n"), /not valid YAML/);
});

// -- patches over the corpus, each through the gate --

test("patches over the corpus", () => {
  for (const path of FACES) {
    const text = read(path);
    const index = new SpanIndex(text);
    const g = gate(path, text);
    assert.ok(g.before.face !== null, path);
    const elements = index.elements();
    const first = elements[0]!;
    // a no-op is byte-identical
    for (const entry of index.entries()) {
      if (entry.path.length > 1 && entry.path[entry.path.length - 2] === "at" && entry.value.kind !== "mapping") {
        assert.equal(setValue(index, entry.path, at(index, entry.path) as never).text, text, `${path} ${entry.path.join(".")}`);
      }
    }
    assert.equal(moveElement(index, first.path, siblings(index, first).indexOf(first)).text, text);
    // a scalar rewritten in the author's own unit changes exactly one line
    for (const entry of elements.filter((e) => index.get([...e.path, "at", "dy"]) !== undefined).slice(0, 2)) {
      const raw = at(index, [...entry.path, "at", "dy"]);
      const length = Length.parse(raw instanceof Object && "value" in (raw as object) ? (raw as { value: number }).value : raw);
      const next = typeof raw === "string" ? `${Number((length.value + 10).toPrecision(6))}${length.unit}` : length.value + 10;
      const p = setValue(index, [...entry.path, "at", "dy"], next);
      gated(g, p, text, 1);
      assert.equal(text.split("\n").filter((line, i) => line !== p.text.split("\n")[i]).length, 1, path);
    }
    gated(g, deleteElement(index, first.path), text, 1);
    gated(g, duplicateElement(index, first.path), text, 1);
    if (siblings(index, first).length > 1) gated(g, moveElement(index, first.path, 1), text, 2);
    const firstAt = index.get([...first.path, "at"]);
    if (firstAt !== undefined && firstAt.value.kind === "mapping" && index.get([...first.path, "at", "angle"]) === undefined) {
      if (index.get([...first.path, "at", "dx"]) === undefined) gated(g, setValue(index, [...first.path, "at", "dx"], "1%r"), text, 1);
      if (index.get([...first.path, "at", "dy"]) !== undefined && (at(index, [...first.path, "at"]) as Map<unknown, unknown>).size > 1) {
        gated(g, remove(index, [...first.path, "at", "dy"]), text, 1);
      }
    }
    if (index.get(["elements"]) !== undefined) gated(g, addElement(index, "rectangle"), text, 1);
  }
});

test("a new element of every default type loads in the face's main colour", () => {
  const text = read(SHAPES);
  for (const type of DEFAULTS.keys()) {
    const p = addElement(new SpanIndex(text), type);
    gate(SHAPES, text).check(p);
    assert.equal(data(p.text).elements[`new_${type}`].color, "color.dim", type);
  }
});

// -- the three rules --

test("deleting a block's only element removes the block", () => {
  const text = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n", "static:\n  bg:\n    type: circle\n    radius: 9%r\n    color: color.fg\n");
  const p = deleteElement(new SpanIndex(text), ["static", "bg"]);
  assert.ok(!("static" in data(p.text)) && !p.text.includes("static:"));
  assert.ok(p.text.endsWith("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n"));
});

test("duplicates: a group's elements renamed, the first free suffix", () => {
  const rings = "examples/features/rings/face.yaml";
  const text = read(rings);
  const p = duplicateElement(new SpanIndex(text), ["elements", "heart_rate"]);
  assert.deepEqual(new Set(Object.keys(data(p.text).elements.heart_rate_copy.children)), new Set(["heart_icon_copy", "heart_value_copy"]));
  gate(rings, text).check(p);
  const twice = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n  a_copy:\n    type: circle\n    radius: 5%r\n    color: color.fg\n");
  assert.deepEqual(Object.keys(data(duplicateElement(new SpanIndex(twice), ["elements", "a"]).text).elements), ["a", "a_copy2", "a_copy"]);
});

test("an element added to a face with no elements block, in the face's colour", () => {
  const text = minimal("", "static:\n  bg:\n    type: circle\n    radius: 9%r\n    color: color.fg\n");
  assert.deepEqual(data(addElement(new SpanIndex(text), "circle").text).elements, { new_circle: { type: "circle", at: { anchor: "center" }, radius: "10%r", color: "color.fg" } });
  assert.equal(faceColor(new SpanIndex(minimal("elements: {}\n"))), "color.fg");
  assert.equal(faceColor(new SpanIndex(read(SHAPES))), "color.dim");
  assert.equal(faceColor(new SpanIndex(minimal("static:\n  bg:\n    type: rectangle\n    color: color.bg\nelements:\n  a:\n    type: circle\n    color: color.fg\n"))), "color.fg");
});

test("keys are added in their mapping's own style; quotes and a missing final newline are kept", () => {
  const text = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n    at: { anchor: center }\n");
  const index = new SpanIndex(text);
  assert.ok(setValue(index, ["elements", "a", "at", "dy"], "3%r").text.includes("at: { anchor: center, dy: 3%r }\n"));
  assert.ok(setValue(index, ["elements", "a", "thickness"], "2px").text.includes("    color: color.fg\n    at: { anchor: center }\n    thickness: 2px\n"));
  assert.ok(setValue(index, ["elements", "a", "overrides", "fr955", "at", "dy"], "4%").text.includes("    overrides: { fr955: { at: { dy: 4% } } }\n"));
  const quoted = minimal("elements:\n  a:\n    type: text\n    text: \"Hi\"\n    font: FONT_SMALL\n    color: color.fg\n    at: { dy: '5%' }\n");
  assert.ok(setValue(new SpanIndex(quoted), ["elements", "a", "at", "dy"], "7%").text.includes("at: { dy: '7%' }"));
  const open = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg");
  const openIndex = new SpanIndex(open);
  for (const p of [duplicateElement(openIndex, ["elements", "a"]), addElement(openIndex, "circle"), setValue(openIndex, ["elements", "a", "thickness"], "2px")]) {
    assert.ok(!p.text.endsWith("\n"), p.what);
    assert.ok(sameData(parse(p.text), p.expected), p.what);
  }
});

test("removing the last key of an override prunes the emptied mappings, up through overrides itself", () => {
  const base = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n    at: { anchor: center }\n");
  const g = gate("face.yaml", base);
  // as the device scope writes it: a flow override nested three deep
  const written = setValue(new SpanIndex(base), ["elements", "a", "overrides", "fenix8solar47mm", "at", "dx"], "10%r");
  assert.ok(written.text.includes("    overrides: { fenix8solar47mm: { at: { dx: 10%r } } }\n"));
  const gone = remove(new SpanIndex(written.text), ["elements", "a", "overrides", "fenix8solar47mm", "at", "dx"]);
  g.check(gone);
  assert.equal(gone.text, base);
  assert.ok(sameData(parse(gone.text), gone.expected));
  // a sibling key keeps the override, and only the emptied mapping goes
  const two = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n    at: { anchor: center }\n"
    + "    overrides: { fr955: { at: { dx: 1px }, size: { width: 2px } } }\n");
  const kept = remove(new SpanIndex(two), ["elements", "a", "overrides", "fr955", "at", "dx"]);
  assert.ok(kept.text.includes("    overrides: { fr955: { size: { width: 2px } } }\n"), kept.text);
  assert.ok(sameData(parse(kept.text), kept.expected));
  // the same in block style, through a flow leaf
  const block = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n    at: { anchor: center }\n"
    + "    overrides:\n      fr955:\n        at: { dx: 1px }\n");
  const pruned = remove(new SpanIndex(block), ["elements", "a", "overrides", "fr955", "at", "dx"]);
  assert.equal(pruned.text, base);
  assert.ok(sameData(parse(pruned.text), pruned.expected));
});

test("scalars already written are set together in place", () => {
  const text = minimal("elements:\n  a:\n    type: circle\n    at: { dx: 10, dy: '20' }\n    radius: 5\n");
  const index = new SpanIndex(text);
  const p = setScalars(index, [[["elements", "a", "at", "dx"], 12], [["elements", "a", "at", "dy"], 31]]);
  assert.ok(p !== undefined && p.text.includes("at: { dx: 12, dy: 31 }"));
  assert.ok(sameData(parse(p.text), p.expected));
  const one = setValue(index, ["elements", "a", "at", "dx"], 12);
  assert.equal(p.text, setValue(new SpanIndex(one.text), ["elements", "a", "at", "dy"], 31).text);
  assert.equal(setScalars(index, [[["elements", "a", "at", "dx"], 1], [["elements", "a", "fill"], true]]), undefined);
});

// -- lists, mappings and renames --

test("a list replaces targets in its own style", () => {
  for (const path of FACES) {
    const text = read(path);
    const index = new SpanIndex(text);
    const targets = (at(index, ["build", "targets"]) as string[]).slice();
    const next = [...targets.reverse(), "fenix7"];
    const p = setValue(index, ["build", "targets"], next);
    gate(path, text).check(p);
    const after = new SpanIndex(p.text);
    assert.deepEqual(at(after, ["build", "targets"]), next, path);
    const entry = index.at(["build", "targets"]);
    const flow = (e: Entry): boolean => (e.value as { flow?: boolean }).flow === true;
    assert.equal(flow(entry), flow(after.at(["build", "targets"])), path);
    const head = text.slice(0, text.lastIndexOf("\n", entry.key.start.index) + 1);
    const tail = text.slice(index.valueEnd(entry));
    assert.ok(p.text.startsWith(head) && p.text.endsWith(tail) && p.text.length > head.length + tail.length, path);
  }
});

test("a block mapping is replaced at its indent, keeping the key line", () => {
  const text = "format: 2\nresources:\n  palette:  # the swatches\n    a: \"#000000\"\n    # a comment inside goes with the old value\n    b: \"#FFFFFF\"\nelements: {}\n";
  const p = setValue(new SpanIndex(text), ["resources", "palette"], new Map([["a", "#000000"], ["c", "#555555"]]));
  assert.equal(p.text, "format: 2\nresources:\n  palette:  # the swatches\n    a: \"#000000\"\n    c: \"#555555\"\nelements: {}\n");
  assert.ok(sameData(parse(p.text), p.expected));
  assert.deepEqual(data(setValue(new SpanIndex(text), ["resources", "palette"], new Map()).text).resources.palette, {});
});

test("every colour renames with its references and back", () => {
  for (const path of FACES) {
    const text = read(path);
    const index = new SpanIndex(text);
    const g = gate(path, text);
    const palette = at(index, ["resources", "palette"]);
    for (const name of palette instanceof Map ? palette.keys() : []) {
      const p = renameReference(index, ["resources", "palette", name], `${String(name)}_x`, "color.");
      g.check(p);
      assert.ok(p.text.includes(`color.${String(name)}_x`) || !text.includes(`color.${String(name)}`), `${path} ${String(name)}`);
      assert.equal(renameReference(new SpanIndex(p.text), ["resources", "palette", `${String(name)}_x`], String(name), "color.").text, text, `${path} ${String(name)}`);
    }
  }
});

test("a rename reaches into expressions but not longer names, and is refused onto an existing one", () => {
  const text = "resources:\n  palette:\n    a: \"#000000\"\n    ab: \"#FFFFFF\"\nelements:\n  x:\n    color: \"cond ? color.a : color.ab\"\n    choices: [color.a, color.ab]\n    text: 'color.a'\n";
  const p = renameReference(new SpanIndex(text), ["resources", "palette", "a"], "z", "color.");
  const d = data(p.text);
  assert.deepEqual(Object.keys(d.resources.palette), ["z", "ab"]);
  assert.deepEqual(d.elements.x, { color: "cond ? color.z : color.ab", choices: ["color.z", "color.ab"], text: "color.z" });
  assert.ok(p.text.includes("text: 'color.z'"));
  assert.throws(() => renameKey(new SpanIndex("resources:\n  palette:\n    a: \"#000000\"\n    b: \"#FFFFFF\"\n"), ["resources", "palette", "a"], "b"), /already exists/);
});

test("rewriting leaves keys and block scalars alone; a chain checks its first step", () => {
  const text = "color.a: color.a\nnote: |\n  color.a\nlist: [color.a]\n";
  assert.equal(rewriteScalars(new SpanIndex(text), (s) => s.replace("color.a", "color.b"), "x").text, "color.a: color.b\nnote: |\n  color.a\nlist: [color.b]\n");
  const lying = makePatch("a: 2\n", new Map([["a", 1]]), "lie");
  assert.throws(() => chain(lying, (i) => setValue(i, ["a"], 3)), /more than intended/);
});

// -- a line's ends and an arc's angles --

for (const device of TARGETS) {
  test(`a line's ends move apart and land, and an arc's angles turn in the author's unit, ${device}`, () => {
    const text = read(SHAPES);
    const view = new View(SHAPES, text, db.get(device), repoFileExists, bake);
    const lines = view.face.walk().filter((e) => (e as { shape?: string }).shape === "line").map((e) => e.id);
    assert.ok(lines.length > 0);
    for (const line of lines) {
      const before = view.placed(line) as any;
      const start = move(view, line, 4, -3, "auto", "at");
      assert.ok(start.landed);
      let placed = view.placed(line, view.place(loadText(SHAPES, start.patch.text, repoFileExists))) as any;
      assert.deepEqual(placed.center, [before.center[0] + 4, before.center[1] - 3]);
      assert.deepEqual(placed.end, before.end);
      const end = move(view, line, -5, 2, "auto", "to");
      assert.ok(end.landed);
      placed = view.placed(line, view.place(loadText(SHAPES, end.patch.text, repoFileExists))) as any;
      assert.deepEqual(placed.end, [before.end[0] - 5, before.end[1] + 2]);
      assert.deepEqual(placed.center, before.center);
    }
    assert.throws(() => move(view, "card", 1, 1, "auto", "to"), /not a line/);
    const arc = view.placed("outer_arc") as any;
    const turned = turn(view, "outer_arc", "sweep", Number(arc.sweep) - 23);
    assert.ok(turned.landed);
    assert.equal(data(turned.patch.text).elements.outer_arc.sweep, `${Number(arc.sweep) - 23}deg`);
    const rotated = turn(view, "outer_arc", "start_angle", 33.3);
    assert.ok(rotated.landed);
    assert.equal(data(rotated.patch.text).elements.outer_arc.start_angle, "33deg");
    assert.throws(() => turn(view, "card", "start_angle", 10), /no start_angle/);
    assert.throws(() => turn(view, "outer_arc", "radius", 10), /not start_angle or sweep/);
  });
}

// -- structure --

test("grouping moves nothing, and ungrouping gives the text back", () => {
  const device = db.get("fr955");
  for (const path of FACES) {
    const text = read(path);
    const index = new SpanIndex(text);
    const g = gate(path, text);
    const blocks = new Map<string, Entry[]>();
    for (const e of index.elements()) {
      const key = JSON.stringify(e.path.slice(0, -1));
      blocks.set(key, [...(blocks.get(key) ?? []), e]);
    }
    let before: Map<string, string> | null = null;
    const placements = (t: string): Map<string, string> => {
      const loaded = loadText(path, t, repoFileExists);
      const [resolved] = resolveAll(loaded.face!, [device], new Bag(), bake);
      return new Map(resolved.get(device.id)!.items.map((p) => [p.id, JSON.stringify([p.box, p.center])]));
    };
    for (const entries of blocks.values()) {
      if (entries.length < 2 || entries[0]!.isFlow || entries[1]!.isFlow) continue;
      let p: Patch;
      try {
        p = group(index, [entries[0]!.path, entries[1]!.path]);
        g.check(p);
      } catch (error) {
        assert.ok(error instanceof Refused && error.message.includes("subscreen"), String(error));
        continue;
      }
      before ??= placements(text);
      const after = placements(p.text);
      for (const [id, place] of before) if (after.has(id)) assert.equal(after.get(id), place, `${path} ${id}`);
      const made = new SpanIndex(p.text);
      const created = made.elements().find((e) => !index.elementIds().has(e.name))!;
      assert.equal(ungroup(made, created.path).text, text, path);
    }
  }
});

test("an element moves between blocks, creating and emptying them", () => {
  const text = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n  # b's own comment travels with it\n  b:\n    type: circle\n    radius: 6%r\n    color: color.fg\n");
  const moved = moveToBlock(new SpanIndex(text), ["elements", "b"], ["static"]);
  assert.deepEqual([Object.keys(data(moved.text).static), Object.keys(data(moved.text).elements)], [["b"], ["a"]]);
  assert.ok(moved.text.includes("  # b's own comment travels with it\n  b:\n"));
  const back = moveToBlock(new SpanIndex(moved.text), ["static", "b"], ["elements"]);
  assert.deepEqual(data(back.text).elements, data(text).elements);
  assert.ok(!("static" in data(back.text)));
  const grouped = group(new SpanIndex(text), [["elements", "a"]], "g");
  const into = moveToBlock(new SpanIndex(grouped.text), ["elements", "b"], ["elements", "g", "children"], "a");
  assert.deepEqual(Object.keys(data(into.text).elements.g.children), ["b", "a"]);
  assert.ok(into.text.includes("      b:\n        type: circle\n"));
});

test("structure refuses what it cannot do", () => {
  const text = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n  g:\n    type: group\n    at: { anchor: center, dy: 5%r }\n"
    + "    children:\n      c:\n        type: circle\n        radius: 2%r\n        color: color.fg\n");
  const index = new SpanIndex(text);
  assert.throws(() => moveToBlock(index, ["elements", "a"], ["elements"]), /already in/);
  assert.throws(() => moveToBlock(index, ["elements", "g"], ["elements", "g", "children"]), /into itself/);
  assert.throws(() => moveToBlock(index, ["elements", "a"], ["resources"]), /not an element block/);
  assert.throws(() => moveToBlock(index, ["elements", "g", "children", "c"], ["elements", "a", "children"]), /not a group/);
  assert.throws(() => group(index, [["elements", "a"], ["elements", "g", "children", "c"]]), /side by side in one block/);
  assert.throws(() => ungroup(index, ["elements", "g"]), /has at/);
  assert.throws(() => add(index, "graph"), /needs its series/);
  assert.throws(() => add(index, "teapot"), /no element type/);
});

test("every type can be added", () => {
  const text = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n");
  for (const type of elementTypes().filter((t) => t !== "data" && t !== "hands")) {
    const p = add(new SpanIndex(text), type, ["elements"], null, null, type === "graph" ? "steps" : null);
    gate(SHAPES, text).check(p);
    assert.equal(data(p.text).elements[`new_${type}`].type, type);
  }
});

// -- paste --

test("pasted elements keep their text and take fresh ids where the face has them", () => {
  const text = minimal("elements:\n  dot:\n    type: circle\n    at: { dx: 0, dy: 0 }\n    radius: 5\n    color: color.fg\n  last:\n    type: circle\n    at: { dx: 9, dy: 9 }\n    radius: 2\n    color: color.fg\n");
  const clip = "dot:   # the copied one\n  type: circle\n  at: { dx: 30, dy: 0 }\n  radius: 5\n  color: color.fg\nbox:\n  type: group\n  children:\n    dot2:\n      type: circle\n      at: { dx: 1, dy: 1 }\n      radius: 1\n      color: color.fg\n";
  const p = paste(new SpanIndex(text), clip, ["elements"], "last");
  assert.ok(sameData(parse(p.text), p.expected));
  const d = data(p.text);
  assert.deepEqual(Object.keys(d.elements), ["dot", "dot3", "box", "last"]);
  assert.deepEqual(Object.keys(d.elements.box.children), ["dot2"]);
  assert.ok(p.text.includes("  dot3:   # the copied one\n    type: circle\n    at: { dx: 30, dy: 0 }"));
  assert.deepEqual(new Gate("face.yaml", text, () => false).check(p).errors, []);
  const index = new SpanIndex(minimal("elements:\n  dot:\n    type: circle\n    radius: 5\n"));
  for (const bad of ["just some words", "a: 1\n", "- type: circle\n"]) assert.throws(() => paste(index, bad), /not elements/, bad);
});

test("child, setChild and deleteChild reach a mapping's key and a list's index, negative from the end", () => {
  const list = ["a", "b", "c"];
  const data = new Map<string, unknown>([["k", list]]) as never;
  assert.equal(child(child(data, "k"), -1), "c");
  setChild(list, -3, "z");
  deleteChild(list, 1);
  assert.deepEqual(list, ["z", "c"]);
  for (const bad of [() => child(data, "nope"), () => child(list, 2), () => setChild(list, 5, "x"), () => deleteChild(data, "nope"), () => child("text", 0)]) {
    assert.throws(bad, ShapeError);
  }
});

test("a key written back reads back as the same key: null, a bool, a number and the string null", () => {
  const keys = [null, true, 5, "null", "plain"];
  const written = flow(new Map(keys.map((k, i) => [k, i])) as never);
  const back = (parse(`k: ${written}\n`) as Map<unknown, Map<unknown, unknown>>).get("k")!;
  assert.deepEqual([...back.keys()], keys, written);
});

// -- list items --

/** The path of every list in `data`, outer before inner. */
function listPaths(data: Data, here: Step[] = []): Path[] {
  if (data instanceof Map) return [...data].flatMap(([k, v]) => listPaths(v, [...here, k as Step]));
  if (Array.isArray(data)) return [here, ...data.flatMap((v, i) => listPaths(v, [...here, i]))];
  return [];
}

/** `p` parses to its expected data, which is `want`, and leaves everything outside `[start, end)` of `text` alone. */
function listPatch(p: Patch, want: Data, text: string, [start, end]: [number, number], label: string): void {
  assert.ok(sameData(parse(p.text), p.expected), `${label}: ${p.what} does not parse to its data\n${p.text}`);
  assert.ok(sameData(p.expected, want), `${label}: ${p.what} expects the wrong data`);
  assert.ok(p.text.startsWith(text.slice(0, start)) && p.text.endsWith(text.slice(end)), `${label}: ${p.what} changed text outside the list`);
}

test("every list in the corpus takes an item at either end, loses each, and reorders, byte-exact outside it and round-tripping", () => {
  let lists = 0;
  for (const path of DESIGNS) {
    const text = read(path);
    const index = new SpanIndex(text);
    for (const list of listPaths(index.data)) {
      const label = `${path} ${list.join(".")}`;
      const items = dataAt(index.data, list) as Data[];
      const span = listSpan(index, list);
      const changed = (change: (copy: Data[]) => void): Data => {
        const copy = deepCopy(index.data);
        change(dataAt(copy, list) as Data[]);
        return copy;
      };
      const probe = deepCopy(items[0]!);
      // an item at either end, then taken out again: the text as it was
      for (const at of [0, items.length]) {
        const inserted = insertItem(index, list, at, probe);
        listPatch(inserted, changed((l) => l.splice(at, 0, probe)), text, span, label);
        assert.equal(removeItem(new SpanIndex(inserted.text), list, at).text, text, `${label}: insert at ${at} then remove`);
      }
      // each item out
      for (let at = 0; at < items.length; at++) {
        const removed = removeItem(index, list, at);
        if (items.length > 1) {
          listPatch(removed, changed((l) => l.splice(at, 1)), text, span, label);
        } else {
          assert.ok(sameData(parse(removed.text), removed.expected), `${label}: ${removed.what}`);
          const entry = index.get(list);
          const flowList = (index.at(list).value as { flow?: boolean }).flow === true;
          if (entry !== undefined && !flowList) assert.equal(index.get(list) !== undefined && dataAt(removed.expected, list.slice(0, -1)) instanceof Map && (dataAt(removed.expected, list.slice(0, -1)) as Map<unknown, unknown>).has(list[list.length - 1]), false, `${label}: the emptied list's key stays`);
          else assert.deepEqual(dataAt(removed.expected, list), [], label);
        }
      }
      // first to last and back, last to first and back: the text as it was
      if (items.length > 1) {
        const last = items.length - 1;
        for (const [from, to] of [[0, last], [last, 0]]) {
          const moved = moveItem(index, list, from!, to!);
          listPatch(moved, changed((l) => { const [m] = l.splice(from!, 1); l.splice(to!, 0, m!); }), text, span, label);
          assert.equal(moveItem(new SpanIndex(moved.text), list, to!, from!).text, text, `${label}: move ${from} to ${to} and back`);
        }
      }
      lists++;
    }
  }
  assert.ok(lists > 100, `${lists} lists`);
});

test("a block list of block mappings takes a block item, matching its neighbours", () => {
  const text = minimal("elements:\n  a:\n    type: pattern\n    pattern: radial\n    count: 4\n    color: color.fg\n    parts:\n      - type: polygon\n        points:\n          - { dx: -3%r, dy: -56%r }\n          - { dy: -64%r }\n          - { dx: 3%r, dy: -56%r }\n          - { dy: -50%r }\n      - type: circle\n        radius: 2%r\n");
  const index = new SpanIndex(text);
  const g = gate("face.yaml", text);
  const part = new Map<string, Data>([["type", "polygon"], ["points", [new Map([["dx", "1%r"]]), new Map([["dy", "2%r"]]), new Map([["dx", "3%r"]])]]]);
  const added = insertItem(index, ["elements", "a", "parts"], 2, part);
  g.check(added);
  assert.ok(added.text.endsWith("      - type: circle\n        radius: 2%r\n      - type: polygon\n        points:\n          - { dx: 1%r }\n          - { dy: 2%r }\n          - { dx: 3%r }\n"), added.text);
  const first = insertItem(index, ["elements", "a", "parts"], 0, new Map<string, Data>([["type", "circle"], ["radius", "1%r"]]));
  g.check(first);
  assert.ok(first.text.includes("    parts:\n      - type: circle\n        radius: 1%r\n      - type: polygon\n"), first.text);
  // a point among `- { dx: .., dy: .. }` lines is one more such line
  const point = insertItem(index, ["elements", "a", "parts", 0, "points"], 1, new Map([["dx", "0%r"], ["dy", "-60%r"]]));
  g.check(point);
  assert.ok(point.text.includes("          - { dx: -3%r, dy: -56%r }\n          - { dx: 0%r, dy: -60%r }\n          - { dy: -64%r }\n"), point.text);
  const gone = removeItem(index, ["elements", "a", "parts", 0, "points"], 0);
  g.check(gone);
  assert.ok(gone.text.includes("        points:\n          - { dy: -64%r }\n          - { dx: 3%r, dy: -56%r }\n          - { dy: -50%r }\n      - type: circle\n"), gone.text);
  const swapped = moveItem(index, ["elements", "a", "parts"], 1, 0);
  g.check(swapped);
  assert.ok(swapped.text.includes("    parts:\n      - type: circle\n        radius: 2%r\n      - type: polygon\n        points:\n"), swapped.text);
  assert.equal(moveItem(new SpanIndex(swapped.text), ["elements", "a", "parts"], 0, 1).text, text);
});

test("an item's comment lines travel with it, and a list's comments and blank lines stay in place", () => {
  const text = "parts:\n  # the first\n  - { a: 1 }   # on its line\n\n  # the second\n  - b: 2\n    c: 3\n\n  # after the last\nnext: 1\n";
  const index = new SpanIndex(text);
  const moved = moveItem(index, ["parts"], 0, 1);
  assert.equal(moved.text, "parts:\n  # the second\n  - b: 2\n    c: 3\n\n  # the first\n  - { a: 1 }   # on its line\n\n  # after the last\nnext: 1\n");
  assert.ok(sameData(parse(moved.text), moved.expected));
  assert.equal(removeItem(index, ["parts"], 0).text, "parts:\n\n  # the second\n  - b: 2\n    c: 3\n\n  # after the last\nnext: 1\n");
  // the blank lines around a removed item stay, as around a removed mapping entry
  assert.equal(removeItem(index, ["parts"], 1).text, "parts:\n  # the first\n  - { a: 1 }   # on its line\n\n\n  # after the last\nnext: 1\n");
  assert.equal(insertItem(index, ["parts"], 2, "z").text, "parts:\n  # the first\n  - { a: 1 }   # on its line\n\n  # the second\n  - b: 2\n    c: 3\n  - z\n\n  # after the last\nnext: 1\n");
});

test("a flow list takes, loses and reorders items with its own separators", () => {
  const text = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n    lint: { allow: [safe-area], reason: on purpose }\n");
  const index = new SpanIndex(text);
  const g = gate("face.yaml", text);
  const targets = ["build", "targets"];
  const front = insertItem(index, targets, 0, "fr955");
  g.check(front);
  assert.ok(front.text.includes("build: { targets: [fr955, fenix8solar47mm] }\n"));
  const back = insertItem(index, targets, 1, "fr955");
  g.check(back);
  assert.ok(back.text.includes("build: { targets: [fenix8solar47mm, fr955] }\n"));
  const three = new SpanIndex(insertItem(new SpanIndex(back.text), targets, 1, "fenix8solar51mm").text);
  assert.ok(three.text.includes("[fenix8solar47mm, fenix8solar51mm, fr955]"));
  assert.ok(moveItem(three, targets, 2, 0).text.includes("[fr955, fenix8solar47mm, fenix8solar51mm]"));
  assert.ok(moveItem(three, targets, 0, 2).text.includes("[fenix8solar51mm, fr955, fenix8solar47mm]"));
  assert.ok(removeItem(three, targets, 1).text.includes("[fenix8solar47mm, fr955]"));
  assert.ok(removeItem(three, targets, 2).text.includes("[fenix8solar47mm, fenix8solar51mm]"));
  // a list inside a flow mapping; its last item out leaves `[]`
  const allow = ["elements", "a", "lint", "allow"];
  const more = insertItem(index, allow, 1, "contrast");
  g.check(more);
  assert.ok(more.text.includes("lint: { allow: [safe-area, contrast], reason: on purpose }\n"));
  const none = removeItem(index, allow, 0);
  assert.ok(none.text.includes("lint: { allow: [], reason: on purpose }\n"));
  assert.ok(sameData(parse(none.text), none.expected));
  assert.ok(insertItem(new SpanIndex(none.text), allow, 0, "contrast").text.includes("lint: { allow: [contrast], reason: on purpose }\n"));
  // a multi-line flow list keeps its line breaks
  const wrapped = "a: [one, two,\n    three]\n";
  assert.equal(insertItem(new SpanIndex(wrapped), ["a"], 2, "x").text, "a: [one, two,\n    x,\n    three]\n");
  assert.equal(insertItem(new SpanIndex(wrapped), ["a"], 3, "x").text, "a: [one, two,\n    three,\n    x]\n");
  assert.equal(removeItem(new SpanIndex(wrapped), ["a"], 2).text, "a: [one, two]\n");
  assert.equal(insertItem(new SpanIndex("a: [ ]\n"), ["a"], 0, 1).text, "a: [1]\n");
});

test("the last item of a block list takes the list's key with it, and the first key of a block item leaves the dash", () => {
  const index = new SpanIndex("a:\n  parts:\n    - { x: 1 }\n  skip:\n    - 0\nb:\n  only:\n    - 1\n");
  const parts = removeItem(index, ["a", "parts"], 0);
  assert.equal(parts.text, "a:\n  skip:\n    - 0\nb:\n  only:\n    - 1\n");
  assert.ok(sameData(parse(parts.text), parts.expected));
  const only = removeItem(index, ["b", "only"], 0);
  assert.equal(only.text, "a:\n  parts:\n    - { x: 1 }\n  skip:\n    - 0\n");
  assert.ok(sameData(parse(only.text), only.expected));
  const item = new SpanIndex("parts:\n  - type: polygon  # shaft\n    color: x\n  - type: circle\n");
  const headless = remove(item, ["parts", 0, "type"]);
  assert.equal(headless.text, "parts:\n  - color: x\n  - type: circle\n");
  assert.ok(sameData(parse(headless.text), headless.expected));
  const emptied = remove(item, ["parts", 1, "type"]);
  assert.equal(emptied.text, "parts:\n  - type: polygon  # shaft\n    color: x\n  - {}\n");
  assert.ok(sameData(parse(emptied.text), emptied.expected));
});

test("the first item makes its list: flow under a missing or empty key, block when asked", () => {
  const text = minimal("elements:\n  a:\n    type: pattern\n    pattern: radial\n    count: 4\n    skip:\n    color: color.fg\n    parts:\n      - { type: circle, radius: 1%r }\n");
  const index = new SpanIndex(text);
  const allow = insertItem(index, ["elements", "a", "lint", "allow"], 0, "safe-area");
  assert.ok(allow.text.includes("      - { type: circle, radius: 1%r }\n    lint: { allow: [safe-area] }\n"), allow.text);
  assert.ok(sameData(parse(allow.text), allow.expected));
  const skip = insertItem(index, ["elements", "a", "skip"], 0, 0);
  assert.ok(skip.text.includes("    skip: [0]\n"), skip.text);
  assert.ok(sameData(parse(skip.text), skip.expected));
  const block = insertItem(index, ["elements", "a", "skip"], 0, 0, { block: true });
  assert.ok(block.text.includes("    skip:\n      - 0\n    color: color.fg\n"), block.text);
  assert.ok(sameData(parse(block.text), block.expected));
  const made = insertItem(index, ["elements", "a", "lint", "allow"], 0, "safe-area", { block: true });
  assert.ok(made.text.includes("    lint:\n      allow:\n        - safe-area\n"), made.text);
  assert.ok(sameData(parse(made.text), made.expected));
  assert.throws(() => insertItem(index, ["elements", "a", "skip"], 1, 0), /has no items yet/);
});

test("a value inside a list item is set in place, a key added to it, and a whole item replaced", () => {
  const text = minimal("elements:\n  a:\n    type: pattern\n    pattern: radial\n    count: 4\n    color: color.fg\n    parts:\n      - type: circle\n        radius: 2%r\n      - { type: circle, radius: 1%r }\n");
  const index = new SpanIndex(text);
  const g = gate("face.yaml", text);
  const parts = ["elements", "a", "parts"];
  const inPlace = setValue(index, [...parts, 0, "radius"], "3%r");
  g.check(inPlace);
  assert.ok(inPlace.text.includes("      - type: circle\n        radius: 3%r\n"));
  const added = setValue(index, [...parts, 0, "at", "dy"], "10%r");
  g.check(added);
  assert.ok(added.text.includes("        radius: 2%r\n        at: { dy: 10%r }\n      - { type: circle, radius: 1%r }\n"), added.text);
  const flowAdded = setValue(index, [...parts, 1, "at", "dy"], "10%r");
  g.check(flowAdded);
  assert.ok(flowAdded.text.includes("      - { type: circle, radius: 1%r, at: { dy: 10%r } }\n"), flowAdded.text);
  const whole = setValue(index, [...parts, 1], new Map([["type", "circle"], ["radius", "4%r"]]));
  g.check(whole);
  assert.ok(whole.text.includes("      - { type: circle, radius: 4%r }\n"), whole.text);
  const target = setValue(index, ["build", "targets", 0], "fr955");
  g.check(target);
  assert.ok(target.text.includes("build: { targets: [fr955] }\n"));
  assert.throws(() => setValue(index, [...parts, 0], new Map([["type", "circle"]])), /block item/);
  assert.throws(() => setValue(index, [...parts, 2, "radius"], "1%r"), /not in the file/);
});

test("list edits refuse what they cannot do", () => {
  const index = new SpanIndex("a: [1, 2]\nb:\n  - - x\n    - y\nc: 1\n");
  assert.throws(() => insertItem(index, ["a"], 3, 0), /has 2 items/);
  assert.throws(() => insertItem(index, ["a"], -1, 0), /has 2 items/);
  assert.throws(() => removeItem(index, ["a"], 2), /no item 2/);
  assert.throws(() => moveItem(index, ["a"], 0, 2), /no item 2/);
  assert.throws(() => insertItem(index, ["c"], 0, 0), /not a list/);
  assert.throws(() => removeItem(index, ["d"], 0), /not in the file/);
  assert.throws(() => insertItem(index, ["b", 0], 0, "z"), /shares a line/);
  assert.equal(moveItem(index, ["a"], 1, 1).text, index.text);
});

test("an id-keyed part has a path and a span like any mapping entry, and a set on it patches its own line", () => {
  const text = minimal("elements:\n  a:\n    type: pattern\n    pattern: radial\n    count: 4\n    color: color.fg\n    parts:\n      tick:\n        type: line\n        at: { dy: -90%r }\n        to: { dy: -80%r }\n      dot: { type: circle, at: { dy: -76%r }, radius: 1%r }\n");
  const index = new SpanIndex(text);
  const tick = index.at(["elements", "a", "parts", "tick"]);
  assert.equal(tick.key.start.line, text.split("\n").findIndex((l) => l.includes("tick:")));
  assert.deepEqual(tick.path, ["elements", "a", "parts", "tick"]);
  assert.equal((at(index, ["elements", "a", "parts", "dot", "radius"]) as string), "1%r");
  const g = gate("face.yaml", text);
  const grown = setValue(index, ["elements", "a", "parts", "dot", "radius"], "2%r");
  g.check(grown);
  assert.ok(grown.text.includes("      dot: { type: circle, at: { dy: -76%r }, radius: 2%r }\n"), grown.text);
  assert.equal(changedBlocks(text, grown.text), 1);
  const moved = setValue(index, ["elements", "a", "parts", "tick", "to", "dy"], "-70%r");
  g.check(moved);
  assert.ok(moved.text.includes("        to: { dy: -70%r }\n"), moved.text);
  assert.equal(changedBlocks(text, moved.text), 1);
  // a part added by id is a new mapping entry, in the block's own style
  const added = setValue(index, ["elements", "a", "parts", "hub"], new Map<string, Data>([["type", "circle"], ["radius", "3%r"]]));
  g.check(added);
  assert.ok(added.text.includes("      dot: { type: circle, at: { dy: -76%r }, radius: 1%r }\n      hub: { type: circle, radius: 3%r }\n"), added.text);
});
