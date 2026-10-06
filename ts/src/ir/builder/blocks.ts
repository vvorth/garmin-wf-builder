// The named top-level blocks other than `fonts:` and `config:`:
// `layouts:`, `palette:` and `theme: schemes:`, and the expression scope
// every block binds.
import * as catalog from "../../catalog.ts";
import { layoutIds } from "../../desugar.ts";
import type { Span } from "../../diagnostics.ts";
import type { Data } from "../../edit/yaml.ts";
import * as expr from "../../expr.ts";
import { Color, ColorError } from "../../palette.ts";
import { repr } from "../../py.ts";
import { ColorScheme, DataElement, type Element, LayoutDecl, slotOf, walkElements } from "../model.ts";
import { configField, localName } from "../naming.ts";
import { FontBlock } from "./fonts.ts";
import { lintSuppression, type Node } from "./state.ts";

/** Builds `layouts:`, `palette:` and `theme: schemes:`, then the scope expressions resolve against. */
export class TopLevelBlocks extends FontBlock {
  /** `layouts:`: post-desugar each body is `{}` or `{lint: ...}`, so this records the names and their `lint:`. */
  buildLayouts(raw: Node): void {
    for (const [name, spec] of raw as Map<string, Node>) {
      const span = this.doc.span(raw, name);
      this.layouts.declare(name, span);
      this.layouts.set(name, LayoutDecl.create({ name, ...lintSuppression(spec), span }));
    }
  }

  /** Stamp `Element.layout` on each layout's synthetic groups and their descendants, then apply the slot rule. */
  assignLayouts(elements: Element[]): void {
    if (this.layouts.size > 0) {
      const byId = new Map(elements.map((e) => [e.id, e]));
      for (const decl of this.layouts.values()) {
        for (const generatedId of layoutIds(decl.name)) {
          const group = byId.get(generatedId);
          if (group === undefined) continue;
          for (const element of walkElements([group])) element.layout = decl.name;
        }
      }
    }
    for (const element of walkElements(elements)) {
      if (slotOf(element) !== null && element.layout !== null) {
        const what = element instanceof DataElement ? "a 'type: data' element" : "a gauge with 'slot:'";
        this.bag.error("layouts", `${repr(element.id)}: ${what} may not be inside layout ${repr(element.layout)} content`,
          element.span, {
            notes: [
              "the Data axis is face-wide -- one <complication "
              + "id=...> however many layouts read it -- so a slot "
              + "belongs in the shared top-level 'elements:', not "
              + "inside a 'layouts:' body",
              "docs/guide/styles-and-layouts.md",
            ],
          });
      }
    }
  }

  /** `layouts:` with no `config: style:` naming one is an error: nothing lets the wearer pick it. */
  checkLayoutsReachable(data: Node): void {
    if (this.layouts.size === 0) return;
    if (this.config_style !== null || this.rejected_config.has("style")) return;
    this.bag.error("layouts", "layouts: is declared, but no 'config: style:' entry ever names "
      + "one as its 'layout:' -- nothing lets the wearer pick it", this.doc.span(data, "layouts", "key"), {
      notes: ["declared layouts: " + [...this.layouts.keys()].join(", "),
        "add a 'config: style:' block with an entry naming one, or remove 'layouts:'"],
    });
  }

  /** `palette:`: named colours, short (`name: "#RRGGBB"`) or long (`{value, label}`). */
  buildPalette(raw: Node): void {
    for (const [name, value] of raw as Map<string, Data>) {
      const span = this.doc.span(raw, name);
      this.palette.declare(name, span);
      let rawValue: Data | undefined, valueSpan: Span | null, label: Data | undefined;
      if (value instanceof Map) {
        rawValue = value.get("value");
        valueSpan = this.doc.span(value, "value") ?? span;
        label = value.get("label");
      } else {
        rawValue = value;
        valueSpan = span;
        label = undefined;
      }
      if (typeof rawValue === "string" && rawValue.startsWith("color.")) {
        this.bag.error("palette", `palette entry ${repr(name)} refers to ${repr(rawValue)}`, valueSpan, {
          notes: [
            "palette entries must be literal colours",
            "name the role directly from 'color:'/'track_color:' instead -- "
            + "e.g. 'color: color.accent' -- rather than through a palette entry",
          ],
        });
        this.palette.reject(name);
        continue;
      }
      try {
        this.palette.set(name, Color.parse(rawValue ?? null, `color.${name}`));
      } catch (error) {
        if (!(error instanceof ColorError)) throw error;
        this.bag.error("palette", error.message, valueSpan);
        this.palette.reject(name);
        continue;
      }
      if (label !== undefined && label !== null) this.palette_labels.set(name, label as string);
    }
  }

  /** A `color.<swatch>` reference where a build-time literal colour is required. */
  paletteReference(name: string, span: Span | null): Color | null {
    const key = name.slice("color.".length);
    return this.palette.resolve(this.bag, key, span,
      { code: "config", message: `unknown palette entry ${repr(name)}`, note: "declared palette entries", prefix: "color." });
  }

  /** A `config:` `default:`/`choices:` colour: a literal hex, or a `color.<swatch>` reference. */
  resolveConfigColor(raw: Data | undefined, what: string, span: Span | null): Color | null {
    if (typeof raw === "string" && raw.startsWith("color.")) return this.paletteReference(raw, span);
    try {
      return Color.parse(raw ?? null, what);
    } catch (error) {
      if (!(error instanceof ColorError)) throw error;
      this.bag.error("config", error.message, span);
      return null;
    }
  }

  /** `theme: schemes:`: named role-to-colour sets; every accepted scheme must declare the same roles. */
  buildColorScheme(raw: Node): void {
    const roleSets = new Map<string, Map<string, Color>>();
    for (const [name, spec] of raw as Map<string, Node>) {
      const span = this.doc.span(raw, name);
      this.color_scheme.declare(name, span);
      const label = (spec.get("label") ?? null) as string | null;
      const rawColors = spec.get("colors") as Node;
      const colors = new Map<string, Color>();
      let ok = true;
      for (const role of rawColors.keys() as Iterable<string>) {
        const roleSpan = this.doc.span(rawColors, role);
        const color = this.resolveConfigColor(rawColors.get(role), `theme.schemes.${name}.colors.${role}`, roleSpan);
        if (color === null) {
          ok = false;
          continue;
        }
        colors.set(role, color);
      }
      if (!ok) {
        this.color_scheme.reject(name);
        continue;
      }
      this.color_scheme.set(name, ColorScheme.create({ name, label, colors, span }));
      roleSets.set(name, colors);
    }
    if (roleSets.size < 2) return;
    const union = new Set<string>();
    for (const colors of roleSets.values()) for (const role of colors.keys()) union.add(role);
    for (const [name, colors] of roleSets) {
      const missing = [...union].filter((r) => !colors.has(r));
      if (missing.length === 0) continue;
      this.bag.error("color-scheme", `theme.schemes.${name}: missing role(s) ${missing.sort().join(", ")} -- every scheme must declare the `
        + "same roles", this.color_scheme.get(name)!.span, {
        notes: [
          `theme.schemes.${name} declares: ` + ([...colors.keys()].sort().join(", ") || "(none)"),
          "otherwise 'color.<role>' would be undefined whenever the wearer picks the scheme that lacks it",
        ],
      });
      this.color_scheme.reject(name);
      this.color_scheme.delete(name);
    }
  }

  /** A bare scheme name from a `config: style:` entry's `scheme:`. */
  schemeReference(name: string, span: Span | null): string | null {
    const scheme = this.color_scheme.resolve(this.bag, name, span,
      { code: "config", message: `unknown color scheme ${repr(name)}`, note: "declared schemes (theme: schemes:)" });
    return scheme !== null ? name : null;
  }

  /** A bare layout name from a `config: style:` entry's `layout:`. */
  layoutReference(name: string, span: Span | null): string | null {
    const decl = this.layouts.resolve(this.bag, name, span,
      { code: "config", message: `unknown layout ${repr(name)}`, note: "declared layouts" });
    return decl !== null ? name : null;
  }

  /** Bind `color.<name>` to its swatch's constant (0 for a declared-then-rejected one). */
  private definePaletteColor(name: string, constant: number): void {
    this.scope.define(`color.${name}`, { value: new expr.Value("color"), code: `Palette.${name.toUpperCase()}`, constant });
  }

  /** Bind a config colour path to the view field it reads back from; never folded, as the wearer can change it. */
  private defineConfigColor(path: string, code: string): void {
    this.scope.define(path, { value: new expr.Value("color"), code, constant: null });
  }

  /** Populate the expression scope: catalogue sources, palette, config. */
  buildScope(): void {
    for (const [path, source] of catalog.CATALOG) {
      this.scope.define(path, { value: new expr.Value(source.type, catalog.guardNeeded(source)), code: localName(path) });
    }
    for (const [name, color] of this.palette) this.definePaletteColor(name, color.value);
    // Declared-then-rejected entries and axes are bound too: one error, not N.
    for (const name of [...this.palette.rejected].sort()) this.definePaletteColor(name, 0);
    for (const entry of this.config.values()) this.defineConfigColor(`color.${entry.role}`, entry.field);
    for (const name of [...this.rejected_config].filter((n) => n !== "style").sort()) {
      this.defineConfigColor(`color.${this.config_roles.get(name)}`, configField(name));
    }
    // A scheme's roles: one binding per role of the default style entry's scheme.
    if (this.config_style !== null && this.config_style.defaultEntry.colors !== null) {
      const defaultScheme = this.color_scheme.get(this.config_style.defaultEntry.colors)!;
      this.configColorsRoles = [...defaultScheme.colors.keys()].sort();
      for (const role of defaultScheme.colors.keys()) this.defineConfigColor(`color.${role}`, configField(`colors_${role}`));
    } else if (this.rejected_config.has("style")) {
      const roles = new Set<string>();
      for (const scheme of this.color_scheme.values()) for (const role of scheme.colors.keys()) roles.add(role);
      if (roles.size > 0) {
        this.configColorsRoles = [...roles].sort();
        for (const role of this.configColorsRoles) this.defineConfigColor(`color.${role}`, configField(`colors_${role}`));
      }
    }
    this.scope.used.clear();
  }
}
