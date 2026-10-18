// A slot drawn round the dial: a turned icon (`rotate:`), and its pieces.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { PlacedIcon } from "../src/layout.ts";
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
