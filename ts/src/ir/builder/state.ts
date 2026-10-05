// The semantic pass's shared state and the small helpers every layer of it
// uses: `NamedRegistry` (the declared/accepted/rejected bookkeeping a named
// top-level block keeps), `dedupAppend`, `andPaths` and a node's own `lint:`
// suppression. Port of wfb/ir/builder/state.py.
import type { Bag, Span } from "../../diagnostics.ts";
import type { Data, DataKey } from "../../edit/yaml.ts";
import * as expr from "../../expr.ts";
import type { Color } from "../../palette.ts";
import { deepEqual, repr } from "../../py.ts";
import type { YamlDocument } from "../../yamlsrc.ts";
import type {
  ColorScheme, ConfigColor, ConfigDataSlot, ConfigStyle, Expression, FontSpec, HandSet, LayoutDecl,
} from "../model.ts";

/** A YAML mapping as the builder reads it. */
export type Node = Map<DataKey, Data>;

/** `node` when it is a mapping, else an empty one: Python's `x or {}` over a schema-valid value. */
export function mapping(node: Data | undefined): Node {
  return node instanceof Map ? node : new Map();
}

/** `node` when it is a list, else an empty one: Python's `x or []`. */
export function list(node: Data | undefined): Data[] {
  return Array.isArray(node) ? node : [];
}

/**
 * A named top-level block (`fonts:`, `palette:`, `layouts:`, `theme:
 * schemes:`, `config: slots:`, `hand_sets:`) as it parses: the accepted
 * entries in declaration order, plus every declared name and the rejected
 * ones, so a reference to a declared-then-rejected name stays quiet ("one
 * error, not N", docs/lore/codegen.md).
 */
export class NamedRegistry<T> extends Map<string, T> {
  declared = new Map<string, Span | null>();
  rejected = new Set<string>();

  declare(name: string, span: Span | null): void {
    this.declared.set(name, span);
  }

  reject(name: string): void {
    this.rejected.add(name);
  }

  /** The accepted entry `name`, or `null` after reporting it; nothing is reported for a declared-then-rejected name. */
  resolve(bag: Bag, name: string, span: Span | null,
    { code, message, note, prefix = "" }: { code: string; message: string; note: string; prefix?: string }): T | null {
    if (this.has(name)) return this.get(name)!;
    if (this.rejected.has(name)) return null;
    const known = [...this.declared.keys()].sort().map((n) => `${prefix}${n}`).join(", ") || "(none declared)";
    bag.error(code, message, span, { notes: [`${note}: ${known}`] });
    return null;
  }
}

/** Append `color` unless it is null or already present (by value, as Python's `in` compares). */
export function dedupAppend(colors: Expression[], color: Expression | null): void {
  if (color !== null && !colors.some((c) => deepEqual(c, color))) colors.push(color);
}

export interface LintSuppression {
  lint_allow: Set<string>;
  lint_reason: string | null;
}

/** A node's own `lint: {allow, reason}`. */
export function lintSuppression(node: Node): LintSuppression {
  const lint = mapping(node.get("lint"));
  return {
    lint_allow: new Set(list(lint.get("allow")) as string[]),
    lint_reason: (lint.get("reason") as string | undefined) ?? null,
  };
}

/** `'a'`, `'a' and 'b'`, `'a', 'b' and 'c'`, for a diagnostic. */
export function andPaths(paths: readonly string[]): string {
  const quoted = paths.map(repr);
  if (quoted.length === 1) return quoted[0]!;
  return quoted.slice(0, -1).join(", ") + " and " + quoted[quoted.length - 1];
}

/** Whether a design-relative file exists; the builder asks it for a baked font's `source:`. */
export type FileExists = (path: string) => boolean;

/** Everything the semantic pass accumulates while it walks a document. */
export class BuilderState {
  readonly doc: YamlDocument;
  readonly bag: Bag;
  readonly fileExists: FileExists;
  palette = new NamedRegistry<Color>();
  /** Accepted long-form palette entries' labels, keyed by name. */
  palette_labels = new Map<string, string>();
  fonts = new NamedRegistry<FontSpec>();
  layouts = new NamedRegistry<LayoutDecl>();
  color_scheme = new NamedRegistry<ColorScheme>();
  config_data = new NamedRegistry<ConfigDataSlot>();
  hand_sets = new NamedRegistry<HandSet>();
  /** `accent_color`/`data_color` axes; a rejected axis (or `"style"`) goes in `rejected_config`. */
  config = new Map<string, ConfigColor>();
  rejected_config = new Set<string>();
  config_style: ConfigStyle | null = null;
  /** The scheme roles `color.<role>` may name; `null` means no Styles colours at all. */
  configColorsRoles: string[] | null = null;
  /** Each declared colour axis's role, rejected axes included. */
  config_roles = new Map<string, string>();
  scope = new expr.Scope();
  seen_ids = new Map<string, Span | null>();
  /** Derived Monkey C symbol to the element id and span that claimed it first. */
  seen_symbols = new Map<string, [string, Span | null]>();
  face_antialias = false;
  face_min_1px = false;
  face_aod_default_hide = true;
  face_aod_lint_allow = new Set<string>();
  face_aod_lint_reason: string | null = null;
  /** `null` for both an absent `aod: dim:` and `dim: 1`. */
  face_aod_dim: number | null = null;
  face_aod_mask = true;

  constructor(doc: YamlDocument, bag: Bag, fileExists: FileExists) {
    this.doc = doc;
    this.bag = bag;
    this.fileExists = fileExists;
  }
}
