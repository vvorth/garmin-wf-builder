// The edit gate: a patch is accepted only when its text parses to what it
// intended and loads with no new error. Ported from tests/test_edit.py's
// refusals, with the slot that is added together with its element.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { REPO_ROOT } from "../src/devices/node.ts";
import { Gate, loadText } from "../src/edit/gate.ts";
import { addElement, DEFAULTS, patch as makePatch, setValue } from "../src/edit/patch.ts";
import { addSlot } from "../src/edit/slots.ts";
import { indexFor, parse, Refused, SpanIndex } from "../src/edit/spans.ts";
import { add, elementTypes } from "../src/edit/structure.ts";
import type { Data } from "../src/edit/yaml.ts";
import { installAssets, repoFileExists } from "../src/node.ts";

installAssets();

const SHAPES = "examples/features/shapes/face.yaml";
const shapesText = (): string => readFileSync(join(REPO_ROOT, SHAPES), "utf8");

function minimal(elements: string, prefix = ""): string {
  return "format: 2\n"
    + "face: { id: 9c1d5f30-6a72-4b18-8d4e-0f2a71c93b64, name: Edit, version: 1.0.0 }\n"
    + "build: { targets: [fenix8solar47mm] }\n"
    + "resources:\n  palette:\n    fg: \"#FFFFFF\"\n"
    + prefix + elements;
}

const at = (data: Data, ...path: string[]): Data => path.reduce((d, k) => (d as Map<string, Data>).get(k)!, data);

test("the gate refuses a patch that changes more than intended", () => {
  const text = shapesText();
  const patch = setValue(new SpanIndex(text), ["elements", "card", "at", "dy"], "-20%");
  // the same text claimed as a different change
  const wrong = makePatch(patch.text.replace("radius: 92%r", "radius: 91%r"), patch.expected, patch.what);
  assert.throws(() => new Gate(SHAPES, text, repoFileExists).check(wrong), (e: unknown) => e instanceof Refused && /more than intended/.test(e.message));
});

test("the gate refuses a patch that adds an error, naming the patch", () => {
  const text = shapesText();
  const patch = setValue(new SpanIndex(text), ["elements", "card", "at", "dy"], "lots");
  assert.throws(() => new Gate(SHAPES, text, repoFileExists).check(patch),
    (e: unknown) => e instanceof Refused && e.message.includes("set elements.card.at.dy"));
});

test("the gate refuses an edit that breaks a reference", () => {
  const text = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n");
  const patch = setValue(new SpanIndex(text), ["elements", "a", "color"], "color.nope");
  assert.throws(() => new Gate(SHAPES, text, repoFileExists).check(patch), Refused);
});

test("the gate ignores errors the text already had, and refuses a new one", () => {
  const broken = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.no\n"
    + "  b:\n    type: circle\n    radius: 5%r\n    color: color.fg\n");
  const gate = new Gate("scratch/face.yaml", broken, repoFileExists);
  assert.ok(gate.before.errors.length > 0);
  // A face that did not load may be patched while it adds no error.
  const after = gate.check(setValue(new SpanIndex(broken), ["elements", "b", "radius"], "6%r"));
  assert.ok(after.face === null && after.errors.length > 0);
  const worse = setValue(new SpanIndex(broken), ["elements", "b", "color"], "color.nope");
  assert.throws(() => gate.check(worse), (e: unknown) => e instanceof Refused && /nope/.test(e.message));
});

test("a load reuses the index and still sees a merge key", () => {
  // The index's own construction has merged a `<<` key out of its nodes, so such a text is parsed again.
  const merged = minimal("elements:\n  a: &a\n    type: circle\n    at: { dx: 10, dy: 10 }\n    radius: 5\n"
    + "    color: color.fg\n  b:\n    <<: *a\n    at: { dx: 20, dy: 20 }\n");
  const plain = merged.replace("    <<: *a\n", "    type: circle\n    radius: 5\n    color: color.fg\n");
  indexFor(merged);
  const a = loadText("scratch/face.yaml", merged, repoFileExists), b = loadText("scratch/face.yaml", plain, repoFileExists);
  assert.deepEqual(a.errors, []);
  assert.deepEqual(b.errors, []);
  const shape = (face: typeof a.face): [string, string][] => face!.walk().map((e) => [e.id, e.constructor.name]);
  assert.deepEqual(shape(a.face), shape(b.face));
});

test("diagnostics name the design, not a scratch file", () => {
  const loaded = loadText("my/face.yaml", minimal("elements:\n  a:\n    type: circle\n    color: color.no\n"), repoFileExists);
  assert.ok(loaded.errors.length > 0);
  assert.ok(loaded.errors.every((d) => d.span === null || d.span.path === "my/face.yaml"));
});

test("a new element of every default type loads", () => {
  const text = shapesText();
  for (const type of [...DEFAULTS.keys()].sort()) {
    const patch = addElement(new SpanIndex(text), type);
    new Gate(SHAPES, text, repoFileExists).check(patch);
    assert.equal(at(patch.expected, "elements", `new_${type}`, "color"), "color.dim", type);
  }
});

test("every type can be added", () => {
  const text = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n");
  for (const type of elementTypes().filter((t) => t !== "data" && t !== "hands")) {
    const patch = add(new SpanIndex(text), type, ["elements"], null, null, type === "graph" ? "steps" : null);
    new Gate(SHAPES, text, repoFileExists).check(patch);
    assert.equal(at(parse(patch.text), "elements", `new_${type}`, "type"), type);
  }
});

test("a data element can be added on a declared slot", () => {
  const text = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n",
    "config:\n  slots:\n    top: { default: steps, choices: any }\n");
  const patch = add(new SpanIndex(text), "data", ["elements"], null, null, "top");
  new Gate(SHAPES, text, repoFileExists).check(patch);
  assert.equal(at(parse(patch.text), "elements", "new_data", "slot"), "top");
});

test("a slot is added with a data element drawing it, and refused twice or for an unknown type", () => {
  const text = minimal("elements:\n  a:\n    type: circle\n    radius: 5%r\n    color: color.fg\n");
  const patch = addSlot(new SpanIndex(text), "top", "heart_rate");
  new Gate(SHAPES, text, repoFileExists).check(patch);
  const data = parse(patch.text);
  assert.equal(at(data, "config", "slots", "top", "default"), "heart_rate");
  assert.equal(at(data, "config", "slots", "top", "choices"), "any");
  assert.equal(at(data, "elements", "new_data", "slot"), "top");
  assert.ok(patch.text.includes("config:\n  slots:\n    top:\n      default: heart_rate\n"));
  assert.throws(() => addSlot(new SpanIndex(patch.text), "top", "steps"), (e: unknown) => e instanceof Refused && /already/.test(e.message));
  assert.throws(() => addSlot(new SpanIndex(patch.text), "other", "nope"),
    (e: unknown) => e instanceof Refused && /not a complication type/.test(e.message));
});
