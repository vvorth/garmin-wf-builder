// The `whole-degree` lint: `dc.drawArc` truncates its angles, so an arc
// whose start or sweep is off a whole degree is drawn somewhere else.
import assert from "node:assert/strict";
import { test } from "node:test";
import { checked, MINIMAL } from "./designs.ts";

const findings = (body: string): string[] =>
  checked(MINIMAL + body).filter((d) => d.code === "whole-degree").map((d) => d.message);

const shape = (start: string, sweep: string): string => `
  ring:
    type: arc
    at: { anchor: center }
    radius: 90%r
    thickness: 4px
    start_angle: ${start}
    sweep: ${sweep}
    color: color.fg
`;

const segments = (start: string, sweep: string, gap: string, lint = ""): string => `
  steps:
    type: gauge
    style: segments
    value: activity.steps
    max: activity.step_goal
    at: { anchor: center }
    radius: 93%r
    thickness: 8%r
    start_angle: ${start}
    sweep: ${sweep}
    count: 12
    gap: ${gap}
    color: color.fg
    absent: hide${lint}
`;

const cells = (start: string, sweep: string, step: string, count = 12): string => `
  cells:
    type: pattern
    pattern: radial
    at: { anchor: center }
    count: ${count}
    step_angle: ${step}
    color: color.fg
    parts:
      cell: { type: arc, radius: 93%r, thickness: 8%r, start_angle: ${start}, sweep: ${sweep} }
`;

const scale = (to: string): string => `
  hr:
    type: gauge
    style: scale
    value: heart_rate.current
    max: 200
    at: { anchor: center }
    radius: 58%r
    thickness: 3px
    start_angle: 240deg
    sweep: 240deg
    color: color.fg
    bands:
      - { to: ${to}, color: color.fg }
      - { to: 1.0, color: color.bg }
    absent: hide
`;

test("an arc on whole degrees is quiet; a half-degree start or sweep warns with where it lands", () => {
  assert.deepEqual(findings(shape("-2deg", "-11deg")), []);
  assert.deepEqual(findings(shape("-1.5deg", "-12deg")),
    ["ring: on fenix8solar47mm, its arc from -1.5deg sweeping -12deg is off a whole degree -- it draws from -2deg sweeping -12deg"]);
  assert.deepEqual(findings(shape("10deg", "12.5deg")),
    ["ring: on fenix8solar47mm, its arc from 10deg sweeping 12.5deg is off a whole degree -- it draws from 10deg sweeping 13deg"]);
});

test("a segments gauge: whole cells and gaps are quiet; half-degree cells warn, with the default gap too", () => {
  assert.deepEqual(findings(segments("358deg", "-176deg", "4deg")), []);
  assert.deepEqual(findings(segments("358.5deg", "-177deg", "3deg")),
    ["steps: on fenix8solar47mm, all 12 of its arcs are off a whole degree -- the first, from 358.5deg sweeping -12deg, draws from 358deg sweeping -12deg"]);
  const unwritten = (sweep: string): string => segments("359deg", sweep, "2deg").replace("    gap: 2deg\n", "");
  assert.deepEqual(findings(unwritten("-178deg")), [], "(178 - 11 x 2) / 12 = 13deg a cell");
  assert.equal(findings(unwritten("-176deg")).length, 1, "(176 - 11 x 2) / 12 is not whole");
});

test("a radial pattern's arc part: every copy is checked, not only copy 0", () => {
  assert.deepEqual(findings(cells("-2deg", "-11deg", "-15deg")), []);
  assert.deepEqual(findings(cells("-1.5deg", "-12deg", "-15deg")),
    ["cells.cell: on fenix8solar47mm, all 12 of its arcs are off a whole degree -- the first, from -1.5deg sweeping -12deg, draws from -2deg sweeping -12deg"]);
  assert.deepEqual(findings(cells("0deg", "10deg", "7.5deg", 2)),
    ["cells.cell: on fenix8solar47mm, 1 of its 2 arcs, from 7.5deg sweeping 10deg, is off a whole degree -- it draws from 7deg sweeping 10deg"]);
});

test("a scale's bands are arcs too", () => {
  assert.deepEqual(findings(scale("0.5")), []);
  assert.deepEqual(findings(scale("0.33")),
    ["hr: on fenix8solar47mm, 2 of its 3 arcs are off a whole degree -- the first, from 240deg sweeping 79.2deg, draws from 240deg sweeping 79deg"]);
});

test("whole-degree is suppressible with a reason", () => {
  const allowed = segments("358.5deg", "-177deg", "3deg", `
    lint: { allow: [whole-degree], reason: "a degree either way is fine here" }`);
  assert.deepEqual(findings(allowed), []);
});
