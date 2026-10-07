// A touch and hold reaches only a target the last frame drew.
import assert from "node:assert/strict";
import { test } from "node:test";
import { Bag } from "../src/diagnostics.ts";
import { checkHoldTargets } from "../src/lint.ts";
import { generated, MINIMAL, resolved } from "./designs.ts";

const DESIGN = MINIMAL + `
  hr:
    type: text
    text: "{heart_rate.current}"
    absent: hide
    font: FONT_SMALL
    at: {anchor: center, dy: -30%}
    color: color.fg
    visible: heart_rate.current > 100
    on_hold: heart_rate
  plain:
    type: text
    text: "B"
    font: FONT_SMALL
    at: {anchor: center}
    color: color.fg
    visible: "true"
    on_hold: battery
  box:
    type: group
    visible: activity.steps > 10
    on_hold: steps
    children:
      s:
        type: text
        text: "{activity.steps}"
        absent: hide
        font: FONT_SMALL
        at: {anchor: center, dy: 30%}
        color: color.fg
`;

const file = (files: Map<string, string>, suffix: string): string => [...files].find(([name]) => name.endsWith(suffix))![1];
/** The delegate's `if` testing `id`'s hold box, through to its opening brace. */
const hitTest = (delegate: string, id: string): string => delegate.split(`// \`${id}\``)[1]!.split("{")[0]!;

test("a hold reaches a target only while its visible: last held", () => {
  const files = generated(DESIGN);
  const view = file(files, "View.mc"), delegate = file(files, "Delegate.mc");
  assert.match(view, /var holdsShown as Number = 0;/);
  assert.match(view.split("function onUpdate")[1]!, /^[^}]*holdsShown = 0;/);
  // each sets its bit only past its own visible: guard; a group's member sets the group's
  assert.match(view.split("function drawHr")[1]!, /return;\s*}\s*holdsShown \|= 0x1;/);
  assert.match(view.split("function drawS")[1]!, /return;\s*}\s*holdsShown \|= 0x2;/);
  assert.match(hitTest(delegate, "hr"), /\(_view\.holdsShown & 0x1\) != 0/);
  assert.match(hitTest(delegate, "box"), /\(_view\.holdsShown & 0x2\) != 0/);
  // a condition that is always true gates nothing
  assert.doesNotMatch(hitTest(delegate, "plain"), /holdsShown/);
  assert.doesNotMatch(view.split("function drawPlain")[1]!.split("\n    }")[0]!, /holdsShown/);
});

test("a face with no hidden hold target has no mask", () => {
  const files = generated(DESIGN.replace("visible: heart_rate.current > 100", "").replace("visible: activity.steps > 10", ""));
  for (const text of files.values()) assert.doesNotMatch(text, /holdsShown/);
});

/** `text`'s hold-overlap warning against `hr`. */
function overlap(text: string): string {
  const bag = new Bag();
  checkHoldTargets(resolved(text), bag);
  return bag.items.find((d) => d.code === "hold-overlap" && d.message.includes("overlaps hr's"))!.message;
}

test("hold-overlap says a hidden first target lets the second through", () => {
  const overlapping = DESIGN.replace("dy: -30%", "dy: 30%");
  assert.match(overlap(overlapping), /opens 'heart_rate' whenever hr is drawn$/);
  assert.match(overlap(overlapping.replace("visible: heart_rate.current > 100", "")), /always opens 'heart_rate'$/);
});
