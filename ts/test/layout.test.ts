// Per-device layout: units, angles, boxes, draw order, clips, text extents,
// graphs and a data element's icon-and-text geometry.
import assert from "node:assert/strict";
import { test } from "node:test";
import { bakeFonts, ICON_FONT } from "../src/emit/resources.ts";
import { dataPairGeometry, insideScreen, insideVisibleAreaFor, isFullBleed, PlacedGraph, type Placed, resolve, type ResolvedFace } from "../src/layout.ts";
import { readFontFile } from "../src/node.ts";
import { REPO_ROOT } from "../src/devices/node.ts";
import { join } from "node:path";
import { db, face, resolved } from "./designs.ts";

const OPEN_SANS = "ts/test/fixtures/slice/assets/OpenSans-Regular.ttf";
const find = (r: ResolvedFace, id: string): any => r.items.find((p) => p.id === id)! as Placed & Record<string, any>;

const DESIGN = `
format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [fenix8solar47mm, fenix8solar51mm]
resources:
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
elements:
  background:
    type: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: color.bg
  ring:
    type: gauge
    style: arc
    value: activity.steps
    max: activity.step_goal
    at: {anchor: center}
    radius: 50%r
    thickness: 10px
    start_angle: 180deg
    sweep: 340deg
    color: color.fg
    absent: hide
  dot:
    type: circle
    at: {anchor: center, angle: 90deg, radius: 40%r}
    radius: 6px
    color: color.fg
  badge:
    type: icon
    icon: steps
    size: 20px
    at: {anchor: center, dy: 25%}
    color: color.fg
`;

const GRAPH = `
format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [fenix8solar47mm, fenix8solar51mm]
resources:
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
elements:
  hr_graph:
    type: graph
    series: heart_rate
    range: 4h
    style: line
    thickness: 3px
    color: color.fg
    at: {anchor: center}
    size: {width: 60%, height: 20%}
`;

const sleepy = DESIGN.replace("    at: {anchor: center, dy: 25%}\n    color: color.fg", "    at: {anchor: center, dy: 25%}\n    color: color.fg\n    sleep_update: true");

test("percent of the screen fills the framebuffer, per device", () => {
  const small = resolved(DESIGN), large = resolved(DESIGN, "fenix8solar51mm");
  const bg = find(small, "background").box;
  assert.deepEqual([bg.x, bg.y, bg.width, bg.height], [0, 0, 260, 260]);
  assert.equal(find(small, "ring").radius, 65);
  assert.equal(find(large, "ring").radius, 70);
  assert.deepEqual(find(small, "ring").center, [130, 130]);
  assert.deepEqual(find(large, "ring").center, [140, 140]);
});

test("angles: author's to Garmin's, polar placement, an arc's box", () => {
  const r = resolved(DESIGN);
  const ring = find(r, "ring");
  assert.equal(ring.start_angle, 180);
  assert.equal(ring.garmin_start, 270);
  assert.equal(ring.garmin_direction, "ARC_CLOCKWISE");
  assert.deepEqual(find(r, "dot").center, [182, 130]);
  assert.ok(ring.box.width >= 2 * (ring.radius + Math.floor(ring.thickness / 2)));
});

test("an icon is sized to its own glyph and centred", () => {
  const badge = find(resolved(DESIGN), "badge");
  assert.equal(badge.size, 20);
  assert.ok(badge.box.width > 0 && badge.box.height > 0);
  assert.deepEqual(badge.center, [130, 195]);
  assert.ok(badge.font_key && badge.codepoint);
});

test("full bleed, and a ring measured as a circle", () => {
  const device = db.get("fenix8solar47mm");
  const r = resolved(DESIGN);
  assert.ok(isFullBleed(find(r, "background").box, device));
  assert.ok(!isFullBleed(find(r, "badge").box, device));
  const ring = find(r, "ring");
  assert.ok(insideScreen(ring.box, device));
  assert.equal(insideVisibleAreaFor(ring, device), true);
});

test("draw order follows the document, and z overrides it", () => {
  assert.deepEqual(resolved(DESIGN).items.map((p) => p.id), ["background", "ring", "dot", "badge"]);
  assert.equal(resolved(DESIGN.replace("  background:\n", "  background:\n    z: 5\n")).items.at(-1)!.id, "background");
});

test("a text's extent comes from its real font", () => {
  const design = DESIGN.replace("resources:\n", `resources:\n  fonts:\n    clock:\n      source: ${OPEN_SANS}\n      size: 60px\n`)
    + "  clock:\n    type: text\n    text: \"{time.clock:%H:%M}\"\n    font: font.clock\n    at: {anchor: center}\n    color: color.fg\n";
  const clock = find(resolved(design), "clock");
  assert.equal(clock.widest, "23:59");
  assert.equal(clock.width_is_estimated, false);
  assert.ok(clock.measured_width > 0);
});

test("the low-power clip: none, the tight union, a group's box ignored, clamped off screen", () => {
  const device = db.get("fenix8solar47mm");
  assert.equal(resolved(DESIGN).clipFor("low_power"), null);
  const clip = resolved(sleepy).clipFor("low_power")!;
  assert.ok(clip.area < 0.05 * device.width * device.height);
  const grouped = DESIGN.replace("  badge:\n    type: icon\n    icon: steps\n    size: 20px\n    at: {anchor: center, dy: 25%}\n    color: color.fg\n",
    "  badge_group:\n    type: group\n    sleep_update: true\n    children:\n      badge:\n        type: icon\n        icon: steps\n        size: 20px\n        at: {anchor: center, dy: 25%}\n        color: color.fg\n        sleep_update: true\n");
  assert.deepEqual(resolved(grouped).clipFor("low_power"), clip);
  const off = DESIGN.replace("    at: {anchor: center, dy: 25%}\n    color: color.fg",
    "    at: {anchor: center, dy: 25%, dx: 500%}\n    color: color.fg\n    sleep_update: true\n    lint: {allow: [off-screen], reason: \"probing\"}");
  const offClip = resolved(off).clipFor("low_power")!;
  assert.ok(offClip.width >= 0 && offClip.height >= 0 && offClip.area === 0);
  const drawn = resolved(DESIGN).drawnInMode("active");
  assert.ok(drawn.length > 0 && drawn.every((p) => p.kind !== "group"));
});

test("the widest text accounts for a longer fallback", () => {
  const design = `
format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [fenix8solar47mm]
resources:
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
elements:
  background:
    type: rectangle
    at: {anchor: center}
    size: {width: 100%, height: 100%}
    color: color.bg
  status:
    type: text
    text: "{complication.training_status}"
    at: {anchor: center}
    color: color.fg
    absent: {value: "'Not Available'"}
`;
  assert.equal(find(resolved(design), "status").widest, "Not Available");
});

const fontDesign = (size: string, extra = "", text = "12:00"): string => `
format: 2
face: {id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57, name: Test}
build:
  targets: [fenix8solar47mm, fenix8solar51mm]
resources:
  fonts:
    clock:
      source: ${OPEN_SANS}
      size: ${size}
${extra}
  palette: {bg: "#000000", fg: "#FFFFFF"}
elements:
  clock:
    type: text
    text: "${text}"
    font: font.clock
    at: {anchor: center}
    color: color.fg
`;

test("a %r font size reaches the placed text per device", () => {
  const f = face(fontDesign("18%r"));
  const sizes = Object.fromEntries(["fenix8solar47mm", "fenix8solar51mm"].map((id) => {
    const device = db.get(id);
    return [id, find(resolve(f, device, bakeFonts(f, device, (p) => readFontFile(p === ICON_FONT ? p : join(REPO_ROOT, p)))), "clock").font.px];
  }));
  assert.deepEqual(sizes, { fenix8solar47mm: 23, fenix8solar51mm: 25 });
});

test("a monospaced font widens the placed text box", () => {
  const box = (extra: string): [any, any] => {
    const f = face(fontDesign("40px", extra, "00:00"));
    const device = db.get("fenix8solar47mm");
    const fonts = bakeFonts(f, device, (p) => readFontFile(p === ICON_FONT ? p : join(REPO_ROOT, p)));
    return [find(resolve(f, device, fonts), "clock").box, fonts.get("clock")];
  };
  const [proportional] = box("");
  const [mono, font] = box("      monospace: true");
  assert.equal(font.measure("00:00")[0], 5 * font.cell_width);
  assert.ok(Math.abs(mono.width - 5 * font.cell_width) <= 1);
  assert.ok(mono.width > proportional.width);
});

test("a graph resolves to a box and a pixel thickness", () => {
  const r = resolved(GRAPH);
  const placed = find(r, "hr_graph");
  assert.ok(placed instanceof PlacedGraph);
  assert.equal(placed.box.width, Math.round(0.6 * r.device.width));
  assert.equal(placed.box.height, Math.round(0.2 * r.device.height));
  assert.equal(placed.thickness, 3);
  assert.ok(placed.bar_width >= 1);
  const large = find(resolved(GRAPH, "fenix8solar51mm"), "hr_graph");
  assert.equal(large.thickness, 3);
  assert.notEqual(large.box.width, placed.box.width);
  assert.equal(find(resolved(GRAPH.replace("    style: line\n    thickness: 3px\n", "    style: bars\n    bar_width: 4px\n")), "hr_graph").bar_width, 4);
});

test("a data element's icon and text, in each position", () => {
  let g = dataPairGeometry("left", 10, 12, 30, 14, 4);
  assert.deepEqual([g.width, g.height, g.iconX, g.textX, g.iconY, g.textY], [44, 14, 0, 14, 1, 0]);
  g = dataPairGeometry("right", 10, 12, 30, 14, 4);
  assert.deepEqual([g.width, g.height, g.textX, g.iconX], [44, 14, 0, 34]);
  g = dataPairGeometry("top", 10, 12, 30, 14, 4);
  assert.deepEqual([g.width, g.height, g.iconY, g.textY, g.iconX, g.textX], [30, 30, 0, 16, 10, 0]);
  g = dataPairGeometry("bottom", 10, 12, 30, 14, 4);
  assert.deepEqual([g.width, g.height, g.textY, g.iconY], [30, 30, 0, 18]);
  for (const position of ["left", "right", "top", "bottom"]) {
    const alone = dataPairGeometry(position, 0, 0, 30, 14, 4);
    assert.equal(position === "left" || position === "right" ? alone.width : alone.height, position === "left" || position === "right" ? 30 : 14, position);
  }
});
