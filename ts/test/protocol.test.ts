// Every answer the worker sends, and every event it announces, held to the
// shapes `src/studio/protocol.ts` declares: each interface is written out
// again here as a structural check (the keys present, each of the right
// kind, none the contract does not list), and every operation is requested
// on a real example face. The type check holds the worker's code to the
// interfaces; this holds what actually crosses `postMessage` to them.
import assert from "node:assert/strict";
import { test } from "node:test";
import { CHIVO, Client, minimalText, newStudio, openExample, read, readText, type Reply, SHOWCASE } from "./studio-client.ts";
import type { EditOp } from "../src/studio/protocol.ts";

// -- the checks ----------------------------------------------------------------

type Check = ((value: unknown, at: string) => void) & { optional?: boolean };

const show = (value: unknown): string => {
  const text = JSON.stringify(value, (_, v) => (v instanceof Map ? `Map(${v.size})` : v instanceof Uint8Array ? `Uint8Array(${v.length})` : v));
  return text === undefined ? String(value) : text.length > 80 ? text.slice(0, 77) + "..." : text;
};
const fail = (at: string, want: string, got: unknown): never => assert.fail(`${at}: expected ${want}, got ${show(got)}`);

const str: Check = (v, at) => { if (typeof v !== "string") fail(at, "a string", v); };
const num: Check = (v, at) => { if (typeof v !== "number" || !Number.isFinite(v)) fail(at, "a number", v); };
const int: Check = (v, at) => { if (!Number.isInteger(v)) fail(at, "an integer", v); };
const bool: Check = (v, at) => { if (typeof v !== "boolean") fail(at, "a boolean", v); };
const nul: Check = (v, at) => { if (v !== null) fail(at, "null", v); };
/** A JSON value: what `plain` leaves, never a `Map`, `undefined` or a class instance. */
const value: Check = (v, at) => {
  if (v === null || typeof v === "boolean" || typeof v === "string") return;
  if (typeof v === "number") return num(v, at);
  if (Array.isArray(v)) return v.forEach((item, i) => value(item, `${at}[${i}]`));
  if (typeof v === "object" && Object.getPrototypeOf(v) === Object.prototype) {
    return Object.entries(v).forEach(([k, item]) => value(item, `${at}.${k}`));
  }
  fail(at, "a JSON value", v);
};
const literal = (...names: unknown[]): Check => (v, at) => { if (!names.includes(v)) fail(at, `one of ${names.map(show).join(", ")}`, v); };
const nullable = (c: Check): Check => (v, at) => { if (v !== null) c(v, at); };
const opt = (c: Check): Check => Object.assign(((v, at) => c(v, at)) as Check, { optional: true });
const list = (c: Check): Check => (v, at) => {
  if (!Array.isArray(v)) fail(at, "a list", v);
  (v as unknown[]).forEach((item, i) => c(item, `${at}[${i}]`));
};
const tuple = (...cs: Check[]): Check => (v, at) => {
  if (!Array.isArray(v) || v.length !== cs.length) fail(at, `a tuple of ${cs.length}`, v);
  cs.forEach((c, i) => c((v as unknown[])[i], `${at}[${i}]`));
};
const plainObject = (v: unknown, at: string): Record<string, unknown> => {
  if (v === null || typeof v !== "object" || Array.isArray(v) || v instanceof Map) fail(at, "an object", v);
  return v as Record<string, unknown>;
};
const record = (c: Check): Check => (v, at) => { for (const [k, item] of Object.entries(plainObject(v, at))) c(item, `${at}.${k}`); };
/** An object with exactly `keys` (an `opt` key may be absent); `open` admits others, as a drawing op's own fields. */
const obj = (keys: Record<string, Check>, { open = false } = {}): Check => (v, at) => {
  const o = plainObject(v, at);
  for (const [k, c] of Object.entries(keys)) {
    if (!(k in o)) {
      if (!c.optional) fail(`${at}.${k}`, "a key", undefined);
      continue;
    }
    c(o[k], `${at}.${k}`);
  }
  if (!open) for (const k of Object.keys(o)) if (!(k in keys)) fail(`${at}.${k}`, "no such key in the contract", o[k]);
};
const oneOf = (...cs: Check[]): Check => (v, at) => {
  const reasons: string[] = [];
  for (const c of cs) {
    try {
      c(v, at);
      return;
    } catch (e) {
      reasons.push((e as Error).message);
    }
  }
  fail(at, `one of the shapes (${reasons.join(" / ")})`, v);
};

// -- the shapes, one per interface of protocol.ts ---------------------------------

const path = list(oneOf(str, int));
const treeNode: Check = (v, at) => obj({ kind: literal("element", "hand", "part"), id: str, type: value, path, line: int, end: int, z: opt(value), children: list(treeNode) })(v, at);
const treeBlock = obj({ kind: literal("block"), label: str, path, line: nullable(int), children: list(treeNode) });
const diagnostic = obj({ severity: literal("error", "warning", "note"), code: str, message: str, notes: list(str), file: opt(str), line: opt(int), col: opt(int) });
const history = obj({
  version: int, can_undo: bool, can_redo: bool, undo: nullable(str), redo: nullable(str),
  states: list(obj({ seq: int, time: num, label: str, current: bool, redo: bool })), total: int,
  snapshots: list(obj({ name: str, time: num, reason: str, seq: int, label: str, current: bool })),
});
const globals = obj({
  face: obj({ name: nullable(str), version: nullable(str), id: nullable(str) }),
  defaults: obj({ antialias: value, min_1px: value, aod: obj({ visible: value, dim: value, mask: value }) }),
  palette: list(obj({ name: str, value, label: value, long: bool, dithers_on: list(str), used_by: list(str), automatic: bool, problem: nullable(str), launcher: bool })),
  schemes: obj({ names: list(str), roles: list(str), colors: record(record(value)), base: record(nullable(str)), inherited: record(list(str)) }),
  styles: obj({ default: nullable(str), entries: list(obj({ name: str, index: int, label: nullable(str), layout: nullable(str), scheme: nullable(str) })) }),
  layouts: list(str),
  layout_entries: list(obj({ name: str, label: nullable(str), elements: int, static: int, styles: list(str) })),
  fonts: list(obj({ name: str, source: nullable(str), face: value, size: value })),
  slots: list(obj({ name: str, label: nullable(str), default: nullable(str), choices: oneOf(list(obj({ type: nullable(str), icon: nullable(str) })), str, nul), drawn_by: list(str) })),
  roles: list(str),
  axes: obj({
    accent_color: nullable(obj({ default: nullable(str), choices: oneOf(str, list(value)), raw: value, role: str, own_role: bool })),
    data_color: nullable(obj({ default: nullable(str), choices: oneOf(str, list(value)), raw: value, role: str, own_role: bool })),
  }),
  displays: list(int),
  hand_sets: list(str),
  hands: list(obj({ name: str, hands: record(obj({ parts: int, color: value })), placed_by: list(str), line: int, end: int })),
  targets: list(str),
  target_problems: record(str),
});
const SUMMARY = {
  id: str, name: str, version: int, text: str, missing: list(str), loads: bool, targets: list(str), styles: list(obj({ name: str, label: str })),
  tree: list(treeBlock), diagnostics: list(diagnostic), assets: list(str), history, globals,
};
const summary = obj(SUMMARY);
const structured = obj({ ...SUMMARY, select: nullable(str) });
const dragged = obj({ ...SUMMARY, landed: bool, what: str });

const handle = obj({
  kind: literal("end", "size", "angle", "vertex", "segment"), part: opt(literal("at", "to")), key: opt(oneOf(str, list(str))), axis: opt(literal("x", "y")), gain: opt(num),
  index: opt(int), after: opt(int), mirrored: opt(literal(true)),
  x: num, y: num, cx: opt(num), cy: opt(num), start: opt(num), sweep: opt(num),
  live: opt(nullable(oneOf(obj({ consts: record(num) }), obj({ angle: str })))),
});
const frame = obj({
  version: int, device: str, scale: int, width: int, height: int, shape: str, minor_radius: num, frame: str,
  items: list(obj({
    id: str, kind: str, drawn: bool, line: nullable(int), box: tuple(num, num, num, num), center: tuple(num, num), handles: list(handle),
    path: opt(path), angle: opt(num),
  })),
  local: nullable(obj({ element: path, origin: tuple(num, num), radius: num, angle: num })),
  layers: list(oneOf(
    obj({ id: str, kind: str, ops: nullable(list(obj({ op: str }, { open: true }))) }),
    obj({ id: str, kind: str, origin: nullable(tuple(num, num)), image: nullable(str) }),
  )),
  tiles: obj({ data: str, index: record(tuple(int, int, int, literal("mask", "rgba"))) }),
});

const WIDGETS = ["readonly", "object", "length", "angle", "align", "color", "expression", "template", "enum", "slot", "handset", "font", "icon",
  "complication", "bool", "number", "text", "yaml"];
const effective = obj({ value, from: literal("own", "override", "aod", "group", "defaults", "absent"), selector: opt(str), group: opt(str) });
const field: Check = (v, at) => obj({
  key: str, path, kind: literal("scalar", "object", "list", "choice"), widget: literal(...WIDGETS), description: str, value, present: bool, required: bool,
  default: value, geometry: bool, effective,
  enum: opt(list(value)), children: opt(list(field)), item: opt(field), items: opt(list(field)), branches: opt(list(field)), chosen: opt(nullable(int)), truncated: opt(literal(true)),
  text: opt(str), rules: opt(literal("value", "color", "boolean")),
})(v, at);
const scopeOverride = obj({ selector: str, keys: record(value) });
const context = obj({ frame: literal("awake", "asleep", "aod"), style: nullable(str) });
const inspect = obj({
  element: path, id: str, type: str, subject: literal("element", "hand", "part"), context, fields: list(field), unknown: list(str), aod_keys: list(str),
  overrides: obj({ device: opt(scopeOverride), shape: opt(scopeOverride), display: opt(scopeOverride) }),
  overridden: list(obj({ selector: str, keys: record(value), line: int, end: int })), parts: nullable(obj({ count: int, shapes: list(str), line: int, end: int })),
  device: nullable(str), shape: nullable(str), display: nullable(str), error: nullable(str),
});

const vocabulary = obj({
  sources: record(list(str)), icons: list(str), complications: list(str), series: list(str), types: list(str),
  mip: list(obj({ name: str, value: str, label: str })), hand_presets: list(str), categories: list(str),
  complication_types: list(obj({ name: str, label: str, category: str, icon: nullable(str), sample: nullable(str) })), icon_glyphs: record(int),
  source_info: record(obj({ type: literal("number", "float", "boolean", "string", "time", "date", "color"), unit: nullable(str), quantity: nullable(str), doc: str, nullable: bool })),
  format_codes: obj({ time: list(tuple(str, str)), date: list(tuple(str, str)), duration: list(tuple(str, str)), number: list(tuple(str, str)) }),
  lint_codes: list(str),
  devices: list(obj({ id: str, name: str, shape: str, size: str, width: int, height: int, ppi: nullable(num), skin: bool, display: str, fonts: list(str) })),
  unreadable_devices: list(obj({ id: str, reason: str })),
});
const home = obj({
  templates: list(obj({ name: str, blurb: str })),
  documents: list(obj({ id: str, name: str, created: num, changed: num, version: int, snapshots: int })), store: str, shared: bool,
});
const skin = obj({ device: str, scale: int, image: str, width: int, height: int, x: int, y: int });
const deleted = obj({ deleted: str });
const renamed = obj({ id: str, name: str });
const uiState = obj({ state: record(value) });
const buildResult = obj({ ok: bool, device: str, log: str, seconds: num, memory: nullable(str), download: nullable(str) });
const refusal = obj({ error: str });
const EVENTS: Record<string, Check> = {
  created: obj({ id: str }),
  changed: obj({ id: str, version: int, tab: nullable(str) }),
  deleted: obj({ id: str }),
  renamed: obj({ id: str, name: str }),
  snapshot: obj({ id: str, name: str, version: int }),
  error: obj({ id: opt(str), message: str }),
};

/** A file answer: bytes with their type, and no JSON. */
function file(r: Reply, type: string, at: string): void {
  assert.equal(r.status, 200, `${at}: ${show(r.json)}`);
  assert.ok(r.body instanceof Uint8Array && r.body.length > 0, `${at}: a body`);
  assert.equal(r.type, type, `${at}: its type`);
  assert.equal(r.json, undefined, `${at}: no json`);
  if (r.filename !== undefined) str(r.filename, `${at}.filename`);
}

const flatten = (blocks: any[]): any[] => blocks.flatMap((b) => [...b.children.flatMap((n: any) => [n, ...flatten([n])])]);

// -- every operation on a real face ------------------------------------------------

test("every answer the worker sends has the protocol's shape", async () => {
  const studio = await newStudio();
  const client = new Client(studio);
  client.tab = "tab-1";
  const id = openExample(studio, SHOWCASE).id;
  const ok = async (op: string, args: Record<string, unknown> = {}, body: Uint8Array | null = null): Promise<Reply> => {
    const r = await client.call(op, args, body);
    assert.equal(r.status, 200, `${op}: ${show(r.json)}`);
    return r;
  };
  const face = (await ok("get", { id })).json;
  summary(face, "get");
  assert.ok(face.loads && face.targets.length > 0, "the showcase loads");
  const device = face.targets[0];

  home((await ok("home")).json, "home");
  vocabulary((await ok("vocabulary")).json, "vocabulary");
  skin((await ok("skin", { device, scale: 1 })).json, "skin");

  const drawn = (await ok("frame", { id, device, scale: 1 })).json;
  frame(drawn, "frame");
  assert.ok(drawn.items.some((i: any) => i.handles.length > 0), "some element has handles");
  assert.equal(drawn.local, null);
  // entered into a hands element: the local frame, its parts as items, each handle of the new kinds among them
  const hands = flatten(face.tree).find((n: any) => n.type === "hands");
  assert.ok(hands, "the showcase places a hand set");
  const entered = (await ok("frame", { id, device, scale: 1, enter: hands.path })).json;
  frame(entered, "frame entered");
  assert.deepEqual(entered.local.element, hands.path);
  const partItems = entered.items.filter((i: any) => i.path);
  assert.ok(partItems.length > 0 && partItems.every((i: any) => i.id === i.path.join("/") && typeof i.angle === "number"));
  const kinds = new Set(partItems.flatMap((i: any) => i.handles.map((h: any) => h.kind)));
  assert.ok(kinds.has("vertex") && kinds.has("segment"), [...kinds].join(", "));
  file(await ok("thumbnail", { id, device }), "image/png", "thumbnail");
  file(await ok("cover", { id }), "image/png", "cover");
  const set = face.globals.hand_sets[0];
  assert.ok(set, "the showcase declares a hand set");
  file(await ok("handset", { id, name: set, device }), "image/png", "handset");

  const nodes = flatten(face.tree);
  assert.ok(nodes.length > 10, "the showcase has elements");
  assert.ok(nodes.some((n) => n.kind === "hand") && nodes.some((n) => n.kind === "part"), "hands and parts in the tree");
  for (const node of nodes) {
    const own = (await ok("inspect", { id, element: node.path, device })).json;
    inspect(own, `inspect ${node.id} on ${device}`);
    assert.equal(own.subject, node.kind, `${node.id}'s subject`);
    inspect((await ok("inspect", { id, element: node.path, device: "" })).json, `inspect ${node.id}`);
    inspect((await ok("inspect", { id, element: node.path, device, frame: "aod", style: face.styles[0].name })).json, `inspect ${node.id} in AOD`);
  }
  // not an element: the same shape, with the reason
  const none = (await ok("inspect", { id, element: ["resources"], device })).json;
  inspect(none, "inspect resources");
  assert.equal(none.error, "not an element");
  assert.deepEqual([none.fields, none.type, none.device], [[], "", device]);

  let version = face.version;
  const take = (r: Reply): any => {
    version = r.json.version;
    return r.json;
  };
  summary(take(await ok("edit", { id, version, edit: { op: "set", path: ["face", "version"], value: "9.9.9" } })), "edit");
  const text = nodes.find((n) => n.type === "text" && drawn.items.some((i: any) => i.id === n.id && i.drawn));
  assert.ok(text, "a drawn text element");
  // an element's own key, as the inspector sends it: `device` is null while no device is viewed
  const own: EditOp = { op: "set", element: text.path, path: ["z"], scope: "all", device: null, value: 3 };
  summary(take(await ok("edit", { id, version, edit: own })), "edit an element's key");
  dragged(take(await ok("drag", { id, version, device, element: text.id, gesture: { kind: "move", part: "both", dx: 1, dy: 0 } })), "drag");
  // a part, by its frame item id, with a point gesture and the frame's time
  const polygon = partItems.find((i: any) => i.kind === "polygon");
  dragged(take(await ok("drag", { id, version, device, element: polygon.id, time: "10:09:42", gesture: { kind: "vertex", index: 0, dx: 1, dy: 1 } })), "drag a part");
  // a part's own key, and a hand's
  summary(take(await ok("edit", { id, version, edit: { op: "set", element: polygon.path, path: ["filled"], scope: "all", device: null, value: true } })), "edit a part");
  summary(take(await ok("edit", { id, version, edit: { op: "set", element: hands.children[0].path, path: ["color"], scope: "all", device: null, value: "color.fg" } })), "edit a hand");
  structured(take(await ok("structure", { id, version, edit: { op: "duplicate", path: text.path } })), "structure");
  // an aod: restyle, through the aod scope
  const restyled: EditOp = { op: "set", element: text.path, path: ["color"], scope: "aod", device: null, value: "color.fg" };
  summary(take(await ok("edit", { id, version, edit: restyled })), "edit in the aod scope");
  // the layout and style ops, each a batch step and an edit of its own
  const layouts = face.globals.layouts;
  const reorder: EditOp[] = [
    { op: "rename_layout", name: layouts[0], to: "renamed" },
    { op: "move_key", path: ["layouts", "renamed"], to: layouts.length - 1 },
    { op: "set_default_style", name: face.globals.styles.entries[0].name },
  ];
  structured(take(await ok("batch", { id, version, label: "reorder", edits: reorder })), "batch of layout ops");
  const spare = face.globals.layout_entries.find((l: any) => !l.styles.includes(face.globals.styles.entries[0].name) && l.name !== layouts[0]);
  assert.ok(spare, "a layout the new default style does not pick");
  const dropLayout: EditOp = { op: "delete_layout", name: spare.name };
  summary(take(await ok("edit", { id, version, edit: dropLayout })), "delete_layout");
  // a text that is YAML but no face: the summary, its globals included, is whole
  const broken = take(await ok("text", { id, version, text: "- 1\n" }));
  summary(broken, "text");
  assert.equal(broken.loads, false);
  assert.ok(broken.tree.every((b: any) => b.line === null && b.children.length === 0), "empty blocks");
  assert.deepEqual([broken.globals.palette, broken.globals.targets, broken.globals.styles], [[], [], { default: null, entries: [] }]);
  summary(take(await ok("undo", { id, version })), "undo");
  summary(take(await ok("redo", { id, version })), "redo");
  summary(take(await ok("goto", { id, version, seq: face.version })), "goto");
  history((await ok("history", { id })).json, "history");
  const snapped = (await ok("snapshot", { id })).json;
  history(snapped, "snapshot");
  renamed((await ok("rename", { id, name: "Renamed" })).json, "rename");
  const zip = await ok("download", { id, form: "zip" });
  file(zip, "application/zip", "download zip");
  assert.ok(zip.filename!.endsWith(".zip"));
  file(await ok("download", { id, form: "yaml" }), "application/yaml", "download yaml");
  summary(take(await ok("restore", { id, version, snapshot: snapped.snapshots[0].name })), "restore");
  const copy = (await ok("copy", { id, snapshot: snapped.snapshots[0].name })).json;
  summary(copy, "copy");
  assert.notEqual(copy.id, id);
  deleted((await ok("delete", { id: copy.id })).json, "delete");
  uiState((await ok("ui_state", { id, action: "get" })).json, "ui_state get");
  uiState((await ok("ui_state", { id, action: "set", state: { locked: ["a"] } })).json, "ui_state set");

  const fresh = (await ok("new", { template: "minimal", name: "Fresh" })).json;
  summary(fresh, "new");
  summary((await ok("upload", { filename: "u.yaml" }, new TextEncoder().encode(minimalText("Up")))).json, "upload");
  const withFont = (await ok("assets", { id: fresh.id, version: fresh.version, filename: "C.ttf", font: "big", size: "30%r" }, read(CHIVO))).json;
  summary(withFont, "assets");
  buildResult((await ok("build", { id: fresh.id, version: withFont.version, device: "fr955" })).json, "build");

  // refusals: one shape, whatever the status
  for (const [r, status] of [
    [await client.call("undo", { id, version: 0 }), 409], [await client.call("get", { id: "0".repeat(32) }), 404],
    [await client.call("nosuchop", { id }), 400], [await client.call("inspect", { id, element: "clock" }), 400],
  ] as const) {
    assert.equal(r.status, status, show(r.json));
    refusal(r.json, `refusal ${status}`);
    assert.equal(r.body, undefined);
  }

  // every event announced, and each kind at least once
  const seen = new Set<string>();
  for (const [name, data] of client.events) {
    assert.ok(name in EVENTS, `an event the contract lists: ${name}`);
    EVENTS[name]!(data, `event ${name}`);
    seen.add(name);
  }
  assert.deepEqual([...seen].sort(), ["changed", "created", "deleted", "renamed", "snapshot"]);
  assert.ok(client.events.some(([n, d]) => n === "changed" && d["tab"] === "tab-1"), "a change names its tab");
});

test("the words describe every source and the specs a placeholder takes, by what it reads", async () => {
  const studio = await newStudio();
  const client = new Client(studio);
  const words = (await client.call("vocabulary", {})).json;
  const catalog = await import("../src/catalog.ts");
  // every catalogue path, with its own type, unit, quantity, doc and nullability, and nothing else
  assert.deepEqual(Object.keys(words.source_info).sort(), [...catalog.CATALOG.keys()].sort());
  assert.deepEqual(words.source_info["activity.steps"], { type: "number", unit: null, quantity: null, doc: "steps today", nullable: true });
  assert.deepEqual(words.source_info["weather.temperature"].quantity, "temperature");
  assert.equal(words.source_info["time.clock"].type, "time");
  // the codes as written after the colon, each with what it draws: a clock's, a date's and a duration's differ where they must
  const codes = (kind: string): string[] => words.format_codes[kind].map(([spec]: [string, string]) => spec);
  assert.ok(codes("time").includes("%H") && codes("time").includes("%h") && !codes("time").includes("%Y"), codes("time").join(" "));
  assert.ok(codes("date").includes("%Y") && codes("date").includes("%b") && !codes("date").includes("%H"), codes("date").join(" "));
  assert.ok(codes("duration").includes("%-H") && codes("duration").includes("%S"), codes("duration").join(" "));
  assert.deepEqual(codes("number").slice(0, 3), ["d", "02d", ".1f"]);
  assert.ok(words.format_codes.time.every(([, label]: [string, string]) => label.length > 0));
});

test("a scheme's base, and the roles it inherits from it, are in the globals", async () => {
  const studio = await newStudio();
  const doc = openExample(studio, "examples/analog-custom/face.yaml");
  const { globalsOf } = await import("../src/studio/inspect.ts");
  const schemes = globalsOf(doc.text, (await import("./studio-client.ts")).db).schemes;
  assert.deepEqual(schemes.base, { dark: null, light: "dark", blue: "dark", green: "dark" });
  assert.deepEqual(schemes.inherited, { dark: [], light: ["track"], blue: ["fg", "track"], green: ["fg", "track"] });
  // a derived scheme's colours are what it draws with: its own, then the base's, in the base's order
  assert.deepEqual(schemes.colors["blue"], { bg: "color.darkest_blue", fg: "color.white", track: "color.light_gray" });
  assert.deepEqual(schemes.colors["light"], { bg: "color.white", fg: "color.black", track: "color.light_gray" });
});

test("a key that takes a rule list says which family, and a rule list or an inline font keeps its key's control", async () => {
  const { inspect } = await import("../src/studio/inspect.ts");
  const showcase = readText(SHOWCASE);
  const fields = (path: (string | number)[]): any[] => (inspect(showcase, path, null) as any).fields;
  const dnd = fields(["layouts", "digital", "elements", "dnd_icon"]);
  const color = dnd.find((f) => f.key === "color");
  assert.deepEqual([color.widget, color.rules, color.value], ["color", "color", [{ when: "device.do_not_disturb", value: "color.accent" }, { else: "color.dark" }]]);
  assert.deepEqual(dnd.find((f) => f.key === "visible").rules, "boolean");
  assert.equal(dnd.find((f) => f.key === "size").rules, undefined);
  const gauge = fields(["layouts", "digital", "elements", "steps_bar"]);
  assert.deepEqual(["value", "max"].map((k) => gauge.find((f) => f.key === k)?.rules), ["value", "value"]);
  // an inline font is the font control's, not a YAML box
  const inline = minimalText() + "  own:\n    type: text\n    text: X\n    font: { source: assets/A.ttf, size: 12%r }\n";
  const font = (inspect(inline, ["elements", "own"], null) as any).fields.find((f: any) => f.key === "font");
  assert.deepEqual([font.widget, font.value], ["font", { source: "assets/A.ttf", size: "12%r" }]);
});
