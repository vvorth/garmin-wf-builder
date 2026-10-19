// A curved (radial) reading is held, and outlined in the editor, by the arc
// of the reading it draws, not by the box round every reading its slot
// could show: on the watch the delegate turns the width the view drew into
// that arc (`WfbHold.inArc`), and the editor's frame measures the reading
// it shows. Both are held here to the pixels the preview draws.
import assert from "node:assert/strict";
import { test } from "node:test";
import { drawnReading, drawnRunBox } from "../src/draw/index.ts";
import { layers } from "../src/draw/layers.ts";
import { radialRunArc } from "../src/kinds/data.ts";
import { PlacedData } from "../src/layout.ts";
import { previewOptions, resolveStyleEntry, sampleValues } from "../src/preview.ts";
import { generated, MINIMAL, resolved } from "./designs.ts";

const DESIGN = MINIMAL.replace("resources:", `config:
  slots:
    bezel: { default: steps, choices: any }
    low: { default: body_battery, choices: [body_battery, heart_rate] }
resources:
  fonts:
    reading: { face: [BionicSemiBold, RobotoCondensedBold], size: 14%r }`) + `
  steps_value:
    type: data
    slot: bezel
    font: font.reading
    at: { anchor: center }
    curve: { style: radial, angle: -46deg, radius: 80%r }
    align: left
    icon: { size: 10%r, position: left, color: color.fg }
    color: color.fg
    absent: { text: "--" }
    on_hold: auto
  low_value:
    type: data
    slot: low
    font: font.reading
    at: { anchor: center }
    curve: { style: radial, angle: 180deg, radius: 80%r, direction: counter_clockwise }
    align: center
    color: color.fg
    absent: hide
    on_hold: auto
  plain_value:
    type: data
    slot: low
    font: FONT_SMALL
    at: { anchor: center, dy: 20% }
    color: color.fg
    on_hold: auto
`;

const DEVICE = "fenix8solar47mm";

/** Whether `(x, y)` is in `arc` about `(cx, cy)`: `WfbHold.inArc`, transcribed. */
function inArc(x: number, y: number, cx: number, cy: number, r0sq: number, r1sq: number, from: number, sweep: number): boolean {
  const dx = x - cx, dy = cy - y, d2 = dx * dx + dy * dy;
  if (d2 < r0sq || d2 > r1sq) return false;
  const size = Math.abs(sweep);
  if (size >= 360) return true;
  const angle = Math.atan2(dy, dx) * 180 / Math.PI;
  let turn = sweep < 0 ? from - angle : angle - from;
  while (turn < 0) turn += 360;
  while (turn >= 360) turn -= 360;
  return turn <= size;
}

test("the editor outlines a curved reading round the reading it draws, well inside its every-pick box", () => {
  const r = resolved(DESIGN, DEVICE);
  const options = previewOptions();
  const values = sampleValues(r, options, resolveStyleEntry(r.face, options.style));
  const steps = r.items.find((p) => p.id === "steps_value") as PlacedData;
  const drawn = drawnRunBox(r, steps, values)!;
  // the box round every pick reaches across the top for the longest weather condition; the drawn one stays at the upper left
  assert.ok(steps.box.width > 150, `the every-pick box is ${steps.box.width}px wide`);
  assert.ok(drawn.width < steps.box.width / 2 && drawn.x + drawn.width < r.device.width / 2, JSON.stringify(drawn));
  // a pick changes what is drawn, and so the outline: a weather condition runs on round the dial
  const weather = drawnRunBox(r, steps, values, [["bezel", "current_weather"]])!;
  assert.ok(weather.width > drawn.width + 20, `${JSON.stringify(weather)} beside ${JSON.stringify(drawn)}`);
  // anything else keeps its box
  assert.equal(drawnRunBox(r, r.items.find((p) => p.id === "plain_value")!, values), null);
});

test("every pixel a curved reading draws, its icon included, lies on its arc, and the arc is not much more", () => {
  const r = resolved(DESIGN, DEVICE);
  const options = previewOptions();
  const values = sampleValues(r, options, resolveStyleEntry(r.face, options.style));
  const stack = layers(r, options);
  for (const id of ["steps_value", "low_value"]) {
    const p = r.items.find((q) => q.id === id) as PlacedData;
    const image = stack.find((l) => l.id === id)!.image!;
    const box = drawnRunBox(r, p, values)!;
    const [cx, cy] = p.anchor_point;
    let ink = 0, outside = 0, x0 = Infinity, y0 = Infinity, x1 = -1, y1 = -1;
    for (let y = 0; y < image.height; y++) {
      for (let x = 0; x < image.width; x++) {
        if (image.data[(y * image.width + x) * 4 + 3]! === 0) continue;
        ink++;
        [x0, y0, x1, y1] = [Math.min(x0, x), Math.min(y0, y), Math.max(x1, x), Math.max(y1, y)];
        // a pixel's centre, a pixel of slack for anti-aliased edges
        if (x < box.x - 1 || x > box.x + box.width + 1 || y < box.y - 1 || y > box.y + box.height + 1) outside++;
      }
    }
    assert.ok(ink > 50, `${id} drew ${ink} pixels`);
    assert.equal(outside, 0, `${id}: ${outside} of ${ink} drawn pixels fall outside its outline ${JSON.stringify(box)}`);
    // and the outline is the ink's own bounds give or take a line's band, not a box round other readings
    assert.ok(box.width <= x1 - x0 + 1 + 12 && box.height <= y1 - y0 + 1 + 14,
      `${id}: outline ${JSON.stringify(box)} round ink ${JSON.stringify([x0, y0, x1 - x0 + 1, y1 - y0 + 1])}`);
    // the held arc holds every drawn pixel too, give or take a pixel of anti-aliased edge
    const width = r.device.db.measure.measure(drawnReading(r, p, values)!, p.font.metric!)[0];
    const arc = radialRunArc(p, width, 1);
    let missed = 0;
    for (let y = 0; y < image.height; y++) {
      for (let x = 0; x < image.width; x++) {
        if (image.data[(y * image.width + x) * 4 + 3]! === 0) continue;
        if (!inArc(x, y, cx, cy, Math.floor(arc.inner) ** 2, Math.ceil(arc.outer) ** 2, arc.from, arc.sweep)) missed++;
      }
    }
    assert.equal(missed, 0, `${id}: ${missed} drawn pixels miss the arc`);
  }
});

test("the watch tests a held curved reading against the arc of what the view drew; a straight one keeps its box", () => {
  const files = generated(DESIGN, [DEVICE, "fr955"]);
  const file = (suffix: string): string => [...files].find(([name]) => name.endsWith(suffix))![1];
  const view = file("View.mc"), delegate = file("Delegate.mc"), layout = file(`source-${DEVICE}/Layout.mc`);
  // the view records the width it drew, every frame, where the delegate can read it
  assert.match(view, /^ {4}var holdSpanStepsValue as Number = 0;$/m);
  assert.match(view, /holdSpanStepsValue = dc\.getTextWidthInPixels\(text, \w+\);/);
  assert.doesNotMatch(view, /holdSpanPlainValue/);
  // per device: the band squared, the run's scale and what lies before and after the reading
  for (const name of ["R0SQ", "R1SQ", "PER_PX", "BEFORE", "AFTER"]) assert.match(layout, new RegExp(`const STEPS_VALUE_HOLD_${name} `));
  assert.doesNotMatch(layout, /STEPS_VALUE_HOLD_X/);
  assert.match(layout, /const PLAIN_VALUE_HOLD_X /);
  assert.match(delegate, /if \(WfbHold\.inArc\(x, y, Layout\.STEPS_VALUE_CX, Layout\.STEPS_VALUE_CY,/);
  assert.match(delegate, /Layout\.PLAIN_VALUE_HOLD_X/);
  assert.ok(files.has("runtime-lib/WfbHold.mc") || [...files.keys()].some((k) => k.endsWith("WfbHold.mc")), "the barrel carries WfbHold");

  // the delegate's own arithmetic, on this device's constants, is the host's arc
  const r = resolved(DESIGN, DEVICE);
  const constant = (name: string): number => Number(layout.match(new RegExp(`const ${name} as \\w+ = (-?[0-9.]+)f?;`))![1]);
  for (const id of ["steps_value", "low_value"]) {
    const p = r.items.find((q) => q.id === id) as PlacedData;
    const prefix = id.toUpperCase();
    const call = delegate.split(`// \`${id}\``)[1]!.split("{")[0]!;
    const [, fromCode, sweepCode] = call.match(/R1SQ,\n\s*(.+),\n\s*(.+)\)\)/)!;
    for (const width of [0, 24, 61, 140]) {
      const code = (text: string): number => Function(`return ${text
        .replace(/_view\.holdSpan\w+/g, String(width))
        .replace(/Layout\.(\w+)/g, (_, name: string) => String(constant(name)))};`)() as number;
      const host = radialRunArc(p, width);
      assert.ok(Math.abs(code(fromCode!) - host.from) < 1e-3, `${id} at ${width}px: from ${code(fromCode!)} vs ${host.from}`);
      assert.ok(Math.abs(code(sweepCode!) - host.sweep) < 1e-3, `${id} at ${width}px: sweep ${code(sweepCode!)} vs ${host.sweep}`);
      assert.equal(constant(`${prefix}_HOLD_R0SQ`), Math.floor(host.inner) ** 2);
      assert.equal(constant(`${prefix}_HOLD_R1SQ`), Math.ceil(host.outer) ** 2);
    }
  }
});
