// A slot drawn round the dial: a turned icon (`rotate:`), and its pieces.
import assert from "node:assert/strict";
import { test } from "node:test";
import { Tiles, toJson } from "../src/draw/jsonform.ts";
import { stepKey } from "../src/icons.ts";
import { type PlacedData, type PlacedIcon, type PlacedText, radialSpacingRadius } from "../src/layout.ts";
import { frameItems, newRenderer, previewOptions, render, sampleValues } from "../src/preview.ts";
import { checked, divergences, errors, generated, method, MINIMAL, resolved, view } from "./designs.ts";

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

test("the preview pastes a turned glyph where drawText puts it", () => {
  // A quarter-turned battery: a tall glyph whose turned ink is wider than its upright advance.
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
  // The weather choice's condition text is the widest reading: its sector runs past 12 o'clock, but stays at the rim.
  assert.ok(p.box.x < cx && p.box.bottom < cy - 60, `box ${JSON.stringify(p.box)} sits along the upper rim`);
});

test("an upright reading takes a face: font too", () => {
  assert.deepEqual(errors(curvedData("")).map((d) => d.message), []);
  assert.match(method(view(curvedData("")), "drawValue"), /if \(textFont != null\) \{/);
});

test("curve: needs a face: font", () => {
  const baked = errors(curvedData(RADIAL).replace("font: font.reading", "font: FONT_SMALL"));
  assert.ok(baked.some((d) => /only support scalable fonts/.test(d.message + d.notes.join(" "))), baked.map((d) => d.message).join("\n"));
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

/** A group holding slot `left`'s icon, plus `more` inside it; `on_hold: auto` on the group. */
const slotGroup = (more = ""): string => `${MINIMAL.replace("elements:", `${SLOT.replace("config:\n  slots:\n", "config:\n  slots:\n    right: {default: stress, choices: [stress, steps]}\n")}elements:`)}
  slot_group:
    type: group
    size: {width: 50%, height: 50%}
    at: {anchor: center}
    on_hold: auto
    children:
      glyph:
        type: icon
        slot: left
        size: 20%r
        at: {anchor: center}
        color: color.fg
${more}`;

test("on_hold: auto on a group follows the one slot drawn inside it", () => {
  const files = generated(slotGroup());
  const delegate = [...files].find(([name]) => name.endsWith("Delegate.mc"))![1];
  assert.match(delegate, /`slot_group` -> whatever the wearer picked for slot left/);
  assert.match(delegate, /Complications\.exitTo\(_view\.holdTargetForSlotGroup\(\)\);/);
  assert.match(view(slotGroup()), /function holdTargetForSlotGroup\(\) as Complications\.Id \{\s+return _configDataLeft;/);
});

test("a fixed-source member does not count; a second slot is ambiguous", () => {
  const clock = `      clock:\n        type: text\n        text: "{time.hour}"\n        font: FONT_SMALL\n        at: {anchor: center, dy: 20%}\n        color: color.fg\n`;
  assert.deepEqual(errors(slotGroup(clock)).map((d) => d.message), []);
  assert.match(view(slotGroup(clock)), /function holdTargetForSlotGroup\(\)/);
  const other = `      other:\n        type: icon\n        slot: right\n        size: 10%r\n        at: {anchor: center, dy: 30%}\n        color: color.fg\n`;
  const twice = errors(slotGroup(other));
  assert.ok(twice.some((d) => d.code === "hold-auto-ambiguous" && /'left', 'right'/.test(d.message)), twice.map((d) => d.message).join("\n"));
});

test("a group with no slot keeps today's auto: resolved from bound sources, or refused", () => {
  const plain = `${MINIMAL}
  plain:
    type: group
    size: {width: 50%, height: 50%}
    at: {anchor: center}
    on_hold: auto
    children:
      clock:
        type: text
        text: "{time.hour}"
        font: FONT_SMALL
        at: {anchor: center}
        color: color.fg
`;
  assert.ok(errors(plain).some((d) => d.code === "hold-auto-unresolved"), errors(plain).map((d) => d.message).join("\n"));
});

const PAIR = "    icon: {size: 10%r, position: left, color: color.hot}\n";
/** A curved data element with an icon, the icon in its own colour. */
const curvedPair = (extra: string, targets?: string): string =>
  curvedData(extra, targets).replace('fg: "#FFFFFF"', 'fg: "#FFFFFF"\n    hot: "#FF0000"');

/** A radial pair with this `align:` and `icon: {position:}`, and anything more on the icon. */
const radialPair = (align: string, position: string, extra = "", curve = RADIAL, targets?: string): string =>
  curvedPair(`${curve.replace("align: left", `align: ${align}`)}${PAIR.replace("position: left", `position: ${position}`).replace("}\n", `${extra}}\n`)}`, targets);

test("a radial reading takes its icon before or after the run, with any align", () => {
  for (const align of ["left", "center", "right"]) {
    for (const position of ["left", "right"]) assert.deepEqual(errors(radialPair(align, position)).map((d) => d.message), [], `${align}/${position}`);
    for (const position of ["top", "bottom"]) {
      const refused = errors(radialPair(align, position));
      assert.ok(refused.some((d) => /a radial reading takes its icon before or after the run: 'icon: \{position: left\}' or 'icon: \{position: right\}', with any 'align:'/.test(d.message)),
        `${align}/${position}: ${refused.map((d) => d.message).join("\n")}`);
    }
  }
});

test("an angled reading takes its icon on any side", () => {
  for (const position of ["left", "right", "top", "bottom"]) {
    const text = curvedPair(`    curve: {style: angled, angle: 20deg}\n${PAIR.replace("position: left", `position: ${position}`)}`);
    assert.deepEqual(errors(text).map((d) => d.message), [], position);
  }
});

test("beside an icon, a radial radius must be px or %r", () => {
  const refused = errors(curvedPair(`${RADIAL.replace("radius: 80%r", "radius: 40%")}${PAIR}`));
  assert.ok(refused.some((d) => /beside an icon, 'curve: \{radius:\}' must be px or %r, not %/.test(d.message)), refused.map((d) => d.message).join("\n"));
  assert.deepEqual(errors(curvedPair(RADIAL.replace("radius: 80%r", "radius: 40%"))).map((d) => d.message), []);
});

test("icon: {upright:} applies only beside curve:", () => {
  const upright = PAIR.replace("color: color.hot", "upright: true");
  assert.deepEqual(errors(curvedPair(`${RADIAL}${upright}`)).map((d) => d.message), []);
  const refused = errors(curvedPair(upright));
  assert.ok(refused.some((d) => /'icon: \{upright:\}' applies only beside 'curve:'/.test(d.message)), refused.map((d) => d.message).join("\n"));
});

test("an angled pair is the upright pair turned about the anchor", () => {
  const text = curvedPair(`    curve: {style: angled, angle: 20deg}\n${PAIR}`);
  const draw = method(view(text), "drawValue");
  assert.match(draw, /dc\.drawAngledText\(\(Layout\.VALUE_CX \+ \(startX \+ iconGlyphWidth \+ gap - Layout\.VALUE_CX\) \* Layout\.VALUE_COS \+ 0\.5\)\.toNumber\(\),/);
  assert.match(draw, /dc\.drawText\(\(Layout\.VALUE_CX \+ \(startX \+ dc\.getTextWidthInPixels\(iconGlyph, iconFont\) \/ 2 - Layout\.VALUE_CX\) \* Layout\.VALUE_COS/);
  assert.match(draw, /_fontIcon10pctrSlotLeftR20/);
  const layout = [...generated(text)].find(([name]) => name.endsWith("Layout.mc"))![1];
  assert.match(layout, /const VALUE_COS as Float = 0\.939\d*f;/);
  assert.match(layout, /const VALUE_SIN as Float = 0\.342\d*f;/);
});

test("a pinned radial icon's font is baked at the turn the layout placed it at, per device, under one name", () => {
  const devices = ["fenix8solar47mm", "fenix8solar51mm"];
  const text = curvedPair(`${RADIAL}${PAIR}`, `[${devices.join(", ")}]`);
  const turns = devices.map((id) => {
    const r = resolved(text, id);
    const p = r.items.find((item) => item.id === "value") as PlacedData;
    assert.equal(p.icon_font_key, "icon_10pctr_slot_left_pinned_value");
    assert.equal(r.fonts.get(p.icon_font_key!)!.rotate, p.icon_turn, id);
    return p.icon_turn;
  });
  assert.notEqual(turns[0], turns[1], "the radius and the glyph's advance differ per device, so the turn does");
  const files = generated(text);
  for (const id of devices) assert.match(files.get(`resources-${id}/fonts/fonts.xml`)!, /id="FontIcon10pctrSlotLeftPinnedValue"/);
  assert.match(method(view(text), "drawValue"), /dc\.drawText\(Layout\.VALUE_ICON_X, Layout\.VALUE_ICON_Y, iconFont, iconGlyph,/);
});

/** The red (icon) pixels of one 1x preview frame. */
function iconInk(text: string): [number, number][] {
  const frame = render(resolved(text), previewOptions({ scale: 1 }));
  const out: [number, number][] = [];
  for (let y = 0; y < frame.height; y++) {
    for (let x = 0; x < frame.width; x++) {
      const i = (y * frame.width + x) * 4;
      if (frame.data[i]! > 128 && frame.data[i + 1]! < 64) out.push([x, y]);
    }
  }
  return out;
}

test("the preview draws a pinned icon before the run's start, turned to face out", () => {
  // At 9 o'clock a clockwise run climbs; its icon sits just below the start, its top pointing out (left).
  const text = curvedPair(`${RADIAL.replace("-46deg", "-90deg")}${PAIR}`).replace("default: steps", "default: battery")
    .replace("choices: [steps,", "choices: [battery, steps,");
  const p = resolved(text).items.find((item) => item.id === "value") as PlacedData;
  const ink = iconInk(text);
  assert.ok(ink.length > 20, `${ink.length} icon pixels`);
  const mx = ink.reduce((s, [x]) => s + x, 0) / ink.length, my = ink.reduce((s, [, y]) => s + y, 0) / ink.length;
  assert.ok(Math.abs(mx - p.icon_point![0]) <= 2 && Math.abs(my - p.icon_point![1]) <= 2, `ink at ${mx},${my}; placed at ${p.icon_point}`);
  const [cx, cy] = p.anchor_point;
  assert.ok(mx < cx - 80 && my > cy + 2, `left of the centre and below the run's start at 9 o'clock: ${mx},${my}`);
  // The battery's terminal is its top: turned to face out, it is the thin end on the left.
  const xs = ink.map(([x]) => x), left = Math.min(...xs), right = Math.max(...xs);
  const column = (x: number): number => ink.filter(([ix]) => ix === x).length;
  assert.ok(column(left) < column(right), `the terminal's column (${column(left)}) is thinner than the base's (${column(right)})`);
  assert.ok(p.box.x <= p.icon_point![0] && p.box.bottom >= p.icon_point![1], "the lint box covers the icon");
});

const placedValue = (text: string, id = "fenix8solar47mm"): PlacedData => resolved(text, id).items.find((item) => item.id === "value") as PlacedData;

test("a free-end or centred icon's angle is computed on the watch from the measured width", () => {
  const draw = method(view(radialPair("left", "right")), "drawValue");
  assert.match(draw, /var textWidth = dc\.getTextWidthInPixels\(text, textFont\);\s+var iconTheta = Layout\.VALUE_ICON_THETA \+ Layout\.VALUE_ICON_PER_PX \* textWidth;/);
  assert.match(draw, /var iconStep = \(textWidth \* Layout\.VALUE_ICON_STEP_PER_PX \+ 0\.5\)\.toNumber\(\);/);
  assert.match(draw, /_fontIcon10pctrSlotLeftStepsValue = WatchUi\.loadResource\(Layout\.VALUE_ICON_STEPS\[iconStep\]\) as FontResource;/);
  assert.match(draw, /dc\.drawText\(\(Layout\.VALUE_CX \+ Layout\.VALUE_ICON_R \* Math\.cos\(iconTheta\) \+ 0\.5\)\.toNumber\(\), \(Layout\.VALUE_CY - Layout\.VALUE_ICON_R \* Math\.sin\(iconTheta\) \+ 0\.5\)\.toNumber\(\), iconFont, iconGlyph,/);
  // A clockwise run walks towards smaller Garmin angles: an icon that follows it moves that way per pixel, one that leads it the other.
  const ccw = RADIAL.replace("radius: 80%r}", "radius: 80%r, direction: counter_clockwise}");
  const sign = (align: string, position: string, curve = RADIAL): number => Math.sign(placedValue(radialPair(align, position, "", curve)).icon_track!.per_px);
  assert.deepEqual([sign("left", "right"), sign("right", "left"), sign("center", "right"), sign("center", "left")], [-1, 1, -1, 1]);
  assert.deepEqual([sign("left", "right", ccw), sign("right", "left", ccw), sign("center", "right", ccw), sign("center", "left", ccw)], [1, -1, 1, -1]);
});

/** Garmin degrees of a pixel's centre about `(cx, cy)`. */
const garminAt = ([x, y]: [number, number], cx: number, cy: number): number => (Math.atan2(cy - (y + 0.5), x + 0.5 - cx) * 180) / Math.PI;
const numOf = (n: unknown): number => (typeof n === "object" && n !== null ? (n as { value: number; add: number }).value + (n as { add: number }).add : n as number);

/** One pair's frame: its red icon and white reading pixels, and its program as the editor's JSON (the reading's and the icon's text ops). */
function pairFrame(text: string): { p: PlacedData; red: [number, number][]; white: [number, number][]; reading: string; iconAt: [number, number]; iconFont: string } {
  const r = resolved(text);
  const p = r.items.find((item) => item.id === "value") as PlacedData;
  const frame = render(r, previewOptions({ scale: 1 }));
  const red: [number, number][] = [], white: [number, number][] = [];
  for (let y = 0; y < frame.height; y++) {
    for (let x = 0; x < frame.width; x++) {
      const i = (y * frame.width + x) * 4;
      if (frame.data[i]! > 128 && frame.data[i + 1]! < 64) red.push([x, y]);
      else if (frame.data[i]! > 128 && frame.data[i + 1]! > 128 && frame.data[i + 2]! > 128) white.push([x, y]);
    }
  }
  const options = previewOptions();
  const renderer = newRenderer(r, options, sampleValues(r, options, null), [0, 0, 0]);
  const placed = frameItems(r, options, null).find((item) => item.id === "value")!;
  const [ops, fonts] = toJson(renderer, placed, new Tiles());
  const texts = ops.filter((op) => op.op === "text");
  const reading = texts.find((op) => fonts.get(op["font"] as string)!.vector)!;
  const icon = texts.find((op) => !fonts.get(op["font"] as string)!.vector)!;
  return { p, red, white, reading: reading["text"] as string, iconAt: [numOf(icon["x"]), numOf(icon["y"])], iconFont: fonts.get(icon["font"] as string)!.baked! };
}

test("the preview puts a free-end icon past the run's end, where the watch's arithmetic does", () => {
  for (const [curve, ccw] of [[RADIAL.replace("-46deg", "-60deg"), false],
    [RADIAL.replace("-46deg", "200deg").replace("radius: 80%r}", "radius: 80%r, direction: counter_clockwise}"), true]] as const) {
    const { p, red, white, reading, iconAt, iconFont } = pairFrame(radialPair("left", "right", "", curve));
    const t = p.icon_track!;
    const [cx, cy] = p.anchor_point;
    // The watch's own arithmetic: the angle from the measured width, the nearest baked step.
    const width = resolved(radialPair("left", "right", "", curve)).device.db.measure.measure(reading, p.font.metric!)[0];
    const theta = t.theta + t.per_px * width;
    assert.deepEqual(iconAt, [Math.trunc(cx + t.middle * Math.cos(theta) + 0.5), Math.trunc(cy - t.middle * Math.sin(theta) + 0.5)]);
    assert.equal(iconFont, stepKey(p.icon_font_key!, Math.min(Math.trunc(width * t.steps_per_px + 0.5), t.steps - 1)));
    // And the pixels: the icon's ink centred there, past the reading's last ink along the run.
    assert.ok(red.length > 20 && white.length > 20, `${red.length} icon and ${white.length} reading pixels`);
    const mx = red.reduce((s, [x]) => s + x + 0.5, 0) / red.length, my = red.reduce((s, [, y]) => s + y + 0.5, 0) / red.length;
    assert.ok(Math.hypot(mx - iconAt[0], my - iconAt[1]) <= 2.5, `icon ink at ${mx},${my}; drawn at ${iconAt}`);
    const icon = red.map((px) => garminAt(px, cx, cy)), text = white.map((px) => garminAt(px, cx, cy));
    if (ccw) assert.ok(Math.min(...icon) > Math.max(...text), `counter-clockwise: icon from ${Math.min(...icon)}deg, reading up to ${Math.max(...text)}deg`);
    else assert.ok(Math.max(...icon) < Math.min(...text), `clockwise: icon up to ${Math.max(...icon)}deg, reading from ${Math.min(...text)}deg`);
  }
});

test("a centred pair centres on the authored angle, the icon before or after the reading", () => {
  for (const position of ["left", "right"]) {
    const { p, red, white } = pairFrame(radialPair("center", position, "", RADIAL.replace("-46deg", "-90deg")));
    const [cx, cy] = p.anchor_point;
    const all = [...red, ...white].map((px) => garminAt(px, cx, cy));
    // At 9 o'clock (Garmin 180) atan2 wraps: measure from the authored angle instead.
    const off = all.map((a) => ((a - 180 + 540) % 360) - 180);
    const middle = (Math.min(...off) + Math.max(...off)) / 2;
    assert.ok(Math.abs(middle) <= 2.5, `${position}: the pair's ink is centred ${middle}deg off the authored angle`);
    const icon = red.map((px) => ((garminAt(px, cx, cy) - 180 + 540) % 360) - 180), text = white.map((px) => ((garminAt(px, cx, cy) - 180 + 540) % 360) - 180);
    // Clockwise at 9 o'clock reads upward: before the reading is below it (larger Garmin angle).
    if (position === "left") assert.ok(Math.min(...icon) > Math.max(...text), `left: icon from ${Math.min(...icon)}, reading up to ${Math.max(...text)}`);
    else assert.ok(Math.max(...icon) < Math.min(...text), `right: icon up to ${Math.max(...icon)}, reading from ${Math.min(...text)}`);
  }
});

test("each device bakes the steps its own widest reading reaches, and the view stays one file", () => {
  const devices = ["fenix8solar47mm", "fenix8solar51mm", "fr955"];
  const text = radialPair("left", "right", "", RADIAL, `[${devices.join(", ")}]`);
  const counts = devices.map((id) => {
    const r = resolved(text, id);
    const p = r.items.find((item) => item.id === "value") as PlacedData;
    const t = p.icon_track!, key = p.icon_font_key!;
    assert.ok(!r.fonts.has(key) && !r.fonts.has(stepKey(key, t.steps)), `${id}: only the steps are baked`);
    for (let i = 0; i < t.steps; i++) {
      const font = r.fonts.get(stepKey(key, i))!;
      assert.equal(font.rotate, t.turns[i], `${id} step ${i}`);
      // The watch clips a glyph to its cell: every turned glyph's ink stays inside it.
      for (const g of font.glyphs.values()) {
        if (g.width === 0) continue;
        assert.ok(g.xoffset >= 0 && g.xoffset + g.width <= g.xadvance && g.yoffset >= 0 && g.yoffset + g.height <= font.line_height,
          `${id} step ${i}: ${JSON.stringify(g)} in a ${font.line_height} line`);
      }
    }
    // Any reading up to the widest picks a step within half a step of its exact turn.
    const widest = r.device.db.measure.measure(p.widest, p.font.metric!)[0];
    for (let w = 0; w <= widest; w++) {
      const exact = 90 - ((t.theta + t.per_px * w) * 180) / Math.PI;
      const step = Math.min(Math.trunc(w * t.steps_per_px + 0.5), t.steps - 1);
      const off = ((t.turns[step]! - exact) % 360 + 540) % 360 - 180;
      assert.ok(Math.abs(off) <= 1.5 + 1e-9, `${id}: a ${w} px reading snaps ${off}deg off`);
    }
    return t.steps;
  });
  assert.ok(counts.every((n) => n > 5), `steps ${counts}`);
  assert.deepEqual(divergences(text), [], "the view and delegate are one file for every target");
  const files = generated(text);
  devices.forEach((id, i) => {
    const layout = files.get(`source-${id}/Layout.mc`)!;
    assert.equal((layout.match(/Rez\.Fonts\.FontIcon10pctrSlotLeftStepsValueS\d+/g) ?? []).length, counts[i], id);
  });
});

test("icon: {upright: true} at the free end draws the slot's upright font at the computed point, with no steps", () => {
  for (const align of ["left", "center"]) {
    const text = radialPair(align, "right", ", upright: true");
    const r = resolved(text);
    const p = r.items.find((item) => item.id === "value") as PlacedData;
    assert.equal(p.icon_font_key, "icon_10pctr_slot_left");
    assert.equal(p.icon_track!.steps, 0);
    assert.ok(![...r.fonts.keys()].some((k) => k.includes("_steps_")), [...r.fonts.keys()].join(" "));
    const draw = method(view(text), "drawValue");
    assert.match(draw, /var iconTheta = Layout\.VALUE_ICON_THETA/);
    assert.doesNotMatch(draw, /iconStep/);
    assert.equal(pairFrame(text).iconFont, "icon_10pctr_slot_left");
  }
});

test("a radial run's advances are laid out along its baseline circle, as the simulator drew them", () => {
  // The curved-slot probe on fenix8solar47mm: RobotoCondensedBold 28 px, clockwise from 150deg (Garmin), VCENTER.
  // Its ink ran 16.1 px past width/R for "12345678" at R = 52, and 4.6 px for "1234" at R = 78; the baseline rule predicts 17.5 and 5.5.
  const probe = (reading: string, radius: number): string => `${MINIMAL.replace("resources:\n", "resources:\n  fonts:\n    probe: { face: [RobotoCondensedBold], size: 28px }\n")}
  value:
    type: text
    text: "${reading}"
    font: font.probe
    at: {anchor: center}
    curve: {style: radial, angle: -60deg, radius: ${radius}px}
    align: left
    color: color.fg
`;
  for (const [reading, radius, past] of [["12345678", 52, 16.1], ["1234", 78, 4.6]] as const) {
    const r = resolved(probe(reading, radius));
    const p = r.items.find((item) => item.id === "value") as PlacedText;
    const metric = p.font.metric!;
    const width = r.device.db.measure.measure(reading, metric)[0];
    const spacing = radialSpacingRadius(radius, "center", null, r.device.db.measure.ascent(metric), r.device.db.measure.lineHeight(metric));
    assert.ok(spacing < radius, `the baseline sits inside the circle: ${spacing}`);
    const frame = render(r, previewOptions({ scale: 1 }));
    const [cx, cy] = p.anchor_point;
    let end = 360;
    for (let y = 0; y < frame.height; y++) {
      for (let x = 0; x < frame.width; x++) if (frame.data[(y * frame.width + x) * 4]! > 128) end = Math.min(end, garminAt([x, y], cx, cy));
    }
    const beyond = ((150 - (width / radius) * 180 / Math.PI - end) * Math.PI / 180) * radius;
    assert.ok(Math.abs(beyond - past) <= 2, `"${reading}" at R=${radius}: ink ends ${beyond.toFixed(1)} px past width/R, measured ${past}`);
  }
});
