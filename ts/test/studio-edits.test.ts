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
import { type Document, frameKey, LABEL_WIDTH, type Studio } from "../src/studio/document.ts";
import { inspect, vocabulary } from "../src/studio/inspect.ts";
import { Client, dataOf, db, newStudio, openExample, read, SHOWCASE, versionOf } from "./studio-client.ts";
import { addLayoutLabel, addLayoutSteps } from "../app/values.ts";
import { globalsOf } from "../src/studio/inspect.ts";

/** + Layout as the page sends it: the steps it composes from the face's styles, as one batch. */
function addLayout(doc: Document, name: string): void {
  const styles = globalsOf(doc.text, db).styles;
  doc.batch({ op: "batch", label: addLayoutLabel(name, styles), edits: addLayoutSteps(name, styles) }, doc.version);
}

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
    [/the colour dim is used by 1 element: seconds/, () => edit(doc, { op: "remove", path: ["resources", "palette", "dim"] })],
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

test("+ Layout on a face whose styles name only schemes points every style at the new layout", async () => {
  const doc = switchable(await newStudio());
  edit(doc, { op: "add_scheme", name: "light" });
  assert.deepEqual(dataOf(doc).config.style.choices, { dark: { scheme: "dark" }, light: { scheme: "light" } });
  const states = (doc.history()["total"] as number);
  addLayout(doc, "alt");
  assert.deepEqual(dataOf(doc).config.style.choices, { dark: { scheme: "dark", layout: "alt" }, light: { scheme: "light", layout: "alt" } });
  assert.deepEqual(dataOf(doc).layouts, { alt: {} });
  assert.notEqual(doc.analysis().face, null);
  assert.equal(doc.history()["total"], states + 1);
  assert.equal((doc.history()["states"] as any[])[0].label, "add the layout alt, picked by dark, light");
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
  assert.equal((vocabulary()["icon_glyphs"] as any).heart, 0xF05F6);
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

test("a colour or font something uses is not deleted", async () => {
  const studio = await newStudio();
  const doc = make(studio, minimal().replace("resources:\n", "resources:\n  fonts:\n    big:\n      source: assets/OpenSans-Regular.ttf\n      size: 20%r\n    spare:\n      source: assets/OpenSans-Regular.ttf\n      size: 10%r\n")
    .replace("font: FONT_NUMBER_HOT", "font: font.big"));
  doc.commit(doc.text, new Map([["assets/OpenSans-Regular.ttf", read("ts/test/fixtures/slice/assets/OpenSans-Regular.ttf")]]), "font file", doc.version);
  assert.notEqual(doc.analysis().face, null);
  refusedAlone(doc, [
    [/^the colour text is used by 1 element: clock; change them first$/, () => edit(doc, { op: "remove", path: ["resources", "palette", "text"] })],
    [/^the colour bg is used by 1 element: background; change them first$/, () => edit(doc, { op: "remove", path: ["resources", "palette", "bg"] })],
    [/^the font big is used by 1 element: clock; change them first$/, () => edit(doc, { op: "remove", path: ["resources", "fonts", "big"] })],
  ]);
  edit(doc, { op: "set", path: ["elements", "seconds", "color"], value: "color.text" });
  refusedAlone(doc, [[/^the colour text is used by 2 elements: clock, seconds; change them first$/, () => edit(doc, { op: "remove", path: ["resources", "palette", "text"] })]]);
  edit(doc, { op: "remove", path: ["resources", "fonts", "spare"] });
  assert.deepEqual(Object.keys(dataOf(doc).resources.fonts), ["big"]);
  // dim lost its last user above, so it goes
  edit(doc, { op: "remove", path: ["resources", "palette", "dim"] });
  assert.deepEqual(Object.keys(dataOf(doc).resources.palette), ["bg", "text"]);
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
  assert.deepEqual(Object.fromEntries(fields["icon"].children.map((c: any) => [c.key, c.widget])), { size: "length", position: "enum", gap: "length", color: "color", upright: "bool" });
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
  assert.ok(doc.text.includes("          blade:\n            type: polygon\n            points:\n              - { dy: 5%r }\n"), doc.text);
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

// -- the gate covers the resolve --

/** The minimal starter's background with a `pt` width: legal to load, impossible to lay out (no font in scope). */
function withPtWidth(text: string): string {
  const typed = text.replace("size: { width: 100%, height: 100% }", "size: { width: 4pt, height: 100% }");
  assert.notEqual(typed, text);
  return typed;
}

const errorsOf = (summary: any): any[] => summary.diagnostics.filter((d: any) => d.severity === "error");

test("a pt length with no font in scope is refused, not committed", async () => {
  const doc = make(await newStudio());
  refusedAlone(doc, [[/pt units need a reference font/,
    () => edit(doc, { op: "set", element: ["static", "background"], path: ["size", "width"], value: "4pt" })]]);
  assert.deepEqual(errorsOf(doc.summary()), []);
  assert.deepEqual(doc.summary()["targets"], ["fenix8solar47mm", "fenix8solar51mm", "fr955"]);
});

test("a pt length typed in the YAML is recorded, reported on its line, and undone", async () => {
  const client = await Client.open();
  const doc = make(client.studio);
  const typed = withPtWidth(doc.text);
  const line = typed.split("\n").findIndex((l) => l.startsWith("  background:")) + 1;
  assert.equal((await client.call("text", { id: doc.id, version: doc.version, text: typed })).status, 200);
  const got = await client.call("get", { id: doc.id });
  assert.equal(got.status, 200);
  assert.equal(got.json.text, typed);
  assert.ok(got.json.loads);
  const errors = errorsOf(got.json);
  assert.ok(errors.length > 0 && errors.every((d) => /pt units need a reference font/.test(d.message)), JSON.stringify(errors));
  assert.equal(errors[0].line, line);
  assert.deepEqual(got.json.targets, []);
  const frame = await client.call("frame", { id: doc.id, device: "fenix8solar47mm" });
  assert.equal(frame.status, 400);
  assert.match(frame.json.error, /not drawn/);
  const undone = await client.call("undo", { id: doc.id, version: got.json.version });
  assert.equal(undone.status, 200);
  assert.deepEqual(errorsOf(undone.json), []);
  assert.equal(undone.json.targets.length, 3);
});

test("the cover of a face that does not lay out is no picture, not a crash", async () => {
  const client = await Client.open();
  const doc = make(client.studio);
  doc.replaceText(withPtWidth(doc.text), doc.version);
  assert.equal(doc.cover(), null);
  assert.equal((await client.call("cover", { id: doc.id })).status, 404);
});

test("a drag on a face that does not lay out is refused with the reason", async () => {
  const doc = make(await newStudio());
  doc.replaceText(withPtWidth(doc.text), doc.version);
  assert.throws(() => doc.drag("clock", { kind: "move", dx: 5, dy: 0 }, "fenix8solar47mm", "auto", doc.version),
    (e: Error) => e instanceof Refused && /pt units need a reference font/.test(e.message));
});

test("a target the face cannot draw on is refused with the compiler's reason", async () => {
  const doc = openExample(await newStudio(), SHOWCASE);
  const targets = dataOf(doc).build.targets;
  assert.ok(!targets.includes("fr255"));
  refusedAlone(doc, [[/'font: font\.romandial' has no usable face on fr255/,
    () => edit(doc, { op: "set", path: ["build", "targets"], value: [...targets, "fr255"] })]]);
  assert.deepEqual(errorsOf(doc.summary()), []);
});

test("a font file that does not bake is refused, not stored", async () => {
  const doc = make(await newStudio());
  const before = [doc.text, doc.version, Object.keys(doc.head.assets)];
  // not a font at all: refused by its first bytes
  assert.throws(() => doc.addAsset("bad.ttf", new TextEncoder().encode("not a font"), null, doc.version, ["bad", "10%r"]),
    (e: Error) => e instanceof Refused && /not a TrueType or OpenType font file/.test(e.message));
  // an sfnt signature over garbage: refused by the bake, through the gate
  const garbage = new Uint8Array([0x4f, 0x54, 0x54, 0x4f, ...new TextEncoder().encode("not a font, just the signature")]);
  assert.throws(() => doc.addAsset("bad.otf", garbage, null, doc.version, ["bad", "10%r"]),
    (e: Error) => e instanceof Refused && /add the font bad from assets\/bad\.otf: /.test(e.message));
  assert.deepEqual([doc.text, doc.version, Object.keys(doc.head.assets)], before);
});

// -- the aod scope --

test("an edit in the aod scope writes the element's aod: block, for the keys its kind may restyle", async () => {
  const doc = make(await newStudio());
  const clock = ["elements", "clock"];
  edit(doc, { op: "set", element: clock, path: ["visible"], value: false, scope: "aod" });
  assert.deepEqual(dataOf(doc).elements.clock.aod, { visible: false });
  edit(doc, { op: "set", element: clock, path: ["color"], value: "color.dim", scope: "aod" });
  assert.deepEqual(dataOf(doc).elements.clock.aod, { visible: false, color: "color.dim" });
  assert.equal((doc.history()["states"] as any[])[0].label, "set elements.clock.aod.color to color.dim");
  edit(doc, { op: "set", element: clock, path: ["dim"], value: 0.5, scope: "aod" });
  assert.equal(dataOf(doc).elements.clock.aod.dim, 0.5);
  refusedAlone(doc, [
    [/^at\.dy cannot be restyled in AOD on a text; aod: takes color, font, text, outline, visible, dim$/,
      () => edit(doc, { op: "set", element: clock, path: ["at", "dy"], value: "1px", scope: "aod" })],
    [/^thickness cannot be restyled in AOD on a text/, () => edit(doc, { op: "set", element: clock, path: ["thickness"], value: "1px", scope: "aod" })],
    [/not all, device, shape, display or aod/, () => edit(doc, { op: "set", element: clock, path: ["color"], value: "color.dim", scope: "asleep" })],
  ]);
  // a remove in the aod scope prunes the emptied block
  edit(doc, { op: "remove", element: clock, path: ["color"], scope: "aod" });
  edit(doc, { op: "remove", element: clock, path: ["dim"], scope: "aod" });
  assert.deepEqual(dataOf(doc).elements.clock.aod, { visible: false });
  edit(doc, { op: "remove", element: clock, path: ["visible"], scope: "aod" });
  assert.ok(!("aod" in dataOf(doc).elements.clock));
  assert.notEqual(doc.analysis().face, null);
});

// -- layouts and styles --

const layoutsOf = (doc: Document): string[] => Object.keys(dataOf(doc).layouts);
const stylesOf = (doc: Document): any => dataOf(doc).config.style;

test("a layout is renamed with every style naming it", async () => {
  const doc = openExample(await newStudio(), SHOWCASE);
  const before = dataOf(doc).layouts.analog;
  edit(doc, { op: "rename_layout", name: "analog", to: "classic" });
  assert.deepEqual(layoutsOf(doc), ["classic", "digital", "roman"]);
  assert.deepEqual(dataOf(doc).layouts.classic, before);
  const choices = stylesOf(doc).choices;
  assert.deepEqual(Object.entries(choices).filter(([, c]: [string, any]) => c.layout === "classic").map(([k]) => k), ["analog_dark", "analog_light", "analog_crimson"]);
  assert.ok(!Object.values(choices).some((c: any) => c.layout === "analog"));
  assert.equal(doc.head.label, "rename the layout analog to classic");
  assert.notEqual(doc.analysis().face, null);
  refusedAlone(doc, [
    [/not a name/, () => edit(doc, { op: "rename_layout", name: "classic", to: "1x" })],
    [/already exists/, () => edit(doc, { op: "rename_layout", name: "classic", to: "digital" })],
    [/no layout called nope/, () => edit(doc, { op: "rename_layout", name: "nope", to: "x" })],
  ]);
});

test("a layout is deleted with the styles naming it; the default moves, or the delete is refused naming it", async () => {
  const doc = openExample(await newStudio(), SHOWCASE);
  edit(doc, { op: "delete_layout", name: "roman" });
  assert.deepEqual(layoutsOf(doc), ["analog", "digital"]);
  assert.deepEqual(Object.keys(stylesOf(doc).choices), ["analog_dark", "analog_light", "analog_crimson", "digital_dark", "digital_light"]);
  assert.equal(stylesOf(doc).default, "digital_dark");
  assert.equal(doc.head.label, "delete the layout roman, with the styles roman_dark, roman_crimson");
  assert.notEqual(doc.analysis().face, null);
  refusedAlone(doc, [
    [/the default style digital_dark picks digital/, () => edit(doc, { op: "delete_layout", name: "digital" })],
    [/no style called nope/, () => edit(doc, { op: "delete_layout", name: "digital", also_default: "nope" })],
    [/digital_light picks digital too/, () => edit(doc, { op: "delete_layout", name: "digital", also_default: "digital_light" })],
    [/no layout called nope/, () => edit(doc, { op: "delete_layout", name: "nope" })],
  ]);
  edit(doc, { op: "delete_layout", name: "digital", also_default: "analog_light" });
  assert.deepEqual(layoutsOf(doc), ["analog"]);
  assert.equal(stylesOf(doc).default, "analog_light");
  assert.deepEqual(Object.keys(stylesOf(doc).choices), ["analog_dark", "analog_light", "analog_crimson"]);
  assert.notEqual(doc.analysis().face, null);
  refusedAlone(doc, [[/analog is the last layout, and every style picks it/, () => edit(doc, { op: "delete_layout", name: "analog", also_default: "analog_dark" })]]);
  // a face whose styles do not need a layout: the last one goes, and layouts: with it
  const plain = make(await newStudio());
  addLayout(plain, "only");
  addLayout(plain, "spare");
  edit(plain, { op: "delete_layout", name: "spare" });
  assert.deepEqual(layoutsOf(plain), ["only"]);
  assert.deepEqual(Object.keys(stylesOf(plain).choices), ["only"]);
});

test("a mapping entry is moved among its siblings, its lines with it, in block and flow mappings", async () => {
  const doc = openExample(await newStudio(), SHOWCASE);
  const lines = (t: string): string[] => t.split("\n").sort();
  const before = doc.text;
  edit(doc, { op: "move_key", path: ["config", "style", "choices", "roman_dark"], to: 0 });
  assert.deepEqual(Object.keys(stylesOf(doc).choices), ["roman_dark", "analog_dark", "analog_light", "analog_crimson", "digital_dark", "digital_light", "roman_crimson"]);
  assert.deepEqual(lines(doc.text), lines(before), "the same lines, reordered");
  assert.equal(doc.head.label, "move config.style.choices.roman_dark to position 0");
  // a flow mapping's entry
  edit(doc, { op: "move_key", path: ["config", "style", "choices", "analog_dark", "scheme"], to: 0 });
  assert.deepEqual(Object.keys(stylesOf(doc).choices.analog_dark), ["scheme", "label", "layout"]);
  assert.ok(doc.text.includes("analog_dark: { scheme: dark, label: \"Analog \u00b7 Dark\", layout: analog }"), doc.text.split("\n").find((l) => l.includes("analog_dark:")));
  // the palette, and a slot
  const palette = Object.keys(dataOf(doc).resources.palette);
  edit(doc, { op: "move_key", path: ["resources", "palette", palette[2]!], to: palette.length - 1 });
  assert.deepEqual(Object.keys(dataOf(doc).resources.palette), [...palette.slice(0, 2), ...palette.slice(3), palette[2]]);
  edit(doc, { op: "move_key", path: ["config", "slots", "right_register"], to: 0 });
  assert.deepEqual(Object.keys(dataOf(doc).config.slots), ["right_register", "left_register"]);
  // an element's own key, through the element target
  edit(doc, { op: "move_key", element: ["elements", "left_register"], path: ["color"], to: 1 });
  assert.equal(Object.keys(dataOf(doc).elements.left_register)[1], "color");
  assert.notEqual(doc.analysis().face, null);
  refusedAlone(doc, [
    [/cannot move to position 9/, () => edit(doc, { op: "move_key", path: ["config", "slots", "right_register"], to: 9 })],
    [/is not in the file/, () => edit(doc, { op: "move_key", path: ["config", "slots", "nope"], to: 0 })],
    [/'to' must be a list index/, () => edit(doc, { op: "move_key", path: ["config", "slots", "right_register"] })],
  ]);
  doc.undo(doc.version);
  doc.undo(doc.version);
  doc.undo(doc.version);
  doc.undo(doc.version);
  doc.undo(doc.version);
  assert.equal(doc.text, before);
});

test("the default style is set from the panel as a plain set, and the gate refuses one that names no style", async () => {
  const doc = openExample(await newStudio(), SHOWCASE);
  const setDefault = (name: string): void => {
    doc.batch({ op: "batch", label: `make ${name} the default style`, edits: [{ op: "set", path: ["config", "style", "default"], value: name }] }, doc.version);
  };
  setDefault("analog_light");
  assert.equal(stylesOf(doc).default, "analog_light");
  assert.equal(doc.head.label, "make analog_light the default style");
  refusedAlone(doc, [[/default 'nope' is not one of 'choices:'/, () => setDefault("nope")]]);
});

test("the edits that were only a composition of primitives are gone: add_layout and set_default_style are unknown edits", async () => {
  const doc = openExample(await newStudio(), SHOWCASE);
  refusedAlone(doc, [
    [/unknown edit 'add_layout'/, () => edit(doc, { op: "add_layout", name: "spare" })],
    [/unknown edit 'set_default_style'/, () => edit(doc, { op: "set_default_style", name: "analog_light" })],
  ]);
});

test("the layout and style ops are batch steps", async () => {
  const doc = openExample(await newStudio(), SHOWCASE);
  doc.batch({ op: "batch", label: "reshuffle", edits: [
    { op: "rename_layout", name: "roman", to: "numerals" },
    { op: "move_key", path: ["layouts", "numerals"], to: 0 },
    { op: "set", path: ["config", "style", "default"], value: "roman_dark" },
    { op: "delete_layout", name: "analog" },
  ] }, doc.version);
  assert.deepEqual(layoutsOf(doc), ["numerals", "digital"]);
  assert.equal(stylesOf(doc).default, "roman_dark");
  assert.equal(stylesOf(doc).choices.roman_dark.layout, "numerals");
  assert.equal(doc.head.label, "reshuffle");
  assert.notEqual(doc.analysis().face, null);
});

// -- batches --

const BATCH_STEPS = [
  { op: "set", path: ["elements", "clock", "color"], value: "color.dim" },
  { op: "set", path: ["face", "version"], value: "2.0.0" },
  { op: "set", path: ["elements", "seconds", "color"], value: "color.text" },
];

test("a batch of edits is one change, labelled, and one undo", async () => {
  const doc = make(await newStudio());
  const [change] = doc.batch({ op: "batch", label: "restyle the clock", edits: BATCH_STEPS }, doc.version);
  assert.equal(doc.version, 2);
  assert.equal(change.label, "restyle the clock");
  let d = dataOf(doc);
  assert.deepEqual([d.elements.clock.color, d.face.version, d.elements.seconds.color], ["color.dim", "2.0.0", "color.text"]);
  assert.equal((doc.history()["states"] as any[]).length, 2);
  doc.undo(doc.version);
  d = dataOf(doc);
  assert.deepEqual([d.elements.clock.color, d.face.version, d.elements.seconds.color], ["color.text", "1.0.0", "color.dim"]);
  // no label: the steps' own, joined
  doc.batch({ op: "batch", edits: BATCH_STEPS.slice(0, 2) }, doc.version);
  assert.equal(doc.head.label, "set elements.clock.color to color.dim; set face.version to 2.0.0");
  // a long one is cut to the history's width
  doc.batch({ op: "batch", edits: [1, 2, 3, 4, 5, 6].map((n) => ({ op: "set", path: ["face", "version"], value: `${n}.0.0` })) }, doc.version);
  assert.equal(doc.head.label.length, LABEL_WIDTH);
  assert.ok(doc.head.label.startsWith("set face.version to 1.0.0; ") && doc.head.label.endsWith("..."));
});

test("a batch mixes an edit with a structural one, each on the text the last left", async () => {
  const doc = make(await newStudio());
  doc.batch({ op: "batch", label: "a dim label", edits: [
    { op: "add", type: "text" },
    { op: "set", path: ["elements", "new_text", "color"], value: "color.dim" },
    { op: "move", path: ["elements", "new_text"], block: ["elements"], before: "clock" },
  ] }, doc.version);
  const d = dataOf(doc);
  assert.equal(d.elements.new_text.color, "color.dim");
  assert.deepEqual(Object.keys(d.elements), ["new_text", "clock", "seconds"]);
  assert.equal(doc.version, 2);
});

test("a batch refused at a step leaves the face alone and names the step", async () => {
  const doc = make(await newStudio());
  refusedAlone(doc, [
    [/^step 2, remove elements\.nope\.color: elements\.nope\.color is not set$/, () => doc.batch({ op: "batch", label: "x", edits: [
      { op: "set", path: ["face", "version"], value: "9.9.9" },
      { op: "remove", path: ["elements", "nope", "color"] },
    ] }, doc.version)],
    [/^step 1, frobnicate: unknown edit 'frobnicate'$/, () => doc.batch({ op: "batch", label: "x", edits: [{ op: "frobnicate" }] }, doc.version)],
    [/^a batch needs at least one edit$/, () => doc.batch({ op: "batch", label: "x", edits: [] }, doc.version)],
    [/^a batch needs at least one edit$/, () => doc.batch({ op: "batch", label: "x" }, doc.version)],
    [/^step 2 is not an edit$/, () => doc.batch({ op: "batch", label: "x", edits: [BATCH_STEPS[0], "set"] }, doc.version)],
  ]);
  assert.equal(versionOf(doc), "1.0.0");
});

test("a batch whose steps are each fine alone is refused by the gate for their combination", async () => {
  const doc = make(await newStudio());
  // the rename is fine, and so is picking dim against the face as it was; together the pick dangles
  refusedAlone(doc, [[/^recolour: unknown colour 'color\.dim' \(line \d+\)$/, () => doc.batch({ op: "batch", label: "recolour", edits: [
    { op: "rename", path: ["resources", "palette", "dim"], to: "grey", prefix: "color." },
    { op: "set", path: ["elements", "clock", "color"], value: "color.dim" },
  ] }, doc.version)]]);
  assert.ok("dim" in palette(doc));
});

test("a batch through the requests is one announced change", async () => {
  const client = await Client.open();
  const doc = await client.create();
  const r = await client.call("batch", { id: doc.id, version: 1, label: "restyle", edits: BATCH_STEPS });
  assert.equal(r.status, 200, JSON.stringify(r.json));
  assert.equal(r.json.version, 2);
  assert.equal(r.json.history.states[0].label, "restyle");
  assert.deepEqual(client.events.filter(([n]) => n === "changed").map(([, d]) => d["version"]), [2]);
  const refused = await client.call("batch", { id: doc.id, version: 2, label: "x", edits: [{ op: "remove", path: ["elements", "nope"] }] });
  assert.equal(refused.status, 400);
  assert.match(refused.json.error, /^step 1, remove elements\.nope: /);
  assert.equal((await client.call("batch", { id: doc.id, version: 1, label: "x", edits: BATCH_STEPS })).status, 409);
});

// -- list items --

test("a list item is inserted, moved and removed through the document, each one undoable change", async () => {
  const client = await Client.open();
  const doc = make(client.studio);
  const edit = (version: number, edit: unknown) => client.call("edit", { id: doc.id, version, edit });
  const texts = [doc.text];
  let r = await edit(doc.version, { op: "insert_item", path: ["build", "targets"], at: 0, value: "fr245" });
  assert.equal(r.status, 200, JSON.stringify(r.json));
  assert.deepEqual(dataOf(doc).build.targets, ["fr245", "fenix8solar47mm", "fenix8solar51mm", "fr955"]);
  assert.equal(r.json.history.states[0].label, "insert build.targets.0: fr245");
  texts.push(doc.text);
  r = await edit(doc.version, { op: "move_item", path: ["build", "targets"], from: 0, to: 3 });
  assert.equal(r.status, 200, JSON.stringify(r.json));
  assert.deepEqual(dataOf(doc).build.targets, ["fenix8solar47mm", "fenix8solar51mm", "fr955", "fr245"]);
  assert.equal(r.json.history.states[0].label, "move build.targets.0 to 3");
  texts.push(doc.text);
  r = await edit(doc.version, { op: "remove_item", path: ["build", "targets"], at: 3 });
  assert.equal(r.status, 200, JSON.stringify(r.json));
  assert.deepEqual(dataOf(doc).build.targets, ["fenix8solar47mm", "fenix8solar51mm", "fr955"]);
  assert.equal(r.json.history.states[0].label, "remove build.targets.3");
  assert.equal(doc.text, texts[0]);
  assert.equal(doc.history()["total"], 4);
  for (const text of [texts[2], texts[1], texts[0]]) {
    const undone = await client.call("undo", { id: doc.id, version: doc.version });
    assert.equal(undone.status, 200);
    assert.equal(doc.text, text);
  }
  // through an element: the path is the element's own
  await edit(doc.version, { op: "set", element: ["elements", "clock"], path: ["lint"], value: { allow: ["safe-area"], reason: "on purpose" } });
  const withLint = await edit(doc.version, { op: "insert_item", element: ["elements", "clock"], path: ["lint", "allow"], at: 1, value: "text-overflow" });
  assert.equal(withLint.status, 200, JSON.stringify(withLint.json));
  assert.deepEqual(dataOf(doc).elements.clock.lint, { allow: ["safe-area", "text-overflow"], reason: "on purpose" });
  assert.ok(doc.text.includes("    lint: { allow: [safe-area, text-overflow], reason: on purpose }\n"), doc.text);
  const bad = await edit(doc.version, { op: "remove_item", path: ["build", "targets"], at: 7 });
  assert.equal(bad.status, 400);
  assert.match(bad.json.error, /no item 7/);
  const noAt = await edit(doc.version, { op: "insert_item", path: ["build", "targets"], value: "x" });
  assert.equal(noAt.status, 400);
  assert.match(noAt.json.error, /at/);
});

// -- parts --

test("a part's keys are edited at its path: a point's dx, a point removed, the parts reordered; another scope is refused", async () => {
  const doc = openExample(await newStudio(), SHOWCASE);
  const blade = ["resources", "hand_sets", "vintage", "hour", "parts", "blade"];
  const before = doc.text;
  const line = (t: string, n: number): string => t.split("\n")[n - 1]!;
  const at = before.split("\n").findIndex((l) => l.includes("- { dx: -1.5%r, dy: -26%r }")) + 1;
  edit(doc, { op: "set", element: blade, path: ["points", 1, "dx"], scope: "all", device: "fr955", value: "-2%r" });
  assert.equal(line(doc.text, at), line(before, at).replace("-1.5%r", "-2%r"));
  assert.equal(doc.text.split("\n").filter((l, i) => l !== before.split("\n")[i]).length, 1, "one line changed");
  assert.equal(doc.head.label, "set resources.hand_sets.vintage.hour.parts.blade.points.1.dx to -2%r");
  // a point removed from the list; the mirrored blade lists two, and the gate keeps it at two
  const classic = ["resources", "hand_sets", "classic", "hour", "parts", "blade"];
  const count = dataOf(doc).resources.hand_sets.classic.hour.parts.blade.points.length;
  edit(doc, { op: "remove_item", element: classic, path: ["points"], at: 1 });
  assert.equal(dataOf(doc).resources.hand_sets.classic.hour.parts.blade.points.length, count - 1);
  assert.equal(doc.head.label, "remove resources.hand_sets.classic.hour.parts.blade.points.1");
  assert.notEqual(doc.analysis().face, null);
  assert.throws(() => edit(doc, { op: "remove_item", element: blade, path: ["points"], at: 1 }), /needs at least 2 items/);
  // parts draw in order: a mapping entry moved among its siblings
  edit(doc, { op: "move_key", element: ["resources", "hand_sets", "vintage", "hour"], path: ["parts", "blade"], to: 0 });
  assert.deepEqual(Object.keys(dataOf(doc).resources.hand_sets.vintage.hour.parts), ["blade", "blade_bg", "ring_bg", "point_bg", "ring", "point"]);
  assert.notEqual(doc.analysis().face, null);
  edit(doc, { op: "move_key", element: ["layouts", "analog", "static", "hour_numerals"], path: ["parts", "numeral"], to: 0 });
  // a hand's own colour, through its path
  edit(doc, { op: "set", element: ["resources", "hand_sets", "vintage", "hour"], path: ["color"], scope: "all", value: "color.dim" });
  assert.equal(dataOf(doc).resources.hand_sets.vintage.hour.color, "color.dim");
  refusedAlone(doc, [
    [/a part has no overrides/, () => edit(doc, { op: "set", element: blade, path: ["points", 1, "dx"], scope: "device", device: "fr955", value: "1px" })],
    [/a part has no overrides/, () => edit(doc, { op: "set", element: blade, path: ["color"], scope: "aod", device: "fr955", value: "color.fg" })],
    [/a part has no overrides/, () => edit(doc, { op: "remove", element: blade, path: ["mirror"], scope: "shape", device: "fr955" })],
    [/a hand has no overrides/, () => edit(doc, { op: "set", element: ["resources", "hand_sets", "vintage", "hour"], path: ["color"], scope: "display", device: "fr955", value: "color.fg" })],
    [/a part has no overrides/, () => doc.drag(blade.join("/"), { kind: "vertex", index: 0, dx: 1, dy: 0 }, "fr955", "device", doc.version)],
    [/a part has no overrides/, () => doc.drag(blade.join("/"), { kind: "move", dx: 1, dy: 0 }, "fr955", "shape", doc.version)],
    [/not a polygon/, () => doc.drag("resources/hand_sets/vintage/hour/parts/ring", { kind: "vertex", index: 0, dx: 1, dy: 0 }, "fr955", "auto", doc.version)],
    [/no ends to move apart/, () => doc.drag("resources/hand_sets/vintage/hour/parts/ring", { kind: "move", part: "to", dx: 1, dy: 0 }, "fr955", "auto", doc.version)],
    [/has no size.width to resize/, () => doc.drag("resources/hand_sets/vintage/hour/parts/ring", { kind: "resize", key: ["size", "width"], delta: 1 }, "fr955", "auto", doc.version)],
    [/only an arc part has angles/, () => doc.drag("resources/hand_sets/vintage/hour/parts/ring", { kind: "turn", key: "start_angle", degrees: 1 }, "fr955", "auto", doc.version)],
    [/is not a part/, () => doc.drag("resources/hand_sets/vintage/hour", { kind: "move", dx: 1, dy: 0 }, "fr955", "auto", doc.version)],
    [/not a part/, () => doc.drag("resources/hand_sets/vintage/hour/parts/nope", { kind: "move", dx: 1, dy: 0 }, "fr955", "auto", doc.version)],
  ]);
  // an arc part is centred on its copy's origin: it turns and resizes, and does not move
  const patterns = openExample(doc.studio, "examples/features/patterns/face.yaml");
  refusedAlone(patterns, [
    [/centred on the axis and has no at: to move/, () => patterns.drag("static/segments/parts/segment", { kind: "move", dx: 1, dy: 0 }, "fr955", "auto", patterns.version)],
    [/is not a part/, () => patterns.drag("static/segments/parts/segment/radius", { kind: "move", dx: 1, dy: 0 }, "fr955", "auto", patterns.version)],
  ]);
});

// -- conditions written from rows --

test("a colour built in rows is the rule list the examples write, compiles as the ternary it replaces, and an edit keeps a block list block", async () => {
  const { readCondition, writeRows, ruleListSteps } = await import("../app/condition-editor.ts");
  const { generated } = await import("./designs.ts");
  const showcase = (await import("./studio-client.ts")).readText(SHOWCASE);
  const studio = await newStudio();
  const DND = ["layouts", "digital", "elements", "dnd_icon"];
  const at = (doc: Document, path: (string | number)[]): any => path.reduce((d: any, k) => d[k], dataOf(doc));
  /** What the rows write over the key's value, through the Document: one set, or the in-place steps as one batch. */
  const write = (doc: Document, element: (string | number)[], value: unknown, next: unknown): void => {
    const steps = ruleListSteps(value as any, next as any) ?? [{ op: "set", path: [], value: next }];
    const edits = steps.map((s: any) => ({ ...s, element, scope: "all", device: null, path: ["color", ...s.path] }));
    if (edits.length === 1) doc.edit(edits[0]!, doc.version);
    else doc.batch({ label: "rows", edits }, doc.version);
  };
  // dnd_icon written as the ternary the showcase's comment names, opened in rows and written back from them
  const ternary = "device.do_not_disturb ? color.accent : color.dark";
  const block = /        color: {26}[^\n]*\n          - when: device\.do_not_disturb\n            value: color\.accent\n          - else: color\.dark\n/;
  assert.match(showcase, block);
  const asTernary = make(studio, showcase.replace(block, `        color: "${ternary}"\n`));
  const reading = readCondition(ternary, "color");
  assert.equal(reading.mode, "rows");
  write(asTernary, DND, ternary, writeRows((reading as any).rows, "color"));
  assert.deepEqual(at(asTernary, [...DND, "color"]), at(make(studio, showcase), [...DND, "color"]), "the showcase's own rule list");
  assert.match(asTernary.text, /\n        color: \[\{ when: device\.do_not_disturb, value: color\.accent \}, \{ else: color\.dark \}\]\n/);
  // the same Monkey C as the ternary it replaces, on every target (a face with no font file, which the generator reads from disk)
  const plainTernary = "device.do_not_disturb ? color.text : color.dim";
  const small = minimal() + `  dnd:\n    type: text\n    text: DND\n    font: FONT_SMALL\n    color: "${plainTernary}"\n`;
  const smallDoc = make(studio, small);
  write(smallDoc, ["elements", "dnd"], plainTernary, writeRows((readCondition(plainTernary, "color") as any).rows, "color"));
  assert.notEqual(smallDoc.text, small);
  const fromRows = generated(smallDoc.text), fromTernary = generated(small);
  assert.deepEqual([...fromRows.keys()].sort(), [...fromTernary.keys()].sort());
  for (const [file, source] of fromTernary) if (file.endsWith(".mc")) assert.equal(fromRows.get(file), source, file);
  // a row changed in the showcase's block list: that one line (the patch engine quotes a scalar holding ">"), the list still block style
  const doc = make(studio, showcase);
  const alarm = ["layouts", "digital", "elements", "alarm_icon"];
  const own = at(doc, [...alarm, "color"]);
  const rows = readCondition(own, "color");
  assert.equal(rows.mode, "rows");
  const changed = { ...(rows as any).rows, rules: [{ ...(rows as any).rows.rules[0], when: { source: "device.alarm_count", op: ">", value: "1" } }] };
  write(doc, alarm, own, writeRows(changed, "color"));
  const before = showcase.split("\n"), after = doc.text.split("\n");
  assert.deepEqual(after.map((l, i) => [l, before[i]]).filter(([a, b]) => a !== b), [['          - when: "device.alarm_count > 1"', "          - when: device.alarm_count > 0"]]);
  // a row added to it is a block item before the else
  const more = { ...changed, rules: [...changed.rules, { when: { source: "system.charging", op: "==", value: "true" }, value: "color.fg" }] };
  write(doc, alarm, at(doc, [...alarm, "color"]), writeRows(more, "color"));
  assert.match(doc.text, /          - when: "device\.alarm_count > 1"\n            value: color\.accent\n          - when: system\.charging\n            value: color\.fg\n          - else: color\.dark\n/);
});

// -- a lint warning accepted on its element --

test("accept here: the lint block the page composes lands in one batch and the warning clears, an existing block keeping its codes and reason", async () => {
  const { lintSteps } = await import("../app/values.ts");
  const studio = await newStudio();
  const doc = openExample(studio, "examples/features/outline/face.yaml");
  const LINT = /\n    lint:\n      allow: \[text-outline-interior\]\n      reason: "[^"]*"/;
  assert.ok(LINT.test(doc.text));
  const warned = (d: Document): string[] => d.diagnostics().filter((x) => x.code === "text-outline-interior" && x.severity === "warning")
    .map((x) => String(x.line));
  const labelLine = (d: Document): number => indexFor(d.text).get(["elements", "label"])!.key.start.line + 1;
  // without its block, the label warns, on a line inside the element
  doc.replaceText(doc.text.replace(LINT, ""), doc.version);
  const lines = warned(doc).map(Number);
  assert.ok(lines.length > 0 && lines.every((l) => l >= labelLine(doc) && l < labelLine(doc) + 8), String(lines));
  const before = doc.text;
  // no block: the whole block is written, as one change
  const steps = lintSteps(["elements", "label"], "text-outline-interior", "an opaque label the ring decorates", null);
  assert.deepEqual(steps, [{ op: "set", path: ["elements", "label", "lint"], value: { allow: ["text-outline-interior"], reason: "an opaque label the ring decorates" } }]);
  const v = doc.version;
  doc.batch({ op: "batch", label: "accept text-outline-interior on label", edits: steps }, doc.version);
  assert.equal(doc.version, v + 1);
  assert.deepEqual(warned(doc), []);
  assert.deepEqual(dataOf(doc).elements.label.lint, { allow: ["text-outline-interior"], reason: "an opaque label the ring decorates" });
  assert.equal(doc.history().states[0]!.label, "accept text-outline-interior on label");
  // byte-exact outside the element's new block
  const added = doc.text.split("\n").filter((l) => !before.split("\n").includes(l));
  assert.deepEqual(added, ["    lint: { allow: [text-outline-interior], reason: an opaque label the ring decorates }"]);

  // an element with a block already: the code joins its allow list and its reason stays
  const doc2 = openExample(studio, "examples/features/outline/face.yaml");
  doc2.replaceText(doc2.text.replace(LINT, "\n    lint:\n      allow: [contrast]\n      reason: \"kept as it was\""), doc2.version);
  assert.ok(warned(doc2).length > 0);
  const written = dataOf(doc2).elements.label.lint;
  const kept = lintSteps(["elements", "label"], "text-outline-interior", "kept as it was", written);
  assert.deepEqual(kept, [{ op: "insert_item", path: ["elements", "label", "lint", "allow"], at: 1, value: "text-outline-interior" }]);
  doc2.batch({ op: "batch", label: "accept", edits: kept }, doc2.version);
  assert.deepEqual(warned(doc2), []);
  assert.deepEqual(dataOf(doc2).elements.label.lint, { allow: ["contrast", "text-outline-interior"], reason: "kept as it was" });
  // a reason the author changed is written too
  assert.deepEqual(lintSteps(["elements", "label"], "contrast", "new words", { allow: ["contrast"], reason: "old" }),
    [{ op: "set", path: ["elements", "label", "lint", "reason"], value: "new words" }]);
  // every code it offers is one the compiler lets a lint: block accept
  assert.ok(vocabulary().lint_codes.includes("text-outline-interior") && !vocabulary().lint_codes.includes("lint-allow"));
});

// -- a font's options --

test("a fonts: entry inspects as its own branch and its options are edited through the generic ops", async () => {
  const client = await Client.open();
  const doc = openExample(client.studio, "examples/features/vector-text/face.yaml");
  const ask = async (name: string): Promise<any> => (await client.call("inspect", { id: doc.id, element: ["resources", "fonts", name] })).json;
  const baked = await ask("clock");
  assert.equal(baked.subject, "font");
  assert.equal(baked.type, "font");
  assert.equal(baked.error, null);
  // a baked font's own keys, written first; a vector font's keys, a build error here, are not offered
  assert.deepEqual(baked.fields.map((f: any) => f.key), ["source", "size", "monospace", "antialias", "glyphs", "align"]);
  assert.deepEqual(Object.fromEntries(baked.fields.map((f: any) => [f.key, f.widget])),
    { source: "text", size: "length", monospace: "bool", antialias: "bool", glyphs: "text", align: "enum" });
  const vector = await ask("dial");
  assert.deepEqual(vector.fields.map((f: any) => f.key), ["face", "size", "unsupported"]);
  const face = vector.fields[0];
  assert.equal(face.kind, "choice");
  assert.equal(face.chosen, 1, "a list of faces");
  assert.deepEqual(face.branches.map((b: any) => b.kind === "list" ? `list of ${b.item.widget}` : b.widget), ["face", "list of face"]);
  assert.deepEqual(face.branches[1].items.map((i: any) => i.value), ["BionicSemiBold", "RobotoCondensedBold"]);
  // the ops a font's form sends: the entry is the element target, in the all scope
  const target = { element: ["resources", "fonts", "clock"], scope: "all" };
  const edited = async (op: Record<string, unknown>): Promise<number> => (await client.call("edit", { id: doc.id, version: doc.version, edit: { ...op, ...target } })).status;
  assert.equal(await edited({ op: "set", path: ["glyphs"], value: "0123456789:" }), 200);
  assert.equal(await edited({ op: "set", path: ["align"], value: "right" }), 200);
  assert.equal(await edited({ op: "set", path: ["antialias"], value: false }), 200);
  const clock = dataOf(doc).resources.fonts.clock;
  assert.deepEqual([clock.glyphs, clock.align, clock.antialias, clock.monospace], ["0123456789:", "right", false, true]);
  // align without monospace is a build error the gate refuses
  const refused = await client.call("edit", { id: doc.id, version: doc.version, edit: { op: "set", path: ["monospace"], value: false, ...target } });
  assert.equal(refused.status, 400);
  // a vector font's face list, an item added and the list made one name again
  const dial = { element: ["resources", "fonts", "dial"], scope: "all" };
  const r1 = await client.call("edit", { id: doc.id, version: doc.version, edit: { op: "insert_item", path: ["face"], at: 2, value: "RobotoBlack", ...dial } });
  assert.equal(r1.status, 200, JSON.stringify(r1.json));
  assert.deepEqual(dataOf(doc).resources.fonts.dial.face, ["BionicSemiBold", "RobotoCondensedBold", "RobotoBlack"]);
  const r2 = await client.call("edit", { id: doc.id, version: doc.version, edit: { op: "set", path: ["face"], value: "RobotoCondensedBold", ...dial } });
  assert.equal(r2.status, 200, JSON.stringify(r2.json));
  assert.equal(dataOf(doc).resources.fonts.dial.face, "RobotoCondensedBold");
  // each target's published faces come with the vocabulary, to suggest
  const devices = (await client.call("vocabulary", {})).json.devices;
  assert.ok(devices.find((d: any) => d.id === "fenix8solar47mm").faces.includes("BionicSemiBold"));
});
