// The per-element-kind interface and its registry. Port of the build half
// of wfb/kinds/__init__.py; the stages after the IR (layout, draw, emit,
// lint) add their methods as they are ported.
//
// Every element kind is one `ElementKind` subclass in its own module, which
// registers an instance here (`register`). `./index.ts` imports all nine,
// in schema order, so importing it fills the registry.
import type { Data, DataKey } from "../edit/yaml.ts";
import type { Builder } from "../ir/builder/index.ts";
import type { Element, Face } from "../ir/model.ts";
import { ringGroups } from "../ir/rings.ts";
import type { Placed, Resolver } from "../layout.ts";
import type { Box } from "../units.ts";

/** Kind names, in schema order. */
export const NAMES = ["group", "shape", "text", "gauge", "icon", "graph", "data", "hands", "pattern"] as const;

/** The `type:`s one kind, `shape`, draws. */
export const PRIMITIVES: readonly string[] = ["rectangle", "circle", "line", "arc", "ellipse", "polygon"];

type Node = Map<DataKey, Data>;

/** The kind that builds an element node: its `type:`, except that every primitive is the `shape` kind's. */
export function kindOf(node: Node): string {
  const written = node.get("type");
  return PRIMITIVES.includes(written as string) ? "shape" : (written as string);
}

/** A primitive's shape, its `type:`; `null` for any other kind. */
export function shapeOf(node: Node): string | null {
  const written = node.get("type");
  return PRIMITIVES.includes(written as string) ? (written as string) : null;
}

/** `[code, what, notes]` when an `aod:` override key cannot apply to a kind. */
export type Refusal = [string, string, string[]];

/** The fields every kind shares, which `Builder` reads off the node before the kind builds the rest. */
export type Common = Pick<Element, "id" | "kind" | "at" | "modes" | "sleep_update" | "z" | "span" | "lint_allow"
  | "lint_reason" | "on_hold" | "visible" | "static" | "antialias" | "min_1px" | "aod_own_hide" | "aod_own" | "unsupported">;

/** A schema path: keys and list indices. */
export type SchemaPath = readonly (string | number)[];

/** One element kind's behaviour; every method has a default meaning "nothing to do here". */
export abstract class ElementKind<E extends Element = Element> {
  /** The schema's own discriminator (`type: <name>`). */
  abstract readonly name: string;
  /** The IR class this kind builds. */
  abstract readonly irClass: abstract new () => E;
  /** Extra Monkey C symbols this kind's generated code may own, reserved per id. */
  readonly extraSymbols: readonly ((id: string) => string)[] = [];
  /** `[phrase, note]` when this kind can never be `static:`. */
  readonly staticForbidden: readonly [string, string] | null = null;
  /** Draws primitives, so `antialias:` reaches it as a runtime `Dc.setAntiAlias`. */
  readonly antialiased: boolean = false;
  /** Draws an `outline:` ring. */
  readonly ringed: boolean = false;

  /** Why this element, of a `ringed` kind, cannot draw an `outline:` ring yet, or `null`. */
  ringRefusal(_element: E): string | null {
    return null;
  }

  /** Build the IR element from a schema-valid node; `path` is its schema path. */
  abstract build(b: Builder, node: Node, common: Common, path: SchemaPath): Element | null;

  /** `[code, what, notes]` when an `aod:` override's `key` cannot apply to this kind. */
  aodRefusal(_key: string, _shape: string | null, _literalText: boolean): Refusal | null {
    return null;
  }

  // -- layout --

  /** Resolve one element for one device, inside its parent's box. */
  resolve(_r: Resolver, _element: E, _parent: Box, _depth: number): Placed {
    throw new Error(`${this.name}: resolve`);
  }

  /** Why this device does not draw `placed` at all, or `null` when it draws. */
  hiddenReason(_placed: Placed): string | null {
    return null;
  }

  /** `[cx, cy, radius]` for a genuinely round element, else `null`. */
  circularExtent(_placed: Placed): [number, number, number] | null {
    return null;
  }
}

/**
 * Every width `element` draws a ring at, in first-seen order: its own
 * `outline:`, a text's `aod: {outline:}`, and its share of each outlined
 * group it sits in.
 */
export function ringWidths(element: Element, face: Face): number[] {
  const out: number[] = [];
  const rings = [element.outline];
  if (element.kind === "text" && element.aod !== null) rings.push(element.aod.outline);
  for (const outline of rings) if (outline !== null && !out.includes(outline.width)) out.push(outline.width);
  for (const ring of ringGroups(face.elements)) {
    if (ring.ids.has(element.id)) {
      const width = ring.widthOf(element.id);
      if (!out.includes(width)) out.push(width);
    }
  }
  return out;
}

const BY_NAME = new Map<string, ElementKind>();
const BY_CLASS = new Map<Function, ElementKind>();

export function register<E extends Element>(kind: ElementKind<E>): void {
  BY_NAME.set(kind.name, kind as unknown as ElementKind);
  BY_CLASS.set(kind.irClass, kind as unknown as ElementKind);
}

export function get(name: string): ElementKind {
  const kind = BY_NAME.get(name);
  if (kind === undefined) throw new Error(`no element kind ${name}`);
  return kind;
}

export function forElement(element: Element): ElementKind {
  const kind = BY_CLASS.get(element.constructor);
  if (kind === undefined) throw new Error(`no element kind for ${element.constructor.name}`);
  return kind;
}

export function names(): readonly string[] {
  return NAMES;
}
