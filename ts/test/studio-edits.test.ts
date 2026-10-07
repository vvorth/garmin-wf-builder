// The editor's edits through the worker's document: colours, schemes,
// slots and hand sets, each one gated patch.
import assert from "node:assert/strict";
import { test } from "node:test";
import * as complications from "../src/complications.ts";
import { Bag } from "../src/diagnostics.ts";
import { automaticName, isAutomatic, userNames } from "../src/edit/colors.ts";
import { loadText } from "../src/edit/gate.ts";
import { presets } from "../src/edit/hands.ts";
import { indexFor, Refused } from "../src/edit/spans.ts";
import { runDesign } from "../src/lint.ts";
import { decodePng } from "../src/png.ts";
import * as starters from "../src/starters.ts";
import { bundle } from "../src/studio/bundle.ts";
import { type Document, frameKey, type Studio } from "../src/studio/document.ts";
import { inspect, vocabulary } from "../src/studio/inspect.ts";
import { Client, dataOf, newStudio, openExample, SHOWCASE } from "./studio-client.ts";

const SLOT_GAUGE = "examples/features/slot-gauge/face.yaml";

function make(studio: Studio, text: string | null = null, template = "minimal"): Document {
  return studio.create(bundle("T", text ?? starters.instantiate(template, "T")), "new");
}

const edit = (doc: Document, op: Record<string, unknown>): void => {
  doc.edit(op, doc.version);
};
const palette = (doc: Document): any => dataOf(doc).resources.palette;
const colorOf = (doc: Document, element: string): string => dataOf(doc).elements[element].color;
const pick = (doc: Document, element: string, value: string): void => edit(doc, { op: "use_color", path: ["elements", element, "color"], value });
const minimal = (): string => starters.instantiate("minimal", "T");

/** `work` refused with a message matching `reason`, and the face left as it was. */
function refusedAlone(doc: Document, cases: [RegExp, () => void][]): void {
  const before = [doc.text, doc.version];
  for (const [reason, work] of cases) assert.throws(work, (e: Error) => e instanceof Refused && reason.test(e.message), String(reason));
  assert.deepEqual([doc.text, doc.version], before);
}

// -- colours --

test("the editor names a colour after its value", () => {
  assert.equal(automaticName("#ff5500"), "international_orange");
  assert.equal(automaticName("#FF8000"), "cFF8000");
  assert.ok(isAutomatic("cFF8000", "#FF8000") && isAutomatic("red_2", "#FF0000"));
  assert.ok(!isAutomatic("accent", "#FF0000") && !isAutomatic("cFF8000_dim", "#FF8000"));
});

test("one of the 64 is added under its name with its label", async () => {
  const doc = make(await newStudio());
  pick(doc, "clock", "#FF0000");
  assert.equal(colorOf(doc, "clock"), "color.red");
  assert.deepEqual(palette(doc).red, { value: "#FF0000", label: "Red" });
  assert.equal((doc.history()["states"] as any[])[0].label, "set elements.clock.color to color.red (adds red)");
});

test("a custom colour is a c swatch, and one of the 64 keeps its name", async () => {
  const doc = make(await newStudio());
  pick(doc, "clock", "#FF8000");
  assert.equal(colorOf(doc, "clock"), "color.cFF8000");
  assert.equal(palette(doc).cFF8000, "#FF8000");
  pick(doc, "seconds", "#ff5500");
  assert.equal(colorOf(doc, "seconds"), "color.international_orange");
});

test("a colour the palette holds is reused whatever its name", async () => {
  const doc = make(await newStudio());
  const before = palette(doc);
  pick(doc, "clock", "#000");
  assert.equal(colorOf(doc, "clock"), "color.bg");
  assert.deepEqual(palette(doc), before);
});

test("a name taken by another colour or a role gets a suffix", async () => {
  const studio = await newStudio();
  let doc = make(studio, minimal().replace('    dim: "#AAAAAA"\n', '    dim: "#AAAAAA"\n    red: "#CC0000"\n'));
  pick(doc, "clock", "#FF0000");
  assert.equal(colorOf(doc, "clock"), "color.red_2");
  doc = make(studio, minimal() + "\nconfig:\n  accent_color:\n    role: red\n    default: color.bg\n    choices: [color.bg, color.text]\n");
  pick(doc, "clock", "#FF0000");
  assert.equal(colorOf(doc, "clock"), "color.red_2");
});

test("an automatic swatch goes with its last user, an author's never", async () => {
  const doc = make(await newStudio());
  pick(doc, "clock", "#FF8000");
  pick(doc, "seconds", "#FF8000");
  assert.ok("dim" in palette(doc));
  pick(doc, "clock", "#FF0000");
  assert.ok("cFF8000" in palette(doc));
  pick(doc, "seconds", "#FF0000");
  assert.ok(!("cFF8000" in palette(doc)));
  assert.ok("dim" in palette(doc));
});

test("an automatic swatch follows its value, label and all", async () => {
  const doc = make(await newStudio());
  pick(doc, "clock", "#FF0000");
  edit(doc, { op: "set_swatch", name: "red", value: "#AA0000" });
  assert.equal(colorOf(doc, "clock"), "color.bright_red");
  assert.deepEqual(palette(doc).bright_red, { value: "#AA0000", label: "Bright Red" });
  edit(doc, { op: "set_swatch", name: "bright_red", value: "#123456" });
  assert.equal(colorOf(doc, "clock"), "color.c123456");
  assert.deepEqual(palette(doc).c123456, { value: "#123456" });
});

test("an author's swatch keeps its name when its value changes", async () => {
  const doc = make(await newStudio());
  edit(doc, { op: "set_swatch", name: "dim", value: "#555555" });
  assert.equal(palette(doc).dim, "#555555");
  assert.equal(colorOf(doc, "seconds"), "color.dim");
});

test("the rename reaches only the whole name", async () => {
  const text = minimal().replace('    dim: "#AAAAAA"\n', '    dim: "#AAAAAA"\n    cFF8000: "#FF8000"\n    cFF8000_dim: "#AA5500"\n')
    .replace("    color: color.dim\n", '    color: "time.second > 30 ? color.cFF8000 : color.cFF8000_dim"\n');
  const doc = make(await newStudio(), text);
  edit(doc, { op: "set_swatch", name: "cFF8000", value: "#FF5500" });
  assert.equal(colorOf(doc, "seconds"), "time.second > 30 ? color.international_orange : color.cFF8000_dim");
  assert.ok("international_orange" in palette(doc) && "cFF8000_dim" in palette(doc));
  assert.ok(!("cFF8000" in palette(doc)));
});

test("remove unused keeps what the launcher icon reads", async () => {
  const doc = make(await newStudio());
  pick(doc, "seconds", "#FF0000");
  edit(doc, { op: "add_swatch", value: "#123456" });
  edit(doc, { op: "remove_unused" });
  assert.deepEqual(Object.keys(palette(doc)).sort(), ["bg", "red", "text"]);
  assert.throws(() => edit(doc, { op: "remove_unused" }), /every colour in the palette is in use/);
});

test("a colour already held is not added twice", async () => {
  const doc = make(await newStudio());
  assert.throws(() => edit(doc, { op: "add_swatch", value: "#000000" }), /already, as bg/);
});

test("colour refusals leave the face alone", async () => {
  const doc = make(await newStudio(), minimal() + '\ntheme:\n  schemes:\n    dark:\n      colors: { ink: "#FFFFFF" }\n'
    + "\nconfig:\n  style:\n    default: d\n    choices: { d: { scheme: dark } }\n");
  refusedAlone(doc, [
    [/color\.dim/, () => edit(doc, { op: "remove", path: ["resources", "palette", "dim"] })],
    [/both a palette swatch and a colour role/, () => edit(doc, { op: "rename", path: ["resources", "palette", "dim"], to: "ink", prefix: "color." })],
    [/no colour called/, () => edit(doc, { op: "set_swatch", name: "nope", value: "#000000" })],
    [/is not a colour/, () => pick(doc, "clock", "orange-ish")],
  ]);
});

test("the panel says who uses each colour", async () => {
  const doc = make(await newStudio());
  const byName = Object.fromEntries(((doc.summary()["globals"] as any).palette as any[]).map((p) => [p.name, p]));
  assert.deepEqual(byName.bg.used_by, ["background"]);
  assert.deepEqual(byName.dim.used_by, ["seconds"]);
  assert.ok(!byName.dim.automatic);
  assert.ok(byName.bg.launcher);
  assert.deepEqual(userNames(indexFor(doc.text), "nope"), []);
});

test("the colour axes are written as lists", async () => {
  const doc = make(await newStudio());
  edit(doc, { op: "set", path: ["config"], value: { accent_color: { default: "color.text", choices: ["color.text", "color.dim"] } } });
  const axes = (doc.summary()["globals"] as any).axes;
  assert.deepEqual(axes.accent_color, { default: "color.text", choices: ["color.text", "color.dim"], raw: ["color.text", "color.dim"], role: "accent", own_role: false });
  assert.equal(axes.data_color, null);
  assert.ok((doc.summary()["globals"] as any).roles.includes("accent"));
  edit(doc, { op: "set", path: ["config", "accent_color", "choices"], value: ["color.text", "color.dim", "color.bg"] });
  assert.equal((doc.summary()["globals"] as any).axes.accent_color.choices.at(-1), "color.bg");
  assert.throws(() => edit(doc, { op: "set", path: ["config", "accent_color", "default"], value: "color.nope" }), Refused);
});

test("the vocabulary names the 64", async () => {
  const client = await Client.open();
  const mip = (await client.call("vocabulary")).json.mip;
  assert.equal(mip.length, 64);
  assert.deepEqual(mip[0], { name: "white", value: "#FFFFFF", label: "White" });
});

// -- schemes --

function switchable(studio: Studio): Document {
  const doc = make(studio);
  edit(doc, { op: "make_switchable", names: ["bg", "text"], scheme: "dark" });
  return doc;
}

test("colours made switchable keep their names and a style picks them", async () => {
  const doc = switchable(await newStudio());
  const d = dataOf(doc);
  assert.deepEqual(d.resources.palette, { dim: "#AAAAAA" });
  assert.deepEqual(d.theme, { schemes: { dark: { colors: { bg: "#000000", text: "#FFFFFF" } } } });
  assert.deepEqual(d.config.style, { default: "dark", choices: { dark: { scheme: "dark" } } });
  assert.equal(d.elements.clock.color, "color.text");
  assert.ok(doc.text.includes('theme:\n  schemes:\n    dark:\n      colors:\n        bg: "#000000"\n'));
  assert.notEqual(doc.analysis().face, null);
});

test("a scheme is added, renamed and deleted with its styles", async () => {
  const doc = switchable(await newStudio());
  edit(doc, { op: "add_scheme", name: "light" });
  assert.deepEqual(dataOf(doc).theme.schemes.light, { colors: { bg: "#000000", text: "#FFFFFF" } });
  assert.deepEqual(dataOf(doc).config.style.choices.light, { scheme: "light" });
  edit(doc, { op: "rename_scheme", name: "light", to: "day" });
  assert.deepEqual(dataOf(doc).config.style.choices.light, { scheme: "day" });
  edit(doc, { op: "delete_scheme", name: "day" });
  assert.deepEqual(Object.keys(dataOf(doc).theme.schemes), ["dark"]);
  assert.deepEqual(Object.keys(dataOf(doc).config.style.choices), ["dark"]);
});

test("a new scheme on a face with layouts gets a style per layout", async () => {
  const doc = openExample(await newStudio(), SHOWCASE);
  edit(doc, { op: "add_scheme", name: "mint", like: "navy" });
  const choices = dataOf(doc).config.style.choices;
  assert.deepEqual(Object.fromEntries(Object.entries(choices).filter(([k]) => k.endsWith("_mint"))), {
    analog_mint: { layout: "analog", scheme: "mint" }, digital_mint: { layout: "digital", scheme: "mint" }, roman_mint: { layout: "roman", scheme: "mint" },
  });
  assert.deepEqual(dataOf(doc).theme.schemes.mint.colors, dataOf(doc).theme.schemes.navy.colors);
});

test("a role is added, renamed and deleted in every scheme", async () => {
  const doc = switchable(await newStudio());
  edit(doc, { op: "add_scheme", name: "light" });
  edit(doc, { op: "add_role", name: "hot", value: "#ff5500" });
  assert.deepEqual(Object.values(dataOf(doc).theme.schemes).map((s: any) => s.colors.hot), ["#FF5500", "#FF5500"]);
  edit(doc, { op: "rename_role", name: "text", to: "ink" });
  assert.ok(Object.values(dataOf(doc).theme.schemes).every((s: any) => "ink" in s.colors && !("text" in s.colors)));
  assert.equal(dataOf(doc).elements.clock.color, "color.ink");
  edit(doc, { op: "delete_role", name: "hot" });
  assert.ok(Object.values(dataOf(doc).theme.schemes).every((s: any) => !("hot" in s.colors)));
});

test("removing the schemes keeps one scheme's colours and drops scheme-only styles", async () => {
  const doc = switchable(await newStudio());
  edit(doc, { op: "add_scheme", name: "light" });
  edit(doc, { op: "remove_theme", keep: "dark" });
  const d = dataOf(doc);
  assert.ok(!("theme" in d) && !("config" in d));
  assert.deepEqual(d.resources.palette, { dim: "#AAAAAA", bg: "#000000", text: "#FFFFFF" });
  assert.notEqual(doc.analysis().face, null);
});

test("removing the showcase's schemes keeps every layout style and warns of the copies", async () => {
  const doc = openExample(await newStudio(), SHOWCASE);
  const before = dataOf(doc).config.style.choices;
  edit(doc, { op: "remove_theme", keep: "dark" });
  const d = dataOf(doc);
  const choices = d.config.style.choices;
  assert.deepEqual(Object.keys(choices), Object.keys(before));
  assert.ok(Object.entries(choices).every(([k, c]: [string, any]) => !("scheme" in c) && c.layout === before[k].layout));
  assert.equal(d.config.style.default, "digital_dark");
  const p = d.resources.palette;
  assert.deepEqual([p.bg, p.fg, p.notify], ["#000000", "#FFFFFF", "#000000"]);
  const lints = new Bag();
  runDesign(doc.analysis().face!, lints);
  assert.deepEqual(lints.items.filter((x) => x.code === "duplicate-style").map((x) => x.message.split(":")[0]).sort(), [
    "config.style.choices.analog_crimson", "config.style.choices.analog_light", "config.style.choices.digital_light", "config.style.choices.roman_crimson",
  ]);
});

test("scheme refusals leave the face alone", async () => {
  const studio = await newStudio();
  const doc = switchable(studio);
  refusedAlone(doc, [
    [/dim names a colour already/, () => edit(doc, { op: "rename_role", name: "text", to: "dim" })],
    [/only scheme/, () => edit(doc, { op: "delete_scheme", name: "dark" })],
    [/used by/, () => edit(doc, { op: "delete_role", name: "text" })],
    [/is a palette colour/, () => edit(doc, { op: "add_role", name: "dim", value: "#FFFFFF" })],
    [/has schemes already/, () => edit(doc, { op: "make_switchable", names: ["dim"], scheme: "other" })],
    [/no scheme called/, () => edit(doc, { op: "remove_theme", keep: "nope" })],
  ]);
  const plain = make(studio);
  assert.throws(() => edit(plain, { op: "make_switchable", names: ["nope"], scheme: "dark" }), /not a palette colour/);
});

test("a role with no style to pick its scheme says so in the author's words", () => {
  const text = minimal().replace("    color: color.text\n", "    color: color.fg\n") + '\ntheme:\n  schemes:\n    dark:\n      colors: { fg: "#FFFFFF" }\n';
  assert.deepEqual(loadText("face.yaml", text, () => false).errors.map((e) => e.message), [
    "color: color.fg is a role of 'theme: schemes:', but no 'config: style:' entry picks a scheme",
  ]);
});

// -- slots --

test("every complication type has a name for people and a group", () => {
  assert.deepEqual(new Set(complications.PRESENTATION.keys()), new Set(complications.TYPES.keys()));
  const labels = [...complications.TYPES.keys()].map(complications.label);
  assert.equal(new Set(labels).size, labels.length);
  assert.deepEqual(new Set([...complications.TYPES.keys()].map(complications.category)), new Set(complications.CATEGORIES));
  assert.equal(complications.label("floors_climbed"), "Floors climbed");
});

test("the vocabulary offers each type with its icon and sample", () => {
  const types = Object.fromEntries((vocabulary()["complication_types"] as any[]).map((t) => [t.name, t]));
  assert.equal(Object.keys(types).length, 42);
  assert.deepEqual(types["heart_rate"], { name: "heart_rate", label: "Heart rate", category: "health", icon: "heart", sample: "72" });
  assert.equal(types["wheelchair_pushes"].sample, null);
  assert.equal((vocabulary()["icon_glyphs"] as any).heart, 0xF02D1);
});

test("a slot is added with a data element drawing it", async () => {
  const doc = make(await newStudio());
  edit(doc, { op: "add_slot", name: "top", default: "heart_rate" });
  const d = dataOf(doc);
  assert.deepEqual(d.config.slots, { top: { default: "heart_rate", choices: "any" } });
  assert.equal(d.elements.new_data.slot, "top");
  assert.ok(doc.text.includes("config:\n  slots:\n    top:\n      default: heart_rate\n"));
  refusedAlone(doc, [
    [/already/, () => edit(doc, { op: "add_slot", name: "top", default: "steps" })],
    [/not a complication type/, () => edit(doc, { op: "add_slot", name: "other", default: "nope" })],
  ]);
});

function frameLayers(doc: Document, picks: [string, string][] = []): [Record<string, any>, any] {
  const frame = doc.frame(frameKey({ device: "fr955", picks })) as any;
  return [Object.fromEntries(frame.layers.map((l: any) => [l.id, l])), frame];
}

test("the face is drawn showing a slot's pick", async () => {
  const doc = openExample(await newStudio(), SLOT_GAUGE);
  const [plain, frame] = frameLayers(doc);
  const [battery, picked] = frameLayers(doc, [["top", "battery"]]);
  assert.notEqual(picked.frame, frame.frame);
  assert.notDeepEqual(battery["top_ring"].ops, plain["top_ring"].ops);
  assert.notDeepEqual(battery["top_reading"].ops, plain["top_reading"].ops);
  const [, ignored] = frameLayers(doc, [["top", "sunrise"]]);
  assert.equal(ignored.frame, frame.frame);
});

test("a slot shown with no scale draws no gauge", async () => {
  const doc = openExample(await newStudio(), SLOT_GAUGE);
  const [plain] = frameLayers(doc);
  const [scaled] = frameLayers(doc, [["right", "battery"]]);
  assert.notDeepEqual(plain["right_needle"].ops, scaled["right_needle"].ops);
});

test("a data element's icon is edited and format is not offered", async () => {
  const doc = openExample(await newStudio(), SHOWCASE);
  const path = indexFor(doc.text).elements().find((e) => e.name === "left_register")!.path;
  const fields = Object.fromEntries((inspect(doc.text, path, null)["fields"] as any[]).map((f) => [f.key, f]));
  assert.equal(fields["icon"].widget, "object");
  assert.deepEqual(Object.fromEntries(fields["icon"].children.map((c: any) => [c.key, c.widget])), { size: "length", position: "enum", gap: "length", color: "color" });
  assert.ok(!("format" in fields));
});

// -- hand sets --

const sets = (doc: Document): any => dataOf(doc).resources.hand_sets;
const handsElements = (doc: Document): any => Object.fromEntries(Object.entries(dataOf(doc).elements).filter(([, v]: [string, any]) => v.type === "hands"));

test("the presets are the four decided", () => {
  assert.deepEqual([...presets().keys()], ["classic", "baton", "dauphine", "subdial"]);
});

test("each preset loads into a face in its colours", async () => {
  const studio = await newStudio();
  for (const preset of ["classic", "baton", "dauphine", "subdial"]) {
    const doc = make(studio);
    edit(doc, { op: "add_hand_set", name: "dial", preset });
    assert.notEqual(doc.analysis().face, null);
    assert.deepEqual(doc.analysis().bag.errors, []);
    for (const hand of Object.values(sets(doc).dial) as any[]) assert.equal(hand.color, "color.text");
    assert.deepEqual(handsElements(doc), { new_hands: { type: "hands", at: { anchor: "center" }, set: "dial" } });
  }
});

test("a second set is not placed again, and points are one a line", async () => {
  const doc = make(await newStudio());
  edit(doc, { op: "add_hand_set", name: "dial", preset: "dauphine" });
  edit(doc, { op: "add_hand_set", name: "small", preset: "subdial" });
  assert.deepEqual(Object.keys(handsElements(doc)), ["new_hands"]);
  assert.ok(doc.text.includes("          - type: polygon\n            points:\n              - { dy: 5%r }\n"));
});

test("the accent is used where the face has one", async () => {
  const doc = make(await newStudio(), null, "analog");
  edit(doc, { op: "add_hand_set", name: "dial", preset: "baton" });
  assert.equal(sets(doc).dial.second.color, "color.accent");
});

test("a set is duplicated, renamed with its elements, and deleted when unused", async () => {
  const doc = make(await newStudio());
  edit(doc, { op: "add_hand_set", name: "dial", preset: "classic" });
  edit(doc, { op: "duplicate_hand_set", name: "dial" });
  assert.deepEqual(sets(doc).dial_copy, sets(doc).dial);
  edit(doc, { op: "rename_hand_set", name: "dial", to: "main" });
  assert.equal(handsElements(doc).new_hands.set, "main");
  edit(doc, { op: "delete_hand_set", name: "dial_copy" });
  assert.deepEqual(Object.keys(sets(doc)), ["main"]);
});

test("hand set refusals leave the face alone", async () => {
  const doc = make(await newStudio());
  edit(doc, { op: "add_hand_set", name: "dial", preset: "classic" });
  refusedAlone(doc, [
    [/new_hands places the hand set dial/, () => edit(doc, { op: "delete_hand_set", name: "dial" })],
    [/already/, () => edit(doc, { op: "add_hand_set", name: "dial", preset: "baton" })],
    [/no preset called/, () => edit(doc, { op: "add_hand_set", name: "other", preset: "nope" })],
    [/not a hand set name/, () => edit(doc, { op: "rename_hand_set", name: "dial", to: "1x" })],
    [/no hand set called/, () => edit(doc, { op: "duplicate_hand_set", name: "nope" })],
  ]);
});

test("the panel lists each set with its lines and users", async () => {
  const doc = openExample(await newStudio(), SHOWCASE);
  const byName = Object.fromEntries(((doc.summary()["globals"] as any).hands as any[]).map((h) => [h.name, h]));
  assert.deepEqual(new Set(Object.keys(byName)), new Set(["classic", "vintage"]));
  const classic = byName["classic"];
  const lines = doc.text.split("\n");
  assert.equal(lines[classic.line - 1]!.trim(), "classic:");
  assert.ok(lines[classic.end - 1]!.trim());
  assert.equal(lines.slice(classic.end).find((l: string) => l.trim() && !l.trim().startsWith("#"))!.trim(), "vintage:");
  assert.deepEqual(new Set(Object.keys(classic.hands)), new Set(["hour", "minute", "second"]));
  assert.ok(classic.placed_by.length > 0);
});

test("a hands element's set is a choice of the declared sets", async () => {
  const doc = make(await newStudio());
  edit(doc, { op: "add_hand_set", name: "dial", preset: "classic" });
  const path = indexFor(doc.text).elements().find((e) => e.name === "new_hands")!.path;
  const fields = Object.fromEntries((inspect(doc.text, path, null)["fields"] as any[]).map((f) => [f.key, f]));
  assert.equal(fields["set"].widget, "handset");
});

test("a set is drawn alone", async () => {
  const client = await Client.open();
  const doc = make(client.studio);
  edit(doc, { op: "add_hand_set", name: "dial", preset: "baton" });
  const got = await client.call("handset", { id: doc.id, name: "dial", device: "fr955", scale: 2 });
  assert.equal(got.status, 200);
  assert.equal(got.type, "image/png");
  const image = decodePng(got.body!)!;
  assert.ok(image.width < 2 * 260 && image.height < 2 * 260);
  // cropped to its ink: some pixel on each edge is drawn
  const alpha = (x: number, y: number): number => image.pixels[(y * image.width + x) * 4 + 3]!;
  assert.ok([...Array(image.width).keys()].some((x) => alpha(x, 0)) && [...Array(image.height).keys()].some((y) => alpha(0, y)));
  const missing = await client.call("handset", { id: doc.id, name: "nope", device: "fr955" });
  assert.equal(missing.status, 400);
  assert.match(missing.json.error, /no hand set called nope/);
});
