// Guards by API level: since SDK 9.3.0, monkeyc refuses a symbol newer than a
// target's API level unless an enclosing `has` check names it or its module,
// so the generated code writes that check at the use, and only where some
// target's level needs it.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import * as availability from "../src/availability.ts";
import { REPO_ROOT } from "../src/devices/node.ts";
import { RUNTIME_LIB } from "../src/emit/usage.ts";
import { db, face, generated, MINIMAL, view } from "./designs.ts";

const installed = (...ids: string[]): boolean => ids.every((id) => db.ids().includes(id));
const guards = (text: string, ids: string[]) => availability.computeGuards(face(text), ids.map((id) => db.get(id)));

const slotted = (targets: string, choices: string): string => `${MINIMAL.replace("targets: [fenix8solar47mm]", `targets: [${targets}]`)
  .replace("elements:", `config:
  slots:
    top: { default: steps, choices: ${choices} }
elements:`)}
  reading:
    type: data
    slot: top
    at: {anchor: center}
    font: FONT_SMALL
    color: color.fg
`;

const bound = (targets: string): string => `${MINIMAL.replace("targets: [fenix8solar47mm]", `targets: [${targets}]`)}
  solar:
    type: text
    text: "{complication.solar_input:.0f}"
    font: FONT_SMALL
    at: {anchor: center}
    color: color.fg
    absent: hide
`;

const ALIGN = readFileSync(join(REPO_ROOT, "examples/features/align/face.yaml"), "utf8");

test("a complication type newer than a target's level guards the module there, even where the module exists", () => {
  if (!installed("fr955", "fenix8solar47mm")) return;
  // sleep_score is API 6.0.2: choices: any names it, and fr955 is 5.2.0.
  assert.equal(guards(slotted("fr955", "any"), ["fr955"]).complications, true);
  assert.ok(guards(slotted("fr955", "any"), ["fr955"]).modules.has("Complications"));
  assert.equal(guards(slotted("fenix8solar47mm", "any"), ["fenix8solar47mm"]).complications, false);
  // steps is 4.2.0, which fr955 reaches.
  assert.equal(guards(slotted("fr955", "[steps, heart_rate]"), ["fr955"]).complications, false);
  assert.deepEqual([...availability.complicationTypesNamed(face(slotted("fr955", "[steps, heart_rate]")))].sort(), ["heart_rate", "steps"]);
});

test("the editor, ResourceReference and Drawable.isVisible guard by their own levels", () => {
  if (!installed("venusq2", "fr955", "fenix8solar47mm")) return;
  assert.equal(guards(ALIGN, ["venusq2", "fenix8solar47mm"]).editor_level, true, "venusq2 is 5.0.0, the editor 5.1.0");
  assert.equal(guards(ALIGN, ["fr955", "fenix8solar47mm"]).editor_level, false, "fr955 is 5.2.0, though its own table lacks the editor");
  if (installed("fenix5", "fenix6")) {
    assert.equal(guards(ALIGN, ["fenix5"]).drawable_visible_level, true);
    assert.equal(guards(ALIGN, ["fenix6"]).drawable_visible_level, false);
    assert.equal(guards(ALIGN, ["fenix6"]).resource_reference_level, true);
  }
  assert.equal(guards(ALIGN, ["fenix8solar47mm"]).resource_reference_level, false);
});

test("a frame reads a guarded module behind a check written in the read, not one kept in a local", () => {
  if (!installed("venu", "fenix8solar47mm")) return;
  const v = view(bound("venu, fenix8solar47mm"), ["venu", "fenix8solar47mm"]);
  assert.match(v, /var solarInputComplication = \(Toybox has :Complications\) \? WfbComplications\.valueOf\(/);
  assert.doesNotMatch(v, /var hasComplications/);
  assert.doesNotMatch(view(bound("fenix8solar47mm"), ["fenix8solar47mm"]), /Toybox has :Complications/);
});

test("SlotText's switch sits inside the module check where a type is newer than a target", () => {
  if (!installed("fr955", "fenix8solar47mm")) return;
  const guarded = generated(slotted("fr955", "any"), ["fr955"]).get("source/SlotText.mc")!;
  assert.match(guarded, /as String\? \{\n        if \(Toybox has :Complications\) \{\n            var value = c\.value;/);
  assert.match(guarded, /\n        return null;\n    \}/);
  assert.doesNotMatch(generated(slotted("fenix8solar47mm", "any"), ["fenix8solar47mm"]).get("source/SlotText.mc")!, /Toybox has/);
});

test("the editor's callbacks name each symbol under a check on its own module or class", () => {
  if (!installed("venusq2", "fenix8solar47mm")) return;
  const files = generated(ALIGN, ["venusq2", "fenix8solar47mm"]);
  const delegate = [...files].find(([name]) => name.endsWith("Delegate.mc") && !name.includes("ConfigMenu"))![1];
  assert.match(delegate, /if \(Application has :WatchFaceConfig\) \{\n\s+var id = options\[:configId\]/);
  assert.match(delegate, /\(WatchUi has :WATCH_FACE_CONFIG_TYPE_COMPLICATION\) && options\[:type\] == WatchUi\.WATCH_FACE_CONFIG_TYPE_COMPLICATION/);
  assert.match(delegate, /if \(WatchUi\.WatchFaceDelegate has :setSelectedComplication\) \{\n\s+setSelectedComplication\(chosen\);/);
  const v = [...files].find(([name]) => name.endsWith("View.mc"))![1];
  assert.match(v, /function applyConfig\(settings as WatchFaceConfig\.Settings\) as Void \{\n\s+if \(Application has :WatchFaceConfig\) \{/);
  assert.match(v, /if \(\(WatchUi has :ComplicationDrawableRef\) && box != null\)/);
  const drawable = [...files].find(([name]) => name.endsWith("SlotDrawable.mc"))![1];
  assert.match(drawable, /if \(Graphics has :BoundingBox\) \{\n\s+var box = new Graphics\.BoundingBox\(\);/);
  const plain = [...generated(ALIGN, ["fr955", "fenix8solar47mm"])].find(([name]) => name.endsWith("Delegate.mc") && !name.includes("ConfigMenu"))![1];
  assert.doesNotMatch(plain, /has :WatchFaceConfig|has :setSelectedComplication/);
});

test("the barrel checks the module itself, every caller notwithstanding", () => {
  const complications = RUNTIME_LIB.get("WfbComplications.mc")!;
  for (const fn of ["subscribe", "valueOf", "count"]) {
    assert.match(complications.split(`function ${fn}(`)[1]!.split("\n    }")[0]!, /if \(Toybox has :Complications\) \{/, fn);
  }
  assert.match(RUNTIME_LIB.get("WfbReading.mc")!.split("function unitSuffix(")[1]!, /if \(Toybox has :Complications\) \{\n\s+switch \(unit\)/);
  // An early return on the negated check is not one monkeyc 9.3.0 sees.
  assert.doesNotMatch(RUNTIME_LIB.get("WfbConditions.mc")!, /if \(!\(Toybox has :Weather\)\)/);
});
