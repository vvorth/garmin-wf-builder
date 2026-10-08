// `overrides:` beyond geometry: `color:`/`track_color:` and `visible:`, and
// the `display:` selector, each decided per device in `Layout.mc` while the
// view stays shared.
import assert from "node:assert/strict";
import test from "node:test";
import { Expression } from "../src/ir/model.ts";
import { HIDDEN_BY_OVERRIDE, type ResolvedFace } from "../src/layout.ts";
import { Bag } from "../src/diagnostics.ts";
import { checkOverrideSelectors } from "../src/lint.ts";
import { db, errors, face, generated, MINIMAL, resolved } from "./designs.ts";

const TARGETS = ["fenix847mm", "fenix8solar47mm", "fr955"];

const DESIGN = MINIMAL.replace("targets: [fenix8solar47mm]", `targets: [${TARGETS.join(", ")}]`)
  .replace("    fg: \"#FFFFFF\"\n", "    fg: \"#FFFFFF\"\n    accent: \"#00AAFF\"\n    red: \"#FF0000\"\n    dim: \"#555555\"\n") + `
  clock:
    type: text
    text: "{time.clock:%H:%M}"
    font: FONT_NUMBER_MEDIUM
    at: {anchor: center}
    color: color.fg
    overrides:
      "display:amoled": {color: color.accent}
      "shape:round": {color: color.dim}
      fr955: {color: color.red}
  extras:
    type: group
    overrides:
      "display:amoled": {visible: false}
      fenix847mm: {visible: true}
      fr955: {visible: false}
    children:
      dot:
        type: circle
        at: {anchor: center, dy: 30%}
        radius: 3%r
        color: color.fg
`;

const color = (r: ResolvedFace, id: string): number =>
  Number((r.items.find((p) => p.id === id)!.element as unknown as { color: Expression }).color.constant);

const layout = (files: Map<string, string>, device: string): string => files.get(`source-${device}/Layout.mc`)!;

test("a colour override: the device id over its shape, the shape over its display", () => {
  assert.equal(color(resolved(DESIGN, "fenix847mm"), "clock"), 0x555555, "round beats display:amoled");
  assert.equal(color(resolved(DESIGN, "fr955"), "clock"), 0xff0000, "the device id beats its shape");
  const square = DESIGN.replace("\"shape:round\": {color: color.dim}", "\"shape:rectangle\": {color: color.dim}");
  assert.equal(color(resolved(square, "fenix847mm"), "clock"), 0x00aaff, "display:amoled alone");
  assert.equal(color(resolved(square, "fenix8solar47mm"), "clock"), 0xffffff, "nothing matches: its own");
});

test("the view picks the colour through a per-device Layout constant", () => {
  const files = generated(DESIGN);
  const views = [...files].filter(([name]) => name.endsWith("View.mc"));
  assert.equal(views.length, 1, "one view every target shares");
  assert.match(views[0]![1], /Layout\.CLOCK_VARIANT == \d+\) \? Palette\.RED/);
  const variants = TARGETS.map((d) => /CLOCK_VARIANT as Number = (\d+)/.exec(layout(files, d))![1]);
  assert.equal(new Set(variants).size, 2, "fenix847mm and fenix8solar47mm share shape:round's colour; fr955 has its own");
  assert.equal(variants[0], variants[1]);
});

test("visible: false hides a group's subtree on its devices, and a narrower true undoes it", () => {
  const amoled = resolved(DESIGN, "fenix847mm"), fr955 = resolved(DESIGN, "fr955");
  assert.equal(amoled.hidden.has("dot"), false, "fenix847mm: visible: true over display:amoled's false");
  assert.equal(fr955.hidden.get("dot"), HIDDEN_BY_OVERRIDE);
  const files = generated(DESIGN);
  assert.match(layout(files, "fr955"), /DOT_SHOWN as Boolean = false/);
  assert.match(layout(files, "fenix847mm"), /DOT_SHOWN as Boolean = true/);
  const view = [...files].find(([name]) => name.endsWith("View.mc"))![1];
  assert.match(view, /if \(!Layout\.DOT_SHOWN\)/);
});

test("a colour override needs a colour the element writes, on a kind that draws in it", () => {
  const unwritten = DESIGN.replace("      dot:\n        type: circle\n",
    "      dot:\n        type: circle\n        overrides:\n          fr955: {track_color: color.red}\n");
  assert.deepEqual(errors(unwritten).map((d) => d.message), ["dot.overrides.fr955: 'track_color:' is not a key this element writes"]);
  const onGroup = DESIGN.replace("fr955: {visible: false}", "fr955: {color: color.red}");
  assert.deepEqual(errors(onGroup).map((d) => d.message), ["extras.overrides.fr955: a group takes no 'color:' override"]);
});

test("a display: selector no target matches is the override-unreachable warning", () => {
  const lcd = DESIGN.replace("fr955: {color: color.red}", "\"display:lcd\": {color: color.red}");
  const bag = new Bag();
  checkOverrideSelectors(face(lcd), db.ids(), TARGETS.map((id) => db.get(id)), bag);
  assert.deepEqual(bag.items.map((d) => [d.code, d.message]),
    [["override-unreachable", "clock: no device in this build matches the override 'display:lcd', so it changes nothing"]]);
  const venu = new Bag();
  checkOverrideSelectors(face(lcd), db.ids(), [db.get("venusq")], venu);
  assert.equal(venu.items.filter((d) => d.code === "override-unreachable" && d.message.includes("display:lcd")).length, 0);
});
