// A slot drawn round the dial: a turned icon (`rotate:`), and its pieces.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { PlacedIcon } from "../src/layout.ts";
import { previewOptions, render } from "../src/preview.ts";
import { MINIMAL, resolved } from "./designs.ts";

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
