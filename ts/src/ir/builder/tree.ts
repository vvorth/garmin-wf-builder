// The element tree: one node to one `Element` through its kind
// (`kinds/`), ids and derived symbols, `overrides:` and `on_hold:`
// targets.
import * as catalog from "../../catalog.ts";
import * as complications from "../../complications.ts";
import type { Span } from "../../diagnostics.ts";
import type { Data, DataKey } from "../../edit/yaml.ts";
import type { Common, SchemaPath } from "../../kinds/base.ts";
import * as kinds from "../../kinds/index.ts";
import { SHAPE_GEOMETRY_KEYS } from "../../kinds/shape.ts";
import { repr, str, truthy } from "../../py.ts";
import { DataElement, type Element, HOLD_AUTO, type Position, ROLE_VALUE, Shape } from "../model.ts";
import { elementConstPrefix, elementMethodName } from "../naming.ts";
import { ringGroups } from "../rings.ts";
import type { Builder } from "./index.ts";
import { lintSuppression, mapping, type Node } from "./state.ts";
import { StaticPass } from "./static.ts";

/** The keys an `overrides:` patch may carry. */
const OVERRIDE_FIELDS = ["at", "size", "radius", "align"];

/** Kinds whose `align:` is a `TEXT_JUSTIFY_*` flag in the shared view, so no override may change it. */
const GLYPH_KINDS = new Set(["text", "icon", "data"]);

/** The key `Element.overrides` holds one `[shape, device]` selector pair under: Python's `str` of the pair as a list. */
export function overrideKey(shape: string | null, device: string | null): string {
  return repr([shape, device]);
}

/** `patch` deep-merged over `base`: mappings key by key, anything else replaced. */
function merged(base: Node, patch: Node): Node {
  const out: Node = new Map(base);
  for (const [key, value] of patch) {
    const existing = out.get(key);
    out.set(key, value instanceof Map && existing instanceof Map ? merged(existing, value) : value);
  }
  return out;
}

/** The `type:` the author wrote for `element`. */
function kindName(element: Element): string {
  return element instanceof Shape ? element.shape : element.kind;
}

/** Whether this element's own `align:` places it. */
function takesAlign(element: Element): boolean {
  if (element instanceof Shape) return SHAPE_GEOMETRY_KEYS.get(element.shape)?.has("align") ?? false;
  return ["group", "gauge", "graph"].includes(element.kind);
}

/** Builds the element tree, dispatching each node to its kind. */
export class ElementTree extends StaticPass {
  /** Build every element of an `elements:`/`children:` list, dropping any that reported an error. */
  buildElements(raw: Data[], path: SchemaPath): Element[] {
    const out: Element[] = [];
    raw.forEach((node, index) => {
      const element = this.buildElement(node as Node, [...path, index]);
      if (element !== null) out.push(element);
    });
    return out;
  }

  private buildElement(node: Node, path: SchemaPath): Element | null {
    const span = this.doc.spanForPath([...path] as DataKey[]);
    const elementId = node.get("id") as string;
    if (this.seen_ids.has(elementId)) {
      const first = this.seen_ids.get(elementId);
      this.bag.error("duplicate-id", `duplicate element id ${repr(elementId)}`, this.doc.span(node, "id"),
        { notes: first ? [`first declared at ${first}`] : [] });
      return null;
    }
    this.seen_ids.set(elementId, span);
    if (!this.checkSymbolCollision(elementId, node, span)) return null;
    const [aodOwnHide, aodOwn] = this.buildAodAuthored(node);
    const at = this.position(node.get("at"), node, "at", { allowSubscreen: true });
    if (!this.checkSubscreen(node, at, path, span)) return null;
    const sleepUpdate = (node.get("sleep_update") ?? null) as boolean | null;
    const lint = lintSuppression(node);
    const onHold = this.holdTarget(node);
    const visible = this.visibleOf(node);
    const common: Common = {
      id: elementId,
      kind: kinds.kindOf(node),
      at,
      modes: sleepUpdate === true ? ["active", "low_power"] : ["active"],
      sleep_update: sleepUpdate,
      z: (node.get("z") ?? null) as number | null,
      span,
      ...lint,
      on_hold: onHold,
      visible,
      static: truthy(node.get("static") ?? false),
      antialias: node.has("antialias") ? truthy(node.get("antialias")) : null,
      min_1px: node.has("min_1px") ? truthy(node.get("min_1px")) : null,
      aod_own_hide: aodOwnHide,
      aod_own: aodOwn,
      unsupported: (node.get("unsupported") ?? null) as string | null,
    };
    if (!kinds.names().includes(common.kind)) { // unreachable once the schema has run
      this.bag.error("element", `unsupported element type ${repr(node.get("type"))}`, span);
      return null;
    }
    const element = kinds.get(common.kind).build(this as unknown as Builder, node, common, path);
    if (element !== null && truthy(node.get("overrides"))) {
      if (!this.buildOverrides(node, element)) return null;
    }
    if (element !== null) {
      this.resolveHoldAuto(element);
      if (node.has("outline") && element.outline === null && element.kind !== "text") {
        // `text` builds its own ring, alongside `curve:`; the schema decides which other kinds accept one.
        element.outline = this.buildOutline(node, "outline", elementId, element);
      }
      const refusal = kinds.get(element.kind).ringRefusal(element);
      if (element.outline !== null && refusal !== null) {
        this.bag.error("outline", `${elementId}: 'outline:' ${refusal}`, this.doc.span(node, "outline", "key") ?? span,
          { notes: ["not implemented yet -- docs/limitations.md §2"] });
        return null;
      }
    }
    return element;
  }

  // -- overrides --------------------------------------------------------------

  /** `overrides:`: each selector's patch checked, then merged and parsed once per `[shape, device]` pair. */
  private buildOverrides(node: Node, element: Element): boolean {
    const raw = node.get("overrides") as Node;
    const shapes = new Map<string, Node>();
    const devices = new Map<string, Node>();
    const selectors: [string, Span | null][] = [];
    let ok = true;
    for (const [rawSelector, patch] of raw) {
      const selector = str(rawSelector);
      selectors.push([selector, this.doc.span(raw, selector, "key") ?? this.doc.span(raw, selector)]);
      if (selector.startsWith("shape:")) shapes.set(selector.slice("shape:".length), patch as Node);
      else devices.set(selector, patch as Node);
      ok = this.checkOverridePatch(node, element, selector, patch as Node) && ok;
    }
    element.override_selectors = selectors;
    if (!ok) return false;
    const combos: [string | null, string | null][] = [
      ...[...shapes.keys()].map((shape): [string, null] => [shape, null]),
      ...[...devices.keys()].map((device): [null, string] => [null, device]),
      ...[...shapes.keys()].flatMap((shape) => [...devices.keys()].map((device): [string, string] => [shape, device])),
    ];
    for (const [shape, device] of combos) {
      const patches = [shapes.get(shape ?? ""), devices.get(device ?? "")].filter((p): p is Node => p !== undefined);
      element.overrides.set(overrideKey(shape, device), this.overrideFields(node, element, patches));
    }
    return true;
  }

  /** One selector's patch: only keys this element writes (or takes), and every value valid. */
  private checkOverridePatch(node: Node, element: Element, selector: string, patch: Node): boolean {
    const label = `${element.id}.overrides.${selector}`;
    const errorsBefore = this.bag.errors.length;
    for (const key of patch.keys() as Iterable<string>) {
      const span = this.doc.span(patch, key, "key") ?? this.doc.span(patch, key);
      if (key === "align") {
        if (GLYPH_KINDS.has(element.kind)) {
          this.bag.error("overrides", `${label}: 'align:' on a ${kindName(element)} is the draw call's `
            + "justification, which every target shares", span, { notes: ["move it with 'at:' instead"] });
        } else if (!takesAlign(element)) {
          this.bag.error("overrides", `${label}: a ${kindName(element)} takes no 'align:'`, span);
        }
      } else if (key === "size" || key === "radius") {
        if (!node.has(key)) {
          this.bag.error("overrides", `${label}: '${key}:' is not a key this element writes`, span, {
            notes: ["an override changes the element's own geometry; it cannot add a key the element does not have"],
          });
        } else if (key === "size") {
          this.size(patch.get("size"));
        } else {
          this.length(patch, "radius");
        }
      } else if (key === "at") {
        const at = patch.get("at");
        const base = mapping(node.get("at"));
        const mergedAnchor = at instanceof Map ? (at.has("anchor") ? at.get("anchor") : base.get("anchor")) : null;
        if ((mergedAnchor === "subscreen") !== (base.get("anchor") === "subscreen")) {
          this.bag.error("overrides", `${label}: an override cannot move an element into or out of the subscreen window`, span);
        } else if (at instanceof Map) {
          this.position(merged(base, at), patch, "at", { allowSubscreen: mergedAnchor === "subscreen" });
        }
      }
    }
    return this.bag.errors.length === errorsBefore;
  }

  /** The element's geometry fields with `patches` merged over its own keys in order. */
  private overrideFields(node: Node, element: Element, patches: Node[]): Map<string, unknown> {
    let own: Node = new Map(OVERRIDE_FIELDS.filter((key) => node.has(key)).map((key) => [key, node.get(key)!]));
    for (const patch of patches) {
      if (patch.has("align")) own.delete("align");
      own = merged(own, patch);
    }
    const touched = new Set(patches.flatMap((patch) => [...patch.keys()]));
    const fields = new Map<string, unknown>();
    if (touched.has("at")) fields.set("at", this.position(own.get("at"), own, "at", { allowSubscreen: element.inSubscreen }));
    if (touched.has("size")) fields.set("size", this.size(own.get("size")));
    if (touched.has("radius")) fields.set("radius", this.length(own, "radius"));
    if (touched.has("align")) {
      const [align, verticalAlign] = this.alignment(own);
      fields.set("align", align);
      fields.set("vertical_align", verticalAlign);
    }
    return fields;
  }

  /** What an outlined `group` needs of its members: a ring each can draw, and a colour that reads no data. */
  checkGroupOutlines(elements: Element[]): void {
    for (const ring of ringGroups(elements)) {
      const group = ring.group;
      const span = group.span;
      for (const [leaf] of ring.members) {
        const kind = kinds.get(leaf.kind);
        const refusal = kind.ringRefusal(leaf);
        if (refusal !== null && kind.ringed) {
          this.bag.error("outline", `${group.id}: 'outline:' on a group needs every member to draw a `
            + `ring, and ${repr(leaf.id)} cannot: 'outline:' ${refusal}`, leaf.span ?? span,
          { notes: ["not implemented yet -- docs/limitations.md §2"] });
        } else if (!kind.ringed) {
          this.bag.error("outline", `${group.id}: 'outline:' on a group needs every member to draw a `
            + `ring, and ${repr(leaf.id)} is a '${leaf.kind}', which cannot yet`, leaf.span ?? span, {
            notes: ["text, icons, shapes, hands, patterns and gauges can be "
              + "ringed; move this element out of the group, or drop the group's 'outline:'"],
          });
        }
      }
      if (group.outline!.color.sources.length > 0) {
        this.bag.error("outline", `${group.id}: a group's 'outline.color' cannot read data `
          + `(${group.outline!.color.sources.join(", ")})`, span,
        { notes: ["use a palette, scheme or config colour, or a literal"] });
      }
    }
  }

  /** `anchor: subscreen` is a top-level element's alone, and `unsupported:` needs something that can be unavailable. */
  private checkSubscreen(node: Node, at: Position, path: SchemaPath, span: Span | null): boolean {
    const inSubscreen = at.anchor === "subscreen";
    if (inSubscreen && path.includes("children")) {
      this.bag.error("subscreen", `${str(node.get("id"))}: 'anchor: subscreen' is not accepted on a group's child`,
        this.doc.span(node.get("at"), "anchor") ?? span, {
          notes: ["put 'anchor: subscreen' on the top-level group instead: its "
            + "children are then laid out inside the window"],
        });
      return false;
    }
    if (node.has("unsupported") && !inSubscreen && node.get("type") !== "text") {
      this.bag.error("subscreen", `${str(node.get("id"))}: 'unsupported:' is not accepted here`,
        this.doc.span(node, "unsupported") ?? span, {
          notes: ["on this element it governs 'at: {anchor: subscreen}' on a target "
            + "without a subscreen window; this element is not anchored there",
          "drop 'unsupported:', or anchor the element to the subscreen"],
        });
      return false;
    }
    return true;
  }

  /** Reject two distinct ids that derive the same Monkey C symbol. */
  private checkSymbolCollision(elementId: string, node: Node, span: Span | null): boolean {
    const nodeKind = kinds.kindOf(node);
    const extraSymbols = kinds.names().includes(nodeKind) ? kinds.get(nodeKind).extraSymbols : [];
    const candidates = [elementConstPrefix(elementId), elementMethodName(elementId), ...extraSymbols.map((derive) => derive(elementId))];
    const collisions: [string, string, Span | null][] = [];
    for (const symbol of candidates) {
      const claimed = this.seen_symbols.get(symbol);
      if (claimed !== undefined && claimed[0] !== elementId) collisions.push([symbol, claimed[0], claimed[1]]);
    }
    if (collisions.length > 0) {
      const [, otherId, otherSpan] = collisions[0]!;
      const symbols = collisions.map(([symbol]) => repr(symbol)).join(", ");
      const notes = ["element ids only need to be distinct as literal strings today, "
        + "but codegen derives one Monkey C symbol per id, folding case and "
        + "separators away -- 'temp_low' and 'tempLow' both become 'TEMP_LOW'"];
      if (otherSpan !== null) notes.unshift(`${repr(otherId)} first declared at ${otherSpan}`);
      this.bag.error("duplicate-id", `element id ${repr(elementId)} generates the same Monkey C symbol as `
        + `${repr(otherId)} (${symbols})`, this.doc.span(node, "id") ?? span, { notes });
      return false;
    }
    for (const symbol of candidates) this.seen_symbols.set(symbol, [elementId, span]);
    return true;
  }

  /** `on_hold:` against the launchable complication table; `auto` passes through unresolved. */
  private holdTarget(node: Node): string | null {
    const raw = node.get("on_hold");
    if (raw === undefined || raw === null) return null;
    const name = str(raw);
    if (name === HOLD_AUTO) return HOLD_AUTO;
    if (complications.get(name) !== undefined) return name;
    this.bag.error("on-hold", `unknown hold target ${repr(name)}`, this.doc.span(node, "on_hold"),
      { notes: this.complicationSuggestionNotes(name, "launch targets") });
    return null;
  }

  /** Resolve `on_hold: auto` once the element is fully built; a `data` element keeps it for the device. */
  private resolveHoldAuto(element: Element): void {
    if (element instanceof DataElement) return;
    if (element.on_hold === HOLD_AUTO) {
      element.on_hold = this.resolveAutoTarget(element.id, "on_hold", ElementTree.holdAutoSources(element), element.span);
    }
  }

  /** The catalogue paths `on_hold: auto` may resolve from: the first `ROLE_VALUE` expression's sources. */
  private static holdAutoSources(element: Element): readonly string[] {
    for (const [role, expression] of element.boundExpressions()) if (role === ROLE_VALUE) return expression.sources;
    return [];
  }

  /** Resolve `auto` to exactly one complication type, or report why not. */
  private resolveAutoTarget(label: string, key: string, sources: readonly string[], span: Span | null): string | null {
    const found = new Map<string, string>();
    for (const path of sources) {
      const target = catalog.get(path)?.launch_complication ?? null;
      if (target !== null && !found.has(target)) found.set(target, path);
    }
    if (found.size === 1) return found.keys().next().value!;
    const bound = sources.length > 0 ? sources.map(repr).join(", ") : "(none)";
    if (found.size === 0) {
      this.bag.error("hold-auto-unresolved", `${label}: '${key}: auto' could not resolve a hold target -- bound source(s): ${bound}`,
        span, {
          notes: [
            "none of this element's bound source(s) has a conventional "
            + "complication counterpart (a catalogue source's launch_complication)",
            "name a target explicitly instead of 'auto' -- run `wfb complications` for the full list",
          ],
        });
      return null;
    }
    const candidates = [...found.keys()].sort().map(repr).join(", ");
    this.bag.error("hold-auto-ambiguous", `${label}: 'auto' is ambiguous between ${candidates} -- bound source(s): ${bound}`, span,
      { notes: ["name one explicitly instead of 'auto' -- run `wfb complications` for the full list"] });
    return null;
  }
}
