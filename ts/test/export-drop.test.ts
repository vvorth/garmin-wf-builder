// `wfb export --all-devices` dropping the devices that cannot draw a design,
// over installed devices and with no `monkeyc`: which errors are attributed
// to devices, the resolve passes that drop them, and what the export then
// reports.
import assert from "node:assert/strict";
import { test } from "node:test";
import { DROP_REASONS_SHOWN, dropUnsupported, load as loadDesign, resolveAll, selectDevices } from "../src/build.ts";
import { Bag, type Diagnostic } from "../src/diagnostics.ts";
import { bakeFonts } from "../src/emit/resources.ts";
import { db, exists, MINIMAL, PATH, read } from "./designs.ts";

/** A pass as the export runs it: load, select `ids`, resolve and lint; the kept ids when it passes. */
function passFor(text: string): (ids: string[], bag: Bag) => string[] | null {
  return (ids, bag) => {
    bag.registerSource(PATH, text);
    const face = loadDesign(PATH, bag, text, exists);
    if (face === null) return null;
    const devices = selectDevices(face, db, bag, ids, false);
    if (!bag.ok()) return null;
    resolveAll(face, devices, bag, (f, device) => bakeFonts(f, device, read));
    return bag.ok() ? devices.map((d) => d.id) : null;
  };
}

const shown = (items: readonly Diagnostic[]): string[] => items.map((d) => `${d.severity}[${d.code}]`);

/** A design whose rim text curves in a device-resident face, under the default `unsupported: error`. */
const CURVED = MINIMAL.replace("resources:\n", `resources:
  fonts:
    dial: {face: RobotoCondensedBold, size: 10%r}
`) + `
  wordmark:
    type: text
    text: "FIELD"
    font: font.dial
    color: color.fg
    at: {anchor: center}
    curve: {style: radial, angle: 165deg, radius: 60%r, direction: counter_clockwise}
`;

/** A design drawing in the Instinct family's subscreen window. */
const SUBSCREEN = MINIMAL + `
  battery:
    type: text
    text: "{system.battery}"
    font: FONT_TINY
    color: color.fg
    at: {anchor: subscreen}
`;

/** A design with one `config: slots:` slot, drawn by a data element; `extra` goes on the slot. */
const SLOT = (extra = ""): string => MINIMAL.replace("elements:", `config:
  slots:
    top: {${extra}default: steps, choices: [steps, calories]}
elements:`) + `
  reading:
    type: data
    slot: top
    font: FONT_TINY
    color: color.fg
    at: {anchor: center}
    absent: {text: "--"}
`;

test("a slot fails a device without Complications by default, attributed to it, and builds there under 'unsupported: hide'", () => {
  const bag = new Bag();
  passFor(SLOT())(["fenix8solar47mm", "fenix6"], bag);
  assert.deepEqual(bag.errors.map((d) => [d.code, d.devices]), [["slot-unsupported", ["fenix6"]]], bag.render());
  const explicit = new Bag();
  passFor(SLOT("unsupported: error, "))(["fenix6"], explicit);
  assert.deepEqual(explicit.errors.map((d) => d.code), ["slot-unsupported"], explicit.render());
  const hidden = new Bag();
  passFor(SLOT("unsupported: hide, "))(["fenix8solar47mm", "fenix6"], hidden);
  assert.ok(hidden.ok(), hidden.render());
  assert.ok(hidden.items.some((d) => d.severity === "warning" && d.code === "api-gated" && d.message.includes("slot 'top'")), hidden.render());
  const outcome = dropUnsupported(["fenix8solar47mm", "fenix6"], passFor(SLOT()));
  assert.deepEqual(outcome.result, ["fenix8solar47mm"], outcome.bag.render());
  assert.deepEqual([...outcome.dropped.keys()], ["fenix6"]);
});

/** A text reading floors climbed, a field fr245 lacks; `extra` goes on the text, `group` wraps it in a group carrying those lines. */
const FLOORS = (extra = "", group = ""): string => MINIMAL + (group === "" ? `
  floors:
    type: text
    text: "{activity.floors_climbed}"
    font: FONT_TINY
    color: color.fg
    at: {anchor: center}
    absent: {text: "--"}
${extra}` : `
  box:
    type: group
    at: {anchor: center}
    size: {width: 40%, height: 20%}
${group}    children:
      floors:
        type: text
        text: "{activity.floors_climbed}"
        font: FONT_TINY
        color: color.fg
        at: {anchor: center}
        absent: {text: "--"}
`);

test("data a device lacks fails it by default, attributed to it; 'unsupported: hide' on the element or a group builds it", () => {
  if (!db.ids().includes("fr245")) return;
  const bag = new Bag();
  passFor(FLOORS())(["fenix8solar47mm", "fr245"], bag);
  assert.deepEqual(bag.errors.map((d) => [d.code, d.devices]), [["source-unsupported", ["fr245"]]], bag.render());
  const outcome = dropUnsupported(["fenix8solar47mm", "fr245"], passFor(FLOORS()));
  assert.deepEqual(outcome.result, ["fenix8solar47mm"], outcome.bag.render());
  for (const text of [FLOORS("    unsupported: hide\n"), FLOORS("", "    unsupported: hide\n")]) {
    const hidden = new Bag();
    passFor(text)(["fenix8solar47mm", "fr245"], hidden);
    assert.ok(hidden.ok(), hidden.render());
    assert.ok(hidden.items.some((d) => d.severity === "warning" && d.code === "api-gated" && d.message.includes("floors")), hidden.render());
  }
  const nothing = new Bag();
  passFor(MINIMAL.replace("    color: color.bg\n", "    color: color.bg\n    unsupported: hide\n"))(["fenix8solar47mm"], nothing);
  assert.ok(nothing.errors.some((d) => d.message.includes("'unsupported:' is not accepted here")), nothing.render());
});

test("the errors a device's lack causes carry that device; the design's own errors carry none", () => {
  const bag = new Bag();
  passFor(CURVED)(["fenix8solar47mm", "fr255", "fenix6"], bag);
  const unavailable = bag.errors.filter((d) => d.code === "font-unavailable");
  assert.equal(unavailable.length, 1, bag.render());
  assert.deepEqual(unavailable[0]!.devices, ["fenix6", "fr255"]);
  const subscreen = new Bag();
  passFor(SUBSCREEN)(["instinct3solar45mm", "fenix8solar47mm"], subscreen);
  assert.deepEqual(subscreen.errors.map((d) => [d.code, d.devices]), [["subscreen", ["fenix8solar47mm"]]], subscreen.render());
  const lowPower = new Bag();
  passFor(MINIMAL.replace("    color: color.bg\n", "    color: color.bg\n    sleep_update: true\n"))(["fenix8solar47mm", "venux1"], lowPower);
  assert.deepEqual(lowPower.errors.map((d) => [d.code, d.devices]), [["partial-update", ["venux1"]]], lowPower.render());
  const design = new Bag();
  passFor(MINIMAL.replace("color: color.bg", "color: color.nope"))(["fenix8solar47mm"], design);
  assert.ok(design.errors.length > 0 && design.errors.every((d) => d.devices === null), design.render());
});

test("a curved face: text drops each device with no usable face, one note each, and keeps the rest", () => {
  const outcome = dropUnsupported(["fenix8solar47mm", "fr955", "fr255", "fenix6"], passFor(CURVED));
  assert.deepEqual(outcome.result, ["fenix8solar47mm", "fr955"], outcome.bag.render());
  assert.deepEqual(outcome.kept, ["fenix8solar47mm", "fr955"]);
  assert.deepEqual([...outcome.dropped.keys()], ["fr255", "fenix6"]);
  assert.ok(outcome.bag.ok(), outcome.bag.render());
  const notes = outcome.bag.items.filter((d) => d.code === "device-dropped");
  assert.deepEqual(notes.map((d) => d.message), [
    "fr255: dropped from the export (font-unavailable)",
    "fenix6: dropped from the export (font-unavailable)",
  ]);
  for (const note of notes) {
    assert.equal(note.severity, "note");
    assert.deepEqual(note.notes, ["wordmark: 'font: font.dial' has no usable face on fenix6, fr255"]);
  }
  // The final bag is the pass over the kept devices: nothing in it names only a dropped one.
  for (const d of outcome.bag.items) {
    if (d.code === "device-dropped") continue;
    assert.ok(!/\b(fr255|fenix6)\b/.test(d.message), d.message);
  }
});

test("a subscreen element drops the devices with no subscreen window", () => {
  const outcome = dropUnsupported(["instinct3solar45mm", "fenix8solar47mm"], passFor(SUBSCREEN));
  assert.deepEqual(outcome.kept, ["instinct3solar45mm"], outcome.bag.render());
  assert.deepEqual([...outcome.dropped.keys()], ["fenix8solar47mm"]);
  assert.deepEqual(shown(outcome.bag.items.filter((d) => d.code === "device-dropped")), ["note[device-dropped]"]);
  assert.ok(outcome.bag.ok(), outcome.bag.render());
});

test("an error of the design's own drops nothing and fails", () => {
  const broken = MINIMAL.replace("color: color.bg", "color: color.nope");
  const outcome = dropUnsupported(["fenix8solar47mm", "fr955", "fr255"], passFor(broken));
  assert.equal(outcome.result, null);
  assert.deepEqual(outcome.kept, ["fenix8solar47mm", "fr955", "fr255"]);
  assert.equal(outcome.dropped.size, 0);
  assert.ok(!outcome.bag.ok());
  // Beside a device's own lack it still stops the dropping: the export fails as it would have, nothing dropped.
  const mixed = CURVED.replace("resources:\n  fonts:\n", `resources:
  fonts:
    digits: {source: ts/test/fixtures/slice/assets/OpenSans-Regular.ttf, size: 12%r, glyphs: "0123456789"}
`) + `
  label:
    type: text
    text: "ABC"
    font: font.digits
    color: color.fg
    at: {anchor: center, dy: 20%}
`;
  const both = dropUnsupported(["fenix8solar47mm", "fr255"], passFor(mixed));
  assert.equal(both.result, null, both.bag.render());
  assert.equal(both.dropped.size, 0);
  assert.ok(both.bag.errors.some((d) => d.code === "missing-glyph" && d.devices === null), both.bag.render());
  assert.ok(both.bag.errors.some((d) => d.code === "font-unavailable"), both.bag.render());
});

test("a design every candidate fails is an error naming what each one lacked", () => {
  const outcome = dropUnsupported(["fr255", "fenix6"], passFor(CURVED));
  assert.equal(outcome.result, null);
  assert.deepEqual(outcome.kept, []);
  assert.deepEqual(shown(outcome.bag.items), ["note[device-dropped]", "note[device-dropped]", "error[devices]"]);
  const error = outcome.bag.errors[0]!;
  assert.equal(error.message, "nothing left to export: every candidate device was dropped");
  assert.deepEqual(error.notes.slice(0, 2), ["fr255: font-unavailable", "fenix6: font-unavailable"]);
});

test("a drop note quotes the first few errors that dropped the device and counts the rest", () => {
  let text = CURVED;
  for (let i = 0; i < DROP_REASONS_SHOWN; i++) text += CURVED.slice(CURVED.indexOf("\n  wordmark:")).replaceAll("wordmark", `wordmark${i}`);
  const outcome = dropUnsupported(["fenix8solar47mm", "fr255"], passFor(text));
  const note = outcome.bag.items.find((d) => d.code === "device-dropped")!;
  assert.equal(note.notes.length, DROP_REASONS_SHOWN + 1, outcome.bag.render());
  assert.equal(note.notes.at(-1), "and 1 more; `wfb validate -d` with this device lists every one");
});
