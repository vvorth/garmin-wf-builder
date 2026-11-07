// A complication type constant a target's own symbol table lacks: the module
// check `monkeyc` accepts around it is no guard at run time (the VM resolves
// the constant when it reaches it and throws Symbol Not Found), so every
// shared reference to one carries an inline `has` check naming it, and
// `generate` refuses a reference without one.
import assert from "node:assert/strict";
import { test } from "node:test";
import * as availability from "../src/availability.ts";
import { emitGraphRebuild } from "../src/emit/monkeyc/graph.ts";
import { emitTypeSwitch } from "../src/emit/monkeyc/type_guards.ts";
import { generate, unguardedTypes } from "../src/emit/project.ts";
import { bakeFonts } from "../src/emit/resources.ts";
import { Writer } from "../src/emit/writer.ts";
import { type PlacedGraph, resolve } from "../src/layout.ts";
import { db, face, generated, MINIMAL, read } from "./designs.ts";

const installed = (...ids: string[]): boolean => ids.every((id) => db.ids().includes(id));

/** A slot offering sleep_score (API 6.0.2, absent from fr955's table) shown as text, icon and scale, a max: auto gauge on it, and a hold target naming it. */
const DESIGN = `${MINIMAL.replace("targets: [fenix8solar47mm]", "targets: [fenix8solar47mm, fr955]")
  .replace("elements:", `config:
  slots:
    top: { default: steps, choices: [steps, heart_rate, sleep_score] }
elements:`)}
    on_hold: sleep_score
  ring:
    type: gauge
    slot: top
    style: scale
    at: {anchor: center}
    radius: 45%r
    thickness: 4px
    start_angle: 240deg
    sweep: 240deg
    color: color.fg
    absent: hide
  sleep:
    type: gauge
    style: arc
    value: complication.sleep_score
    max: auto
    at: {anchor: center}
    radius: 30%r
    thickness: 4px
    start_angle: 240deg
    sweep: 240deg
    color: color.fg
    absent: hide
  history:
    type: graph
    slot: top
    style: bars
    bar_width: 3px
    at: {anchor: center, dy: 25%}
    size: {width: 60%, height: 15%}
    color: color.fg
  reading:
    type: data
    slot: top
    at: {anchor: center}
    font: FONT_SMALL
    icon: { size: 12%r, gap: 1%r, color: color.fg }
    color: color.fg
`;

const project = (text: string, ids: string[]) => generate(face(text), ids.map((id) => db.get(id)), read);
const SLEEP = "COMPLICATION_TYPE_SLEEP_SCORE";

test("gated_types: the named types some target with the module lacks", () => {
  if (!installed("fenix8solar47mm", "fr955")) return;
  const guards = (ids: string[]) => availability.computeGuards(face(DESIGN), ids.map((id) => db.get(id)));
  assert.deepEqual([...guards(["fenix8solar47mm", "fr955"]).gated_types], ["sleep_score"]);
  assert.deepEqual([...guards(["fenix8solar47mm"]).gated_types], []);
  if (installed("fenix5")) assert.deepEqual([...guards(["fenix8solar47mm", "fenix5"]).gated_types], [], "fenix5 has no module, which the module check covers");
});

test("the generate-time check: a bare reference to a constant some target lacks is reported, a has-covered one is not", () => {
  if (!installed("fr955")) return;
  const fr955 = [db.get("fr955")];
  const src = [
    "function a(t) {",
    "    if (Toybox has :Complications) {",
    "        switch (t) {",
    `            case Complications.${SLEEP}: return 1;`,
    "        }",
    "    }",
    `    if ((Complications has :${SLEEP}) && t == Complications.${SLEEP}) { return 2; }`,
    `    if (Complications has :${SLEEP}) {`,
    `        var x = Complications.${SLEEP};`,
    "    } else {",
    `        var y = Complications.${SLEEP};`,
    "    }",
    `    // Complications.${SLEEP} in a comment`,
    `    var s = "Complications.${SLEEP}";`,
    `    var z = Complications.COMPLICATION_TYPE_STEPS;`,
    "}",
  ].join("\n");
  assert.deepEqual(unguardedTypes("source/A.mc", src, fr955).map((u) => [u.line, u.constant, u.device]),
    [[4, SLEEP, "fr955"], [11, SLEEP, "fr955"]]);
  assert.deepEqual(unguardedTypes("source/A.mc", src, [db.get("fenix8solar47mm")]), [], "a build whose targets all have it checks nothing");
});

test("every shared reference to a gated type sits inside a has check naming it", () => {
  if (!installed("fenix8solar47mm", "fr955")) return;
  assert.deepEqual(project(DESIGN, ["fenix8solar47mm", "fr955"]).unguarded_types, []);
  if (installed("fr255")) assert.deepEqual(project(DESIGN, ["fr255"]).unguarded_types, []);
});

/** Each line of `text` naming `constant`, trimmed. */
function references(text: string, constant: string): string[] {
  return text.split("\n").filter((line) => line.includes(`Complications.${constant}`)).map((line) => line.trim());
}

test("the reproduction: SlotText, the icon chooser, the scale, the reads and the hold target test sleep_score behind its own check", () => {
  if (!installed("fenix8solar47mm", "fr955")) return;
  const files = generated(DESIGN, ["fenix8solar47mm", "fr955"]);
  const slotText = files.get("source/SlotText.mc")!;
  const viewText = files.get("source/TestView.mc")!;
  const delegate = files.get("source/TestDelegate.mc")!;
  const scale = files.get("source/SlotScale.mc")!;
  const hoisted = `if ((Complications has :${SLEEP}) && t == Complications.${SLEEP}) {`;
  assert.deepEqual(references(slotText, SLEEP), [hoisted]);
  assert.match(slotText, new RegExp(`${hoisted.replace(/[()]/g, "\\$&")}\\n\\s+return WfbReading\\.count\\(value, c\\.unit, short\\);`));
  assert.deepEqual(references(scale, SLEEP), [hoisted]);
  assert.match(scale, /case Complications\.COMPLICATION_TYPE_STEPS:/, "a type every target has stays in the switch");
  // the icon chooser, the frame's read, the subscription and max: auto's scale
  assert.deepEqual(references(viewText, SLEEP), [
    `WfbComplications.subscribe(new Complications.Id(Complications.${SLEEP}));`,
    `var sleepScoreComplication = ((Toybox has :Complications) && (Complications has :${SLEEP})) ? WfbComplications.valueOf(new Complications.Id(Complications.${SLEEP})) : null;`,
    hoisted,
    `var scale = ((Toybox has :Complications) && (Complications has :${SLEEP}) && sleepScoreComplication != null) ? SlotScale.scale(Complications.${SLEEP}, sleepScoreComplication) : null;`,
  ]);
  assert.match(viewText, new RegExp(`if \\(Complications has :${SLEEP}\\) \\{\\n\\s+WfbComplications\\.subscribe`));
  assert.match(delegate, new RegExp(`if \\(\\(Toybox has :Complications\\) && \\(Complications has :${SLEEP}\\)\\) \\{\\n\\s+Complications\\.exitTo\\(new Complications\\.Id\\(Complications\\.${SLEEP}\\)\\);`));
});

test("a build whose every target has the type writes the plain switch", () => {
  if (!installed("fenix8solar47mm")) return;
  const files = generated(DESIGN.replace("targets: [fenix8solar47mm, fr955]", "targets: [fenix8solar47mm]"), ["fenix8solar47mm"]);
  const all = [...files.values()].join("\n");
  assert.doesNotMatch(all, /has :COMPLICATION_TYPE_/);
  assert.match(files.get("source/SlotText.mc")!, new RegExp(`case Complications\\.${SLEEP}:\\n\\s+case Complications\\.COMPLICATION_TYPE_STEPS: return WfbReading\\.count`));
  assert.match(files.get("source/SlotScale.mc")!, new RegExp(`case Complications\\.${SLEEP}:\\n\\s+return \\[0, 100\\]`));
});

test("a slot graph's pick of a gated type is tested behind its own check", () => {
  if (!installed("fenix8solar47mm", "fr955")) return;
  // No installed target lacks a plottable type, so gate one by hand: the emitter reads only Guards.
  const resolvedFace = resolve(face(DESIGN), db.get("fenix8solar47mm"), bakeFonts(face(DESIGN), db.get("fenix8solar47mm"), read));
  const graph = resolvedFace.items.find((p) => p.id === "history") as PlacedGraph;
  const w = new Writer();
  emitGraphRebuild(w, graph, { ...availability.NO_GUARDS, complications: true, gated_types: new Set(["steps"]) });
  const text = w.render();
  assert.match(text, /if \(\(Toybox has :Complications\) && \(Complications has :COMPLICATION_TYPE_STEPS\) && t == Complications\.COMPLICATION_TYPE_STEPS\)/);
  assert.match(text, /if \(\(Toybox has :Complications\) && t == Complications\.COMPLICATION_TYPE_HEART_RATE\)/);
  assert.deepEqual(unguardedTypes("g.mc", text, []), []);
});

test("hoisting a fall-through group ORs each gated member behind its own check, and an emptied switch keeps its default", () => {
  const w = new Writer();
  emitTypeSwitch(w, { gated_types: new Set(["steps", "calories"]) }, [{ members: ["steps", "calories", "heart_rate"], body: "return 1;" }]);
  assert.equal(w.render(), [
    "if (((Complications has :COMPLICATION_TYPE_STEPS) && t == Complications.COMPLICATION_TYPE_STEPS) || "
      + "((Complications has :COMPLICATION_TYPE_CALORIES) && t == Complications.COMPLICATION_TYPE_CALORIES)) {",
    "    return 1;",
    "}",
    "switch (t) {",
    "    case Complications.COMPLICATION_TYPE_HEART_RATE: return 1;",
    "}",
    "",
  ].join("\n"));
  const all = new Writer();
  emitTypeSwitch(all, { gated_types: new Set(["steps"]) }, [{ members: ["steps"], body: "return 1;" }], { fallback: "return null;" });
  assert.equal(all.render(), "if ((Complications has :COMPLICATION_TYPE_STEPS) && t == Complications.COMPLICATION_TYPE_STEPS) {\n    return 1;\n}\nreturn null;\n");
});
