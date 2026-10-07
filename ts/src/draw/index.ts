// The single draw program: each element is lowered once into a list of
// drawing ops, which a printer writes as Monkey C and an evaluator paints on
// the host.
//
// Every kind that draws overrides `ElementKind.lower`. `program` puts the
// element's own guards (`visible:`, absence, `antialias:`) around it.
import * as catalog from "../catalog.ts";
import { AodStyle, type RingPass, shownMask } from "../emit/monkeyc/common.ts";
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
  const paths = pathsByLocal();
  const guard = (names: string[], note: string): void => {
    if (names.length > 0) ops.push(NullGuard(names, names.map((name) => paths.get(name)!), note));
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
  return new DrawContext(renderer.resolved, new AodStyle(true), renderer.valueGuards(placed), ring, { picks: renderer.options.picks });
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
  const ctx = new DrawContext(resolved, aod, guards, ring, { complicationsGuarded: plan.device_guards.complications });
  printOps(w, program(ctx, placed, plan, antialiasDefault), aod);
}
