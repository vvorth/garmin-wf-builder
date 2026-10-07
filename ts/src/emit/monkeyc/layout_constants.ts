// `Layout.mc`'s per-device constants, the blocks every kind builds its own
// from: the shared helpers.
import type { WatchNumber } from "../../draw/program.ts";
import { flt } from "../../draw/barrel.ts";
import { type Guards, NO_GUARDS, vectorFontFace } from "../../availability.ts";
import { discPerimeterOffsets, type Element, slotOf } from "../../ir/model.ts";
import { ringGroups } from "../../ir/rings.ts";
import * as kinds from "../../kinds/index.ts";
import {
  HIDDEN_BY_SUBSCREEN, type Placed, type PlacedGauge, type PlacedGraph, type PlacedHands, type PlacedPattern, type PlacedShape,
  type ResolvedFace, type ResolvedHandPart,
} from "../../layout.ts";
import { commentText } from "../../mcsource.ts";
import { formatFixed, formatG } from "../../py.ts";
import { IntBox } from "../../units.ts";
import { Writer } from "../writer.ts";
import {
  constPrefix, describe, type EditorSlot, editorSlots, header, McLiteral, mcNumber, mcType, type SourceFile, vectorFontsUsedIn,
} from "./common.ts";
import * as configMenu from "./config_menu.ts";
import * as profileMod from "./profile.ts";

/** One `Layout` block: `[name, value, note]` per constant. */
export type Constants = [string, WatchNumber | string | boolean | McLiteral, string][];

/** The `_X/_Y/_WIDTH/_HEIGHT` quartet for one resolved box. */
export function boxConstants(prefix: string, box: IntBox, note = ""): Constants {
  return [
    [`${prefix}_X`, box.x, note],
    [`${prefix}_Y`, box.y, ""],
    [`${prefix}_WIDTH`, box.width, ""],
    [`${prefix}_HEIGHT`, box.height, ""],
  ];
}

/** The `_RADIUS/_THICKNESS/_START/_SWEEP` quartet for one resolved arc. */
export function arcConstants(prefix: string, placed: PlacedShape | PlacedGauge): Constants {
  return [
    [`${prefix}_RADIUS`, placed.radius, ""],
    [`${prefix}_THICKNESS`, placed.thickness, "pen width; there is no filled-arc primitive"],
    [`${prefix}_START`, flt(placed.garmin_start),
      `${formatG(placed.start_angle)}deg clockwise from 12 o'clock, in Garmin's convention`],
    [`${prefix}_SWEEP`, flt(placed.sweep), "clockwise-positive degrees"],
  ];
}

/** `{prefix}_AOD_THICKNESS`, only when the element's resolved `aod:` overrides `thickness:`. */
export function aodThicknessConstant(prefix: string, placed: PlacedShape | PlacedGauge | PlacedGraph | PlacedHands | PlacedPattern,
  note = "aod: thickness override"): Constants {
  if (placed.aod_thickness === null) return [];
  return [[`${prefix}_AOD_THICKNESS`, placed.aod_thickness, note]];
}

/** One override, applied uniformly to every part of a hands/pattern element. */
export const EVERY_PART_NOTE = "aod: thickness override, applied to every part";

/** The `Layout` constants for one resolved hand part, or one pattern template part. */
export function handPartConstants(partPrefix: string, owner: string, index: number, part: ResolvedHandPart): Constants {
  if (part.shape === "text") {
    const out: Constants = [
      [`${partPrefix}_X`, part.x, `${owner}, part ${index}: text (the anchor)`],
      [`${partPrefix}_Y`, part.y, ""],
    ];
    if (part.curve.style === "radial") out.push([`${partPrefix}_RADIUS`, part.curve.radius_px, "curve: radial's own circle radius"]);
    return out;
  }
  if (part.shape === "polygon") {
    const points = part.points.map(([x, y]) => `[${x}, ${y}]`).join(", ");
    return [[`${partPrefix}_POINTS`, new McLiteral("Array<Graphics.Point2D>", `[${points}]`),
      `${owner}, part ${index}: a ${part.points.length}-vertex polygon`]];
  }
  if (part.shape === "line") {
    return [
      [`${partPrefix}_X1`, part.x1, `${owner}, part ${index}: a line`],
      [`${partPrefix}_Y1`, part.y1, ""],
      [`${partPrefix}_X2`, part.x2, ""],
      [`${partPrefix}_Y2`, part.y2, ""],
      [`${partPrefix}_THICKNESS`, part.thickness, "pen width"],
    ];
  }
  if (part.shape === "arc") {
    return [
      [`${partPrefix}_RADIUS`, part.radius, `${owner}, part ${index}: an arc`],
      [`${partPrefix}_THICKNESS`, part.thickness, "pen width; there is no filled-arc primitive"],
    ];
  }
  const out: Constants = [
    [`${partPrefix}_X`, part.x, `${owner}, part ${index}: a circle`],
    [`${partPrefix}_Y`, part.y, ""],
    [`${partPrefix}_RADIUS`, part.radius, ""],
  ];
  if (!part.filled) out.push([`${partPrefix}_THICKNESS`, part.thickness, "pen width; there is no filled-arc-style outline shortcut here"]);
  return out;
}

/** The numeric constants of `constants`, by name: what a kind's `lower` names. */
export function numericConstants(constants: Constants): Map<string, WatchNumber> {
  const out = new Map<string, WatchNumber>();
  for (const [name, value] of constants) if (typeof value === "number" || (typeof value === "object" && !(value instanceof McLiteral))) out.set(name, value as WatchNumber);
  return out;
}

/** One `const NAME as TYPE = VALUE;  // note` block. */
function emitConstants(w: Writer, constants: Constants): void {
  for (const [name, value, note] of constants) {
    const suffix = note ? `  // ${commentText(note)}` : "";
    w.line(`const ${name} as ${mcType(value)} = ${mcNumber(value)};${suffix}`);
  }
}

/** The `Layout` constants for one used `face:` font: `_FACE`/`_SIZE`, and `_AVAILABLE` when some target fails it. */
function vectorFontConstants(resolved: ResolvedFace, name: string, guards: Guards): Constants {
  const face = resolved.face, device = resolved.device;
  const spec = face.fonts.get(name)!;
  const prefix = `FONT_${constPrefix(name)}`;
  const resolvedFace = vectorFontFace(spec, device);
  const sizePx = spec.pixelSize(device.minorRadius);
  const requested = (spec.face ?? []).join(", ");
  const out: Constants = [
    [`${prefix}_FACE`, resolvedFace, resolvedFace ? `requested, in author order: ${requested}` : `none of [${requested}] is published on ${device.id}`],
    [`${prefix}_SIZE`, sizePx, ""],
  ];
  if (guards.vector_fonts.has(name)) {
    out.push([`${prefix}_AVAILABLE`, resolvedFace !== "",
      `${device.id} ${resolvedFace ? "publishes" : "does not publish"} a usable face -- some other target in this build does not, so the `
      + "shared view guards construction on this constant"]);
  }
  return out;
}

function highlight(placed: Placed): IntBox {
  return (placed as unknown as { highlight?: IntBox | null }).highlight ?? placed.box;
}

/** One slot's two editor boxes on this device: the tap target and the highlight. */
export function slotBoxConstants(resolved: ResolvedFace, slot: EditorSlot): Constants {
  const members = resolved.items.filter((p) => slotOf(p.element) === slot.name);
  if (members.length === 0) return [];
  let tap = members[0]!.box;
  let lit = highlight(members[0]!);
  for (const placed of members.slice(1)) {
    tap = tap.union(placed.box);
    lit = lit.union(highlight(placed));
  }
  return [
    ...boxConstants(`${slot.constPrefix}_BOX`, tap, "the editor's tap target (estimated)"),
    ...boxConstants(`${slot.constPrefix}_HIGHLIGHT`, lit, "the editor clips the slot's drawable to this box"),
  ];
}

/** Does `element` ring parts it transforms on the watch, through `WfbRing`? */
function transformsAtRuntime(element: Element): boolean {
  return element.kind === "hands" || element.kind === "pattern"
    || (element.kind === "gauge" && (element as unknown as { style?: string }).style === "needle");
}

/** Every distinct ring width over 1px `WfbRing` draws in this design, in first-appearance draw order. */
function outlineWidthsUsed(resolved: ResolvedFace): number[] {
  const out: number[] = [];
  const add = (width: number): void => { if (width > 1 && !out.includes(width)) out.push(width); };
  for (const ring of ringGroups(resolved.face.elements)) for (const [leaf, width] of ring.members) if (transformsAtRuntime(leaf)) add(width);
  for (const placed of resolved.items) {
    const outline = placed.element.outline;
    if (outline !== null && transformsAtRuntime(placed.element)) add(outline.width);
  }
  return out;
}

function outlineOffsetsConstants(width: number): Constants {
  const offsets = discPerimeterOffsets(width);
  const flat = offsets.flatMap(([dx, dy]) => [dx, dy]).join(", ");
  return [[`OUTLINE_OFFSETS_${width}`, new McLiteral("Array<Number>", `[${flat}]`), `${offsets.length} disc-perimeter points, ${width}px ring`]];
}

/** One device's `Layout` module. `profile` adds the profiling overlay's anchors. */
export function emitLayout(resolved: ResolvedFace, guards: Guards = NO_GUARDS, profile: number | null = null): SourceFile {
  const face = resolved.face, device = resolved.device;
  const w = new Writer();
  w.doc(header(face, `Device:    ${device.id} -- ${device.width}x${device.height} ${device.shape}, ${device.displayType}, family ${device.deviceFamily}`)).blank();
  const perItem = resolved.items.map((placed): [Placed, Constants] =>
    [placed, [...shownConstants(resolved, placed, guards), ...kinds.forPlaced(placed).layoutConstants(constPrefix(placed.id), placed), ...holdConstants(resolved, placed)]]);
  const needsGraphics = perItem.some(([, constants]) => constants.some(([, value]) => value instanceof McLiteral && value.type.includes("Graphics.")));
  const imports = needsGraphics ? ["import Toybox.Graphics;", "import Toybox.Lang;"] : ["import Toybox.Lang;"];
  const menuSlots = guards.config_menu && face.config_data.size > 0;
  if (menuSlots) imports.unshift("import Toybox.Complications;");
  w.lines(...imports).blank();
  w.doc(`Layout resolved for ${device.id}.\n`
    + "\n"
    + "Every value here came from a relative unit in the design -- percentages of\n"
    + "the parent box, fractions of the screen's minor radius, angles measured\n"
    + "clockwise from 12 o'clock.  Resolving them here means the device performs\n"
    + "no layout arithmetic at all, which costs neither memory nor frame time.");
  w.block("module Layout", () => {
    w.doc("The screen, for reference.");
    w.line(`const SCREEN_WIDTH as Number = ${device.width};`);
    w.line(`const SCREEN_HEIGHT as Number = ${device.height};`);
    if (menuSlots) configMenu.emitLayoutConstants(w, face, device);
    for (const slot of editorSlots(face)) {
      const boxes = slotBoxConstants(resolved, slot);
      if (boxes.length > 0) {
        w.blank();
        w.doc(`The native editor's boxes for slot ${slot.name}: every element drawing it,\ntaken together.`);
        emitConstants(w, boxes);
      }
    }
    const vectorFonts = vectorFontsUsedIn(resolved);
    if (vectorFonts.length > 0) {
      w.blank();
      w.doc("Device-resident scalable ('face:') fonts this design draws with.\n"
        + "\n"
        + "'_FACE'/'_SIZE' feed Graphics.getVectorFont directly, in onLayout.\n"
        + "'_AVAILABLE' is emitted only for a font at least one target device in\n"
        + "this build fails to publish -- the shared view (identical on every\n"
        + "device) reads it to decide whether to even attempt construction here,\n"
        + "so every device's own Layout.mc has to define it once any device\n"
        + "needs it (computeGuards' vector_fonts).");
      for (const name of vectorFonts) {
        w.blank();
        w.doc(`\`font.${name}\``);
        emitConstants(w, vectorFontConstants(resolved, name, guards));
      }
    }
    const outlineWidths = outlineWidthsUsed(resolved);
    if (outlineWidths.length > 0) {
      w.blank();
      w.doc("'outline:' offsets for each ring wider than 1px this design uses:\n"
        + "the points WfbRing shifts a runtime-transformed part to, index\n"
        + "i/i+1 per (dx, dy) pair.");
      for (const width of outlineWidths) emitConstants(w, outlineOffsetsConstants(width));
    }
    for (const [placed, constants] of perItem) {
      if (constants.length === 0) continue;
      w.blank();
      w.doc(`\`${placed.id}\` -- ${describe(placed)}`);
      emitConstants(w, constants);
    }
    const clip = resolved.clipFor("low_power");
    if (clip !== null) {
      w.blank();
      w.doc("The clip rectangle for low-power updates.\n"
        + "\n"
        + "setClip is charged by region *area* -- every pixel inside it counts as\n"
        + "modified whenever any does -- so this is the tightest box covering all\n"
        + `low-power elements: ${clip.area} px, `
        + `${formatFixed(100.0 * clip.area / (device.width * device.height), 0)}% of the screen.`);
      w.line(`const LOW_POWER_CLIP_X as Number = ${clip.x};`);
      w.line(`const LOW_POWER_CLIP_Y as Number = ${clip.y};`);
      w.line(`const LOW_POWER_CLIP_WIDTH as Number = ${clip.width};`);
      w.line(`const LOW_POWER_CLIP_HEIGHT as Number = ${clip.height};`);
    }
    if (profile) {
      w.blank();
      w.doc("`wfb build --profile`: where each timed entry's reading is drawn (the top\n"
        + "centre of its box), which layout it belongs to (-1: shared), and the\nheader line.");
      for (const line of profileMod.layoutLines(resolved, profileMod.planFor(resolved, profile))) w.line(line);
    }
  });
  return { path: `source-${device.id}/Layout.mc`, text: w.render() };
}

/** `<ID>_SHOWN` for an element in the subscreen window, when some target has none. */
function shownConstants(resolved: ResolvedFace, placed: Placed, guards: Guards): Constants {
  if (!guards.subscreen_hidden.has(placed.id) || placed.kind === "group") return [];
  const reason = resolved.hidden.get(placed.id) ?? null;
  const note = reason === null ? "drawn in the subscreen window"
    : reason === HIDDEN_BY_SUBSCREEN ? "no subscreen on this device: 'unsupported: hide'"
      : "its font has no face on this device: 'unsupported: hide'";
  return [[`${constPrefix(placed.id)}_SHOWN`, reason === null, note]];
}

/** The hit rectangle for an `on_hold:` element: its own drawn box, or empty where it does not draw. */
function holdConstants(resolved: ResolvedFace, placed: Placed): Constants {
  if (placed.element.on_hold === null) return [];
  const prefix = constPrefix(placed.id);
  let box = placed.box;
  let note = "hit region: the element's own drawn box";
  if (resolved.hidden.has(placed.id)) {
    box = new IntBox(0, 0, 0, 0);
    note = "hit region: empty, not drawn on this device";
  }
  return [
    [`${prefix}_HOLD_X`, box.x, note],
    [`${prefix}_HOLD_Y`, box.y, ""],
    [`${prefix}_HOLD_WIDTH`, box.width, ""],
    [`${prefix}_HOLD_HEIGHT`, box.height, ""],
  ];
}
