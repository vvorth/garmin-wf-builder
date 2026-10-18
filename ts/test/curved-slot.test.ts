// A slot drawn round the dial: a turned icon (`rotate:`), and its pieces.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { PlacedIcon } from "../src/layout.ts";
import { previewOptions, render } from "../src/preview.ts";
import { checked, errors, generated, method, MINIMAL, resolved, view } from "./designs.ts";

const icon = (extra: string): string => `${MINIMAL}
  glyph:
    type: icon
    icon: steps
    size: 20%r
    at: {anchor: center}
    color: color.fg
${extra}`;

const placedIcon = (text: string): PlacedIcon => resolved(text).items.find((p) => p.id === "glyph") as PlacedIcon;

test("rotate: bakes a font of its own, and a whole turn is upright", () => {
  const upright = placedIcon(icon("")).font_key;
  assert.equal(placedIcon(icon("    rotate: 0deg")).font_key, upright);
  assert.equal(placedIcon(icon("    rotate: 360deg")).font_key, upright);
  assert.equal(placedIcon(icon("    rotate: -270deg")).font_key, placedIcon(icon("    rotate: 90deg")).font_key);
  assert.notEqual(placedIcon(icon("    rotate: 90deg")).font_key, upright);
});

test("a turned icon's lint box covers ink that leaves its cell", () => {
  // The battery glyph is tall and narrow: turned a quarter, its ink is wider than its advance.
  const battery = (extra: string): string => icon(extra).replace("icon: steps", "icon: battery");
  const upright = placedIcon(battery("")).box, turned = placedIcon(battery("    rotate: 90deg")).box;
  assert.ok(upright.height > upright.width, `upright ${upright.width}x${upright.height}`);
  assert.ok(turned.width >= upright.height - 6, `turned ${turned.width}x${turned.height}`);
});

test("the preview pastes a turned glyph where drawText puts it, not at its grown box", () => {
  // A quarter-turned battery's ink leaves its cell, so its box starts left of the cell.
  const text = icon("    rotate: 90deg").replace("icon: steps", "icon: battery");
  const r = resolved(text);
  const p = r.items.find((item) => item.id === "glyph") as PlacedIcon;
  const font = r.fonts.get(p.font_key)!, g = font.glyphs.get(p.codepoint)!;
  const [cx, cy] = p.anchor_point;
  const [advance] = font.measure(p.codepoint);
  // drawText centred on the anchor: the cell's top-left, then the glyph's own offsets.
  const left = Math.round(cx - advance / 2) + g.xoffset, top = Math.round(cy - font.line_height / 2) + g.yoffset;
  const frame = render(r, previewOptions({ scale: 1 }));
  let x0 = frame.width, y0 = frame.height, x1 = -1, y1 = -1;
  for (let y = 0; y < frame.height; y++) {
    for (let x = 0; x < frame.width; x++) {
      if (frame.data[(y * frame.width + x) * 4]! > 128) [x0, y0, x1, y1] = [Math.min(x0, x), Math.min(y0, y), Math.max(x1, x), Math.max(y1, y)];
    }
  }
  assert.ok(p.box.x < p.cell!.x, "the box grew past the cell");
  assert.ok(Math.abs(x0 - left) <= 1 && Math.abs(y0 - top) <= 1, `ink at ${x0},${y0}; drawText puts it at ${left},${top}`);
});

const SLOT = `
config:
  slots:
    left:
      default: steps
      choices: [steps, stress, current_weather, { type: heart_rate, icon: { codepoint: "U+F04CE" } }]
`;

const slotIcon = (extra: string): string => `${MINIMAL.replace("elements:", `${SLOT}elements:`)}
  glyph:
    type: icon
    slot: left
    size: 20%r
    at: {anchor: center}
    color: color.fg
${extra}`;

/** The lit pixels of one preview frame, showing slot `left` as `pick`. */
function lit(text: string, pick: string): string {
  const frame = render(resolved(text), previewOptions({ scale: 1, picks: [["left", pick]] }));
  return Array.from({ length: frame.width * frame.height }, (_, i) => (frame.data[i * 4]! > 128 ? "1" : "0")).join("");
}

test("an icon with slot: draws the icon of whatever the wearer picked", () => {
  const steps = lit(slotIcon(""), "steps"), stress = lit(slotIcon(""), "stress");
  assert.ok(steps.includes("1") && stress.includes("1"), "both picks draw");
  assert.notEqual(steps, stress);
  const v = view(slotIcon(""));
  assert.match(method(v, "iconForGlyph"), /COMPLICATION_TYPE_HEART_RATE: return "U\+F04CE";/);
  assert.match(method(v, "drawGlyph"), /var iconName = iconForGlyph\(chosenId.getType\(\), pulled\);/);
});

test("an icon with slot: is drawn by the editor's slot drawable, and turns", () => {
  const v = view(slotIcon("    rotate: 30deg"));
  assert.match(method(v, "drawSlotLeft"), /drawGlyph\(dc\);/);
  assert.match(method(v, "drawGlyph"), /_fontIcon20pctrSlotLeftR30/);
});

test("a slot icon and a data element's icon of one size share one font", () => {
  const text = `${slotIcon("")}
  value:
    type: data
    slot: left
    at: {anchor: center, dy: 30%r}
    icon: {size: 20%r}
    color: color.fg
`;
  const keys = new Set(resolved(text).items.flatMap((p) => {
    const q = p as unknown as { font_key?: string; icon_font_key?: string | null };
    return [q.font_key, q.icon_font_key].filter((k): k is string => typeof k === "string");
  }));
  assert.deepEqual([...keys], ["icon_20pctr_slot_left"]);
});

test("on_hold: auto on a slot icon opens the pick's glance; a fixed target is refused", () => {
  const files = generated(slotIcon("    on_hold: auto"));
  const delegate = [...files].find(([name]) => name.endsWith("Delegate.mc"))![1];
  assert.match(delegate, /Complications\.exitTo\(_view\.holdTargetForGlyph\(\)\);/);
  assert.match(view(slotIcon("    on_hold: auto")), /function holdTargetForGlyph\(\) as Complications\.Id \{\s+return _configDataLeft;/);
  const refused = errors(slotIcon("    on_hold: heart_rate"));
  assert.ok(refused.some((d) => d.code === "on-hold" && /only accepts 'auto'/.test(d.message)), refused.map((d) => d.message).join("\n"));
});

test("an icon takes icon: or slot:, not both, and slot: must be declared", () => {
  const both = errors(slotIcon("    icon: steps"));
  assert.ok(both.some((d) => /'icon:' and 'slot:' both choose the glyph/.test(d.message)), both.map((d) => d.message).join("\n"));
  const unknown = errors(slotIcon("").replace("slot: left\n    size", "slot: right\n    size"));
  assert.ok(unknown.some((d) => /unknown slot 'right'/.test(d.message)), unknown.map((d) => d.message).join("\n"));
  const neither = errors(slotIcon("").replace("    slot: left\n", ""));
  assert.ok(neither.some((d) => /needs one of 'icon' or 'slot'/.test(d.message)), neither.map((d) => d.message).join("\n"));
});

const FACE_FONT = `
  fonts:
    reading: { face: [BionicSemiBold, RobotoCondensedBold], size: 11%r }
`;

/** A data element on slot `left`, with a `face:` font declared beside the palette. */
const curvedData = (extra: string, targets = "[fenix8solar47mm]"): string => `${MINIMAL
  .replace("targets: [fenix8solar47mm]", `targets: ${targets}`)
  .replace("resources:\n", `resources:${FACE_FONT}`)
  .replace("elements:", `${SLOT}elements:`)}
  value:
    type: data
    slot: left
    font: font.reading
    at: {anchor: center}
    color: color.fg
${extra}`;

const RADIAL = "    curve: {style: radial, angle: -46deg, radius: 80%r}\n    align: left\n";

test("a curved reading draws through drawRadialText or drawAngledText, in a face: font", () => {
  const radial = method(view(curvedData(RADIAL)), "drawValue");
  assert.match(radial, /var textFont = _fontReading;\s+if \(textFont != null\) \{/);
  assert.match(radial, /dc\.drawRadialText\(Layout\.VALUE_CX, Layout\.VALUE_CY, textFont, text,\s+Graphics\.TEXT_JUSTIFY_LEFT \| Graphics\.TEXT_JUSTIFY_VCENTER, Layout\.VALUE_ANGLE, Layout\.VALUE_RADIUS,\s+Graphics\.RADIAL_TEXT_DIRECTION_CLOCKWISE\);/);
  const angled = method(view(curvedData("    curve: {style: angled, angle: 30deg}\n")), "drawValue");
  assert.match(angled, /dc\.drawAngledText\(Layout\.VALUE_CX, Layout\.VALUE_CY, textFont, text,/);
});

test("a radial reading's box is its sector at the rim, not a box round the centre", () => {
  const r = resolved(curvedData(RADIAL));
  const p = r.items.find((item) => item.id === "value")!;
  const [cx, cy] = [r.device.width / 2, r.device.height / 2];
  assert.ok(p.box.right < cx && p.box.bottom < cy, `box ${JSON.stringify(p.box)} sits in the upper left quarter`);
});

test("an upright reading takes a face: font too", () => {
  assert.deepEqual(errors(curvedData("")).map((d) => d.message), []);
  assert.match(method(view(curvedData("")), "drawValue"), /if \(textFont != null\) \{/);
});

test("curve: needs a face: font, and takes no icon:", () => {
  const baked = errors(curvedData(RADIAL).replace("font: font.reading", "font: FONT_SMALL"));
  assert.ok(baked.some((d) => /only support scalable fonts/.test(d.message + d.notes.join(" "))), baked.map((d) => d.message).join("\n"));
  const icon = errors(curvedData(`${RADIAL}    icon: {size: 10%r}\n`));
  assert.ok(icon.some((d) => /a curved reading takes no 'icon:' here/.test(d.message)), icon.map((d) => d.message).join("\n"));
});

test("a device with no vector fonts is a build error, or with unsupported: hide, leaves the reading out", () => {
  const both = "[fenix8solar47mm, fenix6]";
  const refused = checked(curvedData(RADIAL, both)).filter((d) => d.severity === "error");
  assert.ok(refused.some((d) => d.code === "font-unavailable" && /fenix6/.test(d.message)), refused.map((d) => d.message).join("\n"));
  const hidden = checked(curvedData(`${RADIAL}    unsupported: hide\n`, both)).filter((d) => d.severity === "error");
  assert.deepEqual(hidden.map((d) => d.message), []);
  const baked = errors(curvedData("    unsupported: hide\n").replace("font: font.reading", "font: FONT_SMALL"));
  assert.ok(baked.some((d) => /'unsupported:' is not accepted here/.test(d.message)), baked.map((d) => d.message).join("\n"));
});

