// The single draw program: each element is lowered once into a list of
// drawing ops, which a printer writes as Monkey C and an evaluator paints on
// the host.
//
// Every kind that draws overrides `ElementKind.lower`. `program` puts the
// element's own guards (`visible:`, absence, `antialias:`) around it.
import * as catalog from "../catalog.ts";
import { AodStyle, type RingPass, shownMask } from "../emit/monkeyc/common.ts";
import { RADIAL_DIRECTION } from "../emit/monkeyc/shapes.ts";
import type { Writer } from "../emit/writer.ts";
import { printOps } from "./printer.ts";
import { ReadPlan } from "../emit/monkeyc/readplan.ts";
import { negated } from "../emit/monkeyc/view.ts";
import { localName } from "../ir/naming.ts";
import * as kinds from "../kinds/index.ts";
import type { Placed, ResolvedFace } from "../layout.ts";
import { truthy } from "../py.ts";
import type { Renderer, RGB } from "../preview.ts";
import * as vocab from "../vocab.ts";
import { Evaluator, strValue, type Values } from "./evaluator.ts";
import { AntiAlias, DrawContext, NullGuard, type Op, VisibleGuard } from "./program.ts";

export { DrawContext } from "./program.ts";
export type { Op } from "./program.ts";

/** `placed`'s own drawing, its kind's `lower`. */
export function lowered(ctx: DrawContext, placed: Placed): Op[] {
  return kinds.forPlaced(placed).lower(ctx, placed);
}

let byLocal: Map<string, string> | null = null;

/** Every catalogue path by its reading local's name. */
function pathsByLocal(): Map<string, string> {
  if (byLocal === null) byLocal = new Map([...catalog.CATALOG.keys()].map((path) => [localName(path), path]));
  return byLocal;
}

/** The catalogue path a reading local holds: a fixed entry's, or an indexed one's (`weatherDailyForecast1Condition`). */
function pathOfLocal(local: string, read: readonly string[]): string {
  return pathsByLocal().get(local) ?? read.find((path) => localName(path) === local)!;
}

/**
 * The whole body of `placed`'s `draw<Id>` (or, with `ctx.ring`, its
 * `ring<Id>`) after its reads: `visible:` first, then the absence guard
 * (none for a data element, whose reading is a fresh pull), then the
 * drawing, an `antialias:` switch bracketing only the drawing.
 */
export function program(ctx: DrawContext, placed: Placed, plan: ReadPlan, antialiasDefault: boolean | null = null): Op[] {
  const element = placed.element;
  const kind = kinds.forPlaced(placed);
  const ops: Op[] = [];
  const visible = element.visible;
  if (visible !== null) {
    const always = visible.constant !== null && truthy(visible.constant);
    ops.push(VisibleGuard(visible, plan.visibleGuards(placed), always ? "" : negated(visible),
      always ? 0 : shownMask(plan.resolved.face, element)));
  }
  if (kind.name === "data") return [...ops, ...lowered(ctx, placed)];
  const read = element.expressions().flatMap((x) => [...x.sources]);
  const guard = (names: string[], note: string): void => {
    if (names.length > 0) ops.push(NullGuard(names, names.map((name) => pathOfLocal(name, read)), note));
  };
  const absent = (element as unknown as Record<string, unknown>)["absent"];
  const substitutes = element.valueRoles.size > 0 && (absent === "placeholder" || absent === "fallback");
  if (substitutes || (kind.drawsWhileAbsent(element) && plan.valueGuards(placed).length > 0)) {
    guard(plan.otherGuards(placed),
      "hide -- a nullable colour/track_color/max always hides the element, regardless of the value's own absent:");
  } else {
    guard(plan.guards(placed), vocab.absent(element as never));
  }
  const toggles = antialiasDefault !== null && kind.antialiased && element.resolved_antialias !== antialiasDefault;
  if (toggles) ops.push(AntiAlias(element.resolved_antialias, true));
  ops.push(...lowered(ctx, placed));
  if (toggles && antialiasDefault !== null) ops.push(AntiAlias(antialiasDefault));
  return ops;
}

/** Paint `placed`'s program, its guards included; with `ring`, its share of an outlined group's ring in `ringColor`. */
export function paint(renderer: Renderer, placed: Placed, ring: RingPass | null = null, ringColor: RGB | null = null): void {
  const ctx = context(renderer, placed, ring);
  new Evaluator(renderer, ringColor).runProgram(program(ctx, placed, renderer.readPlan));
}

/** How the host lowers `placed`: with always-on code present, the face's own dimming, and the view's value guards. */
export function context(renderer: Renderer, placed: Placed, ring: RingPass | null = null): DrawContext {
  return new DrawContext(renderer.resolved, new AodStyle(true), renderer.valueGuards(placed), ring, {
    picks: renderer.options.picks, dataSample: renderer.options.data_sample,
  });
}

/** The string `placed` (a text-drawing element) draws at `values`, without painting it; `null` when it draws none. */
export function drawnText(resolved: ResolvedFace, placed: Placed, values: Values, { aod = false } = {}): string | null {
  const ctx = new DrawContext(resolved, new AodStyle(true), new ReadPlan(resolved).valueGuards(placed));
  const ops = lowered(ctx, placed);
  const env = new Map<string, unknown>();
  const walk = (body: readonly Op[]): [boolean, string | null] => {
    for (const op of body) {
      if (op.t === "LetText") {
        const value = strValue(op.value, values, env, aod);
        env.set(op.name, value !== null ? value : strValue(op.initial, values, env, aod));
      } else if (op.t === "Text") {
        return [true, strValue(op.text, values, env, aod)];
      } else if (op.t === "IfNotNull") {
        const found = walk(op.body);
        if (found[0]) return found;
      } else if (op.t === "IfAod") {
        const found = walk(aod ? op.then : op.otherwise);
        if (found[0]) return found;
      } else if (op.t === "IfAwake" && !aod) {
        const found = walk(op.body);
        if (found[0]) return found;
      }
    }
    return [false, null];
  };
  return walk(ops)[1];
}

/** The printed `draw<Id>` body (or a `ring<Id>` pass), after its reads. */
export function emitBody(w: Writer, resolved: ResolvedFace, placed: Placed, plan: ReadPlan, aod: AodStyle,
  ring: RingPass | null = null, antialiasDefault: boolean | null = null): void {
  const guards = kinds.forPlaced(placed).name === "data" ? [] : plan.valueGuards(placed);
  const ctx = new DrawContext(resolved, aod, guards, ring, {
    complicationsGuarded: plan.device_guards.complications, gatedTypes: plan.device_guards.gated_types,
  });
  const ops = program(ctx, placed, plan, antialiasDefault);
  printOps(w, plan.device_guards.curved_text_level ? guardCurvedText(ops) : ops, aod);
}

/**
 * `ops` with each curved draw's `has` checks on the font null check around
 * it. Since SDK 9.3.0 `monkeyc` refuses `dc.drawRadialText` (and the
 * direction constant, and `drawAngledText`) on a target whose API level
 * predates them unless a `has` check naming each encloses the use, even
 * where the draw can never run (docs/lore/platform-constraints.md, 6d).
 * Every curved draw is in a `face:` font, so inside that null check.
 */
function guardCurvedText(ops: readonly Op[], within: string[] | null = null): Op[] {
  return ops.map((op): Op => {
    if (op.t === "Text" && op.style !== null && !op.joined) {
      if (within === null) throw new Error("a curved draw outside its font's null check");
      const checks = op.style === "angled" ? ["(dc has :drawAngledText)"]
        : ["(dc has :drawRadialText)", `(Graphics has :${RADIAL_DIRECTION[op.direction ?? "clockwise"]})`];
      for (const check of checks) if (!within.includes(check)) within.push(check);
      return op;
    }
    if (op.t === "IfNotNull") {
      const has: string[] = [];
      const body = guardCurvedText(op.body, has);
      return has.length > 0 ? { ...op, body, has } : { ...op, body };
    }
    const nested: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(op)) {
      if (Array.isArray(value) && value.length > 0 && typeof value[0] === "object" && value[0] !== null && "t" in value[0]) {
        nested[key] = guardCurvedText(value as Op[], within);
      }
    }
    return Object.keys(nested).length > 0 ? { ...op, ...nested } as Op : op;
  });
}
