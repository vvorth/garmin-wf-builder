// The always-on display: the face-wide `aod:` defaults, each node's own
// `aod:` (`hide`/`show`/an override block), and resolution down the tree
// (element > nearest ancestor group > face default)..
import * as kinds from "../../kinds/index.ts";
import type { Refusal } from "../../kinds/base.ts";
import { isNumber, num, repr, str, truthy } from "../../py.ts";
import * as template from "../../template.ts";
import type { Length } from "../../units.ts";
import { AodOverride, type Element, type Expression, Outline, Shape, Text } from "../model.ts";
import { HandParts } from "./hands.ts";
import { lintSuppression, type Node } from "./state.ts";

/** An element's own resolved `aod:` keys, in the order they were read. */
export type AodKeys = Map<string, unknown>;

/** `[kind, shape, literalText]` of a built element, in the terms `aodRefusal` reads off a raw node. */
function aodKind(element: Element): [string, string | null, boolean] {
  const kind = kinds.forElement(element);
  const shape = element instanceof Shape ? element.shape : null;
  const literalText = element instanceof Text && element.value === null;
  return [kind.name, shape, literalText];
}

/** `aod:` reading and resolution. */
export class AodPass extends HandParts {
  /** Top-level `aod:` (`dim:`, `mask:`) and `defaults: {aod:}`. */
  buildFaceAod(raw: Node, defaultValue: unknown): void {
    this.face_aod_default_hide = ((defaultValue as string | null | undefined) || "hide") === "hide";
    const lint = lintSuppression(raw);
    this.face_aod_lint_allow = lint.lint_allow;
    this.face_aod_lint_reason = lint.lint_reason;
    const dimRaw = raw.get("dim");
    // `dim: 1` means no dimming, exactly like no `dim:`.
    const dim = dimRaw === undefined || dimRaw === null ? null : isNumber(dimRaw) ? num(dimRaw) : Number(dimRaw);
    this.face_aod_dim = dim === null || dim === 1.0 ? null : dim;
    this.face_aod_mask = truthy(raw.has("mask") ? raw.get("mask") : true);
  }

  /** `[code, what, notes]` when an `aod:` override's `key` cannot apply to an element of this kind. */
  aodRefusal(key: string, kind: string | null, shape: string | null, literalText: boolean): Refusal | null {
    if (kind === null || !kinds.names().includes(kind)) return null;
    return kinds.get(kind).aodRefusal(key, shape, literalText);
  }

  /** One element's or group's own `aod:` as `[hide, keys]`. */
  buildAodAuthored(node: Node): [boolean, AodKeys | null] {
    const raw = node.get("aod");
    if (raw === undefined || raw === null) return [false, null];
    if (raw === "hide") return [true, null];
    if (raw === "show") return [false, new Map()];
    const block = raw as Node;
    const elementId = str(node.get("id") ?? "?");
    const keys: AodKeys = new Map();
    for (const key of ["color", "track_color"]) {
      if (block.has(key)) keys.set(key, this.colorExpression(block, key));
    }
    const icon = block.get("icon");
    if (icon instanceof Map && icon.has("color")) keys.set("icon", this.colorExpression(icon, "color"));
    for (const key of ["thickness", "bar_width"]) {
      if (block.has(key)) keys.set(key, this.length(block, key));
    }
    const kind = kinds.kindOf(node), shape = kinds.shapeOf(node);
    if (block.has("filled")) {
      const refusal = this.aodRefusal("filled", kind, shape, false);
      if (refusal !== null) {
        const [code, what, notes] = refusal;
        this.bag.error(code, `${elementId}: ${what}`, this.doc.span(block, "filled") ?? this.doc.span(node, "aod"), { notes });
      } else {
        keys.set("filled", truthy(block.get("filled")));
      }
    }
    if (block.has("font")) {
      const refusal = this.aodRefusal("font", kind, shape, false);
      if (refusal !== null) {
        const [code, what, notes] = refusal;
        this.bag.error(code, `${elementId}: ${what}`, this.doc.span(block, "font") ?? this.doc.span(node, "aod"), { notes });
      } else {
        const resolved = this.fontReference(str(block.get("font")), this.doc.span(block, "font"));
        if (resolved !== null && this.isVectorFont(...resolved)) {
          this.bag.error("aod", `${elementId}: an 'aod: {font: ...}' override naming a 'face:' (vector) font is not implemented yet`,
            this.doc.span(block, "font"), {
              notes: [`${repr(resolved[0])} is declared with 'face:', not 'source:' `
                + "-- name a baked font instead, or drop the override for now"],
            });
        } else if (resolved !== null) {
          keys.set("font", resolved);
        }
      }
    }
    const text = block.get("text");
    if (typeof text === "string") {
      // Kept as the restyle's format string; `lower` has reported a malformed template.
      try {
        keys.set("text", template.aodFormat(text));
      } catch (error) {
        if (!(error instanceof template.TemplateError)) throw error;
      }
    }
    if (block.has("outline")) {
      // Same grammar, colour machinery and width cap as the element's own; `none` is kept.
      const outline = this.buildOutline(block, "outline", `${elementId}.aod`);
      if (outline !== null || block.get("outline") === "none") keys.set("outline", outline !== null ? outline : "none");
    }
    if (block.has("visible")) keys.set("visible", this.visibleOf(block));
    return [false, keys];
  }

  /** The `AodOverride` a drawn element gets from its fully resolved `keys`. */
  private makeAodOverride(element: Element, keys: AodKeys): AodOverride {
    const font = (keys.get("font") ?? null) as [string, boolean] | null;
    const [fontName, fontIsCustom] = font !== null ? font : [null, false];
    const ownVisible = (keys.get("visible") ?? null) as Expression | null;
    const outline = keys.get("outline");
    const pick = <T>(key: string): T | null => (keys.get(key) ?? null) as T | null;
    return AodOverride.create({
      outline: outline instanceof Outline ? outline : null,
      outline_none: outline === "none",
      color: pick<Expression>("color"),
      track_color: pick<Expression>("track_color"),
      icon_color: pick<Expression>("icon"),
      thickness: pick<Length>("thickness"),
      bar_width: pick<Length>("bar_width"),
      filled: pick<boolean>("filled"),
      font: fontName,
      font_is_custom: fontIsCustom,
      format: pick<string>("text"),
      visible: this.conjoinVisible(element.visible, ownVisible),
      visible_override: ownVisible,
    });
  }

  /** Resolve `aod:` over the whole tree: element over nearest ancestor group over the face default. */
  resolveAod(elements: Element[]): void {
    const visit = (items: Element[], forcedHidden: boolean, nearest: AodKeys | null, nearestFrom: Element | null): void => {
      for (const element of items) {
        element.aod_ancestor_hidden = forcedHidden;
        const ownHide = element.aod_own_hide;
        const own = element.aod_own as AodKeys | null;
        let hidden: boolean;
        if (forcedHidden || ownHide) hidden = true;
        else if (own !== null || nearest !== null) hidden = false;
        else hidden = this.face_aod_default_hide;
        const childForcedHidden = forcedHidden || ownHide;
        const childNearest = own !== null ? own : nearest;
        const childNearestFrom = own !== null ? element : nearestFrom;
        if (hidden) {
          element.aod = null;
        } else {
          const effective: AodKeys = new Map(nearest ?? []);
          if (nearestFrom !== null) this.refuseInheritedAodKeys(element, effective, own, nearestFrom);
          if (own !== null) for (const [k, v] of own) effective.set(k, v);
          element.aod = this.makeAodOverride(element, effective);
          const fmt = effective.get("text");
          if (fmt !== undefined && fmt !== null && element instanceof Text && element.value !== null
            && !(own !== null && own.has("text"))) {
            // Inherited from a group, so only checkable here.
            if (element.more.length > 0) {
              this.bag.error("format", `${element.id}: the inherited 'aod: {text:}' restyles one `
                + "reading, and this text has several -- restyling it is not implemented yet", element.span,
              { notes: ["docs/limitations.md, \"Not implemented yet\""] });
            } else {
              this.checkFormatSpec(element.value, str(fmt), element.span);
            }
          }
        }
        visit(element.children(), childForcedHidden, childNearest, childNearestFrom);
      }
    };
    visit(elements, false, null, null);
  }

  /** Report, and drop from `inherited`, every key `group`'s `aod:` passed down that `element` cannot take. */
  private refuseInheritedAodKeys(element: Element, inherited: AodKeys, own: AodKeys | null, group: Element): void {
    const [kind, shape, literal] = aodKind(element);
    for (const key of [...inherited.keys()].sort()) {
      if (own !== null && own.has(key)) continue;
      const refusal = this.aodRefusal(key, kind, shape, literal);
      if (refusal === null) continue;
      const [code, what, notes] = refusal;
      const where = group.span !== null ? `line ${group.span.line}` : "its own 'aod:'";
      this.bag.error(code, `${element.id}: ${what}, inherited from group ${repr(group.id)}`, element.span, {
        notes: [`group ${repr(group.id)} sets 'aod: {${key}: ...}' (${where}) for every element below it`, ...notes,
          `move the group's '${key}' onto the elements that can take it`],
      });
      inherited.delete(key);
    }
  }

  /** Resolve an inherited default, root to leaf, into `Element.resolved_<key>`. */
  resolveInheritedFlag(elements: Element[], key: "antialias" | "min_1px" | "z" | "sleep_update", defaultValue: unknown): void {
    const resolved = `resolved_${key}`;
    const visit = (items: Element[], inherited: unknown): void => {
      for (const element of items) {
        const record = element as unknown as Record<string, unknown>;
        const authored = record[key];
        const value = authored !== null && authored !== undefined ? authored : inherited;
        record[resolved] = value;
        visit(element.children(), value);
      }
    };
    visit(elements, defaultValue);
  }

  /** The group keys a member inherits that later stages read: `z:`, `sleep_update:` and `lint: allow`. */
  resolveGroupKeys(elements: Element[]): void {
    this.resolveInheritedFlag(elements, "z", 0);
    this.resolveInheritedFlag(elements, "sleep_update", false);
    const visit = (items: Element[], allow: Set<string>, sleeper: Element | null): void => {
      for (const element of items) {
        element.inherited_lint_allow = allow;
        element.modes = element.resolved_sleep_update ? ["active", "low_power"] : ["active"];
        const source = element.sleep_update ? element : element.sleep_update === null ? sleeper : null;
        if (element.sleep_update === null && element.resolved_sleep_update
          && (element.kind === "hands" || element.kind === "pattern") && sleeper !== null) {
          this.bag.error(element.kind, `${element.id}: inherits 'sleep_update: true' from group `
            + `${repr(sleeper.id)}, which a '${element.kind}' does not accept`, element.span, {
            notes: [`write 'sleep_update: false' on ${repr(element.id)} to keep it out of the partial update`],
          });
        }
        visit(element.children(), new Set([...allow, ...element.lint_allow]), source);
      }
    };
    visit(elements, new Set(), null);
  }
}
