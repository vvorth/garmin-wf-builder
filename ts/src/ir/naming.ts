// Generated-symbol derivation: how a data source path, an element id or a
// `config:` axis name becomes a Monkey C local, field, method or resource
// id. An element id is its YAML key qualified by its groups' ids with `.`
// (`element_ids.ts`), and `.`, `_` and `-` are all word breaks here, so
// `top.label` gives `drawTopLabel` and `TOP_LABEL`, exactly as `top_label`
// would. Every symbol an id can produce is derived here, so the builder's
// collision check sees them all in one place.

/**
 * The generated local holding one source's value: `activity.step_goal` →
 * `activityStepGoal`; an index is one more word, `weather.daily_forecast[1].condition`
 * → `weatherDailyForecast1Condition`.
 */
export function localName(sourcePath: string): string {
  const parts = sourcePath.replace(/\[(\d+)\]/g, "_$1").replaceAll(".", "_").split("_");
  return parts[0]! + parts.slice(1).map(capitalize).join("");
}

/** Python's `str.capitalize()`: first character upper, the rest lower. */
function capitalize(text: string): string {
  return text.slice(0, 1).toUpperCase() + text.slice(1).toLowerCase();
}

/** The view field a `config:` axis is cached in (`_configAccentColor`). */
export function configField(name: string): string {
  return "_config" + pascal(name);
}

/** `config: data:` slot name to the `<complication id="N">` it is emitted under, 1-based in declaration order. */
export function configDataIds(face: { config_data: ReadonlyMap<string, unknown> }): Map<string, number> {
  return new Map([...face.config_data.keys()].map((name, index) => [name, index + 1]));
}

const isUpper = (c: string): boolean => c !== c.toLowerCase() && c === c.toUpperCase();
const isAlnum = (c: string): boolean => /^[\p{L}\p{N}]$/u.test(c);

/** The layout-constant prefix codegen derives from an element id: `temp_low` and `tempLow` both become `TEMP_LOW`. */
export function elementConstPrefix(elementId: string): string {
  const chars = Array.from(elementId);
  let out = "";
  chars.forEach((char, index) => {
    if (isUpper(char) && index && !isUpper(chars[index - 1]!)) out += "_";
    out += isAlnum(char) ? char.toUpperCase() : "_";
  });
  return out;
}

/** The private draw method codegen derives from an element id (`drawTempLow`). */
export function elementMethodName(elementId: string): string {
  return "draw" + elementSuffix(elementId);
}

/** The method that draws one member's part of an outlined group's ring `width` px wide. */
export function elementRingMethod(elementId: string, width = 1): string {
  const name = "ring" + elementSuffix(elementId);
  return width === 1 ? name : `${name}_${width}`;
}

/**
 * The method that paints one static subtree into the buffer (`paintStaticTicks`; the root a
 * top-level `static:` block becomes gives `paintStatic`). The prefix is not `draw`, so a group
 * `ticks` and the element `static.ticks` (`drawStaticTicks`) never claim one symbol.
 */
export function staticGroupMethod(elementId: string): string {
  const suffix = elementSuffix(elementId);
  return suffix === "Static" ? "paintStatic" : "paintStatic" + suffix;
}

/** The method resolving one `data` element's icon glyph from a `Complications.Type`. */
export function dataIconMethod(elementId: string): string {
  return "iconFor" + elementSuffix(elementId);
}

/** The public method `on_hold: auto` on a `data` element compiles to. */
export function dataHoldMethod(elementId: string): string {
  return "holdTargetFor" + elementSuffix(elementId);
}

export const graphSeriesField = (id: string): string => lowerFirst(elementSuffix(id)) + "Series";
export const graphMinField = (id: string): string => lowerFirst(elementSuffix(id)) + "Min";
export const graphMaxField = (id: string): string => lowerFirst(elementSuffix(id)) + "Max";
export const graphBuiltField = (id: string): string => lowerFirst(elementSuffix(id)) + "BuiltAt";
export const graphTypeField = (id: string): string => lowerFirst(elementSuffix(id)) + "PickedType";
export const graphRebuildMethod = (id: string): string => "rebuild" + elementSuffix(id);

/** The PascalCase stem every element method shares: `top.label` and `temp_low` give `TopLabel` and `TempLow`. */
function elementSuffix(elementId: string): string {
  return elementId.split(/[._-]/).filter(Boolean).map((p) => p.slice(0, 1).toUpperCase() + p.slice(1)).join("");
}

function lowerFirst(text: string): string {
  return text.slice(0, 1).toLowerCase() + text.slice(1);
}

/** Every run of alphanumerics, each with its first character upper-cased. */
export function pascal(text: string): string {
  const cleaned = Array.from(text).map((c) => (isAlnum(c) ? c : " ")).join("");
  return cleaned.split(/\s+/).filter(Boolean).map((w) => w.slice(0, 1).toUpperCase() + w.slice(1)).join("");
}

/** The Monkey C resource id a font named `name` is emitted under. */
export function fontResourceId(name: string): string {
  return `Font${pascal(name)}`;
}

/** The `<string>` resource id of a labelled `config:` choice (`ConfigDataColor0`). */
export function configLabelId(axis: string, index: number): string {
  return `Config${pascal(axis)}${index}`;
}

/** The `<string>` resource id of a labelled style entry (`ConfigStyle0`). */
export function configStyleLabelId(index: number): string {
  return `ConfigStyle${index}`;
}
