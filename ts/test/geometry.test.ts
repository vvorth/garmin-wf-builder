// Pixel drags written back in the author's units, on the three
// verification devices. Ported from tests/test_edit.py; fonts are not baked
// here (the bake comes later), so a custom font measures at its declared size.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { DeviceDatabase } from "../src/devices/device.ts";
import { NodeDeviceFiles, REPO_ROOT } from "../src/devices/node.ts";
import { Gate, loadText } from "../src/edit/gate.ts";
import { candidates, move, pxPerUnit, resize, target, turn, View } from "../src/edit/geometry.ts";
import { setValue } from "../src/edit/patch.ts";
import { Refused, SpanIndex } from "../src/edit/spans.ts";
import type { Data } from "../src/edit/yaml.ts";
import type { BakedFont } from "../src/fonts/bmfont.ts";
import { NodeFontFiles } from "../src/fonts/node.ts";
import { Shape } from "../src/ir/model.ts";
import { installAssets, repoFileExists } from "../src/node.ts";
import { Box } from "../src/units.ts";

installAssets();

const db = new DeviceDatabase(NodeDeviceFiles.discover(), new NodeFontFiles());
const TARGETS = ["fenix8solar47mm", "fenix8solar51mm", "fr955"];
const SHAPES = "examples/features/shapes/face.yaml";
const ALIGN = "examples/features/align/face.yaml";
const read = (path: string): string => readFileSync(join(REPO_ROOT, path), "utf8");
const noBake = (): Map<string, BakedFont> => new Map();
const view = (path: string, text: string, device: string): View => new View(path, text, db.get(device), repoFileExists, noBake);
const refused = (pattern: RegExp) => (e: unknown): boolean => e instanceof Refused && pattern.test(e.message);
const at = (data: Data, path: readonly (string | number)[]): Data =>
  path.reduce<Data>((d, k) => (d as Map<string | number, Data>).get(k)!, data);

test("pixels per unit", () => {
  const screen = new Box(0, 0, 260, 280);
  assert.equal(pxPerUnit("px", "x", screen, 130), 1);
  assert.equal(pxPerUnit("%r", "x", screen, 130), 1.3);
  assert.equal(pxPerUnit("%", "y", screen, 130), 2.8);
  assert.equal(pxPerUnit("%", "minor", screen, 130), 2.6);
  assert.equal(pxPerUnit("pt", "x", screen, 130, 20), 20);
  assert.throws(() => pxPerUnit("pt", "x", screen, 130), refused(/pt/));
});

test("candidates run coarse to fine and stay within half a pixel", () => {
  assert.deepEqual(candidates(4 / 1.3, [10, 5, 1, 0.5, 0.1, 0.05, 0.01], 1.3), [3, 3.1, 3.08]);
  assert.deepEqual(candidates(0.5, [1], 1.0), [0]);
});

for (const device of TARGETS) {
  test(`a move lands on the dragged pixel, ${device}`, () => {
    const v = view(SHAPES, read(SHAPES), device);
    const gate = new Gate(SHAPES, v.index.text, repoFileExists);
    for (const element of v.face.walk()) {
      if (element.id === "chevron") continue; // a polygon: refused
      const before = v.placed(element.id);
      const converted = move(v, element.id, 3, -4);
      assert.ok(converted.landed, `${element.id}: ${converted.patch.what}`);
      const loaded = gate.check(converted.patch);
      const after = v.placed(element.id, v.place(loaded));
      assert.deepEqual(after.center, [before.center[0] + 3, before.center[1] - 4]);
    }
  });

  test(`a resize lands on the dragged pixel, ${device}`, () => {
    const v = view(SHAPES, read(SHAPES), device);
    let done = 0;
    for (const [element, key] of [["card", ["size", "width"]], ["card", ["size", "height"]], ["outer_arc", ["radius"]],
      ["outer_arc", ["thickness"]], ["dot", ["radius"]]] as const) {
      if (v.index.get([...v.authorPath(element), ...key]) === undefined) continue;
      const converted = resize(v, element, key, -2);
      assert.ok(converted.landed, `${element} ${key.join(".")}: ${converted.patch.what}`);
      done++;
    }
    assert.ok(done >= 4);
  });

  test(`a polar move rewrites angle and radius, ${device}`, () => {
    const v = view(ALIGN, read(ALIGN), device);
    for (const element of ["ne_card", "se_card", "nw_card", "top_accent"]) {
      const converted = move(v, element, 4, 3);
      assert.ok(converted.landed, element);
      const data = at(new SpanIndex(converted.patch.text).data, [...v.authorPath(element), "at"]) as Map<string, Data>;
      assert.deepEqual(new Set(data.keys()), new Set(["anchor", "angle", "radius"]));
      assert.ok((data.get("angle") as string).endsWith("deg") && (data.get("radius") as string).endsWith("%r"));
    }
  });

  test(`a line's ends move apart and land, ${device}`, () => {
    const v = view(SHAPES, read(SHAPES), device);
    const lines = v.face.walk().filter((e) => e instanceof Shape && e.shape === "line").map((e) => e.id);
    assert.ok(lines.length > 0);
    for (const line of lines) {
      const before = v.placed(line) as unknown as { center: number[]; end: number[] };
      const start = move(v, line, 4, -3, "auto", "at");
      assert.ok(start.landed);
      let placed = v.placed(line, v.place(loadText(SHAPES, start.patch.text, repoFileExists))) as unknown as typeof before;
      assert.deepEqual(placed.center, [before.center[0]! + 4, before.center[1]! - 3]);
      assert.deepEqual(placed.end, before.end);
      const end = move(v, line, -5, 2, "auto", "to");
      assert.ok(end.landed);
      placed = v.placed(line, v.place(loadText(SHAPES, end.patch.text, repoFileExists))) as unknown as typeof before;
      assert.deepEqual(placed.end, [before.end[0]! - 5, before.end[1]! + 2]);
      assert.deepEqual(placed.center, before.center);
    }
    assert.throws(() => move(v, "card", 1, 1, "auto", "to"), refused(/not a line/));
  });

  test(`an arc's angles turn in the author's unit, ${device}`, () => {
    const v = view(SHAPES, read(SHAPES), device);
    const before = v.placed("outer_arc") as unknown as { sweep: number };
    const turned = turn(v, "outer_arc", "sweep", before.sweep - 23);
    assert.ok(turned.landed);
    assert.equal(at(new SpanIndex(turned.patch.text).data, ["elements", "outer_arc", "sweep"]), `${before.sweep - 23}deg`);
    const rotated = turn(v, "outer_arc", "start_angle", 33.3);
    assert.ok(rotated.landed);
    assert.equal(at(new SpanIndex(rotated.patch.text).data, ["elements", "outer_arc", "start_angle"]), "33deg");
    assert.throws(() => turn(v, "card", "start_angle", 10), refused(/no start_angle/));
    assert.throws(() => turn(v, "outer_arc", "radius", 10), refused(/not start_angle or sweep/));
  });
}

test("a move keeps the author's unit", () => {
  const v = view(SHAPES, read(SHAPES), "fenix8solar47mm");
  assert.ok(move(v, "card", 0, 5).patch.text.includes("at: { anchor: center, dy: -20% }"));
  assert.ok(move(v, "outer_arc", 7, 0).patch.text.includes("at: { anchor: center, dx: 5.5%r }"));
});

test("an extent cannot shrink below one pixel", () => {
  const v = view(ALIGN, read(ALIGN), "fr955");
  assert.equal((v.placed("ne_dot") as unknown as { radius: number }).radius, 1);
  assert.throws(() => resize(v, "ne_dot", ["radius"], -4), refused(/smaller than 1 px/));
  assert.throws(() => resize(v, "ne_dot", ["radius"], -1), refused(/smaller than 1 px/));
  assert.ok(resize(v, "ne_dot", ["radius"], 2).landed);
});

test("a polygon move is refused, and the static block is not an element", () => {
  assert.throws(() => move(view(SHAPES, read(SHAPES), "fenix8solar47mm"), "chevron", 1, 1), refused(/polygon/));
  assert.throws(() => move(view(ALIGN, read(ALIGN), "fenix8solar47mm"), "static", 3, 0), refused(/block/));
});

test("a group and its child move", () => {
  const rings = "examples/features/rings/face.yaml";
  for (const device of TARGETS) {
    const v = view(rings, read(rings), device);
    for (const element of ["heart_rate", "heart_value"]) assert.ok(move(v, element, -2, 3).landed, `${device} ${element}`);
  }
});

const withFr955Override = (text: string): string =>
  setValue(new SpanIndex(text), ["elements", "card", "overrides", "fr955", "at", "dy"], "-17%").text;

test("the target is the most specific source", () => {
  const index = new SpanIndex(withFr955Override(read(SHAPES)));
  const card = ["elements", "card"];
  const fr955 = db.get("fr955"), fenix = db.get("fenix8solar47mm");
  assert.deepEqual(target(index, card, ["at", "dy"], fr955), [...card, "overrides", "fr955", "at", "dy"]);
  assert.deepEqual(target(index, card, ["at", "dy"], fenix), [...card, "at", "dy"]);
  assert.deepEqual(target(index, card, ["at", "dx"], fr955), [...card, "at", "dx"]);
  assert.deepEqual(target(index, card, ["at", "dy"], fr955, "all"), [...card, "at", "dy"]);
  assert.deepEqual(target(index, card, ["at", "dy"], fenix, "shape"), [...card, "overrides", "shape:round", "at", "dy"]);
});

const cardCenter = (text: string, device: string): number[] => view(SHAPES, text, device).placed("card").center;

test("a drag moves exactly the devices that read the patched key", () => {
  const text = withFr955Override(read(SHAPES));
  for (const device of TARGETS) {
    const patch = move(view(SHAPES, text, device), "card", 0, 6).patch;
    const moved = TARGETS.filter((d) => JSON.stringify(cardCenter(patch.text, d)) !== JSON.stringify(cardCenter(text, d)));
    assert.deepEqual(moved, device === "fr955" ? ["fr955"] : ["fenix8solar47mm", "fenix8solar51mm"]);
  }
});

test("a this-device drag creates the override", () => {
  const text = read(SHAPES);
  const converted = move(view(SHAPES, text, "fenix8solar51mm"), "card", 0, 6, "device");
  assert.ok(converted.landed);
  const card = at(converted.patch.expected, ["elements", "card"]) as Map<string, Data>;
  assert.deepEqual([...(card.get("at") as Map<string, Data>)], [["anchor", "center"], ["dy", "-22%"]]);
  assert.deepEqual([...(card.get("overrides") as Map<string, Data>).keys()], ["fenix8solar51mm"]);
  const moved = TARGETS.filter((d) => JSON.stringify(cardCenter(converted.patch.text, d)) !== JSON.stringify(cardCenter(text, d)));
  assert.deepEqual(moved, ["fenix8solar51mm"]);
});
