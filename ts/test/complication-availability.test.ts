// Which complication types a target may name comes from its own symbol
// table, never from its API level: a `choices: any` slot's per-device list,
// an explicit choice the device lacks, and a default it lacks. The structural
// tests run over every installed device; the synthetic ones over copies of
// the fixture device whose level and table disagree, as fr955's did when its
// `choices: any` export named COMPLICATION_TYPE_SLEEP_SCORE and monkeyc
// refused it.
import assert from "node:assert/strict";
import { cpSync, mkdtempSync, readdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { computeGuards, hasComplicationType } from "../src/availability.ts";
import { load, resolveAll, selectDevices } from "../src/build.ts";
import * as complications from "../src/complications.ts";
import { compareVersions, type Device, DeviceDatabase, DeviceError } from "../src/devices/device.ts";
import { NodeDeviceFiles, REPO_ROOT } from "../src/devices/node.ts";
import { Bag, type Diagnostic } from "../src/diagnostics.ts";
import { generate } from "../src/emit/project.ts";
import { slotTypes } from "../src/emit/monkeyc/config_menu.ts";
import { bakeFonts } from "../src/emit/resources.ts";
import { NodeFontFiles } from "../src/fonts/node.ts";
import { installAssets, readFontFile } from "../src/node.ts";
import { db } from "./designs.ts";

installAssets();

/** A design with one data slot `top`, given as `slot`, drawn by `reading`, built for `targets`. */
const slotted = (targets: string[], slot: string): string => `format: 2
face: { id: 6b2f9a3e-5c1d-4e8a-9f7b-3a1d6c8e2f41, name: Test }
build: { targets: [${targets.join(", ")}] }
resources: { palette: { bg: "#000000", fg: "#FFFFFF" } }
config:
  slots:
    top: ${slot}
elements:
  reading:
    type: data
    slot: top
    at: { anchor: center }
    font: FONT_SMALL
    color: color.fg
`;

const read = (p: string) => readFontFile(join(REPO_ROOT, p));
const exists = (): boolean => false;

/** `text` loaded, resolved and linted over `database`, then generated: its diagnostics and files. */
function build(database: DeviceDatabase, text: string): { diagnostics: Diagnostic[]; files: Map<string, string> } {
  const bag = new Bag();
  bag.registerSource("face.yaml", text);
  const face = load("face.yaml", bag, text, exists);
  assert.ok(face !== null, bag.render());
  const devices = selectDevices(face, database, bag);
  resolveAll(face, devices, bag, (f, d) => bakeFonts(f, d, read));
  const files = new Map<string, string>();
  for (const [name, content] of generate(face, devices, read).files()) if (typeof content === "string") files.set(name, content);
  return { diagnostics: bag.items, files };
}

/** The constants of `Layout.<prefix>_TYPES` in a generated Layout.mc, or `null` when it has none. */
function layoutTypes(layout: string, prefix = "CONFIG_DATA_TOP"): string[] | null {
  const m = new RegExp(`const ${prefix}_TYPES as Array<Complications.Type> = \\[(.*)\\];`).exec(layout);
  return m === null ? null : m[1]!.split(", ").filter(Boolean).map((c) => c.replace(/^Complications\./, ""));
}

/** Every installed device that can run a face, with Toybox.Complications and a readable symbol table. */
function tabledDevices(database: DeviceDatabase): Device[] {
  const out: Device[] = [];
  for (const id of database.ids()) {
    const device = database.get(id);
    if (!device.supportsWatchface || compareVersions(device.apiLevel, "3.1.0") < 0) continue;
    try {
      if (device.hasModule("Complications")) out.push(device);
    } catch (error) {
      if (!(error instanceof DeviceError)) throw error;
    }
  }
  return out;
}

test("on every installed device, a choices: any slot names only types that device's own table has", () => {
  const devices = tabledDevices(db);
  for (const device of devices) {
    const files = build(db, slotted([device.id], "{ default: steps, choices: any }")).files;
    const offered = slotTypes({ name: "top", default: "steps", choices: "any" } as never, device).map((t) => t.constant);
    for (const constant of offered) assert.ok(device.hasField(constant), `${device.id}: offers ${constant}, absent from its table`);
    // every per-device file names only what the table has: Layout's list, the phone's list, the native editor's resource
    for (const [name, text] of files) {
      if (!name.startsWith(`source-${device.id}/`) && !name.startsWith(`resources-${device.id}/`)) continue;
      for (const [constant] of text.matchAll(/COMPLICATION_TYPE_[A-Z0-9_]+/g)) {
        assert.ok(device.hasField(constant), `${device.id}: ${name} names ${constant}, absent from its table`);
      }
    }
    const listed = layoutTypes(files.get(`source-${device.id}/Layout.mc`)!);
    if (listed !== null) assert.deepEqual(listed, offered, device.id);
  }
});

test("a type the API level allows but the table lacks is left out, and the lint says nothing about it", () => {
  // vacuous on a device set where levels and tables agree: then every device is still checked above
  const disagreements: [Device, complications.ComplicationType][] = [];
  for (const device of tabledDevices(db)) {
    for (const type of complications.TYPES.values()) {
      if (compareVersions(type.since, device.apiLevel) <= 0 && hasComplicationType(device, type) === false) disagreements.push([device, type]);
    }
  }
  console.log(disagreements.length === 0
    ? "complication-availability: no installed device's level and table disagree"
    : "complication-availability: level allows, table lacks: " + disagreements.map(([d, t]) => `${d.id}:${t.name}`).join(", "));
  for (const [device, type] of disagreements) {
    const { diagnostics, files } = build(db, slotted([device.id], "{ default: steps, choices: any }"));
    const layout = files.get(`source-${device.id}/Layout.mc`)!;
    assert.ok(!layout.includes(type.constant), `${device.id}: Layout names ${type.constant}`);
    assert.deepEqual(diagnostics.filter((d) => d.message.includes(type.name) || d.message.includes(type.constant)).map((d) => d.message), []);
  }
});

/**
 * A database over copies of the fixture device `wfbtest`, one per entry of
 * `variants`: each named by its key, its Connect IQ version raised to
 * `level`, and the constants in `drop` and the lines matching `strip` taken
 * out of its symbol table.
 */
function stubDatabase(variants: Record<string, { level: string; drop: string[]; strip?: RegExp }>): [DeviceDatabase, string] {
  const fixture = join(REPO_ROOT, "ts", "test", "fixtures", "devices");
  const root = mkdtempSync(join(tmpdir(), "wfb-complication-types-"));
  const reference = join(root, "reference");
  cpSync(join(fixture, "reference"), reference, { recursive: true });
  for (const [id, { level, drop, strip }] of Object.entries(variants)) {
    const dir = join(root, id);
    cpSync(join(fixture, "wfbtest"), dir, { recursive: true });
    for (const name of readdirSync(dir)) if (name.startsWith("wfbtest")) renameSync(join(dir, name), join(dir, name.replace("wfbtest", id)));
    const compiler = join(dir, "compiler.json");
    writeFileSync(compiler, readFileSync(compiler, "utf8").replaceAll("wfbtest", id).replace(/"connectIQVersion": "[^"]*"/g, `"connectIQVersion": "${level}"`));
    const simulator = join(dir, "simulator.json");
    writeFileSync(simulator, readFileSync(simulator, "utf8").replaceAll("wfbtest", id));
    const table = join(dir, `${id}.api.debug.xml`);
    let xml = readFileSync(table, "utf8");
    for (const constant of drop) xml = xml.replace(`<entry field="true" symbol="${constant}"/>\n`, "");
    if (strip !== undefined) xml = xml.split("\n").filter((line) => !strip.test(line)).join("\n");
    writeFileSync(table, xml);
    writeFileSync(join(reference, `${id}.json`), readFileSync(join(reference, "wfbtest.json"), "utf8").replaceAll("wfbtest", id));
  }
  return [new DeviceDatabase(NodeDeviceFiles.discover(root, reference), new NodeFontFiles()), root];
}

// `wfbmenu` edits config with the settings menu (no WatchFaceConfig), `wfbnative` with Garmin's editor; both report
// Connect IQ 6.2.0, past sleep_score's 6.0.2, and neither table has COMPLICATION_TYPE_SLEEP_SCORE -- fr955's case.
const [stubs] = stubDatabase({
  wfbmenu: { level: "6.2.0", drop: [], strip: /WatchFaceConfig/ },
  wfbnative: { level: "6.2.0", drop: [] },
});
const SLEEP = complications.TYPES.get("sleep_score")!;

test("the stubs are the incident's shape: a level past sleep_score's since, a table without it", () => {
  for (const id of ["wfbmenu", "wfbnative"]) {
    const device = stubs.get(id);
    assert.ok(compareVersions(SLEEP.since, device.apiLevel) <= 0, id);
    assert.equal(hasComplicationType(device, SLEEP), false, id);
    assert.equal(hasComplicationType(device, complications.TYPES.get("steps")!), true, id);
  }
  assert.ok(!stubs.get("wfbmenu").hasSymbol("Toybox.Application.WatchFaceConfig.getSettings"));
  assert.ok(stubs.get("wfbnative").hasSymbol("Toybox.Application.WatchFaceConfig.getSettings"));
});

test("choices: any leaves out what the table lacks, without a word, and the shared code guards every type it names", () => {
  const { diagnostics, files } = build(stubs, slotted(["wfbmenu", "wfbnative"], "{ default: steps, choices: any }"));
  assert.deepEqual(diagnostics.filter((d) => d.code.startsWith("api-gated")).map((d) => d.message), []);
  const listed = layoutTypes(files.get("source-wfbmenu/Layout.mc")!)!;
  assert.ok(!listed.includes(SLEEP.constant));
  assert.ok(listed.includes("COMPLICATION_TYPE_STEPS"));
  assert.doesNotMatch(files.get("resources-wfbmenu/settings/settings.xml")!, /ConfigTypeSleepScore/);
  assert.match(files.get("resources-wfbnative/configs/watchface.xml")!, /allowAny="true"/);
  // the shared reading switch still names it for a target that has it: inside the module check monkeyc accepts
  const face = load("face.yaml", new Bag(), slotted(["wfbmenu"], "{ default: steps, choices: any }"), exists)!;
  assert.equal(computeGuards(face, [stubs.get("wfbmenu")]).complications, true);
  assert.match(files.get("source/SlotText.mc")!, /if \(Toybox has :Complications\)/);
});

test("an explicit choice the table lacks is a warning and is left out of every list on that device", () => {
  const { diagnostics, files } = build(stubs, slotted(["wfbmenu", "wfbnative"], "{ default: steps, choices: [steps, sleep_score, calories] }"));
  const gated = diagnostics.filter((d) => d.code.startsWith("api-gated"));
  assert.deepEqual(gated.map((d) => `${d.severity} ${d.code} ${d.message}`), ["wfbmenu", "wfbnative"].map((id) =>
    `warning api-gated reading: slot 'top''s 'complication.sleep_score' is not on ${id}: ${id} has no COMPLICATION_TYPE_SLEEP_SCORE, so it is left out of ${id}'s list`));
  assert.ok(gated.every((d) => d.confidence === `exact -- ${d.message.split(" has no ")[0]!.split(": ").at(-1)}'s own symbol table (api.debug.xml)`));
  assert.deepEqual(layoutTypes(files.get("source-wfbmenu/Layout.mc")!), ["COMPLICATION_TYPE_STEPS", "COMPLICATION_TYPE_CALORIES"]);
  assert.deepEqual([...files.get("resources-wfbmenu/settings/settings.xml")!.matchAll(/@Strings\.(ConfigType\w+)/g)].map((m) => m[1]),
    ["ConfigTypeSteps", "ConfigTypeCalories"]);
  const editor = files.get("resources-wfbnative/configs/watchface.xml")!;
  assert.doesNotMatch(editor, /SLEEP_SCORE/);
  assert.match(editor, /<type default="true">Complications.COMPLICATION_TYPE_STEPS<\/type>\s*<type>Complications.COMPLICATION_TYPE_CALORIES<\/type>/);
});

test("a default the table lacks is the api-gated-unguardable error, on the element or on the slot itself", () => {
  const drawn = build(stubs, slotted(["wfbmenu"], "{ default: sleep_score, choices: [sleep_score, steps] }")).diagnostics;
  assert.deepEqual(drawn.filter((d) => d.code.startsWith("api-gated")).map((d) => `${d.severity} ${d.code} ${d.message} @${d.span?.line}`), [
    "error api-gated-unguardable reading: slot 'top''s default 'complication.sleep_score' is not on wfbmenu: wfbmenu has no COMPLICATION_TYPE_SLEEP_SCORE @9",
  ]);
  assert.equal(drawn.find((d) => d.code === "api-gated-unguardable")!.notes[0],
    "the default is named in code every device shares; pick a default every target has, or drop the target");
  // the device's lack, so an export over every device leaves it out
  assert.deepEqual(drawn.find((d) => d.code === "api-gated-unguardable")!.devices, ["wfbmenu"]);
  // no element draws the slot: the slot's own declaration carries it
  const undrawn = slotted(["wfbmenu"], "{ default: sleep_score, choices: any }").replace("    type: data\n    slot: top\n", "    type: text\n    text: \"x\"\n");
  assert.deepEqual(build(stubs, undrawn).diagnostics.filter((d) => d.code.startsWith("api-gated")).map((d) => `${d.code} ${d.message} @${d.span?.line}`), [
    "api-gated-unguardable top: slot 'top''s default 'complication.sleep_score' is not on wfbmenu: wfbmenu has no COMPLICATION_TYPE_SLEEP_SCORE @7",
  ]);
  assert.deepEqual(build(stubs, undrawn).diagnostics.find((d) => d.code === "api-gated-unguardable")!.devices, ["wfbmenu"]);
});

test("a read or hold target the table lacks is decided by the table, not the level", () => {
  const text = slotted(["wfbmenu"], "{ default: steps, choices: any }")
    .replace("    type: data\n    slot: top\n", "    type: text\n    text: \"{complication.sleep_score:d}\"\n    on_hold: sleep_score\n    absent: hide\n");
  const messages = build(stubs, text).diagnostics.filter((d) => d.code === "api-gated").map((d) => d.message).sort();
  assert.deepEqual(messages, [
    "reading: 'complication.sleep_score' is not on wfbmenu: wfbmenu has no COMPLICATION_TYPE_SLEEP_SCORE",
    "reading: holding to launch 'sleep_score' is not on wfbmenu: wfbmenu has no COMPLICATION_TYPE_SLEEP_SCORE",
  ]);
});
