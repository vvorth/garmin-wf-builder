// Stage 1 validation: the JSON Schema, reported against the YAML source.
//
//
// jsonschema reports failures against an instance path. The YAML document
// carries spans for every node, so the two are joined here and the author
// sees a file/line/column pointing at their own text (ADR 0002), never at
// an internal representation.
//
// `oneOf` over the element types would otherwise produce one useless error
// per branch. `narrow` picks the branch the author clearly meant (the one
// whose `type` discriminator matched) and reports only its errors.
//
// The `check*` functions are friendly pre-checks: each catches one mistake
// the schema already refuses (a removed or renamed value, a unit a boxless
// frame cannot measure, a key that belongs to the other style) and says
// why, then returns the paths it accounted for so `validate` drops the
// schema's own, blunter error there. The schema stays normative; a
// pre-check only supplies the reason. A returned path is as narrow as the
// schema error allows, so an unrelated mistake on the same element is still
// reported ("one error, not N").
import type { Bag } from "./diagnostics.ts";
import { type Data, type DataKey, PyFloat, Timestamp } from "./edit/yaml.ts";
import { type Schema, ValidationError, Validator } from "./jsonschema.ts";
import { compareStrings, quoted } from "./py.ts";
import type { YamlDocument } from "./yamlsrc.ts";

export const SUPPORTED_FORMATS = [2] as const;

type Step = string | number;
type Path = Step[];
type Dict = Map<DataKey, Data>;

let schemaJson: Record<string, unknown> | undefined;
let validator: Validator | undefined;

/** The published schema (`schema/wfb-face-2.schema.json`), handed in as parsed JSON so this module runs in the browser too. */
export function loadSchema(schema: Record<string, unknown>): void {
  schemaJson = schema;
  validator = new Validator(schema);
  elementTypes = undefined;
}

export function schema(): Record<string, unknown> {
  if (schemaJson === undefined) throw new Error("the schema is not loaded: call loadSchema first");
  return schemaJson;
}

const isDict = (x: unknown): x is Dict => x instanceof Map;

/** ADR 0009: refuse an unknown format outright rather than parsing part of it. */
export function checkFormatVersion(doc: YamlDocument, bag: Bag): boolean {
  if (!isDict(doc.data)) {
    bag.error("schema", "the document must be a mapping", doc.span(doc.data));
    return false;
  }
  if (!doc.data.has("format")) {
    bag.error("schema", "the document has no 'format:' key", doc.span(doc.data),
      { notes: [`add 'format: ${SUPPORTED_FORMATS[SUPPORTED_FORMATS.length - 1]}' at the top of the file`] });
    return false;
  }
  const declared = doc.data.get("format");
  const value = declared instanceof PyFloat ? declared.value : declared;
  // Python's `declared == 1` holds for True too.
  if (value === 1 || value === true) {
    bag.error("format-version", "this file is format 1, which this compiler no longer reads",
      doc.span(doc.data, "format"),
      { notes: ["change it to 'format: 2': each format 1 key is then reported with its format 2 replacement, to rewrite by hand"] });
    return false;
  }
  if (!(typeof value === "number" && (SUPPORTED_FORMATS as readonly number[]).includes(value))) {
    bag.error("format-version", `this file declares format ${quoted(declared)}, which this compiler does not understand`,
      doc.span(doc.data, "format"), { notes: [`supported format versions: ${SUPPORTED_FORMATS.join(", ")}`] });
    return false;
  }
  return true;
}

/** Run the schema. `true` when the document is structurally sound. */
export function validate(doc: YamlDocument, bag: Bag): boolean {
  if (!checkFormatVersion(doc, bag)) return false;
  const before = bag.errors.length;
  // An unknown element `type:` makes every oneOf branch fail for the same
  // uninformative reason, so it is caught first and named directly.
  const badTypes = [
    ...checkElementTypes(doc, bag), ...checkHandFrame(doc, bag), ...checkPatternFrame(doc, bag),
    ...checkHandsPatternAlignment(doc, bag), ...checkReserved(doc, bag),
  ];
  if (validator === undefined) schema();
  const errors = validator!.iterErrors(doc.data);
  const order = errors.map((e, i) => [e.absolutePath, i] as const)
    .sort((a, b) => comparePaths(a[0], b[0]) || a[1] - b[1]).map(([, i]) => errors[i]!);
  for (const error of order) {
    // Checked per narrowed (leaf) error: a violation nested inside the
    // element `oneOf` only gets its full path once `narrow` has picked the
    // branch the author meant.
    for (const narrowed of narrow(error)) {
      if (badTypes.some((prefix) => under(narrowed.absolutePath, prefix))) continue;
      // `checkHandsPatternAlignment` returns no prefix (an
      // `additionalProperties` failure bundles every unexpected key of an
      // object into one error), so its one schema error is narrowed here.
      let kept = dropPivotAlignmentKeys(narrowed);
      if (kept !== null) kept = dropReservedKeys(kept, badTypes);
      if (kept === null) continue;
      report(doc, bag, kept);
    }
  }
  return bag.errors.length === before;
}

/** Python's comparison of two lists of path steps (strings and ints). */
function comparePaths(a: Path, b: Path): number {
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    const x = a[i]!, y = b[i]!;
    if (x === y) continue;
    if (typeof x === "number" && typeof y === "number") return x - y;
    if (typeof x === "string" && typeof y === "string") return compareStrings(x, y);
    throw new TypeError("'<' not supported between instances of 'str' and 'int'");
  }
  return a.length - b.length;
}

let elementTypes: string[] | undefined;

/** The element types the format understands, read from the schema's own discriminated `element` `oneOf`, in its order. */
export function ELEMENT_TYPES(): string[] {
  if (elementTypes !== undefined) return elementTypes;
  const defs = schema()["$defs"] as Record<string, Record<string, unknown>>;
  elementTypes = (defs["element"]!["oneOf"] as { $ref: string }[]).map((ref) => {
    const name = ref.$ref.slice(ref.$ref.lastIndexOf("/") + 1);
    return ((defs[name]!["properties"] as Record<string, Record<string, string>>)["type"]!["const"])!;
  });
  return elementTypes;
}

/** Names authors reach for that belong to another element type, or to another format entirely. */
export const ELEMENT_ALIASES: ReadonlyMap<string, string> = new Map([
  ["shape", "type: rectangle      # or circle, line, arc, ellipse, polygon"],
  ["rounded_rectangle", "type: rectangle\n    corner_radius: 3%r"],
  ["triangle", "type: polygon"],
  ["progress", "type: gauge"],
  ["ring", "type: gauge\n    style: arc"],
  ["bar", "type: gauge\n    style: bar"],
  ["progress_bar", "type: gauge\n    style: bar"],
  ["complication_slot", "type: data"],
  ["complication", "type: data"],
  ["slot", "type: data"],
  ["label", "type: text"],
  ["string", "type: text"],
  ["digital_clock", "type: text\n    text: \"{time.clock:%H:%M}\""],
  ["clock", "type: text\n    text: \"{time.clock:%H:%M}\""],
  ["time", "type: text\n    text: \"{time.clock:%H:%M}\""],
  ["hand", "type: hands\n    set: <name>      # a name declared under 'resources: hand_sets:'"],
  ["analog", "type: hands\n    set: <name>      # a name declared under 'resources: hand_sets:'"],
  ["analog_clock", "type: hands\n    set: <name>      # a name declared under 'resources: hand_sets:'"],
]);

/** Element types this format does not have yet, so the message can say so. */
export const ELEMENT_NOT_YET: ReadonlyMap<string, string> = new Map([
  ["image", "images are not implemented yet"],
  ["bitmap", "images are not implemented yet"],
  ["raw", "the `raw` escape hatch is not implemented yet (ADR 0007)"],
]);

/**
 * Call `visit(element, path)` for every element mapping in the document,
 * recursing into each one's `children:` unless `visit` returns `true`. The
 * element blocks are mappings keyed by id.
 */
function visitElements(doc: YamlDocument, visit: (element: Dict, path: Path) => boolean | void): void {
  const walk = (elements: unknown, path: Path): void => {
    if (!isDict(elements)) return;
    for (const [index, element] of elements) {
      if (!isDict(element)) continue;
      const here = [...path, index as Step];
      if (!visit(element, here)) walk(element.get("children"), [...here, "children"]);
    }
  };
  const data = doc.data as Dict;
  for (const block of ["static", "elements"]) walk(data.get(block), [block]);
  const layouts = data.get("layouts");
  if (isDict(layouts)) {
    for (const [name, body] of layouts) {
      if (isDict(body)) for (const block of ["static", "elements"]) walk(body.get(block), ["layouts", name as Step, block]);
    }
  }
}

function checkElementTypes(doc: YamlDocument, bag: Bag): Path[] {
  const bad: Path[] = [];
  const types = ELEMENT_TYPES();
  visitElements(doc, (element, here) => {
    if (checkProgressStyleKeys(doc, bag, element) || checkHandsSecondsAlways(doc, bag, element)) {
      bad.push(here);
      return true;
    }
    const kind = element.get("type");
    if (typeof kind === "string" && !types.includes(kind)) {
      const notes: string[] = [];
      const alias = ELEMENT_ALIASES.get(kind);
      const pending = ELEMENT_NOT_YET.get(kind);
      if (alias) notes.push(`write it as:\n    ${alias}`);
      else if (pending) notes.push(pending);
      notes.push("this format has: " + types.join(", "));
      bag.error("schema", `unknown element type ${quoted(kind)}`, doc.span(element, "type"), { notes });
      bad.push(here);
    }
    return false;
  });
  return bad;
}

/** The keys each gauge style draws with. */
const PROGRESS_STYLE_KEYS: ReadonlyMap<string, readonly string[]> = new Map([
  ["arc", ["radius", "thickness", "start_angle", "sweep"]],
  ["bar", ["size"]],
  ["needle", ["start_angle", "sweep", "needle"]],
]);

const PROGRESS_STYLE_SHAPES: ReadonlyMap<string, string> = new Map([
  ["arc", "a stroked ring -- radius, thickness, start_angle, sweep"],
  ["bar", "a rectangle -- size"],
  ["needle", "a gauge needle turned about at: -- start_angle, sweep, needle"],
]);

/** A gauge whose keys belong to another style. `true` when it reported an error for this element. */
function checkProgressStyleKeys(doc: YamlDocument, bag: Bag, element: Dict): boolean {
  if (element.get("type") !== "gauge") return false;
  const style = element.get("style");
  if (typeof style !== "string" || !PROGRESS_STYLE_KEYS.has(style)) return false;
  const own = new Set(PROGRESS_STYLE_KEYS.get(style));
  const others = new Map<string, string>();
  for (const [other, keys] of PROGRESS_STYLE_KEYS) {
    if (other === style) continue;
    for (const key of keys) if (!own.has(key)) others.set(key, other);
  }
  const wrong = [...others.keys()].filter((key) => element.has(key));
  if (wrong.length === 0) return false;
  const missing = PROGRESS_STYLE_KEYS.get(style)!.filter((key) => !element.has(key));
  if (missing.length === 0) return false;
  const plural = wrong.length > 1 ? "s" : "";
  const candidates = [...new Set(wrong.map((key) => others.get(key)!))];
  bag.error("schema",
    `this ${String(element.get("type"))} element is 'style: ${style}' but carries ` +
    `${candidates.join("/")}-only key${plural}: ${wrong.map(quoted).join(", ")}`,
    doc.span(element, "style"),
    {
      notes: [
        `either set 'style: ${candidates.join(" or ")}', or replace those with ${PROGRESS_STYLE_KEYS.get(style)!.map(quoted).join(", ")}`,
        [...PROGRESS_STYLE_SHAPES].map(([name, shape]) => `'${name}' is ${shape}`).join("; "),
      ],
    });
  return true;
}

const RESERVED_ELEMENT_KEYS: ReadonlyMap<string, string> = new Map([
  ["effects", "'effects:' (a drop shadow and the like) is reserved and not implemented yet"],
  ["use", "components ('use:'/'with:', declared under 'resources: components:') are reserved and not implemented yet"],
  ["with", "components ('use:'/'with:', declared under 'resources: components:') are reserved and not implemented yet"],
]);
const RESERVED_DATA_KEYS: ReadonlyMap<string, string> = new Map(["parts", "arrange", "requires", "fallback"].map((key) => [key,
  "a data element's own parts ('parts:', 'arrange:', 'requires:', 'fallback:') are reserved and not implemented yet"]));
const RESERVED_NOTE = "docs/limitations.md, \"Not implemented yet\"";

/** Format 2's reserved vocabulary: each key a friendly "not implemented yet" error, never a generic unknown key. */
function checkReserved(doc: YamlDocument, bag: Bag): Path[] {
  const bad: Path[] = [];
  const report = (container: Dict, key: string, message: string, path: Path, ...notes: string[]): void => {
    bag.error("reserved", `${dottedPath(path)}: ${message}`, doc.span(container, key, "key"), { notes: [...notes, RESERVED_NOTE] });
    bad.push(path);
  };
  const resources = (doc.data as Dict).get("resources");
  if (isDict(resources) && resources.has("components")) {
    report(resources, "components", "components are reserved and not implemented yet", ["resources", "components"]);
  }
  const ruleList = (value: unknown): boolean => Array.isArray(value) && value.length > 0
    && value.every((item) => isDict(item) && (item.has("when") || item.has("else")));
  const parts = (element: Dict, key: string, here: Path, pattern: boolean): void => {
    const items = element.get(key);
    if (!Array.isArray(items)) return;
    items.forEach((part, index) => {
      if (!isDict(part) || !part.has("outline")) return;
      if (pattern && part.get("type") === "text") return;
      report(part, "outline", "'outline:' on a hand, needle or pattern part other than text is reserved and not implemented yet",
        [...here, key, index, "outline"], "a text part of a pattern takes 'outline:' today");
    });
  };
  visitElements(doc, (element, here) => {
    for (const [key, message] of RESERVED_ELEMENT_KEYS) if (element.has(key)) report(element, key, message, [...here, key]);
    if (element.get("type") === "data") {
      for (const [key, message] of RESERVED_DATA_KEYS) if (element.has(key)) report(element, key, message, [...here, key]);
    }
    for (const [key, value] of element) {
      if (ruleList(value)) {
        report(element, key as string, "'when:' rule lists are reserved and not implemented yet", [...here, key as Step],
          "for now, write the choice as one expression: \"cond ? a : b\"");
      }
    }
    if (element.get("type") === "gauge") parts(element, "needle", here, false);
    if (element.get("type") === "pattern") parts(element, "parts", here, true);
  });
  const sets = isDict(resources) ? resources.get("hand_sets") : undefined;
  if (isDict(sets)) {
    for (const [setName, spec] of sets) {
      if (!isDict(spec)) continue;
      for (const [handName, hand] of spec) {
        if (isDict(hand)) parts(hand, "parts", ["resources", "hand_sets", setName as Step, handName as Step], false);
      }
    }
  }
  return bad;
}

/** `seconds: always` is not implemented; say why. */
function checkHandsSecondsAlways(doc: YamlDocument, bag: Bag, element: Dict): boolean {
  if (element.get("type") !== "hands" || element.get("seconds") !== "always") return false;
  bag.error("schema",
    "'seconds: always' is not implemented yet -- a second hand while asleep needs a full-frame buffer and a moving " +
    "onPartialUpdate clip, a different buffer architecture from 'static:'s paint-once one",
    doc.span(element, "seconds"),
    { notes: ["see docs/limitations.md, \"Not implemented yet\"",
      "'seconds: awake' (the default -- drawn while awake, hidden asleep) or 'seconds: never' are implemented"] });
  return true;
}

const HAND_PART_LENGTHS = ["radius", "thickness"];
const HAND_PART_POSITIONS = ["at", "to"];
const HAND_POSITION_LENGTHS = ["dx", "dy", "radius"];

/** `%` or `pt` when `value` is a length string in one of those units. */
function handUnit(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  if (text.endsWith("%r") || text.endsWith("px")) return null;
  if (text.endsWith("%")) return "%";
  if (text.endsWith("pt")) return "pt";
  return null;
}

/** `hands.a.minute.parts[0].radius`: a jsonschema-style path as an author reads it. */
export function dottedPath(path: readonly Step[]): string {
  let out = "";
  for (const part of path) {
    if (typeof part === "number") out += `[${part}]`;
    else if (out) out += `.${part}`;
    else out += part;
  }
  return out;
}

function* partsOf(element: Dict): Generator<[number, Dict]> {
  const parts = element.get("parts");
  if (Array.isArray(parts)) {
    for (let i = 0; i < parts.length; i++) if (isDict(parts[i])) yield [i, parts[i] as Dict];
  }
}

interface Frame {
  noun: string;
  origin: string;
  lengthNote: string;
  anchorNote: string;
  unitRefusals: Record<string, string>;
}

const HAND_FRAME: Frame = {
  noun: "hand part", origin: "the hand's axis",
  lengthNote: "every coordinate in a hand is measured from its axis; %r (the screen's minor radius) scales it with the dial",
  anchorNote: "the axis is the element's own 'at:'; inside a hand, {dx, dy} or {angle, radius} are offsets from it",
  unitRefusals: { "%": "a hand frame has no parent box for '%' to measure against", pt: "a hand has no font for 'pt' to measure against" },
};
const PATTERN_FRAME: Frame = {
  noun: "pattern part", origin: "the pattern's own 'at:'",
  lengthNote: "every coordinate in a pattern part is measured from the pattern's own 'at:'; %r (the screen's minor radius) scales it with the dial",
  anchorNote: "{dx, dy} or {angle, radius} are offsets from 'at:'",
  unitRefusals: { "%": "a pattern part's frame has no parent box for '%' to measure against",
    pt: "a pattern part's geometry has no font for 'pt' to measure against" },
};

/** Explain the two things a hand or pattern part's frame refuses that every other position accepts: `%`/`pt` lengths and `anchor:`. */
function checkFramePart(doc: YamlDocument, bag: Bag, part: Dict, path: Path, frame: Frame): Path[] {
  const bad: Path[] = [];
  const length = (container: Dict, key: string, at: Path): void => {
    const unit = handUnit(container.get(key));
    if (unit === null) return;
    bag.error("schema",
      `${dottedPath(at)}: ${quoted(container.get(key))} -- a ${frame.noun}'s lengths are px or %r only; ${frame.unitRefusals[unit]}`,
      doc.span(container, key), { notes: [frame.lengthNote] });
    bad.push(at);
  };
  const position = (raw: unknown, at: Path): void => {
    if (!isDict(raw)) return;
    if (raw.has("anchor")) {
      bag.error("schema",
        `${dottedPath(at)}: 'anchor:' is not accepted in a ${frame.noun} -- its coordinates are measured from ${frame.origin}, and there is no box to anchor to`,
        doc.span(raw, "anchor"), { notes: [frame.anchorNote] });
      bad.push(at); // the schema reports an unknown key at its object
    }
    for (const key of HAND_POSITION_LENGTHS) length(raw, key, [...at, key]);
  };
  for (const key of HAND_PART_LENGTHS) length(part, key, [...path, key]);
  for (const key of HAND_PART_POSITIONS) position(part.get(key), [...path, key]);
  const size = part.get("size");
  if (isDict(size)) for (const key of ["width", "height"]) length(size, key, [...path, "size", key]);
  const points = part.get("points");
  if (Array.isArray(points)) points.forEach((point, i) => position(point, [...path, "points", i]));
  return bad;
}

function checkHandFrame(doc: YamlDocument, bag: Bag): Path[] {
  const bad: Path[] = [];
  const resources = (doc.data as Dict).get("resources");
  const sets = isDict(resources) ? resources.get("hand_sets") : undefined;
  if (!isDict(sets)) return bad;
  for (const [setName, spec] of sets) {
    if (!isDict(spec)) continue;
    for (const handName of ["hour", "minute", "second"]) {
      const hand = spec.get(handName);
      if (!isDict(hand)) continue;
      for (const [index, part] of partsOf(hand)) {
        bad.push(...checkFramePart(doc, bag, part, ["resources", "hand_sets", setName as Step, handName, "parts", index], HAND_FRAME));
      }
    }
  }
  return bad;
}

/** `checkFramePart` over every pattern's parts, plus a linear pattern's `step:` refusing `pt`. */
function checkPatternFrame(doc: YamlDocument, bag: Bag): Path[] {
  const bad: Path[] = [];
  visitElements(doc, (element, here) => {
    if (element.get("type") !== "pattern") return;
    const step = element.get("step");
    if (isDict(step)) {
      for (const key of ["dx", "dy"]) {
        const value = step.get(key);
        if (typeof value === "string" && value.trim().endsWith("pt")) {
          // Recorded as the whole `step` object: `step:` is an
          // angle-or-{dx, dy} oneOf with no discriminator, so the schema's
          // own error for it narrows only as far as `step` itself.
          const stepPath = [...here, "step"];
          bag.error("schema",
            `${dottedPath([...stepPath, key])}: ${quoted(step.get(key))} -- a linear pattern's step is px, % or %r, not pt: there is no font in scope to measure a pt against`,
            doc.span(step, key), { notes: ["px, %r and a bare number are also fine here"] });
          bad.push(stepPath);
        }
      }
    }
    for (const [i, part] of partsOf(element)) bad.push(...checkFramePart(doc, bag, part, [...here, "parts", i], PATTERN_FRAME));
  });
  return bad;
}

/** Why `type: hands`/`type: pattern` refuse element-level `align:`. */
const PIVOT_ALIGNMENT_REASON: ReadonlyMap<string, string> = new Map([
  ["hands", "'at:' is the axis the hands turn about, not a box to align"],
  ["pattern", "'at:' is the origin every copy turns about (radial) or steps from (linear), not a box to align"],
]);
const PIVOT_ALIGNMENT_KEYS = ["align"];

/** Refuse `align:` on `type: hands`/`type: pattern` with the reason a bare "unknown key" would not give. */
function checkHandsPatternAlignment(doc: YamlDocument, bag: Bag): Path[] {
  visitElements(doc, (element, here) => {
    const kind = element.get("type");
    if (typeof kind !== "string") return;
    const reason = PIVOT_ALIGNMENT_REASON.get(kind);
    if (reason === undefined) return;
    for (const key of PIVOT_ALIGNMENT_KEYS) {
      if (element.has(key)) {
        bag.error("schema", `${dottedPath([...here, key])}: ${quoted(key)} is not accepted on 'type: ${kind}' -- ${reason}`,
          doc.span(element, key), { notes: ["align a hand or pattern part instead, or move 'at:'"] });
      }
    }
  });
  return [];
}

function unexpectedMessage(remaining: string[]): string {
  const joined = remaining.map(quoted).join(", ");
  return `Additional properties are not allowed (${joined} ${remaining.length === 1 ? "was" : "were"} unexpected)`;
}

function sortedStrings(values: Iterable<string>): string[] {
  return [...values].sort(compareStrings);
}

/** Strip `align` from an unknown-key failure on a hands or pattern element, which `checkHandsPatternAlignment` explained. */
function dropPivotAlignmentKeys(error: ValidationError): ValidationError | null {
  if (error.validator !== "additionalProperties") return error;
  if (!isDict(error.instance) || !PIVOT_ALIGNMENT_REASON.has(error.instance.get("type") as string)) return error;
  const offending = new Set(unexpectedKeys(error));
  const remaining = sortedStrings([...offending].filter((k) => !PIVOT_ALIGNMENT_KEYS.includes(k)));
  if (remaining.length === offending.size) return error;
  if (remaining.length === 0) return null;
  error.message = unexpectedMessage(remaining);
  return error;
}

/** Strip the keys `checkReserved` already explained from an unknown-key error on the object holding them. */
function dropReservedKeys(error: ValidationError, reported: Path[]): ValidationError | null {
  if (error.validator !== "additionalProperties") return error;
  const here = error.absolutePath;
  const explained = new Set(reported.filter((path) => path.length === here.length + 1 && under(path, here))
    .map((path) => path[path.length - 1]));
  const offending = new Set(unexpectedKeys(error));
  const remaining = sortedStrings([...offending].filter((k) => !explained.has(k)));
  if (remaining.length === offending.size) return error;
  if (remaining.length === 0) return null;
  error.message = unexpectedMessage(remaining);
  return error;
}

function under(path: readonly Step[], prefix: readonly Step[]): boolean {
  return prefix.length <= path.length && prefix.every((step, i) => step === path[i]);
}

/**
 * Collapse a `oneOf` failure to the branch the author meant. jsonschema
 * flattens every branch's errors into one `context` list, tagged with the
 * branch index in `schemaPath[0]`, so the branches are regrouped here and
 * the ones whose `type` discriminator did not match are dropped.
 */
function* narrow(error: ValidationError): Generator<ValidationError> {
  if (error.validator === "oneOf" && error.context.length === 0) {
    // Every branch passed: a pair of mutually exclusive keys.
    yield exclusive(error);
    return;
  }
  if ((error.validator !== "oneOf" && error.validator !== "anyOf") || error.context.length === 0) {
    yield error;
    return;
  }
  const branches = new Map<unknown, ValidationError[]>();
  for (const sub of error.context) {
    const branch = sub.schemaPath.length > 0 ? sub.schemaPath[0] : 0;
    const list = branches.get(branch);
    if (list) list.push(sub); else branches.set(branch, [sub]);
  }
  const candidates = [...branches.values()].filter((errors) => !errors.some(isDiscriminator));
  if (candidates.length === 0 || candidates.length === branches.size) {
    // Nothing discriminated: drop the branches that do not even take this
    // kind of value, then report whichever remaining branch got furthest.
    const depth = error.absolutePath.length;
    const shaped = [...branches.values()].filter((errors) => !errors.some((sub) => wrongKind(sub, depth)));
    const flat = shaped.flat();
    const pool = flat.length > 0 ? flat : error.context;
    let best = pool[0]!;
    for (const e of pool.slice(1)) {
      const a = [-e.absolutePath.length, Array.from(e.message).length];
      const b = [-best.absolutePath.length, Array.from(best.message).length];
      if (a[0]! < b[0]! || (a[0] === b[0] && a[1]! < b[1]!)) best = e;
    }
    yield* narrow(best);
    return;
  }
  for (const errors of candidates) {
    const required = errors.filter((e) => e.validator === "required");
    const nested = errors.filter((e) => (e.validator === "oneOf" || e.validator === "anyOf") && e.context.length > 0);
    if (nested.length > 0 && required.length === 0) {
      for (const sub of nested) {
        const merged = mergeAlternatives(sub);
        if (merged.validator === "required-one-of") yield merged;
        else yield* narrow(sub);
      }
      continue;
    }
    for (const sub of errors) {
      if (isDiscriminator(sub)) continue;
      yield* narrow(sub);
    }
  }
}

/** Name the mutually exclusive keys behind a "valid under each of" oneOf. */
function exclusive(error: ValidationError): ValidationError {
  const branches = Array.isArray(error.validatorValue) ? error.validatorValue as unknown[] : [];
  const names: string[] = [];
  for (const branch of branches) {
    if (branch === null || typeof branch !== "object" || Array.isArray(branch)) return error;
    const keys = Object.keys(branch);
    if (keys.length !== 1 || keys[0] !== "required") return error;
    const required = (branch as { required: string[] }).required;
    if (required.length !== 1) return error;
    names.push(required[0]!);
  }
  const present = names.filter((n) => isDict(error.instance) && error.instance.has(n));
  if (present.length < 2) return error;
  error.message = `${present.map(quoted).join(" and ")} cannot both be set -- use ${present.map(quoted).join(" or ")}, not both`;
  error.validator = "exclusive-keys";
  return error;
}

/** Did this branch reject the value itself for being the wrong kind of value, rather than for something inside it? */
function wrongKind(sub: ValidationError, depth: number): boolean {
  if (sub.absolutePath.length !== depth) return false;
  if (sub.validator === "type") return true;
  if (sub.validator === "enum" || sub.validator === "const") {
    const value = sub.validatorValue;
    const allowed = sub.validator === "enum" ? (Array.isArray(value) ? value : []) : [value];
    return allowed.every((v) => jsonTypeName(v) !== typeName(sub.instance));
  }
  return false;
}

/** Did this sub-error come from a branch's `type` const not matching? */
function isDiscriminator(sub: ValidationError): boolean {
  const path = sub.schemaPath;
  return sub.validator === "const" && path.length >= 2 && path[path.length - 2] === "type" && path[path.length - 1] === "const";
}

/** "must match one of [needs a, needs b]" as "needs a or b". */
function mergeAlternatives(error: ValidationError): ValidationError {
  const missing = error.context.filter((sub) => sub.validator === "required").map((sub) => sub.message.split("'")[1]!);
  if (missing.length < 2) return error;
  error.message = `needs one of ${missing.map(quoted).join(" or ")}`;
  error.validator = "required-one-of";
  return error;
}

function report(doc: YamlDocument, bag: Bag, error: ValidationError): void {
  const path = error.absolutePath;
  const unexpected = error.validator === "additionalProperties" ? unexpectedKeys(error) : [];
  // An unknown key is pointed at itself, not at the mapping's first key.
  const span = (unexpected.length > 0 ? doc.span(error.instance, unexpected[0], "key") : null) ?? doc.spanForPath(path);
  const [message, notes] = humanise(error);
  bag.error("schema", path.length > 0 ? `${dottedPath(path)}: ${message}` : message, span, { notes });
}

/** A format 1 key an author may still type into a format 2 file, and how format 2 writes it. */
export const FORMAT_1_KEYS: ReadonlyMap<string, string> = new Map([
  ["targets", "'build: {targets: [...]}'"],
  ["fonts", "'resources: {fonts: ...}'"],
  ["palette", "'resources: {palette: ...}'"],
  ["hands", "'set:' on a 'type: hands' element, and 'resources: {hand_sets: ...}' at the top level"],
  ["color_scheme", "'theme: {schemes: ...}'"],
  ["antialias", "'defaults: {antialias: ...}' at the top level"],
  ["min_1px", "'defaults: {min_1px: ...}' at the top level"],
  ["default", "'defaults: {aod: hide|show}'"],
  ["data", "'config: {slots: ...}'"],
  ["colors", "'scheme:'"],
  ["when_absent", "'absent:' -- 'hide', a placeholder string, or {value: <expression>}"],
  ["placeholder", "'absent: \"--\"'"],
  ["fallback", "'absent: {value: <expression>}'"],
  ["vertical_align", "one 'align:', e.g. 'align: top_left'"],
  ["if_unavailable", "'unsupported:'"],
  ["modes", "'sleep_update: true' (for [active, low_power]; [active] is the default)"],
  ["static", "a 'static:' block -- move the element into it"],
  ["value", "one 'text:' template, e.g. 'text: \"{time.hour:02d}\"' (on a gauge, 'value:' is still the reading)"],
  ["format", "one 'text:' template, e.g. 'text: \"{activity.steps:d}\"'"],
  ["glyph", "'icon: \"U+XXXX\"'"],
  ["icon_for", "'icon: {for: <expression>}'"],
  ["icon_size", "'icon: {size: ...}'"],
  ["icon_position", "'icon: {position: ...}'"],
  ["icon_gap", "'icon: {gap: ...}'"],
  ["icon_color", "'icon: {color: ...}'"],
  ["shape", "'type: <shape>' (type: rectangle, circle, line, ...)"],
  ["id", "the element's key: elements are a mapping of id -> element"],
]);

const POSITION_KEYS = new Set(["x", "y", "dx", "dy", "width", "height", "cx", "cy"]);

/** jsonschema's wording turned into something an author can act on. */
function humanise(error: ValidationError): [string, string[]] {
  const notes: string[] = [];
  const description = schemaOf(error)["description"];
  let message: string;
  switch (error.validator) {
    case "exclusive-keys":
    case "required-one-of":
      message = error.message;
      break;
    case "required":
      message = `missing required key ${quoted(error.message.split("'")[1])}`;
      break;
    case "dependentRequired": {
      const parts = error.message.split("'");
      message = `missing required key ${quoted(parts[1])} -- ${quoted(parts[3])} needs it`;
      break;
    }
    case "additionalProperties": {
      message = error.message.replaceAll("Additional properties are not allowed", "unknown key");
      const offending = new Set(unexpectedKeys(error));
      if ([...offending].some((k) => POSITION_KEYS.has(k))) {
        notes.push("positions go in `at:` and sizes in `size:` -- this format has no top-level x/y/width/height, " +
          "because a position is relative to an anchor rather than absolute:\n" +
          "    at: {anchor: center, dy: -18%}\n" +
          "    size: {width: 60%, height: 12%}");
      }
      for (const key of unexpectedKeys(error)) {
        const v1 = FORMAT_1_KEYS.get(key);
        if (v1 !== undefined) notes.push(`'${key}:' is format 1; format 2 writes ${v1}`);
      }
      notes.push("unknown keys are an error, not a warning -- a misspelled key is how a design silently loses an element (ADR 0009)");
      const allowed = schemaOf(error)["properties"];
      if (allowed && typeof allowed === "object" && Object.keys(allowed).length > 0) {
        notes.push("keys allowed here: " + sortedStrings(Object.keys(allowed)).join(", "));
      }
      break;
    }
    case "enum":
      message = `${quoted(error.instance)} is not valid here`;
      notes.push("allowed: " + (Array.isArray(error.validatorValue) ? error.validatorValue : []).map(quoted).join(", "));
      break;
    case "const":
      message = `expected ${quoted(error.validatorValue)}, got ${quoted(error.instance)}`;
      break;
    case "pattern":
      message = error.schemaPath.includes("propertyNames")
        ? `${quoted(error.instance)} is not a valid name`
        : `${quoted(error.instance)} has the wrong shape`;
      break;
    case "type":
      message = `expected ${typeof error.validatorValue === "string" ? error.validatorValue : quoted(error.validatorValue)}, got ${typeName(error.instance)}`;
      break;
    case "minItems":
    case "maxItems":
      if (Array.isArray(error.instance)) {
        // jsonschema's own wording repeats the whole array back: noise around a one-number fact.
        const adjective = error.validator === "minItems" ? "at least" : "at most";
        message = `needs ${adjective} ${String(error.validatorValue)} items, got ${error.instance.length}`;
      } else {
        message = error.message;
      }
      break;
    default:
      message = error.message;
  }
  if (description && ["pattern", "enum", "required", "anyOf", "type", "minItems", "maxItems"].includes(error.validator ?? "")) {
    notes.push(String(description));
  }
  return [message, notes];
}

/** The schema object the error was raised against, or `{}` for a boolean schema. */
function schemaOf(error: ValidationError): Record<string, unknown> {
  const s: Schema | undefined = error.schema;
  return s !== null && typeof s === "object" ? s : {};
}

/** The key names an additionalProperties failure is complaining about. */
function unexpectedKeys(error: ValidationError): string[] {
  const allowed = new Set(Object.keys((schemaOf(error)["properties"] ?? {}) as object));
  const instance = error.instance;
  if (!isDict(instance)) return [];
  return [...instance.keys()].filter((k) => !allowed.has(k as string)) as string[];
}

/**
 * Python's `_type_name` of a value from the author's document, which is
 * ruamel round-trip data, looked up by exact type: a mapping is a
 * `CommentedMap`, a list a `CommentedSeq`, and a float written in the text a
 * `ScalarFloat` (`.inf` and `.nan` stay plain floats, "number").
 *
 * Two of ruamel's types this data cannot tell apart, so they read as plain
 * ones here: a block scalar (`LiteralScalarString`, `FoldedScalarString`,
 * read as "string") and an int written in hex, octal, binary or with
 * underscores (`HexInt`, `OctalInt`, `BinaryInt`, `ScalarInt`, read as
 * "integer").
 */
export function typeName(value: unknown): string {
  if (typeof value === "boolean") return "boolean";
  if (value instanceof PyFloat) return "ScalarFloat";
  if (typeof value === "number") return Number.isInteger(value) ? "integer" : Number.isFinite(value) ? "ScalarFloat" : "number";
  if (typeof value === "string") return "string";
  if (Array.isArray(value)) return "CommentedSeq";
  if (value instanceof Map) return "CommentedMap";
  if (value instanceof Timestamp) return value.iso.includes("T") ? "TimeStamp" : "date";
  if (value === null || value === undefined) return "null";
  return typeof value;
}

/** Python's `_type_name` of a plain JSON value from the schema. */
function jsonTypeName(value: unknown): string {
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "number") return Number.isInteger(value) ? "integer" : "number";
  if (typeof value === "string") return "string";
  if (Array.isArray(value)) return "array";
  if (value === null) return "null";
  return "object";
}
