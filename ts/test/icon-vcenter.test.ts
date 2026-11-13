// A centred baked icon is drawn top-justified from a build-time cell top,
// its centre less half its font's line height rounded up, and never through
// the watch's TEXT_JUSTIFY_VCENTER, which the simulator drew about 2 px off
// y - lineHeight/2 for a baked font (docs/lore/rendering.md).
import assert from "node:assert/strict";
import { test } from "node:test";
import type { BakedFont } from "../src/fonts/bmfont.ts";
import type { PlacedData, PlacedIcon } from "../src/layout.ts";
import { previewOptions, render } from "../src/preview.ts";
import { generated, method, MINIMAL, resolved, view } from "./designs.ts";

const DEVICES = ["fenix8solar47mm", "fenix8solar51mm"];
const TARGETS = MINIMAL.replace("targets: [fenix8solar47mm]", `targets: [${DEVICES.join(", ")}]`)
  .replace('fg: "#FFFFFF"', 'fg: "#FFFFFF"\n    hot: "#FF0000"\n    ring: "#00FF00"');

/** A centred `heart` icon; 20%r bakes a 38 px line on fenix8solar47mm and a 41 px one on fenix8solar51mm. */
const icon = (extra = "", size = "20%r", name = "heart"): string => `${TARGETS}
  glyph:
    type: icon
    icon: ${name}
    size: ${size}
    at: {anchor: center, dy: 7.6px}
    color: color.hot
${extra}`;

const SLOT = `
config:
  slots:
    pocket:
      default: heart_rate
      choices: [heart_rate, steps]
`;

/** A data element on a slot, its icon beside the reading; 25%r bakes a 40 px line on fenix8solar47mm and a 43 px one on fenix8solar51mm. */
const pair = (position = "left", extra = ""): string => `${TARGETS.replace("elements:", `${SLOT}elements:`)}
  pocket:
    type: data
    slot: pocket
    font: FONT_SMALL
    at: {anchor: center, dy: -40px}
    color: color.fg
    icon: {size: 25%r, position: ${position}, color: color.hot${extra}}
`;

const placed = <T>(text: string, id: string, device: string): T => resolved(text, device).items.find((item) => item.id === id) as T;

/** The [min, max] rows of the pixels `match` picks in a 1x preview, and their [min, max] columns. */
function ink(text: string, device: string, match: (r: number, g: number, b: number) => boolean): { rows: [number, number]; cols: [number, number] } {
  const frame = render(resolved(text, device), previewOptions({ scale: 1 }));
  const rows: number[] = [], cols: number[] = [];
  for (let y = 0; y < frame.height; y++) {
    for (let x = 0; x < frame.width; x++) {
      const i = (y * frame.width + x) * 4;
      if (match(frame.data[i]!, frame.data[i + 1]!, frame.data[i + 2]!)) { rows.push(y); cols.push(x); }
    }
  }
  assert.ok(rows.length > 20, `${device}: ${rows.length} pixels`);
  return { rows: [Math.min(...rows), Math.max(...rows)], cols: [Math.min(...cols), Math.max(...cols)] };
}
const red = (r: number, g: number): boolean => r > 128 && g < 64;
const green = (r: number, g: number): boolean => g > 128 && r < 64;

test("a type: icon's draw call is top-justified at its centre less half its line, per device, odd and even lines alike", () => {
  const text = icon();
  const draw = method(view(text), "drawGlyph");
  assert.match(draw, /dc\.drawText\(Layout\.GLYPH_CX, Layout\.GLYPH_TOP, font,\s+"[^"]+",\s+Graphics\.TEXT_JUSTIFY_CENTER\);/);
  assert.doesNotMatch(draw, /VCENTER/);
  const files = generated(text);
  const lines = DEVICES.map((id) => {
    const p = placed<PlacedIcon>(text, "glyph", id);
    const line = resolved(text, id).fonts.get(p.font_key)!.line_height;
    assert.equal(p.line_height, line, id);
    assert.match(files.get(`source-${id}/Layout.mc`)!, new RegExp(`const GLYPH_TOP as Number = ${p.center[1] - Math.ceil(line / 2)};`), id);
    assert.doesNotMatch(files.get(`source-${id}/Layout.mc`)!, /GLYPH_CY/, id);
    // The lint box is the cell the watch draws.
    assert.equal(p.box.y, p.center[1] - Math.ceil(line / 2), id);
    assert.equal(p.box.height, line, id);
    return line;
  });
  assert.deepEqual(lines.map((n) => n % 2), [0, 1], `the two devices' lines (${lines}) cover an even and an odd one`);
});

test("a data element's icon beside the reading is top-justified from its _ICON_HALF, per device", () => {
  for (const [position, extra] of [["left", ""], ["right", ", gap: 3px"]]) {
    const text = pair(position, extra);
    const draw = method(view(text), "drawPocket");
    assert.match(draw, /dc\.drawText\([^,]+, Layout\.POCKET_CY - Layout\.POCKET_ICON_HALF, iconFont, iconGlyph,\s+Graphics\.TEXT_JUSTIFY_LEFT\);/, position);
    // The reading, in a system font, keeps VCENTER.
    assert.match(draw, /textFont|Graphics\.FONT_SMALL, text,\s+Graphics\.TEXT_JUSTIFY_LEFT \| Graphics\.TEXT_JUSTIFY_VCENTER\);/, position);
    const files = generated(text);
    const lines = DEVICES.map((id) => {
      const p = placed<PlacedData>(text, "pocket", id);
      const line = resolved(text, id).fonts.get(p.icon_font_key!)!.line_height;
      assert.equal(p.icon_line_height, line, id);
      assert.match(files.get(`source-${id}/Layout.mc`)!, new RegExp(`const POCKET_ICON_HALF as Number = ${Math.ceil(line / 2)};`), id);
      return line;
    });
    assert.notEqual(lines[0]! % 2, lines[1]! % 2, `lines ${lines}: one odd, one even`);
  }
});

test("an icon stacked over the reading keeps its top-justified draw and needs no _ICON_HALF", () => {
  const text = pair("top");
  assert.doesNotMatch(method(view(text), "drawPocket"), /VCENTER|ICON_HALF/);
  assert.doesNotMatch(generated(text).get("source-fenix8solar47mm/Layout.mc")!, /ICON_HALF/);
});

/**
 * The preview's ink against the cell the watch is told to draw: the cell top
 * is the anchor less half the line rounded up, so the cell's middle is within
 * half a pixel of the anchor's edge `y`, and the ink is exactly some glyph of
 * the font pasted at that top (its `yoffset` through `yoffset + height - 1`).
 * What remains between ink and anchor is the glyph's own place in its cell.
 */
function assertCentredCell(font: BakedFont, anchor: number, rows: [number, number], label: string): void {
  const top = anchor - Math.ceil(font.line_height / 2);
  assert.ok(Math.abs(top + font.line_height / 2 - anchor) <= 0.5, `${label}: cell ${top}+${font.line_height} about ${anchor}`);
  const fits = [...font.glyphs.values()].some((g) => g.height > 0 && top + g.yoffset === rows[0] && top + g.yoffset + g.height - 1 === rows[1]);
  assert.ok(fits, `${label}: ink rows ${rows} are no glyph of the font pasted at cell top ${top} (line ${font.line_height})`);
}

test("the preview pastes a type: icon's cell centred on its anchor, for an odd and an even line", () => {
  for (const id of DEVICES) {
    const text = icon();
    const p = placed<PlacedIcon>(text, "glyph", id);
    assertCentredCell(resolved(text, id).fonts.get(p.font_key)!, p.center[1], ink(text, id, red).rows, `${id} (line ${p.line_height})`);
  }
});

test("the preview pastes a data element's icon cell centred on the reading's row, for an odd and an even line", () => {
  for (const id of DEVICES) {
    const text = pair();
    const p = placed<PlacedData>(text, "pocket", id);
    assertCentredCell(resolved(text, id).fonts.get(p.icon_font_key!)!, p.anchor_point[1], ink(text, id, red).rows, `${id} (line ${p.icon_line_height})`);
  }
});

test("an outlined icon's ring font is drawn from the same cell top as its glyph, and rings it evenly", () => {
  const text = icon("    outline: {color: color.ring}\n");
  const draw = method(view(text), "drawGlyph");
  const tops = draw.match(/dc\.drawText\(Layout\.GLYPH_CX, Layout\.GLYPH_TOP, (\w+),/g) ?? [];
  assert.equal(tops.length, 2, draw);
  assert.match(draw, /ringFont/);
  assert.doesNotMatch(draw, /VCENTER/);
  for (const id of DEVICES) {
    const glyph = ink(text, id, red), ring = ink(text, id, green);
    // A 1 px ring grows the glyph's ink by one pixel on every side.
    assert.deepEqual([ring.rows, ring.cols], [[glyph.rows[0] - 1, glyph.rows[1] + 1], [glyph.cols[0] - 1, glyph.cols[1] + 1]], id);
  }
});

test("a turned icon is top-justified from its own turned font's half line, its ink still centred", () => {
  const text = icon("    rotate: 45deg\n", "20%r", "battery");
  assert.match(method(view(text), "drawGlyph"), /dc\.drawText\(Layout\.GLYPH_CX, Layout\.GLYPH_TOP, font,\s+"[^"]+",\s+Graphics\.TEXT_JUSTIFY_CENTER\);/);
  for (const id of DEVICES) {
    const p = placed<PlacedIcon>(text, "glyph", id);
    // The turned font's own line height (a cell grown to hold turned ink included), not the upright font's.
    const font = resolved(text, id).fonts.get(p.font_key)!;
    assert.equal(font.rotate, 45, id);
    const line = font.line_height;
    assert.equal(p.line_height, line, id);
    assert.match(generated(text).get(`source-${id}/Layout.mc`)!, new RegExp(`const GLYPH_TOP as Number = ${p.center[1] - Math.ceil(line / 2)};`), id);
    const { rows } = ink(text, id, red);
    const middle = (rows[0] + rows[1] + 1) / 2;
    assertCentredCell(font, p.center[1], rows, `${id}: turned, middle ${middle}`);
  }
});

test("an icon aligned to its top or bottom keeps CY and its own justification", () => {
  const top = method(view(icon("    align: top\n")), "drawGlyph");
  assert.match(top, /dc\.drawText\(Layout\.GLYPH_CX, Layout\.GLYPH_CY, font,\s+"[^"]+",\s+Graphics\.TEXT_JUSTIFY_CENTER\);/);
  const bottom = method(view(icon("    align: bottom\n")), "drawGlyph");
  assert.match(bottom, /Layout\.GLYPH_CY - dc\.getFontHeight\(font\)/);
});
