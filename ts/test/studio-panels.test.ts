// The inspector and the Face panel through the worker's document, the
// vocabulary, and the server the worker asks for what only it has.
import assert from "node:assert/strict";
import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { indexFor, Refused } from "../src/edit/spans.ts";
import { decodePng } from "../src/png.ts";
import * as starters from "../src/starters.ts";
import { bundle } from "../src/studio/bundle.ts";
import { type Document, StaleVersion, type Studio } from "../src/studio/document.ts";
import { elementSchema, globalsOf, inspect } from "../src/studio/inspect.ts";
import { start } from "../src/studio/server.ts";
import { CHIVO, Client, dataOf, db, DYNALIGHT, newStudio, read, readText, ROOT, STYLES } from "./studio-client.ts";

const SHAPES = "examples/features/shapes/face.yaml";
const make = (studio: Studio, template = "minimal"): Document => studio.create(bundle("T", starters.instantiate(template, "T")), "new");
const elementPath = (doc: Document, id: string): (string | number)[] => [...indexFor(doc.text).elements().find((e) => e.name === id)!.path];
const fieldsOf = (result: Record<string, unknown>): Record<string, any> => Object.fromEntries((result["fields"] as any[]).map((f) => [f.key, f]));

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
      const shown = new Set([...(result["fields"] as any[]).map((f) => f.key), "children", "overrides"]);
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

test("the inspector reports the overrides the device reads", () => {
  const text = starters.instantiate("minimal", "O").replace("    at: { anchor: center }\n    color: color.text\n",
    '    at: { anchor: center }\n    color: color.text\n    overrides: { fr955: { at: { dy: 2px } }, "shape:round": { at: { dx: 1px } } }\n');
  const clock = indexFor(text).elements().find((e) => e.name === "clock")!.path;
  const on = (id: string): any => JSON.parse(JSON.stringify(inspect(text, clock, db.get(id))["overrides"], (_, v) => (v instanceof Map ? Object.fromEntries(v) : v)));
  assert.deepEqual(on("fr955"), { device: { selector: "fr955", keys: { at: { dy: "2px" } } }, shape: { selector: "shape:round", keys: { at: { dx: "1px" } } } });
  assert.deepEqual(Object.keys(on("fenix8solar47mm")), ["shape"]);
});

// -- the Face panel --

test("the Face panel lists colours, schemes, styles and fonts", () => {
  const g = globalsOf(readText(STYLES), db) as any;
  assert.ok(g.palette.length > 0);
  assert.ok(g.styles.default && g.styles.entries.length > 0);
  assert.deepEqual(g.layouts, ["big", "compact"]);
  assert.deepEqual(g.targets, ["fenix8solar47mm", "fenix8solar51mm", "fr955"]);
  const showcase = globalsOf(readText("examples/showcase/face.yaml"), db) as any;
  const fonts = new Set(showcase.fonts.map((f: any) => f.name));
  assert.ok(fonts.has("digitalclock") && fonts.has("dialfont"));
  assert.ok(showcase.palette.find((p: any) => p.name === "black").long);
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
  doc.edit({ op: "set", element: clock, path: ["at", "dx"], value: 2, scope: "all" }, doc.version);
  const d = dataOf(doc).elements.clock;
  assert.deepEqual(d.overrides, { fr955: { at: { dy: "-5%r" } }, "shape:round": { at: { dy: "3%r" } } });
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
  assert.throws(() => doc.edit({ op: "remove", path: ["resources", "palette", "bg"] }, doc.version), /color\.bg/);
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

// -- the server --

test("the server sends the app, the device digest, a device's extras, and refuses a second build", async () => {
  const server = await start({ host: "127.0.0.1", port: 0, db, fontsDir: null });
  const url = (path: string): string => `http://127.0.0.1:${server.port}${path}`;
  try {
    assert.match(await (await fetch(url("/"))).text(), /app\.js/);
    assert.equal((await fetch(url("/static/vendor/preact-htm.module.js"))).status, 200);
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
  } finally {
    await server.close();
  }
});
