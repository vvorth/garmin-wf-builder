// The semantic pass (ADR 0008 stage 2): `Builder` walks a validated,
// lowered and desugared YAML document and produces a `Face`, resolving
// data sources against the catalogue, type-checking and compiling
// expressions, and requiring null handling wherever the platform makes
// absence normal. Port of wfb/ir/builder/.
//
// `Builder` is one class built from layers, one module each, every layer
// extending the one below it, so a layer calls only what sits beneath:
//
//     state       shared state, `NamedRegistry`, `dedupAppend`, `andPaths`
//     reading     one key of a node: expressions, colours, lengths, fonts
//     absence     `absent:` and `format:`
//     glyphs      icons, `outline:`, `curve:`, `unsupported:`
//     visibility  `visible:` and the enclosing groups' conditions
//     fonts       the `fonts:` block
//     blocks      `layouts:`, `palette:`, `theme: schemes:` and the scope
//     config      the `config:` axes
//     hands       `hand_sets:`, and the parts a hand and a pattern share
//     aod         `aod:`, read and resolved down the tree
//     static      `static:` subtrees
//     tree        the element tree, one node at a time through `kinds/`
//     (here)      `Builder.build`, the entry point
//
// Nothing here knows a screen size: per-device work is layout's.
import type { Bag } from "../../diagnostics.ts";
import { isNumber, num, str, truthy } from "../../py.ts";
import type { YamlDocument } from "../../yamlsrc.ts";
import { Face } from "../model.ts";
import { pascal } from "../naming.ts";
import { type FileExists, list, mapping, type Node } from "./state.ts";
import { ElementTree } from "./tree.ts";

export { ABSENCE_IS_NORMAL } from "./absence.ts";
export { CURVE_STYLE_KEYS, ICON_SIZE_NOTE } from "./glyphs.ts";
export {
  HAND_PART_FILLED_SHAPES, HAND_PART_GEOMETRY_KEYS, HAND_PART_NO_UNFILLED, HAND_PART_REJECTED_SHAPES,
  PATTERN_PART_GEOMETRY_KEYS, PATTERN_PART_REJECTED_SHAPES,
} from "./hands.ts";
export { andPaths, dedupAppend, NamedRegistry, type FileExists } from "./state.ts";
export { overrideKey } from "./tree.ts";

/** The semantic pass: a schema-valid document in, a `Face` out, every mistake reported on the author's own line. */
export class Builder extends ElementTree {
  build(): Face | null {
    const data = this.doc.data as Node;
    const defaults = mapping(data.get("defaults"));
    const resources = mapping(data.get("resources"));
    this.face_antialias = truthy(defaults.get("antialias") ?? false);
    this.face_min_1px = truthy(defaults.get("min_1px") ?? false);
    this.buildFaceAod(mapping(data.get("aod")), defaults.get("aod") ?? null);
    // Layouts first: a `config: style:` entry's `layout:` resolves against them.
    this.buildLayouts(mapping(data.get("layouts")));
    this.buildPalette(mapping(resources.get("palette")));
    this.buildColorScheme(mapping(mapping(data.get("theme")).get("schemes")));
    this.buildConfig(mapping(data.get("config")));
    this.checkLayoutsReachable(data);
    this.buildFonts(mapping(resources.get("fonts")));
    this.buildScope();
    // Hands need the scope (a hand's `color:` reads `color.*`), and come
    // before the elements so `type: hands` resolves against them.
    this.buildHands(mapping(resources.get("hand_sets")));

    const elements = this.buildElements(list(data.get("elements")), ["elements"]);
    if (!this.bag.ok()) return null;
    this.resolveGroupKeys(elements);
    if (!this.bag.ok()) return null;
    // Before `applyStatic`: a slot inside a layout's own `static:` gets the layout error alone.
    this.assignLayouts(elements);
    if (!this.bag.ok()) return null;
    this.applyStatic(elements);
    if (!this.bag.ok()) return null;
    this.checkGroupOutlines(elements);
    if (!this.bag.ok()) return null;
    this.resolveInheritedFlag(elements, "antialias", this.face_antialias);
    this.resolveInheritedFlag(elements, "min_1px", this.face_min_1px);
    this.resolveAod(elements);
    // `resolveAod` can add an error (an inherited `aod: {text:}` checked against a descendant's value).
    if (!this.bag.ok()) return null;

    const face = data.get("face") as Node;
    const name = face.get("name") as string;
    const format = data.get("format");
    return Face.create({
      format: isNumber(format) ? Math.trunc(num(format)) : Number(format),
      uuid: face.get("id") as string,
      name,
      version: (face.has("version") ? face.get("version") : "1.0.0") as string,
      entry: str(face.get("entry") || pascal(name) || "WatchFace"),
      targets: [...(mapping(data.get("build")).get("targets") as string[])],
      palette: new Map(this.palette),
      palette_labels: new Map(this.palette_labels),
      fonts: new Map(this.fonts),
      elements,
      source_path: this.doc.path,
      antialias: this.face_antialias,
      min_1px: this.face_min_1px,
      config: this.config,
      color_scheme: new Map(this.color_scheme),
      scheme_roles_used: new Set([...this.scope.used].filter((p) => p.startsWith("color.")).map((p) => p.slice(6))),
      layouts: [...this.layouts.keys()],
      layout_decls: new Map(this.layouts),
      config_style: this.config_style,
      config_data: new Map(this.config_data),
      hands: new Map(this.hand_sets),
      aod_default_hide: this.face_aod_default_hide,
      aod_lint_allow: this.face_aod_lint_allow,
      aod_lint_reason: this.face_aod_lint_reason,
      aod_dim: this.face_aod_dim,
      aod_mask: this.face_aod_mask,
    });
  }
}

/** Build the IR of a desugared document; `fileExists` answers for a baked font's `source:`. */
export function build(doc: YamlDocument, bag: Bag, fileExists: FileExists): Face | null {
  return new Builder(doc, bag, fileExists).build();
}
