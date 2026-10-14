// The inspector and the Face panel through the worker's document, the
// vocabulary, and the server the worker asks for what only it has.
import assert from "node:assert/strict";
import { readdirSync, statSync } from "node:fs";
import { request as httpRequest } from "node:http";
import { join } from "node:path";
import { test } from "node:test";
import { DeviceDatabase } from "../src/devices/device.ts";
import { MemoryDeviceFiles } from "../src/devices/files.ts";
import { indexFor, Refused } from "../src/edit/spans.ts";
import { ICON_FONT } from "../src/emit/resources.ts";
import { NodeFontFiles } from "../src/fonts/node.ts";
import { readFontFile } from "../src/node.ts";
import { decodePng } from "../src/png.ts";
import * as starters from "../src/starters.ts";
import { bundle, missing } from "../src/studio/bundle.ts";
import { type Document, StaleVersion, Studio } from "../src/studio/document.ts";
import { elementSchema, globalsOf, inspect, vocabulary } from "../src/studio/inspect.ts";
import { allowHostList, digest, start } from "../src/studio/server.ts";
import type { EditContext, Inspect } from "../src/studio/protocol.ts";
import { MemoryBackend, Store } from "../src/studio/store.ts";
import { CHIVO, Client, dataOf, db, DYNALIGHT, newStudio, read, readText, ROOT, STYLES } from "./studio-client.ts";

const SHAPES = "examples/features/shapes/face.yaml";
const make = (studio: Studio, template = "minimal"): Document => studio.create(bundle("T", starters.instantiate(template, "T")), "new");
const elementPath = (doc: Document, id: string): (string | number)[] => [...indexFor(doc.text).elements().find((e) => e.name === id)!.path];
const fieldsOf = (result: Inspect): Record<string, any> => Object.fromEntries(result.fields.map((f) => [f.key, f]));

function faces(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(join(ROOT, dir)).sort()) {
    const path = `${dir}/${name}`;
    if (statSync(join(ROOT, path)).isDirectory()) faces(path, out);
    else if (name === "face.yaml" && !path.includes("/dashboard/")) out.push(path);
  }
  return out;
}

// -- the inspector --

test("every key an element has is a field", () => {
  const fr955 = db.get("fr955");
  for (const path of faces("examples")) {
    const text = readText(path);
    const index = indexFor(text);
    for (const entry of index.elements()) {
      const result = inspect(text, entry.path, fr955);
      assert.deepEqual(result["unknown"], [], `${path}: ${entry.name}`);
      const shown = new Set([...(result["fields"] as any[]).map((f) => f.key), "children"]);
      let data: any = index.data;
      for (const step of entry.path) data = data.get(step);
      for (const key of data.keys()) assert.ok(shown.has(key), `${path}: ${entry.name}.${key}`);
    }
  }
});

test("a shape offers its own keys only", () => {
  const text = readText(SHAPES);
  const byType: Record<string, any> = {};
  for (const entry of indexFor(text).elements()) {
    const result = inspect(text, entry.path, null);
    byType[result["type"] as string] ??= fieldsOf(result);
  }
  const { circle, rectangle, arc } = byType;
  assert.ok("radius" in circle && !("size" in circle) && !("points" in circle));
  assert.ok("size" in rectangle && "corner_radius" in rectangle && !("radius" in rectangle));
  assert.ok("start_angle" in arc && !("start_angle" in rectangle));
});

test("widgets follow the schema", () => {
  const text = starters.instantiate("minimal", "W");
  const clock = indexFor(text).elements().find((e) => e.name === "clock")!.path;
  const f = fieldsOf(inspect(text, clock, db.get("fr955")));
  assert.deepEqual(Object.fromEntries(["type", "text", "font", "color", "align", "visible", "units", "z"].map((k) => [k, f[k].widget])), {
    type: "readonly", text: "template", font: "font", color: "color", align: "align", visible: "expression", units: "enum", z: "number",
  });
  assert.equal(f["at"].widget, "object");
  const at = Object.fromEntries(f["at"].children.map((c: any) => [c.key, c.widget]));
  assert.equal(at["dy"], "length");
  assert.equal(at["angle"], "angle");
  assert.ok(f["text"].required && f["text"].present);
  assert.ok(!f["visible"].present);
  for (const t of ["text", "circle", "gauge", "group", "hands"]) assert.ok(elementSchema(t), t);
});

test("a pattern's step_angle is an angle and its step a {dx, dy} object, whatever the value; a graph's series is a picker", () => {
  const patterns = readText("examples/features/patterns/face.yaml");
  const pathOf = (text: string, id: string): (string | number)[] => [...indexFor(text).elements().find((e) => e.name === id)!.path];
  const f = (text: string, id: string): Record<string, any> => fieldsOf(inspect(text, pathOf(text, id), null));

  const hourTicks = f(patterns, "hour_ticks");
  assert.equal(hourTicks["step_angle"].widget, "angle");
  assert.equal(hourTicks["step_angle"].value, "30deg");
  assert.equal(hourTicks["step"].widget, "object");
  assert.ok(!hourTicks["step"].present);

  const dxStep = f(patterns, "twelve")["step"];
  assert.equal(dxStep.widget, "object");
  assert.deepEqual(Object.fromEntries(dxStep.children.map((c: any) => [c.key, c.widget])), { dx: "length", dy: "length" });

  const noStep = f(patterns, "minute_ticks")["step_angle"];
  assert.equal(noStep.widget, "angle");
  assert.ok(!noStep.present);

  const graph = readText("examples/features/graph/face.yaml");
  const series = f(graph, "hr_graph")["series"];
  assert.equal(series.widget, "enum");
  assert.ok(series.enum.includes("heart_rate") && series.enum.includes("steps"));
  assert.equal(series.value, "heart_rate");
});

test("an icon written as {codepoint} keeps the icon widget with the object as its value, on an element and on a slot choice", () => {
  // A codepoint is an object in the format; it used to fall to the yaml widget, and a slot choice's used to read as no icon.
  const text = starters.instantiate("minimal", "I") + `
  glyph:
    type: icon
    icon: { codepoint: "U+E241" }
    size: 10%r
    at: { anchor: center }
    color: color.dim
`;
  const pathOf = (id: string): (string | number)[] => [...indexFor(text).elements().find((e) => e.name === id)!.path];
  const icon = fieldsOf(inspect(text, pathOf("glyph"), null))["icon"];
  assert.equal(icon.widget, "icon");
  assert.deepEqual(icon.value, { codepoint: "U+E241" });
  const named = fieldsOf(inspect(text.replace('{ codepoint: "U+E241" }', "heart"), pathOf("glyph"), null))["icon"];
  assert.equal(named.widget, "icon");
  assert.equal(named.value, "heart");

  const slots = text + `
config:
  slots:
    top:
      default: steps
      choices: [steps, { type: heart_rate, icon: { codepoint: "U+F0004" } }, { type: calories, icon: fire }]
`;
  const top = (globalsOf(slots, db) as any).slots.find((s: any) => s.name === "top");
  assert.deepEqual(top.choices, [
    { type: "steps", icon: null },
    { type: "heart_rate", icon: { codepoint: "U+F0004" } },
    { type: "calories", icon: "fire" },
  ]);
});

test("a text element's curve: is a small object widget, angled or radial, not the yaml fallback", () => {
  const text = readText("examples/features/vector-text/face.yaml");
  const pathOf = (id: string): (string | number)[] => [...indexFor(text).elements().find((e) => e.name === id)!.path];
  const f = (id: string): Record<string, any> => fieldsOf(inspect(text, pathOf(id), null));

  const angled = f("solar_badge")["curve"];
  assert.equal(angled.widget, "object");
  assert.deepEqual(Object.fromEntries(angled.children.map((c: any) => [c.key, [c.widget, c.value]])), {
    style: ["enum", "angled"], angle: ["angle", "35deg"], radius: ["length", null], direction: ["enum", null],
  });

  const radial = f("wordmark")["curve"];
  assert.deepEqual(Object.fromEntries(radial.children.map((c: any) => [c.key, [c.widget, c.value]])), {
    style: ["enum", "radial"], angle: ["angle", "165deg"], radius: ["length", "60%r"], direction: ["enum", "counter_clockwise"],
  });

  // an element with no curve: still offers the key, each child addable on its own
  const minimal = starters.instantiate("minimal", "C");
  const clock = [...indexFor(minimal).elements().find((e) => e.name === "clock")!.path];
  const plain = fieldsOf(inspect(minimal, clock, null))["curve"];
  assert.equal(plain.widget, "object");
  assert.ok(plain.children.every((c: any) => c.value === null));
});

test("on_hold on a data element offers auto only", () => {
  const pathOf = (text: string, id: string): (string | number)[] => [...indexFor(text).elements().find((e) => e.name === id)!.path];
  const text = starters.instantiate("minimal", "T").replace("elements:\n", "config:\n  slots:\n    top:\n      default: steps\n      choices: any\nelements:\n  reading:\n    type: data\n    slot: top\n    at: { anchor: center }\n    color: color.text\n");
  const f = (id: string): Record<string, any> => fieldsOf(inspect(text, pathOf(text, id), null));
  assert.equal(f("reading")["on_hold"].widget, "complication");
  assert.deepEqual(f("reading")["on_hold"].enum, ["auto"]);
  assert.equal(f("clock")["on_hold"].widget, "complication");
  assert.deepEqual(f("clock")["on_hold"].enum, vocabulary()["complications"]);
  assert.ok((f("clock")["on_hold"].enum as string[]).length > 10);
});

test("the inspector reports the overrides the device reads", () => {
  const text = starters.instantiate("minimal", "O").replace("    at: { anchor: center }\n    color: color.text\n",
    '    at: { anchor: center }\n    color: color.text\n    overrides: { fr955: { at: { anchor: center, dy: 2px } }, "shape:round": { at: { anchor: center, dx: 1px } } }\n');
  const clock = indexFor(text).elements().find((e) => e.name === "clock")!.path;
  const on = (id: string): any => JSON.parse(JSON.stringify(inspect(text, clock, db.get(id))["overrides"], (_, v) => (v instanceof Map ? Object.fromEntries(v) : v)));
  assert.deepEqual(on("fr955"), { device: { selector: "fr955", keys: { at: { anchor: "center", dy: "2px" } } }, shape: { selector: "shape:round", keys: { at: { anchor: "center", dx: "1px" } } } });
  assert.deepEqual(Object.keys(on("fenix8solar47mm")), ["shape"]);
});

test("the inspector reports the display override the device reads, and names the device's display class", () => {
  const text = starters.instantiate("minimal", "O").replace("    at: { anchor: center }\n    color: color.text\n",
    '    at: { anchor: center }\n    color: color.text\n    overrides: { "display:amoled": { at: { anchor: center, dy: 2px } }, "display:mip": { at: { anchor: center, dx: 1px } } }\n');
  const clock = indexFor(text).elements().find((e) => e.name === "clock")!.path;
  const on = (id: string): any => JSON.parse(JSON.stringify(inspect(text, clock, db.get(id)), (_, v) => (v instanceof Map ? Object.fromEntries(v) : v)));
  assert.deepEqual(on("fenix847mm").overrides, { display: { selector: "display:amoled", keys: { at: { anchor: "center", dy: "2px" } } } });
  assert.deepEqual(on("fr955").overrides, { display: { selector: "display:mip", keys: { at: { anchor: "center", dx: "1px" } } } });
  assert.equal(on("fenix847mm").display, "amoled");
  assert.equal(on("fr955").display, "mip");
  assert.equal(inspect(text, clock, null)["display"], null);
});

test("a non-geometry override is visible read-only, regardless of the device viewed; a geometry one is not duplicated there", () => {
  const text = starters.instantiate("minimal", "V").replace("    at: { anchor: center }\n    color: color.text\n",
    '    at: { anchor: center }\n    color: color.text\n    overrides: { fr955: { at: { anchor: center, dy: 2px }, color: color.off, visible: false }, "shape:round": { track_color: color.off } }\n');
  const clock = indexFor(text).elements().find((e) => e.name === "clock")!.path;
  const overridden = (id: string | null): any => JSON.parse(JSON.stringify(
    inspect(text, clock, id ? db.get(id) : null)["overridden"], (_, v) => (v instanceof Map ? Object.fromEntries(v) : v)));
  const onFr955 = overridden("fr955");
  assert.deepEqual(onFr955.find((o: any) => o.selector === "fr955").keys, { color: "color.off", visible: false });
  assert.deepEqual(onFr955.find((o: any) => o.selector === "shape:round").keys, { track_color: "color.off" });
  // the same, regardless of which device (or none) is being viewed
  assert.deepEqual(overridden(null), onFr955);
  assert.deepEqual(overridden("fenix8solar47mm"), onFr955);
});

test("a pattern's parts are summarised with their lines beside the parts field; other elements have no summary", () => {
  const patterns = readText("examples/features/patterns/face.yaml");
  const pathOf = (text: string, id: string): (string | number)[] => [...indexFor(text).elements().find((e) => e.name === id)!.path];
  const hourTicks = inspect(patterns, pathOf(patterns, "hour_ticks"), null);
  assert.deepEqual((hourTicks["parts"] as any).shapes, ["rectangle"]);
  assert.equal((hourTicks["parts"] as any).count, 1);
  assert.ok((hourTicks["parts"] as any).line < (hourTicks["parts"] as any).end);
  // the field itself is the two-shape choice, the written mapping its chosen branch
  const partsField = (hourTicks["fields"] as any[]).find((f) => f.key === "parts");
  assert.deepEqual([partsField.kind, partsField.chosen, partsField.branches[0].kind], ["choice", 0, "object"]);

  const clock = starters.instantiate("minimal", "P");
  const text = inspect(clock, indexFor(clock).elements().find((e) => e.name === "clock")!.path, null);
  assert.equal(text["parts"], null);
});

// -- the field tree --

const AOD = "examples/features/aod/face.yaml";
const pathOf = (text: string, id: string): (string | number)[] => [...indexFor(text).elements().find((e) => e.name === id)!.path];
const treeOf = (text: string, id: string, device: string | null = null, context?: any): Record<string, any> =>
  fieldsOf(inspect(text, pathOf(text, id), device ? db.get(device) : null, context));
const child = (field: any, key: string): any => field.children.find((c: any) => c.key === key);
const keysOf = (fields: any[]): string[] => fields.map((f) => f.key);

/** Every field of the tree, depth first. */
function walk(fields: any[], out: any[] = []): any[] {
  for (const f of fields) {
    out.push(f);
    walk([...(f.children ?? []), ...(f.items ?? []), ...(f.branches ?? []), ...(f.item ? [f.item] : [])], out);
  }
  return out;
}

test("a field is a tree: an object's children, a list's items, a choice's branches with the chosen one", () => {
  const aod = readText(AOD);
  const clock = treeOf(aod, "clock");
  assert.equal(clock["at"].kind, "object");
  assert.deepEqual(keysOf(clock["at"].children), ["anchor", "dx", "dy", "angle", "radius"]);
  assert.deepEqual([child(clock["at"], "anchor").kind, child(clock["at"], "anchor").widget], ["scalar", "enum"]);
  assert.equal(clock["color"].kind, "scalar");
  // the aod: block is an object of the kind's restyling keys; its outline is a choice, written as the {color, width} branch
  assert.equal(clock["aod"].kind, "object");
  assert.deepEqual(keysOf(clock["aod"].children), ["color", "font", "text", "outline", "visible", "dim"]);
  const outline = child(clock["aod"], "outline");
  assert.equal(outline.kind, "choice");
  assert.equal(outline.chosen, 1);
  assert.deepEqual(outline.branches.map((b: any) => [b.kind, b.widget]), [["scalar", "enum"], ["object", "object"]]);
  assert.deepEqual(outline.branches[0].enum, ["none"]);
  assert.deepEqual(keysOf(outline.branches[1].children), ["color", "width"]);
  assert.deepEqual(outline.path, ["aod", "outline"]);
  assert.deepEqual(outline.branches[1].path, ["aod", "outline"]);
  assert.equal(child(outline.branches[1], "width").value, 2);
  // a choice nothing is written for: no branch chosen
  assert.equal(clock["absent"].kind, "choice");
  assert.equal(clock["absent"].chosen, null);
  assert.equal(clock["absent"].branches.length, 3);
  assert.equal(clock["absent"].widget, "enum", "a choice's widget is its first branch's while nothing is written");
  // aod visible: a boolean or an expression; the showcase's absent: {text: "--"} picks the text branch
  const dateText = treeOf(aod, "date_text");
  const visible = child(dateText["aod"], "visible");
  assert.equal(visible.kind, "choice");
  assert.equal(visible.chosen, 0);
  assert.deepEqual(visible.branches.map((b: any) => b.widget), ["bool", "expression"]);
  assert.equal(visible.widget, "bool", "a choice's widget is its chosen branch's");
  const register = treeOf(readText("examples/showcase/face.yaml"), "left_register");
  assert.equal(register["absent"].kind, "choice");
  assert.equal(register["absent"].chosen, 1);
  assert.deepEqual(register["absent"].value, { text: "--" });
  assert.deepEqual(keysOf(register["absent"].branches[1].children), ["text"]);
  // a list: lint.allow, one item present, and the template a new item takes
  const allow = child(dateText["lint"], "allow");
  assert.equal(allow.kind, "list");
  assert.equal(allow.items.length, 1);
  assert.deepEqual([allow.items[0].path, allow.items[0].value, allow.items[0].kind], [["lint", "allow", 0], "aod-unreachable", "scalar"]);
  assert.deepEqual([allow.item.path, allow.item.kind, allow.item.widget, allow.item.present], [["lint", "allow", 1], "scalar", "text", false]);
  // a graph's range: one of {samples} and {duration}, chosen by the key written
  const graph = treeOf(readText("examples/features/graph/face.yaml"), "hr_graph");
  assert.equal(graph["range"].kind, "choice");
  assert.equal(graph["range"].chosen, 1);
  assert.deepEqual(graph["range"].branches.map((b: any) => keysOf(b.children)), [["samples"], ["duration"]]);
  // a key the schema knows is never raw, and nothing in the examples is cut short
  for (const path of faces("examples")) {
    const text = readText(path);
    for (const entry of indexFor(text).elements()) {
      for (const f of walk(inspect(text, entry.path, null).fields)) {
        assert.ok(f.kind !== "scalar" || f.widget !== "yaml" || !f.present || typeof f.value === "object", `${path}: ${entry.name}.${f.path.join(".")} is raw`);
        assert.ok(!f.truncated, `${path}: ${entry.name}.${f.path.join(".")} is cut short`);
      }
    }
  }
});

test("a pattern's parts are an id-keyed mapping of part objects, each with its own fields; the list form is the other branch", () => {
  const showcase = readText("examples/showcase/face.yaml");
  const numerals = treeOf(showcase, "hour_numerals");
  const parts = numerals["parts"];
  assert.deepEqual([parts.kind, parts.chosen, parts.branches.map((b: any) => b.kind)], ["choice", 0, ["object", "list"]]);
  const mapping = parts.branches[0];
  assert.equal(mapping.children.length, 1);
  const part = mapping.children[0];
  assert.deepEqual([part.kind, part.path], ["object", ["parts", "numeral"]]);
  assert.ok(keysOf(part.children).includes("type") && keysOf(part.children).includes("points") && keysOf(part.children).includes("text"));
  assert.deepEqual([child(part, "type").widget, child(part, "type").value], ["enum", "text"]);
  assert.equal(child(part, "text").widget, "template");
  assert.deepEqual(child(part, "at").children.map((c: any) => [c.key, c.widget]), [["dx", "length"], ["dy", "length"], ["angle", "angle"], ["radius", "length"]]);
  // a new part is a new key: the template's own path is the empty id
  assert.equal(mapping.item.kind, "object");
  assert.deepEqual(mapping.item.path, ["parts", ""]);
  // a polygon part's points: a list of positions under the part's id
  const patterns = readText("examples/features/patterns/face.yaml");
  const polygon = treeOf(patterns, "diagonals")["parts"].branches[0];
  const points = child(child(polygon, "triangle"), "points");
  assert.equal(points.kind, "list");
  assert.ok(points.items.length >= 3);
  assert.deepEqual(points.items[0].path, ["parts", "triangle", "points", 0]);
  assert.equal(child(points.items[0], "dy").widget, "length");
  // the read-only summary stays for now
  assert.equal(inspect(showcase, pathOf(showcase, "hour_numerals"), null).parts!.count, 1);
});

test("overrides are an object keyed by selector, each the keys an override may patch, with a template for a new selector", () => {
  const text = starters.instantiate("minimal", "O").replace("    at: { anchor: center }\n    color: color.text\n",
    '    at: { anchor: center }\n    color: color.text\n    overrides: { fr955: { at: { dy: 2px } }, "shape:round": { color: color.dim } }\n');
  const clock = treeOf(text, "clock", "fr955");
  const overrides = clock["overrides"];
  assert.equal(overrides.kind, "object");
  assert.deepEqual(keysOf(overrides.children), ["fr955", "shape:round"]);
  const fr955 = child(overrides, "fr955");
  assert.deepEqual([fr955.kind, fr955.path], ["object", ["overrides", "fr955"]]);
  assert.deepEqual(keysOf(fr955.children), ["at", "size", "radius", "align", "color", "track_color", "visible"]);
  assert.equal(child(child(fr955, "at"), "dy").value, "2px");
  assert.deepEqual(child(child(fr955, "at"), "dy").path, ["overrides", "fr955", "at", "dy"]);
  assert.equal(child(child(overrides, "shape:round"), "color").value, "color.dim");
  assert.deepEqual([overrides.item.kind, overrides.item.path], ["object", ["overrides", ""]]);
  assert.deepEqual(keysOf(overrides.item.children), keysOf(fr955.children));
  // an element with none still offers the key, with no children and the template
  const plain = treeOf(starters.instantiate("minimal", "P"), "clock")["overrides"];
  assert.deepEqual([plain.kind, plain.present, plain.children], ["object", false, []]);
  assert.equal(plain.item.kind, "object");
});

// -- effective values --

const effective = (field: any): any => field.effective;

test("awake, a field reads the most specific override the viewed device has, else the element's own key", () => {
  const text = starters.instantiate("minimal", "E").replace("    at: { anchor: center }\n    color: color.text\n",
    '    at: { anchor: center }\n    color: color.text\n    overrides: { fr955: { at: { dy: 2px }, color: color.dim }, "shape:round": { at: { dx: 1px } } }\n');
  const onFr955 = treeOf(text, "clock", "fr955");
  assert.deepEqual(effective(child(onFr955["at"], "dy")), { value: "2px", from: "override", selector: "fr955" });
  assert.deepEqual(effective(child(onFr955["at"], "dx")), { value: "1px", from: "override", selector: "shape:round" });
  assert.deepEqual(effective(child(onFr955["at"], "anchor")), { value: "center", from: "own" });
  assert.deepEqual(effective(onFr955["at"]), { value: { anchor: "center", dx: "1px", dy: "2px" }, from: "override", selector: "fr955" }, "a mapping merges, most specific last");
  assert.deepEqual(effective(onFr955["color"]), { value: "color.dim", from: "override", selector: "fr955" });
  assert.deepEqual(effective(onFr955["font"]), { value: "FONT_NUMBER_HOT", from: "own" });
  assert.deepEqual(effective(onFr955["visible"]), { value: null, from: "absent" });
  const onFenix = treeOf(text, "clock", "fenix8solar47mm");
  assert.deepEqual(effective(child(onFenix["at"], "dy")), { value: null, from: "absent" });
  assert.deepEqual(effective(child(onFenix["at"], "dx")), { value: "1px", from: "override", selector: "shape:round" });
  assert.deepEqual(effective(onFenix["color"]), { value: "color.text", from: "own" });
  // no device viewed: the element's own keys
  assert.deepEqual(effective(treeOf(text, "clock")["color"]), { value: "color.text", from: "own" });
  // the asleep frame reads as the awake one
  assert.deepEqual(effective(treeOf(text, "clock", "fr955", { frame: "asleep", style: null })["color"]), { value: "color.dim", from: "override", selector: "fr955" });
});

test("in the AOD frame a field reads the always-on cascade: the element's aod:, the nearest group's, defaults:, else the awake value", () => {
  const aod = readText(AOD);
  const AOD_FRAME: EditContext = { frame: "aod", style: null };
  const on = (id: string): Record<string, any> => treeOf(aod, id, "fenix847mm", AOD_FRAME);
  const clock = on("clock");
  assert.deepEqual(effective(clock["color"]), { value: "color.black", from: "aod" });
  assert.deepEqual(effective(clock["text"]), { value: "{time.clock:%H %M}", from: "aod" });
  assert.deepEqual(effective(clock["outline"]), { value: { width: 2, color: "color.dim" }, from: "aod" });
  assert.deepEqual(effective(clock["font"]), { value: "FONT_NUMBER_MEDIUM", from: "own" }, "a key the block leaves alone keeps its awake value");
  assert.deepEqual(effective(child(clock["aod"], "dim")), { value: 1, from: "aod" });
  assert.deepEqual(effective(clock["visible"]), { value: true, from: "aod" }, "writing the block draws the element");
  const dot = on("accent_dot");
  assert.deepEqual(effective(child(dot["aod"], "dim")), { value: 0.6, from: "defaults" });
  assert.deepEqual(effective(dot["filled"]), { value: false, from: "aod" });
  assert.deepEqual(effective(dot["thickness"]), { value: "2px", from: "aod" });
  assert.deepEqual(effective(dot["color"]), { value: "color.accent", from: "own" });
  const bezel = on("bezel_ring");
  assert.deepEqual(effective(bezel["visible"]), { value: false, from: "defaults" }, "nothing in its ancestry mentions aod:");
  assert.deepEqual(effective(bezel["color"]), { value: "color.gray", from: "own" });
  assert.deepEqual(effective(child(bezel["aod"], "visible")), { value: false, from: "defaults" });
  // a group's visible: false is sticky: the child's own aod: {visible: true} cannot undo it
  const dateText = on("date_text");
  assert.deepEqual(effective(dateText["visible"]), { value: false, from: "group", group: "info" });
  assert.deepEqual(effective(child(dateText["aod"], "visible")), { value: false, from: "group", group: "info" });
  const ring = on("battery_ring");
  assert.deepEqual(effective(ring["thickness"]), { value: "1%r", from: "aod" });
  assert.deepEqual(effective(ring["track_color"]), { value: "color.dim", from: "own" });
  // awake, the same keys read the awake design
  assert.deepEqual(effective(treeOf(aod, "clock", "fenix847mm")["color"]), { value: "color.white", from: "own" });
  // the context is echoed; awake and no style when none is given
  assert.deepEqual(inspect(aod, pathOf(aod, "clock"), db.get("fenix847mm"), AOD_FRAME).context, AOD_FRAME);
  assert.deepEqual(inspect(aod, pathOf(aod, "clock"), null).context, { frame: "awake", style: null });
});

test("a group's aod: restyles the elements below it, key by key", () => {
  const text = starters.instantiate("minimal", "G").replace("elements:\n", "elements:\n  info:\n    type: group\n    aod: { color: color.dim, dim: 0.5 }\n    children:\n      label:\n        type: text\n        text: Hi\n        font: FONT_SMALL\n        at: { anchor: center, dy: -30%r }\n        color: color.text\n");
  const label = treeOf(text, "label", "fr955", { frame: "aod", style: null });
  assert.deepEqual(effective(label["color"]), { value: "color.dim", from: "group", group: "info" });
  assert.deepEqual(effective(child(label["aod"], "dim")), { value: 0.5, from: "group", group: "info" });
  assert.deepEqual(effective(label["visible"]), { value: true, from: "group", group: "info" });
  assert.deepEqual(effective(label["font"]), { value: "FONT_SMALL", from: "own" });
  // the group itself: its own block
  const info = treeOf(text, "info", "fr955", { frame: "aod", style: null });
  assert.deepEqual(effective(child(info["aod"], "dim")), { value: 0.5, from: "aod" });
  assert.deepEqual(effective(info["visible"]), { value: true, from: "aod" });
});

test("aod_keys lists what the kind may restyle in its aod: block", () => {
  const aod = readText(AOD);
  const keys = (id: string): string[] => inspect(aod, pathOf(aod, id), null).aod_keys;
  assert.deepEqual(keys("clock"), ["color", "font", "text", "outline"]);
  assert.deepEqual(keys("battery_ring"), ["color", "track_color", "thickness"]);
  assert.deepEqual(keys("accent_dot"), ["color", "thickness", "filled"]);
  assert.deepEqual(keys("info"), ["color", "track_color", "icon", "thickness", "bar_width", "filled", "font", "text", "outline"]);
  assert.deepEqual(inspect(aod, ["resources"], null).aod_keys, []);
});

test("inspect takes the frame and style through the requests", async () => {
  const client = await Client.open();
  const doc = client.studio.create(bundle("A", readText(AOD)), "open");
  const clock = ["elements", "clock"];
  const awake = await client.call("inspect", { id: doc.id, element: clock, device: "fenix847mm" });
  assert.equal(awake.status, 200);
  assert.deepEqual(awake.json.context, { frame: "awake", style: null });
  assert.deepEqual(awake.json.fields.find((f: any) => f.key === "color").effective, { value: "color.white", from: "own" });
  const asleep = await client.call("inspect", { id: doc.id, element: clock, device: "fenix847mm", frame: "aod", style: "" });
  assert.equal(asleep.status, 200);
  assert.deepEqual(asleep.json.context, { frame: "aod", style: null });
  assert.deepEqual(asleep.json.fields.find((f: any) => f.key === "color").effective, { value: "color.black", from: "aod" });
  assert.deepEqual(asleep.json.aod_keys, ["color", "font", "text", "outline"]);
  const bad = await client.call("inspect", { id: doc.id, element: clock, device: "fenix847mm", frame: "dreaming" });
  assert.equal(bad.status, 400);
  assert.match(bad.json.error, /frame/);
});

// -- the Face panel --

test("the Face panel lists colours, schemes, styles and fonts", () => {
  const g = globalsOf(readText(STYLES), db) as any;
  assert.ok(g.palette.length > 0);
  assert.ok(g.styles.default && g.styles.entries.length > 0);
  assert.deepEqual(g.layouts, ["big", "compact"]);
  assert.deepEqual(g.styles.entries.map((e: any) => e.index), g.styles.entries.map((_: any, i: number) => i));
  assert.deepEqual(g.targets, ["fenix8solar47mm", "fenix8solar51mm", "fr955"]);
  const showcase = globalsOf(readText("examples/showcase/face.yaml"), db) as any;
  const fonts = new Set(showcase.fonts.map((f: any) => f.name));
  assert.ok(fonts.has("digitalclock") && fonts.has("dialfont"));
  assert.ok(showcase.palette.find((p: any) => p.name === "black").long);
});

test("the Face panel reads face:, defaults: and each layout's blocks and styles", () => {
  const g = globalsOf(readText("examples/showcase/face.yaml"), db);
  assert.deepEqual(g.face, { name: "Showcase", version: "1.2.0", id: "5ca5867b-1d30-4581-94c0-617033e6824c" });
  assert.deepEqual(g.layout_entries.map((l) => [l.name, l.styles]), [
    ["analog", ["analog_dark", "analog_light", "analog_crimson"]], ["digital", ["digital_dark", "digital_light"]], ["roman", ["roman_dark", "roman_crimson"]],
  ]);
  const analog = g.layout_entries[0]!;
  assert.ok(analog.static > 0 && analog.elements > 0);
  assert.deepEqual(g.styles.entries.map((e) => [e.name, e.index]).slice(0, 2), [["analog_dark", 0], ["analog_light", 1]]);
  const aod = globalsOf(readText(AOD), db);
  assert.deepEqual(aod.defaults, { antialias: null, min_1px: null, aod: { visible: false, dim: 0.6, mask: null } });
  assert.deepEqual(aod.layout_entries, []);
  const minimal = globalsOf(starters.instantiate("minimal", "M"), db);
  assert.deepEqual(minimal.defaults, { antialias: null, min_1px: null, aod: { visible: null, dim: null, mask: null } });
  assert.equal(minimal.face.name, "M");
});

test("a colour off the MIP palette is flagged on MIP targets only", () => {
  const text = 'format: 2\nface: { id: 9c1d5f30-6a72-4b18-8d4e-0f2a71c93b64, name: P, version: 1.0.0 }\nbuild: { targets: [fr955, fenix8solar47mm] }\n'
    + 'resources:\n  palette:\n    ok: "#55AAFF"\n    off: "#123456"\n';
  const byName = Object.fromEntries((globalsOf(text, db) as any).palette.map((p: any) => [p.name, p]));
  assert.deepEqual(byName["ok"].dithers_on, []);
  assert.deepEqual(new Set(byName["off"].dithers_on), new Set(["fr955", "fenix8solar47mm"]));
});

test("a target not installed and a value that is no colour are noted", () => {
  const text = starters.instantiate("minimal", "T").replace("targets: [", "targets: [nosuchwatch, ").replace('bg: "#000000"', 'bg: "#00GG00"');
  const g = globalsOf(text, db) as any;
  assert.deepEqual(Object.keys(g.target_problems), ["nosuchwatch"]);
  const bg = g.palette.find((p: any) => p.name === "bg");
  assert.ok(bg.problem && !bg.automatic);
  assert.ok(g.palette.filter((p: any) => p.name !== "bg").every((p: any) => p.problem === null));
});

// -- edits --

test("a geometry edit goes to the scope asked for", async () => {
  const doc = make(await newStudio());
  const clock = elementPath(doc, "clock");
  doc.edit({ op: "set", element: clock, path: ["at", "dy"], value: "-5%r", scope: "device", device: "fr955" }, doc.version);
  doc.edit({ op: "set", element: clock, path: ["at", "dy"], value: "3%r", scope: "shape", device: "fr955" }, doc.version);
  doc.edit({ op: "set", element: clock, path: ["at", "dy"], value: "1%r", scope: "display", device: "fr955" }, doc.version);
  doc.edit({ op: "set", element: clock, path: ["at", "dx"], value: 2, scope: "all" }, doc.version);
  const d = dataOf(doc).elements.clock;
  // each scope's override holds the whole at: the element's own, then the changed key
  assert.deepEqual(d.overrides, {
    fr955: { at: { anchor: "center", dy: "-5%r" } }, "shape:round": { at: { anchor: "center", dy: "3%r" } }, "display:mip": { at: { anchor: "center", dy: "1%r" } },
  });
  assert.equal(d.at.dx, 2);
  const center = (device: string): number[] => doc.analysis().resolved.get(device)!.items.find((p) => p.id === "clock")!.center;
  assert.notDeepEqual(center("fr955"), center("fenix8solar47mm"));
  assert.equal((doc.history()["states"] as any[])[0].label, "set elements.clock.at.dx to 2");
});

test("only geometry can be overridden", async () => {
  const doc = make(await newStudio());
  assert.throws(() => doc.edit({ op: "set", element: elementPath(doc, "clock"), path: ["font"], value: "FONT_SMALL", scope: "device", device: "fr955" }, doc.version), /cannot be overridden/);
});

test("an edit the gate refuses leaves the face alone", async () => {
  const doc = make(await newStudio());
  const before = [doc.text, doc.version];
  assert.throws(() => doc.edit({ op: "set", path: ["elements", "clock", "color"], value: "color.nope" }, doc.version), /color\.nope/);
  assert.throws(() => doc.edit({ op: "remove", path: ["resources", "palette", "bg"] }, doc.version), /the colour bg is used by 1 element: background/);
  assert.throws(() => doc.edit({ op: "rename", path: ["resources", "palette", "bg"], to: "1x", prefix: "color." }, doc.version), /not a name/);
  assert.throws(() => doc.edit({ op: "explode" }, doc.version), /unknown edit/);
  assert.throws(() => doc.edit({ op: "remove", path: ["elements", "clock", "visible"] }, doc.version), /is not set/);
  assert.throws(() => doc.edit({ op: "set", path: ["face", "version"], value: "2.0.0" }, 0), StaleVersion);
  assert.deepEqual([doc.text, doc.version], before);
});

test("a colour renamed in the panel is renamed everywhere", async () => {
  const doc = make(await newStudio());
  doc.edit({ op: "rename", path: ["resources", "palette", "text"], to: "ink", prefix: "color." }, doc.version);
  assert.ok(!doc.text.includes("color.text") && doc.text.includes("color.ink"));
  assert.notEqual(doc.analysis().face, null);
  doc.undo(doc.version);
  assert.ok(doc.text.includes("color.text"));
});

test("targets and a style are edited from the panel", async () => {
  const doc = (await newStudio()).create(bundle("S", readText(STYLES)), "open");
  doc.edit({ op: "set", path: ["build", "targets"], value: ["fr955"] }, doc.version);
  assert.deepEqual(doc.summary()["targets"], ["fr955"]);
  const first = (doc.summary()["globals"] as any).styles.entries[0];
  doc.edit({ op: "set", path: ["config", "style", "choices", "extra"], value: { layout: "compact", scheme: first.scheme } }, doc.version);
  const entries = Object.fromEntries((doc.summary()["globals"] as any).styles.entries.map((e: any) => [e.name, e]));
  assert.equal(entries["extra"].layout, "compact");
});

test("a font is added and its file replaced", async () => {
  const doc = make(await newStudio());
  doc.addAsset("Chivo.ttf", read(CHIVO), null, doc.version, ["clockface", "20%r"]);
  assert.deepEqual(dataOf(doc).resources.fonts.clockface, { source: "assets/Chivo.ttf", size: "20%r" });
  assert.throws(() => doc.addAsset("Other.ttf", read(CHIVO), null, doc.version, ["clockface", "20%r"]), /already a font/);
  doc.edit({ op: "set", path: ["elements", "clock", "font"], value: "font.clockface" }, doc.version);
  doc.addAsset("Dyna.ttf", read(DYNALIGHT), "assets/Chivo.ttf", doc.version);
  assert.equal(dataOf(doc).resources.fonts.clockface.source, "assets/Dyna.ttf");
  assert.deepEqual(Object.keys(doc.head.assets).sort(), ["assets/Dyna.ttf"]);
  assert.notEqual(doc.analysis().face, null);
});

test("a refused font leaves no file behind", async () => {
  const doc = make(await newStudio());
  doc.addAsset("Chivo.ttf", read(CHIVO), null, doc.version, ["f", "20%r"]);
  const before = Object.keys(doc.head.assets);
  assert.throws(() => doc.addAsset("Bad.ttf", read(CHIVO), null, doc.version, ["f", "20%r"]), Refused);
  assert.deepEqual(Object.keys(doc.head.assets), before);
});

test("inspect and edit through the requests", async () => {
  const client = await Client.open();
  const doc = await client.create("minimal", "H");
  const id = doc.id;
  const edit = (version: number, edit: unknown) => client.call("edit", { id, version, edit });
  const clock = doc.tree.flatMap((b: any) => b.children).find((n: any) => n.id === "clock");
  const result = (await client.call("inspect", { id, element: clock.path, device: "fr955" })).json;
  assert.equal(result.type, "text");
  assert.equal(result.device, "fr955");
  const r = await edit(1, { op: "set", element: clock.path, path: ["font"], value: "FONT_SMALL" });
  assert.equal(r.status, 200);
  assert.equal(r.json.version, 2);
  assert.ok(r.json.text.includes("font: FONT_SMALL"));
  const bad = await edit(2, { op: "set", element: clock.path, path: ["color"], value: "color.nope" });
  assert.equal(bad.status, 400);
  assert.ok(bad.json.error.includes("color.nope"));
  assert.equal((await edit(1, {})).status, 409);
  assert.equal((await edit(2, "not an object")).status, 400);
  assert.equal((await edit(2, { op: "set", element: clock.path, path: ["at", "dy"], value: 1, scope: "device", device: "nosuchwatch" })).status, 400);
  const font = await client.call("assets", { id, filename: "C.ttf", font: "big", size: "30%r", version: 2 }, read(CHIVO));
  assert.equal(font.status, 200, JSON.stringify(font.json));
  assert.deepEqual(font.json.globals.fonts.map((f: any) => f.name), ["big"]);
});

test("the vocabulary lists sources, icons, complications and devices", async () => {
  const client = await Client.open();
  const words = (await client.call("vocabulary")).json;
  assert.ok(words.sources.activity.includes("activity.steps"));
  assert.ok(words.icons.includes("heart"));
  assert.equal(words.complications[0], "auto");
  const fr955 = words.devices.find((d: any) => d.id === "fr955");
  assert.ok(fr955.fonts.includes("FONT_MEDIUM"));
  assert.equal(fr955.shape, "round");
  assert.equal(fr955.ppi, 200);
  assert.ok(fr955.skin);
  assert.deepEqual([fr955.width, fr955.height], [260, 260]);
  assert.ok(words.devices.some((d: any) => d.ppi === null), "some watches' files give no ppi");
});

test("a skin is the watch round its screen", async () => {
  const client = await Client.open();
  const r = await client.call("skin", { device: "fr955", scale: 2 });
  assert.equal(r.status, 200, JSON.stringify(r.json));
  const skin = r.json;
  const image = decodePng(Uint8Array.from(atob(skin.image.split(",", 2)[1]), (c) => c.charCodeAt(0)))!;
  assert.deepEqual([image.width, image.height], [skin.width, skin.height]);
  assert.ok(skin.x + 520 <= skin.width && skin.y + 520 <= skin.height);
  assert.equal(image.pixels[((skin.y + 260) * image.width + skin.x + 260) * 4 + 3], 0);
  assert.equal((await client.call("skin", { device: "nosuchwatch" })).status, 400);
});

test("a face that does not load is not built", async () => {
  const client = await Client.open();
  const doc = make(client.studio);
  doc.replaceText(doc.text.replace("color: color.dim", "color: color.nope"), doc.version);
  const r = await client.call("build", { id: doc.id, device: "fr955", version: doc.version });
  assert.equal(r.status, 400);
  assert.match(r.json.error, /does not load/);
  assert.equal((await client.call("build", { id: doc.id, device: "nosuchwatch", version: doc.version })).status, 400);
  assert.equal((await client.call("build", { id: doc.id, device: "fr955", version: 0 })).status, 409);
});

test("a build's compile does not hold up editing", async () => {
  const client = await Client.open();
  let finish!: () => void;
  (client.router.host as { build: unknown }).build = (_zip: Uint8Array, _device: string, version: number) =>
    new Promise((done) => { finish = () => done({ ok: true, built: version }); });
  const doc = make(client.studio);
  const building = client.call("build", { id: doc.id, device: "fr955", version: doc.version });
  const other = make(client.studio);
  const edited = await Promise.race([
    client.call("text", { id: doc.id, version: doc.version, text: doc.text.replace("T", "U") }),
    new Promise((never) => setTimeout(() => never("timed out"), 2000)),
  ]);
  assert.notEqual(edited, "timed out", "an edit waited for the compile");
  assert.equal((await client.call("get", { id: other.id })).status, 200);
  finish();
  const built = await building;
  assert.equal(built.status, 200);
  // the build is of the face as it was asked for, not as it was edited since
  assert.equal(built.json.built, doc.version - 1);
});

// -- slots --

const slotsOf = (doc: Document): Record<string, any> => Object.fromEntries((doc.summary()["globals"] as any).slots.map((s: any) => [s.name, s]));

test("a slot is declared, drawn and its choices edited from the panel", async () => {
  const doc = make(await newStudio());
  doc.edit({ op: "set", path: ["config", "slots", "top"], value: { default: "steps", choices: "any" } }, doc.version);
  assert.deepEqual(slotsOf(doc)["top"], { name: "top", label: null, default: "steps", choices: "any", drawn_by: [] });
  doc.structure({ op: "add", type: "data", block: ["elements"], choice: "top" }, doc.version);
  const drawer = slotsOf(doc)["top"].drawn_by;
  assert.equal(drawer.length, 1);
  assert.equal(fieldsOf(doc.inspect(elementPath(doc, drawer[0]), null))["slot"].widget, "slot");
  doc.edit({ op: "set", path: ["config", "slots", "top", "choices"], value: ["steps", { type: "heart_rate", icon: "none" }] }, doc.version);
  doc.edit({ op: "set", path: ["config", "slots", "top", "label"], value: "Top" }, doc.version);
  const top = slotsOf(doc)["top"];
  assert.equal(top.label, "Top");
  assert.deepEqual(top.choices, [{ type: "steps", icon: null }, { type: "heart_rate", icon: "none" }]);
  assert.notEqual(doc.analysis().face, null);
});

test("a slot rename repoints its elements and nothing else", async () => {
  const doc = make(await newStudio());
  doc.edit({ op: "set", path: ["config", "slots", "steps"], value: { default: "steps", choices: ["steps", "calories"] } }, doc.version);
  doc.structure({ op: "add", type: "data", block: ["elements"], choice: "steps" }, doc.version);
  doc.edit({ op: "rename", path: ["config", "slots", "steps"], to: "left" }, doc.version);
  const left = slotsOf(doc)["left"];
  assert.equal(left.default, "steps");
  assert.equal(left.drawn_by.length, 1);
  assert.ok(!doc.text.includes("slot: steps") && doc.text.includes("slot: left"));
  assert.notEqual(doc.analysis().face, null);
});

test("an element is renamed in place; a name already used anywhere else is refused", async () => {
  const doc = make(await newStudio());
  doc.edit({ op: "rename", path: ["elements", "clock"], to: "timer" }, doc.version);
  assert.ok(!("clock" in dataOf(doc).elements) && "timer" in dataOf(doc).elements);
  assert.notEqual(doc.analysis().face, null);
  const before = doc.text;
  // "background" is a sibling of "timer" now only via the static: block, not elements: -- still a duplicate id face-wide
  assert.throws(() => doc.edit({ op: "rename", path: ["elements", "timer"], to: "background" }, doc.version), /duplicate element id/);
  assert.equal(doc.text, before);
});

test("a slot edit the face cannot take is refused", async () => {
  const doc = make(await newStudio());
  doc.edit({ op: "set", path: ["config", "slots", "top"], value: { default: "steps", choices: ["steps"] } }, doc.version);
  doc.structure({ op: "add", type: "data", block: ["elements"], choice: "top" }, doc.version);
  const before = doc.text;
  const drawer = slotsOf(doc)["top"].drawn_by[0];
  assert.throws(() => doc.edit({ op: "remove", path: ["config", "slots", "top"] }, doc.version), new RegExp(`${drawer} draws the slot top`));
  assert.throws(() => doc.edit({ op: "set", path: ["config", "slots", "top", "choices"], value: ["calories"] }, doc.version), Refused);
  assert.equal(doc.text, before);
});

test("the last slot deleted takes its config block with it", async () => {
  const doc = make(await newStudio());
  doc.edit({ op: "set", path: ["config", "slots", "top"], value: { default: "steps", choices: "any" } }, doc.version);
  doc.edit({ op: "set", path: ["config", "slots", "bottom"], value: { default: "calories", choices: "any" } }, doc.version);
  doc.edit({ op: "remove", path: ["config", "slots", "top"] }, doc.version);
  assert.deepEqual(Object.keys(slotsOf(doc)), ["bottom"]);
  doc.edit({ op: "remove", path: ["config", "slots", "bottom"] }, doc.version);
  assert.ok(!("config" in dataOf(doc)));
  assert.notEqual(doc.analysis().face, null);
});

test("+ Layout adds an empty layout, bootstrapping a style to name it when there is none yet", async () => {
  const doc = make(await newStudio());
  doc.edit({ op: "add_layout", name: "layout" }, doc.version);
  assert.deepEqual(globalsOf(doc.text, db)["layouts"], ["layout"]);
  assert.equal((globalsOf(doc.text, db)["styles"] as any).entries[0].layout, "layout");
  assert.notEqual(doc.analysis().face, null);
});

test("+ Layout adds a second, unreferenced layout without touching an existing style", async () => {
  const doc = make(await newStudio());
  doc.edit({ op: "add_layout", name: "layout" }, doc.version);
  doc.edit({ op: "add_layout", name: "layout2" }, doc.version);
  assert.deepEqual(globalsOf(doc.text, db)["layouts"], ["layout", "layout2"]);
  assert.equal((globalsOf(doc.text, db)["styles"] as any).entries.length, 1);
  assert.notEqual(doc.analysis().face, null);
});

test("a layout with no style referencing it is deleted through the existing structural delete path", async () => {
  const doc = make(await newStudio());
  doc.edit({ op: "add_layout", name: "layout" }, doc.version);
  doc.edit({ op: "add_layout", name: "layout2" }, doc.version);
  doc.edit({ op: "remove", path: ["layouts", "layout2"] }, doc.version);
  assert.deepEqual(globalsOf(doc.text, db)["layouts"], ["layout"]);
  assert.notEqual(doc.analysis().face, null);
});

// -- the server --

// The browser's devices are the server's digest plus each device's skin
// (sent with its extras); a digest missing a tag the compiler reads shows
// as diagnostics the CLI does not give.
test("a template with its own font assets (showcase) arrives with them, through the new request", async () => {
  const full = await Client.open();
  const summary = await full.create("showcase", "S");
  const doc = full.studio.document(summary.id);
  assert.deepEqual(Object.keys(doc.head.assets).sort(), ["assets/ChivoMono-Bold.ttf", "assets/Dynalight-Regular.ttf", "assets/OFL.txt"]);
  assert.deepEqual(missing(doc.text, { has: (p: string) => p in doc.head.assets }), []);
  assert.notEqual(doc.analysis().face, null);
});

test("a studio over the device digest diagnoses every template as one over the device files", async () => {
  const full = await Client.open();
  const made = [];
  for (const template of starters.names()) made.push([template, await full.create(template)] as const);
  const ids = [...new Set(made.flatMap(([, doc]) => doc.targets as string[]))];
  const sent = digest(db, ids);
  const files = new MemoryDeviceFiles();
  for (const [id, folder] of Object.entries(sent.devices)) {
    for (const [name, text] of Object.entries(folder)) files.add(id, name, text);
    const skin = db.get(id).skinName;
    if (skin !== null) files.add(id, skin, db.files.file(id, skin)!);
  }
  for (const [id, page] of Object.entries(sent.references)) files.addReference(id, page);
  const digested = new Client(new Studio(await Store.open(new MemoryBackend()), new DeviceDatabase(files, new NodeFontFiles()),
    () => readFontFile(ICON_FONT)));
  for (const [template, doc] of made) {
    assert.deepEqual((await digested.create(template)).diagnostics, doc.diagnostics, template);
  }
});

test("the server bundles the page as /dist/app.js: one module rendering into #app, Preact from npm, the rasteriser fetched apart", async () => {
  const server = await start({ host: "127.0.0.1", port: 0, db, fontsDir: null });
  try {
    const response = await fetch(`http://127.0.0.1:${server.port}/dist/app.js`);
    assert.equal(response.status, 200);
    assert.match(response.headers.get("content-type") ?? "", /^text\/javascript/);
    const bundle = await response.text();
    assert.match(bundle, /getElementById\("app"\)/, "the entry's render is in the bundle");
    assert.doesNotMatch(bundle, /vendor\/preact-htm/, "Preact comes from npm, not the vendored module");
    assert.doesNotMatch(bundle, /^\s*import\b.*["']\.\//m, "every relative import is bundled in");
    assert.match(bundle, /from\s*"\/dist\/raster\.js"/, "the rasteriser stays a separate module");
  } finally {
    await server.close();
  }
});

test("the server sends the app, the device digest, a device's extras, and refuses a second build", async () => {
  const server = await start({ host: "127.0.0.1", port: 0, db, fontsDir: null });
  const url = (path: string): string => `http://127.0.0.1:${server.port}${path}`;
  try {
    assert.match(await (await fetch(url("/"))).text(), /\/dist\/app\.js/);
    assert.equal((await fetch(url("/static/studio.css"))).status, 200);
    assert.match(await (await fetch(url("/dist/raster.js"))).text(), /export\s*\{[^}]*\bliveOps\b/);
    assert.equal((await fetch(url("/static/../../package.json"))).status, 404);
    assert.match(await (await fetch(url("/dist/worker.js"))).text(), /wfb-studio/);
    const digest = await (await fetch(url("/api/devices"))).json() as any;
    const xml = digest.devices.fr955["fr955.api.debug.xml"] as string;
    assert.ok(xml.includes("<functionEntry") && !xml.includes("<localVariable"));
    assert.ok(digest.listing[0].length > 0);
    const r = await fetch(url("/api/devices/fr955/extras"));
    const body = await r.json() as any;
    assert.ok(body.skin.name.endsWith(".png"));
    assert.ok(body.calls.length > 0);
    assert.equal((await fetch(url("/api/builds/" + "0".repeat(32)))).status, 404);
    assert.equal((await fetch(url("/api/schema"))).status, 200);
    const help = await fetch(url("/help/docs/guide/studio.md"));
    assert.match(help.headers.get("content-type") ?? "", /^text\/markdown/);
    assert.equal((await fetch(url("/help/docs/screenshots/align.png"))).headers.get("content-type"), "image/png");
    for (const outside of ["ts/package.json", "docs%2F..%2Fts%2Fpackage.json", "docs%2F..%2F..%2Fetc%2Fpasswd"]) {
      assert.equal((await fetch(url("/help/" + outside))).status, 404, outside);
    }
  } finally {
    await server.close();
  }
});

/** The status `method path` gets with exactly these headers (`fetch` would set `Host` itself). */
function statusOf(port: number, method: string, path: string, headers: Record<string, string>): Promise<number> {
  return new Promise((done, fail) => {
    const r = httpRequest({ host: "127.0.0.1", port, method, path, headers, setHost: false }, (response) => {
      response.resume();
      done(response.statusCode ?? 0);
    });
    r.on("error", fail);
    r.end(method === "POST" ? "not a zip" : undefined);
  });
}

test("the server answers only requests addressed to it, and builds only for its own page", async () => {
  const server = await start({ host: "127.0.0.1", port: 0, db, fontsDir: null });
  const at = `127.0.0.1:${server.port}`;
  try {
    for (const host of [at, `localhost:${server.port}`, `[::1]:${server.port}`, `192.168.1.20:${server.port}`]) {
      assert.equal(await statusOf(server.port, "GET", "/api/schema", { Host: host }), 200, host);
    }
    // a name a DNS answer points here: a page on that site reaching the loopback server
    assert.equal(await statusOf(server.port, "GET", "/api/schema", { Host: `attacker.example:${server.port}` }), 403);
    // no Host at all: Node's own parser refuses it
    assert.equal(await statusOf(server.port, "GET", "/api/schema", {}), 400);
    // a build from another site's page is refused before its body is read; from the server's own, it is read
    assert.equal(await statusOf(server.port, "POST", "/api/build?device=fr955", { Host: at, Origin: "https://attacker.example" }), 403);
    assert.equal(await statusOf(server.port, "POST", "/api/build?device=fr955", { Host: at, Origin: `http://${at}` }), 400);
  } finally {
    await server.close();
  }
});

test("--allow-host takes names repeated or comma separated, and refuses what is not a name", () => {
  assert.deepEqual(allowHostList(["studio-box,studio-box.lan", " proxy.example ", "a,,b"]), ["studio-box", "studio-box.lan", "proxy.example", "a", "b"]);
  assert.deepEqual(allowHostList([]), []);
  for (const bad of ["studio-box:8765", "http://studio-box", "a b", "box/path"]) {
    assert.throws(() => allowHostList([bad]), /takes host names, comma separated/, bad);
  }
});

test("--allow-host adds names a request may address the server by; --allow-any-host takes any", async () => {
  const named = await start({ host: "0.0.0.0", allowHosts: ["Studio-Box", "proxy.example"], port: 0, db, fontsDir: null });
  const any = await start({ host: "127.0.0.1", allowAnyHost: true, port: 0, db, fontsDir: null });
  try {
    const box = `studio-box:${named.port}`;
    for (const host of [box, `STUDIO-BOX:${named.port}`, `proxy.example:${named.port}`]) {
      assert.equal(await statusOf(named.port, "GET", "/api/schema", { Host: host }), 200, host);
    }
    assert.equal(await statusOf(named.port, "GET", "/api/schema", { Host: `attacker.example:${named.port}` }), 403);
    // its own page, at that name, may build; another site's page may not
    assert.equal(await statusOf(named.port, "POST", "/api/build?device=fr955", { Host: `Studio-Box:${named.port}`, Origin: `http://${box}` }), 400);
    assert.equal(await statusOf(named.port, "POST", "/api/build?device=fr955", { Host: box, Origin: "https://attacker.example" }), 403);
    assert.equal(await statusOf(any.port, "GET", "/api/schema", { Host: `anything.example:${any.port}` }), 200);
    assert.equal(await statusOf(any.port, "POST", "/api/build?device=fr955", { Host: `anything.example:${any.port}`, Origin: "https://attacker.example" }), 403);
  } finally {
    await named.close();
    await any.close();
  }
});
