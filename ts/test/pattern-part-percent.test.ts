// A linear or grid pattern's parts measure `%` against the box the pattern
// sits in (a group's, or the screen's): across for x and a width, down for y
// and a height, the smaller side for a radius. A radial pattern turns its
// parts and a hand turns with the time, so both keep refusing `%`.
import assert from "node:assert/strict";
import { test } from "node:test";
import { type PlacedPattern, type ResolvedHandPart } from "../src/layout.ts";
import { errors, MINIMAL, resolved } from "./designs.ts";
import { dataOf, newStudio } from "./studio-client.ts";
import { bundle } from "../src/studio/bundle.ts";

/** A pattern in a 70%r × 20%r group (91 × 26 px on fenix8solar47mm, 98 × 28 on 51mm), its parts in `lengths`. */
const grouped = (pattern: string, bar: string, dot: string): string => `${MINIMAL}
  row:
    type: group
    at: {anchor: center}
    size: {width: 70%r, height: 20%r}
    children:
      bars:
        type: pattern
        pattern: ${pattern}
        at: {anchor: left, dx: 7%}
        count: 7
        ${pattern === "radial" ? "step_angle: 30" : "step: {dx: 14%}"}
        color: color.fg
        parts:
          bar: {type: rectangle, size: ${bar}}
          dot: {type: circle, at: {dy: ${dot}}, radius: 5%}
`;

const extent = (part: ResolvedHandPart, axis: 0 | 1): number => {
  const values = (part as unknown as { points: [number, number][] }).points.map((p) => p[axis]);
  return Math.max(...values) - Math.min(...values);
};
const bars = (text: string, device: string): PlacedPattern => resolved(text, device).items.find((p) => p.id === "bars") as PlacedPattern;
const messages = (text: string): string[] => errors(text).map((d) => d.message);

test("a linear pattern's part `%` lengths measure the group's box, per axis", () => {
  const text = grouped("linear", "{width: 10%, height: 80%}", "-30%");
  assert.deepEqual(messages(text), []);
  // a rectangle part's corners round half away from its centre: 9.1 px across draws 10, 20.8 px down draws 20
  for (const [device, frame, bar, dot] of [
    ["fenix8solar47mm", [91, 26], [10, 20], [1, -8]],
    ["fenix8solar51mm", [98, 28], [10, 22], [1, -8]],
  ] as const) {
    const placed = bars(text, device);
    assert.deepEqual([placed.part_frame.width, placed.part_frame.height], frame, device);
    const [rectangle, circle] = placed.parts as [ResolvedHandPart, ResolvedHandPart];
    // a width is across and a height down, of the group's box, not the screen's 260 or 280
    assert.deepEqual([extent(rectangle, 0), extent(rectangle, 1)], bar, device);
    const { radius, y } = circle as unknown as { radius: number; y: number };
    assert.deepEqual([radius, y], dot, `${device}: a radius takes the smaller side, a dy is down`);
  }
});

test("a top-level grid pattern's part `%` measures the screen; `%r` stays the screen's radius", () => {
  const text = `${MINIMAL}
  dots:
    type: pattern
    pattern: grid
    at: {anchor: center}
    count: 4
    columns: 2
    step: {dx: 20%, dy: 20%}
    color: color.fg
    parts:
      by_screen: {type: rectangle, size: {width: 10%, height: 5%}}
      by_radius: {type: rectangle, size: {width: 10%r, height: 5%r}}
`;
  assert.deepEqual(messages(text), []);
  const placed = resolved(text, "fenix8solar47mm").items.find((p) => p.id === "dots") as PlacedPattern;
  const [screen, radius] = placed.parts as [ResolvedHandPart, ResolvedHandPart];
  assert.deepEqual([extent(screen, 0), extent(screen, 1)], [26, 14]); // 10 % and 5 % of 260: 26 and 13, its corners rounded away
  assert.deepEqual([extent(radius, 0), extent(radius, 1)], [14, 6]); // 13 and 6.5 px, of the 130 px radius
});

test("a radial pattern's and a hand's parts still refuse `%`, and every pattern refuses pt", () => {
  const radial = messages(grouped("radial", "{width: 10%, height: 4px}", "-30px"));
  assert.ok(radial.some((m) => /a radial pattern part's lengths are px or %r only; a radial pattern turns each copy's parts/.test(m)), radial.join("\n"));
  assert.equal(radial.length, 2, radial.join("\n")); // the width and the radius; the px dy passes
  const curved = messages(`${MINIMAL}
  ring:
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 4
    step_angle: 90
    color: color.fg
    parts:
      label: {type: text, text: A, font: FONT_SMALL, at: {dy: -40px}, curve: {radius: 30%}}
`);
  assert.ok(curved.some((m) => /radial pattern part's lengths are px or %r only/.test(m) && /curve/.test(m)), curved.join("\n"));
  const pt = messages(grouped("linear", "{width: 10pt, height: 80%}", "-30%"));
  assert.ok(pt.some((m) => /a pattern part's lengths are px, % or %r only/.test(m)), pt.join("\n"));
  const hand = messages(`${MINIMAL.replace("resources:\n", `resources:
  hand_sets:
    plain:
      hour:
        color: color.fg
        parts:
          blade: {type: rectangle, size: {width: 3%, height: 40%r}}
`)}
  clock:
    type: hands
    at: {anchor: center}
    set: plain
`);
  assert.ok(hand.some((m) => /a hand part's lengths are px or %r only/.test(m)), hand.join("\n"));
});

test("dragging a linear pattern's `%` part writes `%` measured against the group", async () => {
  const studio = await newStudio();
  const doc = studio.create(bundle("T", grouped("linear", "{width: 10%, height: 80%}", "-30%")), "new");
  const part = (id: string): any => dataOf(doc).elements.row.children.bars.parts[id];
  // 91 px across: 0.91 px per % of width; 26 px down: 0.26 px per % of height
  doc.drag("elements/row/children/bars/parts/bar", { kind: "resize", key: ["size", "width"], delta: 8 }, "fenix8solar47mm", "auto", doc.version);
  doc.drag("elements/row/children/bars/parts/dot", { kind: "move", dx: 0, dy: 13 }, "fenix8solar47mm", "auto", doc.version);
  // of the screen, the same 8 px would be about 3 % and 13 px about 5 %
  assert.equal(part("bar").size.width, "19%");
  assert.equal(part("dot").at.dy, "20%");
  const [bar, dot] = bars(doc.text, "fenix8solar47mm").parts as [ResolvedHandPart, ResolvedHandPart];
  assert.equal(extent(bar, 0), 18);
  assert.equal((dot as unknown as { y: number }).y, 5);
});
