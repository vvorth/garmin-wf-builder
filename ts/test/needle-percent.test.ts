// A gauge needle's parts measure `%` against the smaller side of the box the
// gauge sits in (a group's, or the screen's), for every length: a needle
// turns, so a per-axis `%` would give it one proportion pointing up and
// another pointing sideways in a box that is not square.
import assert from "node:assert/strict";
import { test } from "node:test";
import { type PlacedGauge, type ResolvedCirclePart, type ResolvedLinePart, type RotatablePart } from "../src/layout.ts";
import { bundle } from "../src/studio/bundle.ts";
import { inspect } from "../src/studio/inspect.ts";
import { errors, MINIMAL, resolved } from "./designs.ts";
import { dataOf, newStudio } from "./studio-client.ts";

/** A needle gauge in a `width` × `height` group, its parts written in `parts`. */
const grouped = (width: string, height: string, parts: string): string => `${MINIMAL}
  sub:
    type: group
    at: {anchor: center, dy: 40%r}
    size: {width: ${width}, height: ${height}}
    children:
      dial:
        type: gauge
        style: needle
        value: system.battery
        max: 100
        at: {anchor: center}
        start_angle: 240deg
        sweep: 240deg
        color: color.fg
        needle:
${parts}`;

const NEEDLE = `          blade: {type: rectangle, at: {dy: -25%}, size: {width: 10%, height: 50%}}
          tip: {type: line, to: {dy: -80%}, thickness: 10%}
          hub: {type: circle, radius: 10%}
`;

const extent = (part: RotatablePart, axis: 0 | 1): number => {
  const values = (part as unknown as { points: [number, number][] }).points.map((p) => p[axis]);
  return Math.max(...values) - Math.min(...values);
};
const dial = (text: string, device: string): PlacedGauge => resolved(text, device).items.find((p) => p.id === "dial") as PlacedGauge;
const messages = (text: string): string[] => errors(text).map((d) => d.message);
/** The blade's width and height, the tip's reach and pen, the hub's radius. */
function measured(placed: PlacedGauge): number[] {
  const [blade, tip, hub] = placed.needle as [RotatablePart, RotatablePart, RotatablePart];
  const line = tip as ResolvedLinePart;
  return [extent(blade, 0), extent(blade, 1), line.y2, line.thickness, (hub as ResolvedCirclePart).radius];
}

test("a needle's `%` lengths all take the smaller side of the group's box", () => {
  // 70%r × 20%r is 91 × 26 px on fenix8solar47mm and 98 × 28 on 51mm: the needle measures 26 (28) for every length
  const wide = grouped("70%r", "20%r", NEEDLE);
  const tall = grouped("20%r", "70%r", NEEDLE);
  assert.deepEqual(messages(wide), []);
  for (const [device, side, lengths] of [
    // a width of 10 % is 2.6 px (its corners, ±1.3 from the centre, round to ±1: 2), a height of 50 % 13 px from -13 to 0, the tip -20.8, its pen 2.6, the hub 2.6
    ["fenix8solar47mm", 26, [2, 13, -21, 3, 3]],
    ["fenix8solar51mm", 28, [2, 14, -22, 3, 3]],
  ] as const) {
    const placed = dial(wide, device);
    assert.deepEqual([placed.part_frame.width, placed.part_frame.height], [side, side], device);
    assert.deepEqual(measured(placed), lengths, device);
    // a box on its side measures the same: the smaller side, not the width or the height
    assert.deepEqual(measured(dial(tall, device)), lengths, `${device}, the group turned on its side`);
  }
});

test("a top-level needle's `%` takes the screen's smaller side; `%r` and px are unchanged", () => {
  const text = `${MINIMAL}
  dial:
    type: gauge
    style: needle
    value: system.battery
    max: 100
    at: {anchor: center}
    start_angle: 240deg
    sweep: 240deg
    color: color.fg
    needle:
      by_screen: {type: line, to: {dy: -40%}, thickness: 2px}
      by_radius: {type: line, to: {dy: -40%r}, thickness: 2px}
`;
  assert.deepEqual(messages(text), []);
  for (const [device, ends] of [["fenix8solar47mm", [-104, -52]], ["fr955", [-104, -52]]] as const) {
    const [screen, radius] = dial(text, device).needle as [ResolvedLinePart, ResolvedLinePart];
    assert.deepEqual([screen.y2, radius.y2], ends, device); // 40 % of 260, and of its 130 px radius
  }
});

test("a needle part refuses pt and an anchor with a needle's own message", () => {
  const pt = messages(grouped("70%r", "20%r", "          tip: {type: line, to: {dy: -80%}, thickness: 1pt}\n"));
  assert.deepEqual(pt.filter((m) => /needle part's lengths are px, % or %r only; a needle has no font for 'pt'/.test(m)).length, 1, pt.join("\n"));
  assert.equal(pt.length, 1, pt.join("\n"));
  const anchored = messages(grouped("70%r", "20%r", "          tip: {type: line, at: {anchor: top}, to: {dy: -80%}}\n"));
  assert.ok(anchored.some((m) => /'anchor:' is not accepted in a needle part/.test(m)), anchored.join("\n"));
});

test("dragging a needle's `%` part writes `%` of the group's smaller side", async () => {
  const studio = await newStudio();
  const doc = studio.create(bundle("T", grouped("70%r", "20%r", NEEDLE)), "new");
  const part = (id: string): any => dataOf(doc).elements.sub.children.dial.needle[id];
  // 26 px is the smaller side: 0.26 px per %, whichever way the drag goes; of the 91 px width a widening would be 0.91 px per %
  doc.drag("elements/sub/children/dial/needle/hub", { kind: "resize", key: ["radius"], delta: 13 }, "fenix8solar47mm", "auto", doc.version);
  assert.equal(part("hub").radius, "60%");
  doc.drag("elements/sub/children/dial/needle/blade", { kind: "resize", key: ["size", "width"], delta: 4 }, "fenix8solar47mm", "auto", doc.version);
  assert.equal(part("blade").size.width, "25%"); // against the 91 px width it would be about 14 %
  const [blade, , hub] = dial(doc.text, "fenix8solar47mm").needle as [RotatablePart, RotatablePart, RotatablePart];
  assert.equal((hub as ResolvedCirclePart).radius, 16);
  assert.equal(extent(blade, 0), 6);
});

test("the Inspector reads a needle part from the needle's own schema branch", () => {
  const text = grouped("70%r", "20%r", NEEDLE);
  const fields = inspect(text, ["elements", "sub", "children", "dial", "needle", "blade"], null).fields;
  const color = fields.find((f) => f.key === "color")!;
  assert.match(color.description, /the gauge's own 'color:'/);
  const size = fields.find((f) => f.key === "size")!;
  assert.deepEqual(size.children!.map((c) => [c.key, c.widget]), [["width", "length"], ["height", "length"]]);
});
