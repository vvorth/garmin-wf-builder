// `<Face>View.mc`: the generated view's fields, lifecycle methods and one
// method per drawn element.
import { type Guards, NO_GUARDS } from "../../availability.ts";
import { READERS } from "../../catalog.ts";
import * as complications from "../../complications.ts";
import { Device } from "../../devices/device.ts";
import * as drawProgram from "../../draw/index.ts";
import { frameMembers } from "../../draw/frames.ts";
import type { Expression, Face } from "../../ir/model.ts";
import { HOLD_AUTO } from "../../ir/model.ts";
import {
  configDataIds, configField, elementMethodName as method, elementRingMethod, fontResourceId, localName, staticGroupMethod,
} from "../../ir/naming.ts";
import { type RingGroup, ringGroups } from "../../ir/rings.ts";
import * as kinds from "../../kinds/index.ts";
import { type Placed, PlacedData, PlacedGraph, PlacedHands, type ResolvedFace } from "../../layout.ts";
import { dimFraction } from "../../palette.ts";
import * as vocab from "../../vocab.ts";
import * as usage from "../usage.ts";
import { Writer } from "../writer.ts";
import {
  andList, aodFontField, aodOnlyFonts, AodStyle, CONFIG_LAYOUT_METHOD, constPrefix, describe, editorSlots, fontField, gatedHolds, header,
  HOLDS_SHOWN, holdTargets, loadedFonts, mcBool, NO_AOD, RingPass, type SourceFile, vectorFontsUsedIn,
} from "./common.ts";
import * as configMenu from "./config_menu.ts";
import {
  emitDataEditorMethods, emitDataHoldMethod, emitDataIconMethod, emitPulsingField, emitResourcesLoadedField, LOAD_RESOURCES_METHOD,
  RESOURCES_LOADED_FIELD,
} from "./data.ts";
import { emitGraphFields, emitGraphRebuild } from "./graph.ts";
import * as profileMod from "./profile.ts";
import { ReadPlan } from "./readplan.ts";

/** Base Toybox imports every generated face needs. */
export const BASE_IMPORTS = ["Toybox.Graphics", "Toybox.Lang", "Toybox.WatchUi"];

/** The Monkey C for "this condition does not hold": a `not` is un-negated rather than wrapped. */
export function negated(expression: Expression): string {
  const code = expression.code;
  const node = expression.ast;
  if (node !== null && node.kind === "unary" && node.op === "not") {
    if (!(code.startsWith("(!") && code.endsWith(")"))) throw new Error(code);
    return code.slice(2, -1);
  }
  return `!${negatable(code)}`;
}

/** `code` wrapped in parentheses unless it already is one group. */
function negatable(code: string): string {
  if (!(code.startsWith("(") && code.endsWith(")"))) return `(${code})`;
  let depth = 0;
  for (let index = 0; index < code.length; index++) {
    const ch = code[index];
    if (ch === "(") {
      depth++;
    } else if (ch === ")") {
      depth--;
      if (depth === 0 && index !== code.length - 1) return `(${code})`;
    }
  }
  return code;
}

/** The view field holding the offscreen buffer, and the method that fills it. */
export const STATIC_FIELD = "_staticBuffer";
export const STATIC_RENDER = "renderStatic";
/** Re-paints the static buffer from the current field values. */
export const REPAINT_STATIC_METHOD = "repaintStatic";
export const RESOLVE_STYLE_METHOD = "resolveStyle";
/** The view field the active layout's declaration-order index is cached in. */
export const CONFIG_LAYOUT_FIELD = configField("layout");
/** A `ring<Id>` method's own parameter: the colour of the group pass it draws for. */
const RING_PARAMETERS = ", ringColor as Number";

/** Which drawn elements go into the offscreen buffer, and in what order. */
class StaticPlan {
  readonly groups: [Placed, Placed[]][];
  readonly members: Placed[];
  readonly modes: string[];

  constructor(groups: [Placed, Placed[]][], members: Placed[], modes: string[]) {
    this.groups = groups;
    this.members = members;
    this.modes = modes;
  }

  get ids(): Set<string> {
    return new Set(this.members.map((p) => p.id));
  }

  /** The method that paints one root: its own for a leaf, a wrapper else. */
  method(placed: Placed): string {
    return placed.kind === "group" ? staticGroupMethod(placed.id) : method(placed.id);
  }
}

/** The face's outlined groups, and how a frame sequence draws their rings. */
class Rings {
  readonly groups: RingGroup[];
  readonly aod: AodStyle;

  constructor(groups: RingGroup[], aod: AodStyle = NO_AOD) {
    this.groups = groups;
    this.aod = aod;
  }

  widths(elementId: string): number[] {
    const out: number[] = [];
    for (const ring of this.groups) {
      if (!ring.ids.has(elementId)) continue;
      const width = ring.widthOf(elementId);
      if (!out.includes(width)) out.push(width);
    }
    return out;
  }

  /** The id of each outlined group's first member drawn here, to the groups whose rings go before it. */
  prelude(items: readonly Placed[]): Map<string, [RingGroup, Placed[]][]> {
    const out = new Map<string, [RingGroup, Placed[]][]>();
    for (const ring of this.groups) {
      const present = items.filter((p) => ring.ids.has(p.id));
      if (present.length === 0) continue;
      if (!out.has(present[0]!.id)) out.set(present[0]!.id, []);
      out.get(present[0]!.id)!.push([ring, present]);
    }
    return out;
  }

  calls(plan: ReadPlan, ring: RingGroup, member: Placed): string {
    const width = ring.widthOf(member.id);
    const color = this.aod.dimmed(ring.group, ring.group.outline!.color);
    return `${elementRingMethod(member.id, width)}(dc${plan.arguments(member)}, ${color});`;
  }

  emitBefore(w: Writer, plan: ReadPlan, prelude: Map<string, [RingGroup, Placed[]][]>, placed: Placed,
    emitCall: ((member: Placed, line: string) => void) | null = null): void {
    for (const [ring, members] of prelude.get(placed.id) ?? []) {
      w.comment(`'${ring.group.id}' outline: every member's ring, then the members`);
      for (const member of members) {
        const line = this.calls(plan, ring, member);
        if (emitCall === null) w.line(line); else emitCall(member, line);
      }
    }
  }
}

/** The face's one static buffer, or `null` when nothing is static. */
function staticPlan(resolved: ResolvedFace): StaticPlan | null {
  const members = resolved.items.filter((p) => p.kind !== "group" && p.element.static_root !== null);
  if (members.length === 0) return null;
  const roots = new Map(resolved.items.filter((p) => p.element.static).map((p) => [p.id, p]));
  const groups: [Placed, Placed[]][] = [];
  for (const placed of members) {
    const root = roots.get(placed.element.static_root!);
    if (root === undefined) continue;
    if (groups.length === 0 || groups[groups.length - 1]![0] !== root) groups.push([root, []]);
    groups[groups.length - 1]![1].push(placed);
  }
  return new StaticPlan(groups, members, [...members[0]!.element.modes]);
}

/** The face-wide `antialias:` default, or `null` when no primitive-drawing element draws anti-aliased. */
function antialiasDefault(resolved: ResolvedFace): boolean | null {
  const used = resolved.items.some((p) => kinds.forPlaced(p).antialiased && p.element.resolved_antialias);
  return used ? resolved.face.antialias : null;
}

function emitAntialiasHelper(w: Writer): void {
  w.doc("Turn primitive anti-aliasing on or off, where the device supports it.\n"
    + "\n"
    + "Guarded rather than called directly: `Dc.setAntiAlias` is absent on roughly a\n"
    + "third of Connect IQ devices, and this view's generated code has to type-check\n"
    + "on every target regardless of which one actually has the symbol.");
  w.block("private function applyAntiAlias(dc as Dc, on as Boolean) as Void", () => {
    w.block("if (dc has :setAntiAlias)", () => w.line("dc.setAntiAlias(on);"));
  });
  w.blank();
}

/** Does this build get an `onPartialUpdate`: a `low_power` mode, and some target supporting it. */
function hasPartialUpdate(resolved: ResolvedFace, guards: Guards): boolean {
  return resolved.drawnInMode("low_power").length > 0 && !guards.partial_update_unsupported;
}

/** The shared view; `profile` times the active frame and leaves the static buffer out. */
export function emitView(resolved: ResolvedFace, guards: Guards = NO_GUARDS, profile: number | null = null): SourceFile {
  const face = resolved.face;
  const plan = new ReadPlan(resolved, guards);
  const graphs = resolved.items.filter((p): p is PlacedGraph => p instanceof PlacedGraph);
  const needsSleepingField = resolved.items.some((p) => p instanceof PlacedHands && p.second !== null && p.element.seconds === "awake");
  const w = new Writer();
  w.doc(`${face.name}.\n`
    + "\n"
    + "One private method per design element, in draw order.  Each is named after\n"
    + "the element's `id:` in the source YAML, so a change on screen leads back to\n"
    + "a line in the design file.");
  const aodOn = guards.amoled_target;
  const aod = new AodStyle(aodOn, aodOn && face.aod_dim !== null ? dimFraction(face.aod_dim) : null);
  const statics = !profile ? staticPlan(resolved) : null;
  const rings = new Rings(ringGroups(face.elements), aod);
  const prof = profile ? profileMod.planFor(resolved, profile) : null;
  const aaDefault = antialiasDefault(resolved);
  const slots = editorSlots(face);
  const aodOnly = aod.on ? aodOnlyFonts(resolved) : [];
  w.block(`class ${face.entry}View extends WatchUi.WatchFace`, () => {
    emitFields(w, resolved, aodOnly);
    if (prof !== null) emitProfileFields(w, prof);
    emitConfigFields(w, face, guards);
    if (guards.config_menu) configMenu.emitFields(w, face);
    emitStaticField(w, statics);
    emitGraphFields(w, graphs);
    if (slots.length > 0) {
      emitPulsingField(w);
      emitResourcesLoadedField(w);
    }
    if (needsSleepingField) {
      w.doc("Whether the watch is currently asleep.  Set by onEnterSleep/onExitSleep below.\n\n"
        + "An awake-only second hand ('seconds: awake') reads it, so its own draw\n"
        + "method skips the second hand while asleep instead of drawing it frozen at\n"
        + "whatever second the once-a-minute sleeping update landed on.");
      w.line("private var _sleeping as Boolean = false;");
      w.blank();
    }
    if (aod.on) {
      w.doc("Whether the AMOLED always-on-display frame should draw: asleep, on a\n"
        + "device that requires burn-in protection. Recomputed in onEnterSleep\n"
        + "(a hardware fact, not a per-frame one) and cleared in onExitSleep --\n"
        + "see docs/guide/always-on-display.md.");
      w.line("private var _aod as Boolean = false;");
      w.blank();
    }
    const gated = gatedHolds(face);
    if (gated.length > 0) {
      w.doc("One bit per hold target a `visible:` can hide ("
        + gated.map((e, bit) => `${bit}: \`${e.id}\``).join(", ") + "),\n"
        + "set as it passes that test and cleared at the start of each onUpdate, so\n"
        + "the delegate's onPress reaches only what the last frame drew.  Public: a\n"
        + "delegate cannot reach a private field.");
      w.line(`var ${HOLDS_SHOWN} as Number = 0;`);
      w.blank();
    }
    emitInitialize(w, face, slots.length > 0, guards);
    if (aaDefault !== null) emitAntialiasHelper(w);
    if (face.hasConfig) emitApplyConfig(w, face, statics);
    if (guards.config_menu) {
      configMenu.emitViewMethods(w, face, face.entry, {
        repaint: statics !== null ? REPAINT_STATIC_METHOD : null, resolveStyle: RESOLVE_STYLE_METHOD, complicationsGuarded: guards.complications,
      });
    }
    if (face.hasConfig && holdTargets(face).some((t) => t.layout !== null)) emitConfigLayoutAccessor(w);
    emitOnLayout(w, resolved, plan, statics, guards, slots.length > 0);
    emitOnUpdate(w, resolved, plan, aod.on, statics, aaDefault, guards, slots.length > 0, rings, prof);
    if (prof !== null) emitProfileOverlay(w, prof);
    if (hasPartialUpdate(resolved, guards)) emitOnPartialUpdate(w, resolved, plan, aaDefault, rings);
    emitSleepHooks(w, resolved, needsSleepingField, aod.on, guards, aodOnly);
    if (plan.complicationReaders().length > 0) emitComplicationCallback(w);
    for (const graph of graphs) emitGraphRebuild(w, graph, guards);
    for (const placed of resolved.items) {
      if (placed instanceof PlacedData && placed.icon_font_key !== null) emitDataIconMethod(w, resolved, placed);
      if (placed instanceof PlacedData && placed.element.on_hold === HOLD_AUTO) emitDataHoldMethod(w, placed, guards);
    }
    if (slots.length > 0) emitDataEditorMethods(w, resolved, plan, slots);
    if (statics !== null) emitStaticMethods(w, face, statics, aaDefault, face.hasConfig, guards.config_menu, plan, rings);
    for (const placed of resolved.items) {
      if (placed.kind === "group") continue;
      w.blank();
      emitElementMethod(w, resolved, placed, plan, aaDefault, aod, guards.subscreen_hidden.has(placed.id));
      for (const width of rings.widths(placed.id)) {
        w.blank();
        emitElementMethod(w, resolved, placed, plan, aaDefault, aod, guards.subscreen_hidden.has(placed.id), width);
      }
    }
  });
  const bodyText = w.render();
  const modules = [...new Set([...BASE_IMPORTS, ...usage.toyboxModules(bodyText)])].sort();
  const preamble = new Writer();
  preamble.doc(header(face)).blank();
  for (const module of modules) preamble.line(`import ${module};`);
  preamble.blank();
  w.prepend(preamble);
  return { path: `source/${face.entry}View.mc`, text: w.render() };
}

function emitStaticField(w: Writer, statics: StaticPlan | null): void {
  if (statics === null) return;
  w.doc("The static content, painted once in onLayout and blitted every frame\n"
    + "afterwards.\n"
    + "\n"
    + "Allocated from the graphics pool, which is separate from the watch face's\n"
    + "own memory limit -- so this costs a full screen of pixels there, not here.\n"
    + "Null on a device without createBufferedBitmap, or if the pool declines the\n"
    + "allocation; onUpdate then draws the same content directly instead, so the\n"
    + "face renders either way.");
  w.line(`private var ${STATIC_FIELD} as BufferedBitmap?;`);
  w.blank();
}

function emitStaticAllocation(w: Writer): void {
  w.comment("the static content, painted once into a buffer in the graphics pool");
  w.block("if (Graphics has :createBufferedBitmap)", () => {
    w.line(`${STATIC_FIELD} = Graphics.createBufferedBitmap({`);
    w.line("    :width => dc.getWidth(),");
    w.line("    :height => dc.getHeight()");
    w.line("}).get() as BufferedBitmap?;");
  });
  w.line(`var buffer = ${STATIC_FIELD};`);
  w.block("if (buffer != null)", () => w.line(`${STATIC_RENDER}(buffer.getDc());`));
}

function emitStaticBlit(w: Writer): void {
  w.comment("static content: one blit of the buffer filled in onLayout");
  w.line(`var buffer = ${STATIC_FIELD};`);
  w.block("if (buffer != null)", () => w.line("dc.drawBitmap(0, 0, buffer);"));
  w.block("else", () => {
    w.comment("no buffer on this device: draw the same content directly");
    w.line(`${STATIC_RENDER}(dc);`);
  });
}

function emitStaticMethods(w: Writer, face: Face, statics: StaticPlan, aaDefault: boolean | null, needsRepaint: boolean, fromMenu: boolean,
  plan: ReadPlan | null, rings: Rings): void {
  w.blank();
  w.doc("Everything that never changes, drawn once.\n"
    + "\n"
    + "Called with the offscreen buffer's Dc from onLayout, and with the screen's\n"
    + "own Dc from onUpdate when there is no buffer.  One method, so the buffered\n"
    + "and unbuffered paths cannot drift apart.");
  w.block(`private function ${STATIC_RENDER}(dc as Dc) as Void`, () => {
    w.comment("a fresh buffer's contents are undefined, and this is the first");
    w.comment("thing drawn in the frame either way, so start from a known ground");
    w.line("dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);");
    w.line("dc.clear();");
    if (aaDefault !== null) w.line(`applyAntiAlias(dc, ${mcBool(aaDefault)});`);
    emitLayoutGuarded(w, face, statics.groups.map(([root]) => root), (root) => w.line(`${statics.method(root)}(dc);`));
  });
  if (needsRepaint) {
    w.blank();
    w.doc("Re-paint the static buffer from the current field values, in place.\n"
      + "\n"
      + (fromMenu ? "Called from `applyConfig`/`applyStoredConfig`: a config colour drawn into static\ncontent"
        : "Called only from `applyConfig`: a config colour drawn into static content")
      + "\n"
      + "was already baked into the buffer once in onLayout, so a wearer's edit\n"
      + "needs this to show before the buffer is blitted again.  Narrows through a\n"
      + "local rather than calling `.getDc()` straight off the field -- `monkeyc`\n"
      + "cannot narrow a `Null` check across a field read (CLAUDE.md).");
    w.block(`private function ${REPAINT_STATIC_METHOD}() as Void`, () => {
      w.line(`var buffer = ${STATIC_FIELD};`);
      w.block("if (buffer != null)", () => w.line(`${STATIC_RENDER}(buffer.getDc());`));
    });
  }
  for (const [root, members] of statics.groups) {
    if (root.kind !== "group") continue;
    w.blank();
    w.doc(`\`${root.element.id}\` -- the static subtree, in draw order.`);
    const prelude = rings.prelude(members);
    w.block(`private function ${statics.method(root)}(dc as Dc) as Void`, () => {
      for (const placed of members) {
        if (plan !== null) rings.emitBefore(w, plan, prelude, placed);
        w.line(`${method(placed.id)}(dc);`);
      }
    });
  }
}

function emitFields(w: Writer, resolved: ResolvedFace, aodOnly: string[]): void {
  const loaded = loadedFonts(resolved);
  const vectorFonts = vectorFontsUsedIn(resolved);
  if (loaded.length === 0 && vectorFonts.length === 0 && aodOnly.length === 0) return;
  if (loaded.length > 0) {
    w.doc("Bitmap fonts -- custom text and icon glyphs alike -- loaded once in\nonLayout rather than per frame.");
    for (const name of loaded) w.line(`private var _${fontField(name)} as FontResource?;`);
    w.blank();
  }
  if (aodOnly.length > 0) {
    w.doc("Bitmap fonts named only by an 'aod: {font: ...}' override\n"
      + "-- never drawn while awake, so they are loaded in onEnterSleep\n"
      + "instead of here, only when _aod ends up true, and released (nulled) in\n"
      + "onExitSleep so they do not sit in memory the whole time.");
    for (const name of aodOnly) w.line(`private var _${aodFontField(name)} as FontResource?;`);
    w.blank();
  }
  if (vectorFonts.length > 0) {
    w.doc("Device-resident scalable ('face:') fonts -- a Graphics.\n"
      + "VectorFont handed back by Graphics.getVectorFont, not a loaded\n"
      + "resource; null wherever this device cannot build it, which every\n"
      + "draw call below checks before using it.");
    for (const name of vectorFonts) w.line(`private var _${fontField(name)} as Graphics.VectorFont?;`);
    w.blank();
  }
}

function emitConfigFields(w: Writer, face: Face, guards: Guards): void {
  if (!face.hasConfig) return;
  w.doc("Colours and complications the wearer can change in the native on-device editor\n"
    + "(fēnix 8 and newer only).  Each starts at its declared default, which is also\n"
    + "the only value a device with no editor -- fr955 -- ever shows.");
  for (const entry of face.config.values()) w.line(`private var ${entry.field} as Number = ${entry.default.asMonkeyc()};`);
  if (face.config_style !== null && face.config_style.defaultEntry.colors !== null) {
    for (const [role, color] of face.color_scheme.get(face.config_style.defaultEntry.colors)!.colors) {
      if (!face.scheme_roles_used.has(role)) continue; // monkeyc warns of an unused member
      w.line(`private var ${configField(`colors_${role}`)} as Number = ${color.asMonkeyc()};`);
    }
  }
  if (face.layouts.length > 0) {
    w.line(`private var ${CONFIG_LAYOUT_FIELD} as Number = ${face.layouts.indexOf(face.config_style!.defaultEntry.layout!)};`);
  }
  for (const slot of face.config_data.values()) {
    const ctype = complications.TYPES.get(slot.default)!;
    if (guards.complications) w.line(`private var ${slot.field} as Complications.Id? = null;  // set in initialize() -- see this method's own doc`);
    else w.line(`private var ${slot.field} as Complications.Id = new Complications.Id(Complications.${ctype.constant});`);
  }
  w.blank();
}

function emitApplyConfig(w: Writer, face: Face, statics: StaticPlan | null): void {
  w.doc("Apply one WatchFaceConfig.Settings snapshot.\n"
    + "\n"
    + "Every field is nullable twice over, so a missing value simply leaves the\n"
    + "existing (defaulted) field alone rather than being treated as an error.");
  w.block("function applyConfig(settings as WatchFaceConfig.Settings) as Void", () => {
    if (face.config_style !== null) {
      const styleLocal = localName("config_style");
      w.line(`var ${styleLocal} = settings.styleId;`);
      w.block(`if (${styleLocal} != null && ${styleLocal} >= 0 && ${styleLocal} < ${face.config_style.entries.length})`, () => {
        w.line(`${RESOLVE_STYLE_METHOD}(${styleLocal});`);
      });
    }
    for (const [name, entry] of face.config) {
      const local = localName(`config_${name}`);
      w.line(`var ${local} = settings.${entry.axis.settings_field};`);
      w.block(`if (${local} != null)`, () => {
        const valueLocal = `${local}Value`;
        w.line(`var ${valueLocal} = ${local}.color;`);
        w.block(`if (${valueLocal} != null)`, () => w.line(`${entry.field} = ${valueLocal} as Number;`));
      });
    }
    if (face.config_data.size > 0) {
      const ids = configDataIds(face);
      w.blank();
      w.comment("config: slots: -- each ComplicationRef names the slot it belongs");
      w.comment("to by 'uniqueIdentifier', matching the <complication id=...> below");
      w.line("var slots = settings.complicationSettings;");
      w.block("if (slots != null)", () => {
        w.block("for (var i = 0; i < slots.size(); i += 1)", () => {
          w.line("var ref = slots[i];");
          w.line("var unique = ref.uniqueIdentifier;");
          w.line("var picked = ref.complicationId;");
          w.block("if (unique == null || picked == null)", () => w.line("continue;"));
          for (const [name, slotId] of ids) {
            const slot = face.config_data.get(name)!;
            w.block(`if (unique == ${slotId})`, () => w.line(`${slot.field} = picked;`));
          }
        });
      });
    }
    if (statics !== null) {
      w.blank();
      w.comment("a config colour may be painted into the static buffer -- repaint");
      w.comment("it now so a wearer's change shows without waiting for onLayout");
      w.line(`${REPAINT_STATIC_METHOD}();`);
    }
    w.line("WatchUi.requestUpdate();");
  });
  w.blank();
  if (face.config_style !== null) emitResolveStyle(w, face);
}

function emitConfigLayoutAccessor(w: Writer): void {
  w.doc("The active layout's index, for the delegate's onPress to test a layout-scoped\n"
    + "hold target against.  Public: a delegate method cannot reach a private field\n"
    + "on this class.");
  w.block(`function ${CONFIG_LAYOUT_METHOD}() as Number`, () => w.line(`return ${CONFIG_LAYOUT_FIELD};`));
  w.blank();
}

function emitResolveStyle(w: Writer, face: Face): void {
  w.doc("Decode one Styles id into this design's config: style: entries.  styleId is\n"
    + "an opaque Number Garmin gives no meaning to -- this is the only place\n"
    + "that meaning is assigned, in 'choices:' order, index 0 first.");
  w.block(`private function ${RESOLVE_STYLE_METHOD}(style as Number) as Void`, () => {
    face.config_style!.entries.forEach((entry, index) => {
      w.block(`if (style == ${index})`, () => {
        const comment: string[] = [];
        if (entry.colors !== null) comment.push(`scheme: ${entry.colors}`);
        if (entry.layout !== null) comment.push(`layout: ${entry.layout}`);
        w.comment(`${entry.name} -- ${comment.join(", ")}`);
        if (entry.colors !== null) {
          for (const [role, color] of face.color_scheme.get(entry.colors)!.colors) if (face.scheme_roles_used.has(role)) w.line(`${configField(`colors_${role}`)} = ${color.asMonkeyc()};`);
        }
        if (entry.layout !== null) w.line(`${CONFIG_LAYOUT_FIELD} = ${face.layouts.indexOf(entry.layout)};`);
      });
    });
  });
  w.blank();
}

function emitInitialize(w: Writer, face: Face, hasSlots: boolean, guards: Guards): void {
  if (hasSlots) {
    w.doc("`editMode` is accepted, not stored: getComplicationDrawable/onTap\n"
      + "(the delegate) are self-gating -- the system simply never calls them\n"
      + "outside the native editor -- and every complication here is pulled\n"
      + "fresh every frame rather than cached or subscribed, so there is\n"
      + "nothing else in this view for edit mode to change.  An unused\n"
      + "*parameter* does not warn (verified, same as the delegate's own\n"
      + "`view` parameter); a written-but-never-read *field* does (verified\n"
      + "the other way -- \"Member variable '_editMode' is not used.\"), which\n"
      + "is why AppBase.onStart's own flag is forwarded here rather than kept.");
  }
  w.block(hasSlots ? "function initialize(editMode as Boolean)" : "function initialize()", () => {
    w.line("WatchFace.initialize();");
    if (guards.complications && face.config_data.size > 0) {
      w.blank();
      w.comment("Toybox.Complications is absent on at least one target -- leave");
      w.comment("every slot's Id null there, which config: slots: draw code below");
      w.comment("already treats as \"nothing chosen\" (absent:-style absence)");
      w.block("if (Toybox has :Complications)", () => {
        for (const slot of face.config_data.values()) {
          w.line(`${slot.field} = new Complications.Id(Complications.${complications.TYPES.get(slot.default)!.constant});`);
        }
      });
    }
    if (guards.config_menu) {
      w.comment("no native editor: config comes from the settings menu's stored choices");
      w.block("if (!(Application has :WatchFaceConfig))", () => w.line(`${configMenu.APPLY_STORED_METHOD}();`));
    }
  });
  w.blank();
}

function emitVectorFontConstruction(w: Writer, name: string, guards: Guards): void {
  const field = `_${fontField(name)}`;
  const prefix = `FONT_${constPrefix(name)}`;
  const assignment = `${field} = Graphics.getVectorFont({:face => Layout.${prefix}_FACE, :size => Layout.${prefix}_SIZE});`;
  const guarded = guards.vector_fonts.has(name);
  if (guarded) w.comment(`font.${name}: some target device in this build does not publish any requested face`);
  w.blockIf(guarded ? `if (Layout.${prefix}_AVAILABLE && (Graphics has :getVectorFont))` : null, () => w.line(assignment));
}

function emitOnLayout(w: Writer, resolved: ResolvedFace, plan: ReadPlan, statics: StaticPlan | null, guards: Guards, hasSlots: boolean): void {
  const face = resolved.face;
  const loaded = loadedFonts(resolved);
  const vectorFonts = vectorFontsUsedIn(resolved);
  const event = plan.complicationReaders();
  const hasConfig = face.hasConfig;
  w.doc("Load resources once.  Loading is expensive and must not happen per frame."
    + (statics !== null ? "\n\nThis is also where the static content is painted, once, into its\noffscreen buffer -- every later frame just blits it." : "")
    + (hasConfig ? "\n\nThe first config read happens here too, so the very first frame\n"
      + "already reflects the wearer's own choice rather than the compiled-in\n"
      + "default -- guarded, since a device with no native editor (fr955) has\n"
      + "no WatchFaceConfig module to call at all." : ""));
  if (hasSlots) {
    w.block("function onLayout(dc as Dc) as Void", () => {
      w.line(`${LOAD_RESOURCES_METHOD}();`);
      if (event.length > 0) {
        w.blank();
        emitSubscriptions(w, plan, event);
      }
      if (statics !== null) {
        w.blank();
        emitStaticAllocation(w);
      }
    });
    w.blank();
    w.doc("Fonts and the first config read: what every slot's draw method needs.\n"
      + "\nCalled from onLayout, and from drawableFor when the native editor asks\nfor a slot before onLayout has run.");
    w.block(`private function ${LOAD_RESOURCES_METHOD}() as Void`, () => {
      w.line(`${RESOURCES_LOADED_FIELD} = true;`);
      emitFontLoads(w, loaded, vectorFonts, guards);
      if (hasConfig) {
        if (loaded.length > 0 || vectorFonts.length > 0) w.blank();
        emitFirstConfigRead(w);
      }
    });
    w.blank();
    return;
  }
  w.block("function onLayout(dc as Dc) as Void", () => {
    if (loaded.length === 0 && vectorFonts.length === 0 && event.length === 0 && statics === null && !hasConfig) {
      w.line("// No resources to load: this face draws entirely from system fonts.");
    }
    emitFontLoads(w, loaded, vectorFonts, guards);
    if (event.length > 0) {
      if (loaded.length > 0 || vectorFonts.length > 0) w.blank();
      emitSubscriptions(w, plan, event);
    }
    if (hasConfig) {
      if (loaded.length > 0 || event.length > 0) w.blank();
      emitFirstConfigRead(w);
    }
    if (statics !== null) {
      if (loaded.length > 0 || event.length > 0 || hasConfig) w.blank();
      emitStaticAllocation(w);
    }
  });
  w.blank();
}

function emitFontLoads(w: Writer, loaded: string[], vectorFonts: string[], guards: Guards): void {
  for (const name of loaded) w.line(`_${fontField(name)} = WatchUi.loadResource(Rez.Fonts.${fontResourceId(name)}) as FontResource;`);
  if (vectorFonts.length > 0) {
    if (loaded.length > 0) w.blank();
    for (const name of vectorFonts) emitVectorFontConstruction(w, name, guards);
  }
}

function emitSubscriptions(w: Writer, plan: ReadPlan, event: string[]): void {
  w.comment("complications: one subscription per type, which keeps the platform's own reading fresh -- the value itself is pulled in "
    + "onUpdate, not delivered here. WfbComplications.subscribe absorbs a device that does not support a given type");
  const guarded = plan.device_guards.complications;
  if (guarded) w.comment("Toybox.Complications is absent on at least one target device");
  w.blockIf(guarded ? "if (Toybox has :Complications)" : null, () => {
    w.line("Complications.registerComplicationChangeCallback(method(:onComplicationChanged));");
    for (const name of event) w.line(`WfbComplications.subscribe(new Complications.Id(Complications.${READERS.get(name)!.complication_type}));`);
  });
}

function emitFirstConfigRead(w: Writer): void {
  w.comment("the native on-device editor, where this device has one -- absent on");
  w.comment("fr955, which keeps running on the compiled-in defaults above");
  w.block("if (Application has :WatchFaceConfig)", () => {
    w.line("var settings = WatchFaceConfig.getSettings(null);");
    w.block("if (settings != null)", () => w.line("applyConfig(settings);"));
  });
}

function emitOnUpdate(w: Writer, resolved: ResolvedFace, plan: ReadPlan, aod: boolean, statics: StaticPlan | null, aaDefault: boolean | null,
  guards: Guards, hasSlots: boolean, rings: Rings, profile: profileMod.ProfilePlan | null): void {
  w.doc("Draw the full face.\n"
    + "\n"
    + "Called once a minute in low-power mode and once a second while the watch is\n"
    + "awake."
    + (aod ? "  While _aod (asleep, on a burn-in-protected device), draws the resolved\n"
      + "'aod:' set instead -- see _aod, set by onEnterSleep/onExitSleep below -- or\n"
      + "nothing at all if the device says the display itself is off (research 11 §6 F)." : "")
    + (statics !== null ? "  The static content comes first, as one blit of a buffer painted in\n"
      + "onLayout -- or, on a device that could not allocate one, drawn straight\n"
      + "onto the screen instead." : "")
    + (aaDefault !== null ? "  Anti-aliasing is reset to the face default here, once, so it covers\n"
      + "both the asleep and awake branches below; an element that overrides the\n"
      + "default sets and restores it around its own drawing." : ""));
  w.block("function onUpdate(dc as Dc) as Void", () => {
    w.line("dc.clearClip();");
    if (gatedHolds(resolved.face).length > 0) w.line(`${HOLDS_SHOWN} = 0;`);
    if (aaDefault !== null) w.line(`applyAntiAlias(dc, ${mcBool(aaDefault)});`);
    if (aod) {
      w.block("if (_aod)", () => emitAodBody(w, resolved, plan, guards, rings));
      w.block("else", () => emitModeBody(w, resolved, plan, "active", statics, rings, profile));
    } else {
      emitModeBody(w, resolved, plan, "active", statics, rings, profile);
    }
    if (hasSlots) {
      w.blank();
      w.comment("the editor's slot skip covers this one redraw: its next move asks");
      w.comment("for a drawable again, but moving on to \"Done\" only redraws");
      w.line("_pulsing = 0;");
    }
  });
  w.blank();
}

function emitTimed(w: Writer, profile: profileMod.ProfilePlan, index: number, body: () => void, baseline = false): void {
  const reps = profile.reps;
  w.block(`if (${profileMod.NEXT} == ${index})`, () => {
    w.line("var t0 = System.getTimer();");
    w.block(`for (var r = 0; r < ${reps}; r++)`, body);
    w.line(`${profileMod.MS}[${index}] += System.getTimer() - t0;`);
    w.line(`${profileMod.REPS}[${index}] += ${reps};`);
  });
  if (!baseline) w.block("else", body);
}

function emitProfileFields(w: Writer, profile: profileMod.ProfilePlan): void {
  const zeros = profile.entries.map(() => "0").join(", ");
  w.doc("`wfb build --profile`: which entry this frame times, and every entry's accumulated\nmilliseconds and repetitions -- "
    + profile.entries.map((entry, i) => `${i} ${entry.label}`).join(", ") + ".");
  w.line(`private var ${profileMod.NEXT} as Number = 0;`);
  w.line(`private var ${profileMod.MS} as Array<Number> = [${zeros}] as Array<Number>;`);
  w.line(`private var ${profileMod.REPS} as Array<Number> = [${zeros}] as Array<Number>;`);
  w.line(`private var ${profileMod.FRAME} as Number = 0;`);
  w.blank();
}

function emitProfileAdvance(w: Writer, profile: profileMod.ProfilePlan): void {
  const count = profile.entries.length;
  w.line(`var next = (${profileMod.NEXT} + 1) % ${count};`);
  if (profile.layouts) {
    w.block(`while (Layout.PROF_LAYOUT[next] != -1 && Layout.PROF_LAYOUT[next] != ${CONFIG_LAYOUT_FIELD})`, () => w.line(`next = (next + 1) % ${count};`));
  }
  w.line(`${profileMod.NEXT} = next;`);
}

function emitProfileOverlay(w: Writer, profile: profileMod.ProfilePlan): void {
  const count = profile.entries.length;
  w.doc("`wfb build --profile`: every timed entry's average draw time per call, in\nmicroseconds less the empty-loop baseline, above its own box; and a "
    + "header with\nthe last frame's milliseconds, the app's memory in KiB and the baseline.");
  w.block("private function drawProfile(dc as Dc) as Void", () => {
    w.line("var stats = System.getSystemStats();");
    w.line(`var loop = (${profileMod.REPS}[0] > 0) ? ${profileMod.MS}[0] * 1000 / ${profileMod.REPS}[0] : 0;`);
    w.line("dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);");
    w.call("dc.drawText", [
      "Layout.PROF_HEAD_X, Layout.PROF_HEAD_Y, Graphics.FONT_XTINY",
      `${profileMod.FRAME} + "ms " + (stats.usedMemory / 1024) + "/" + (stats.totalMemory / 1024) + "K loop " + loop + "us"`,
      "Graphics.TEXT_JUSTIFY_CENTER",
    ]);
    w.line("var h = dc.getFontHeight(Graphics.FONT_XTINY);");
    w.block(`for (var k = 1; k < ${count}; k++)`, () => {
      const conditions = [`${profileMod.REPS}[k] > 0`];
      if (profile.layouts) conditions.push(`(Layout.PROF_LAYOUT[k] == -1 || Layout.PROF_LAYOUT[k] == ${CONFIG_LAYOUT_FIELD})`);
      w.block(`if (${conditions.join(" && ")})`, () => {
        w.line(`var us = ${profileMod.MS}[k] * 1000 / ${profileMod.REPS}[k] - loop;`);
        w.call("dc.drawText", ["Layout.PROF_X[k], Layout.PROF_Y[k] - h, Graphics.FONT_XTINY", '(us > 0 ? us : 0).format("%d")', "Graphics.TEXT_JUSTIFY_CENTER"]);
      });
    });
  });
  w.blank();
}

/** `items` through `emitOne`, each run of one layout inside one `if (_configLayout == N)`. */
function emitLayoutGuarded(w: Writer, face: Face, items: readonly Placed[], emitOne: (p: Placed) => void,
  beforeRun: ((run: Placed[]) => void) | null = null): void {
  let i = 0;
  while (i < items.length) {
    const layout = items[i]!.element.layout;
    const run: Placed[] = [];
    while (i < items.length && items[i]!.element.layout === layout) run.push(items[i++]!);
    const guard = layout === null ? null : `if (${CONFIG_LAYOUT_FIELD} == ${face.layouts.indexOf(layout)})`;
    w.blockIf(guard, () => {
      if (layout !== null && beforeRun !== null) beforeRun(run);
      for (const placed of run) emitOne(placed);
    });
  }
}

/** The reads a frame needs: shared content's at the top, one layout's inside its block (the returned `beforeRun`). */
function emitFrameReads(w: Writer, plan: ReadPlan, items: readonly Placed[], prelude: Map<string, [RingGroup, Placed[]][]>, comment: string,
  aod = false): (run: Placed[]) => void {
  const drawn = (run: readonly Placed[]): Placed[] => {
    const out = [...run];
    for (const placed of run) for (const [, members] of prelude.get(placed.id) ?? []) out.push(...members);
    return out;
  };
  const shared = plan.readersFor(drawn(items.filter((p) => p.element.layout === null)), aod);
  let declared: ReadonlySet<string> = new Set();
  if (shared.length > 0) {
    w.comment(comment);
    declared = plan.emitPulls(w, shared);
    w.blank();
  }
  return (run) => {
    const own = plan.readersFor(drawn(run), aod).filter((r) => !shared.includes(r));
    if (own.length > 0) {
      w.comment("data only this layout draws with");
      plan.emitPulls(w, own, declared);
      w.blank();
    }
  };
}

function drawnIn(resolved: ResolvedFace, mode: string, skip: ReadonlySet<string> = new Set()): Placed[] {
  return frameMembers(resolved.items, mode).filter((p) => !skip.has(p.id));
}

function drawCall(plan: ReadPlan, placed: Placed): string {
  return `${method(placed.id)}(dc${plan.arguments(placed)});`;
}

function emitModeBody(w: Writer, resolved: ResolvedFace, plan: ReadPlan, mode: string, statics: StaticPlan | null, rings: Rings,
  profile: profileMod.ProfilePlan | null): void {
  if (statics !== null && statics.modes.includes(mode)) {
    emitStaticBlit(w);
    w.blank();
  }
  const skip = statics !== null ? statics.ids : new Set<string>();
  const items = drawnIn(resolved, mode, skip);
  const prelude = rings.prelude(items);
  const beforeRun = emitFrameReads(w, plan, items, prelude, "data for this frame");
  if (profile !== null) {
    w.line("var profT0 = System.getTimer();");
    w.comment("the empty loop: the timing overhead every reading includes");
    emitTimed(w, profile, 0, () => undefined, true);
  }
  const one = (placed: Placed): void => {
    if (profile === null) {
      rings.emitBefore(w, plan, prelude, placed);
      w.line(drawCall(plan, placed));
      return;
    }
    for (const [ring, members] of prelude.get(placed.id) ?? []) {
      w.comment(`'${ring.group.id}' outline: every member's ring, then the members`);
      emitTimed(w, profile, profile.index(`${ring.group.id}.ring`), () => { for (const member of members) w.line(rings.calls(plan, ring, member)); });
    }
    emitTimed(w, profile, profile.index(placed.id), () => w.line(drawCall(plan, placed)));
  };
  emitLayoutGuarded(w, resolved.face, items, one, beforeRun);
  if (profile !== null) {
    w.blank();
    w.line(`${profileMod.FRAME} = System.getTimer() - profT0;`);
    w.line("drawProfile(dc);");
    emitProfileAdvance(w, profile);
  }
}

/** Which guard locals the AOD frame has already declared where the next call is. */
class GuardScopes {
  private readonly shared = new Set<string>();
  private layout: string | null = null;
  private block: Set<string> = this.shared;

  declaredFor(layout: string | null): Set<string> {
    if (layout === null) {
      this.layout = null;
      this.block = this.shared;
    } else if (layout !== this.layout) {
      this.layout = layout;
      this.block = new Set(this.shared);
    }
    return this.block;
  }
}

function emitAodBody(w: Writer, resolved: ResolvedFace, plan: ReadPlan, guards: Guards, rings: Rings): void {
  w.comment("research 11 §6 F: the panel is unlit, so there is nothing to draw --");
  w.comment("not even the black clear below, which an off panel could not show anyway");
  let condition = "System.getDisplayMode() == System.DISPLAY_MODE_OFF";
  if (guards.display_mode_guarded) condition = `(System has :getDisplayMode) && (${condition})`;
  w.block(`if (${condition})`, () => w.line("return;"));
  w.blank();
  w.comment("AOD starts from black: Dc keeps its contents between frames,");
  w.comment("and the awake frame's own background does not draw here");
  w.line("dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);");
  w.line("dc.clear();");
  const ids = new Set(plan.aodIds());
  const entries = resolved.items.filter((p) => ids.has(p.id));
  const prelude = rings.prelude(entries);
  const beforeRun = emitFrameReads(w, plan, entries, prelude, "data for this frame", true);
  const scopes = new GuardScopes();
  const one = (placed: Placed): void => {
    const declared = scopes.declaredFor(placed.element.layout);
    rings.emitBefore(w, plan, prelude, placed, (member, line) => emitOneAodCall(w, plan, member, line, declared));
    emitOneAodCall(w, plan, placed, null, declared);
  };
  emitLayoutGuarded(w, resolved.face, entries, one, beforeRun);
  if (resolved.face.aod_mask && entries.length > 0) {
    w.blank();
    w.comment("aod: {mask: ...}: moves the lit pixel every minute");
    w.line("WfbAodMask.apply(dc, System.getClockTime().min);");
  }
}

function emitOneAodCall(w: Writer, plan: ReadPlan, placed: Placed, line: string | null = null, declared: Set<string> | null = null): void {
  const extra = ReadPlan.aodVisibleOverride(placed);
  const condition = plan.aodGuardCondition(placed);
  if (extra !== null) {
    for (const [name, read] of plan.aodGuardDeclarations(placed)) {
      if (declared === null || !declared.has(name)) w.line(`var ${name} = ${read};`);
      if (declared !== null) declared.add(name);
    }
    w.comment(`aod: visible: ${extra.text}`);
  }
  w.blockIf(condition !== null ? `if (${condition})` : null, () => w.line(line ?? drawCall(plan, placed)));
}

function emitOnPartialUpdate(w: Writer, resolved: ResolvedFace, plan: ReadPlan, aaDefault: boolean | null, rings: Rings): void {
  w.doc("Redraw only the `sleep_update: true` elements, once a second, while asleep.\n"
    + "\n"
    + "The clip is the tightest box around them because setClip is charged by\n"
    + "region area (each device's Layout.mc gives its share of the screen).\n"
    + "Overrunning the power budget calls onPowerBudgetExceeded and disables\n"
    + "partial updates for the rest of the app's lifecycle.  Nothing here is\n"
    + "rate-limited by the compiler: any source a `sleep_update: true` element\n"
    + "binds -- weather.* and complication.* included -- is read on every one\n"
    + "of these updates.  The\n"
    + "suppressible partial-update-budget lint is the only thing watching that.");
  w.block("function onPartialUpdate(dc as Dc) as Void", () => {
    w.line("dc.setClip(Layout.LOW_POWER_CLIP_X, Layout.LOW_POWER_CLIP_Y,");
    w.line("           Layout.LOW_POWER_CLIP_WIDTH, Layout.LOW_POWER_CLIP_HEIGHT);");
    if (aaDefault !== null) w.line(`applyAntiAlias(dc, ${mcBool(aaDefault)});`);
    const items = drawnIn(resolved, "low_power");
    const prelude = rings.prelude(items);
    const beforeRun = emitFrameReads(w, plan, items, prelude, "data for this sleep update; every reader is a plain pull");
    emitLayoutGuarded(w, resolved.face, items, (placed) => {
      rings.emitBefore(w, plan, prelude, placed);
      w.line(drawCall(plan, placed));
    }, beforeRun);
    w.line("dc.clearClip();");
  });
  w.blank();
}

function emitSleepHooks(w: Writer, resolved: ResolvedFace, needsSleeping: boolean, aod: boolean, guards: Guards, aodOnly: string[]): void {
  w.doc("Awake: full-power updates resume.");
  w.block("function onExitSleep() as Void", () => {
    if (needsSleeping) w.line("_sleeping = false;");
    if (aod) w.line("_aod = false;");
    for (const name of aodOnly) w.line(`_${aodFontField(name)} = null;`);
    w.line("WatchUi.requestUpdate();");
  });
  w.blank();
  let doc: string;
  if (aod) doc = "Asleep: the next onUpdate draws the resolved 'aod:' set instead of\n'active', if this device requires burn-in protection.";
  else if (needsSleeping) doc = "Asleep: the next onUpdate hides the awake-only second hand.";
  else doc = "Asleep: the next onUpdate draws the low-power layout.";
  w.doc(doc);
  w.block("function onEnterSleep() as Void", () => {
    if (needsSleeping) w.line("_sleeping = true;");
    if (aod) {
      w.line("var settings = System.getDeviceSettings();");
      if (guards.burn_in_field_guarded) w.line(`_aod = (settings has :${Device.BURN_IN_FIELD}) && settings.${Device.BURN_IN_FIELD};`);
      else w.line(`_aod = settings.${Device.BURN_IN_FIELD};`);
      if (aodOnly.length > 0) {
        w.comment("Loaded only now, only when this device actually");
        w.comment("enters the AOD frame -- never sits in memory while awake");
        w.block("if (_aod)", () => {
          for (const name of aodOnly) w.line(`_${aodFontField(name)} = WatchUi.loadResource(Rez.Fonts.${fontResourceId(name)}) as FontResource;`);
        });
      }
    }
    w.line("WatchUi.requestUpdate();");
  });
  w.blank();
  if (hasPartialUpdate(resolved, guards)) {
    w.doc("The power budget was exceeded and partial updates are now off for the\n"
      + "rest of this app's lifecycle.  Nothing can re-enable them; the face\n"
      + "simply falls back to once-a-minute updates.");
    w.block("function onPowerBudgetExceeded(powerInfo as WatchUi.WatchFacePowerInfo) as Void", () => {
      w.line('System.println("wfb: partial-update power budget exceeded: "');
      w.line('               + powerInfo.executionTimeAverage.format("%.2f") + " ms average");');
    });
    w.blank();
  }
}

function emitComplicationCallback(w: Writer): void {
  w.doc("A subscribed complication changed.  Nothing is stored: onUpdate pulls\n"
    + "every complication it needs, so this only asks for an earlier redraw\n"
    + "than the next scheduled one.");
  w.block("function onComplicationChanged(id as Complications.Id) as Void", () => w.line("WatchUi.requestUpdate();"));
  w.blank();
}

/** `draw<Id>`, or with `ringWidth` its `ring<Id>` twin: the reads, then the element's draw program. */
function emitElementMethod(w: Writer, resolved: ResolvedFace, placed: Placed, plan: ReadPlan, aaDefault: boolean | null, aod: AodStyle,
  subscreenGuarded: boolean, ringWidth: number | null = null): void {
  const element = placed.element;
  let signature: string;
  if (ringWidth !== null) {
    w.doc(`\`${element.id}\`'s share of an outlined group's ring: what \`${method(placed.id)}\` draws,\ndilated by ${ringWidth}px in \`ringColor\`, and nothing else.`);
    signature = `private function ${elementRingMethod(placed.id, ringWidth)}(dc as Dc${plan.parameters(placed)}${RING_PARAMETERS}) as Void`;
  } else {
    w.doc(methodDoc(placed));
    signature = `private function ${method(placed.id)}(dc as Dc${plan.parameters(placed)}) as Void`;
  }
  w.block(signature, () => {
    if (subscreenGuarded) {
      w.comment("anchor: subscreen, unsupported: hide -- false on a device without the window");
      w.block(`if (!Layout.${constPrefix(placed.id)}_SHOWN)`, () => w.line("return;"));
      w.blank();
    }
    const declarations = plan.declarations(placed);
    if (declarations.length > 0) {
      w.comment("the values this element is bound to");
      for (const [name, read] of declarations) w.line(`var ${name} = ${read};`);
      w.blank();
    }
    drawProgram.emitBody(w, resolved, placed, plan, aod, ringWidth !== null ? new RingPass("ringColor", ringWidth) : null, aaDefault);
  });
}

function methodDoc(placed: Placed): string {
  const element = placed.element;
  const lines = [`\`${element.id}\` -- ${describe(placed)}.`];
  const bindings = element.expressions().filter((e) => e.sources.length > 0 && e !== element.visible).map((e) => e.shown);
  if (bindings.length > 0) {
    lines.push("");
    lines.push("Bound to " + andList(bindings.map((text) => `\`${text}\``)) + ".");
  }
  if (element.visible !== null) lines.push(`Drawn only when \`${element.visible.shown}\` (absent readings count as hidden).`);
  const policy = (element as unknown as { absent?: string | null }).absent;
  if (policy) {
    const keeps = policy === "hide" && kinds.forPlaced(placed).drawsWhileAbsent(element);
    lines.push(`Absence policy: \`${vocab.absent(element as never)}\`` + (keeps ? " -- the track still draws." : "."));
  }
  if (element.modes.includes("low_power")) lines.push("Redrawn every second while asleep (`sleep_update: true`).");
  return lines.join("\n");
}

