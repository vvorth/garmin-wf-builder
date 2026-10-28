// A segmented gauge's `gap:`: a length along the track, or, on an arc, an
// angle with its unit, the same number of degrees on every screen.
import assert from "node:assert/strict";
import { test } from "node:test";
import { indexFor } from "../src/edit/spans.ts";
import type { PlacedGauge } from "../src/layout.ts";
import { inspect } from "../src/studio/inspect.ts";
import { errors, MINIMAL, resolved } from "./designs.ts";

const arc = (gap: string, sweep = "-180deg"): string => MINIMAL + `
  steps:
    type: gauge
    style: segments
    value: activity.steps
    max: activity.step_goal
    at: { anchor: center }
    radius: 93.5%r
    thickness: 6%r
    start_angle: 360deg
    sweep: ${sweep}
    count: 12
    gap: ${gap}
    color: color.fg
    absent: hide
`;

const gauge = (text: string, device: string): PlacedGauge => resolved(text, device).items.find((p) => p.id === "steps") as PlacedGauge;

test("an angle gap is that many degrees between cells on every screen, signed with the sweep", () => {
  for (const device of ["fenix8solar47mm", "fenix8solar51mm", "fr955"]) {
    const g = gauge(arc("3deg"), device);
    assert.ok(Math.abs(g.step - g.cell - -3) < 1e-9, `${device}: gap ${g.step - g.cell}`);
    // twelve cells and eleven gaps fill the sweep
    assert.ok(Math.abs(12 * g.cell + 11 * -3 - -180) < 1e-9);
  }
  const ccw = gauge(arc("0.01turn", "180deg"), "fenix8solar47mm");
  assert.ok(Math.abs(ccw.step - ccw.cell - 3.6) < 1e-9, `turns: ${ccw.step - ccw.cell}`);
});

test("an arc with no gap: written gets 2 degrees between cells on every screen", () => {
  const unwritten = arc("2deg").replace("    gap: 2deg\n", "");
  for (const device of ["fenix8solar47mm", "fenix8solar51mm", "fr955"]) {
    const g = gauge(unwritten, device);
    assert.ok(Math.abs(g.step - g.cell - -2) < 1e-9, `${device}: gap ${g.step - g.cell}`);
  }
});

test("a length gap on an arc is refused, a bare number included: an arc is measured in degrees", () => {
  for (const gap of ["5px", "2%r", "3%", "5"]) {
    const text = arc(gap);
    const found = errors(text);
    assert.equal(found.length, 1, found.map((d) => d.message).join("\n"));
    assert.equal(found[0]!.message,
      `steps: 'gap: ${gap}' is a length, but an arc's cells are measured in degrees -- give it as an angle, such as 2deg (the default)`);
    assert.equal(found[0]!.span?.line, text.split("\n").findIndex((l) => l.includes(`gap: ${gap}`)) + 1);
  }
});

test("an angle gap on a bar, or a gap of no known unit, is refused", () => {
  const bar = MINIMAL + `
  steps:
    type: gauge
    style: segments
    value: activity.steps
    max: activity.step_goal
    at: { anchor: center }
    size: { width: 60%, height: 8px }
    count: 10
    gap: 3deg
    color: color.fg
    absent: hide
`;
  const found = errors(bar);
  assert.equal(found.length, 1, found.map((d) => d.message).join("\n"));
  assert.match(found[0]!.message, /steps: 'gap: 3deg' is an angle, which only an arc gauge has/);
  assert.equal(found[0]!.span?.line, bar.split("\n").findIndex((l) => l.includes("gap: 3deg")) + 1);
  assert.ok(errors(arc("3dog")).length > 0);
});

test("the editor offers an arc gauge's gap as an angle and a bar's as a length", () => {
  const gapField = (text: string) => {
    const path = [...indexFor(text).elements().find((e) => e.name === "steps")!.path];
    return inspect(text, path, null).fields.find((f) => f.key === "gap")!;
  };
  const onArc = gapField(arc("3deg"));
  assert.equal(onArc.widget, "angle");
  assert.equal(onArc.value, "3deg");
  const onBar = gapField(MINIMAL + `
  steps:
    type: gauge
    style: segments
    value: activity.steps
    max: activity.step_goal
    at: { anchor: center }
    size: { width: 60%, height: 8px }
    count: 10
    gap: 3px
    color: color.fg
    absent: hide
`);
  assert.equal(onBar.widget, "length");
  assert.equal(onBar.value, "3px");
});
