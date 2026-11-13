// The typed data-source catalogue (ADR 0005). The
// tables themselves are `data/catalog.json`, exported from wfb/ by
// tools/export_tables.py, each entry with its SDK page in `source_ref`.
//
// Sources are addressed by dotted path, and each carries what the compiler
// must know about it: its type, so expressions are type-checked at build
// time; its nullability, since every ActivityMonitor.Info field is "or
// Null"; and the permission it implies, from which manifest.xml is derived
// (a missing permission fails silently on the device).
//
// There is no refresh tier: every reader is read fresh, every frame. One
// rule, no exceptions, for where a value comes from: `complication.*` is
// always read through Toybox.Complications; every other path is always a
// direct API read.
import data from "./data/catalog.json" with { type: "json" };
import { Catalogue } from "./diagnostics.ts";

export type Type = "number" | "float" | "boolean" | "string" | "time" | "date" | "color";

export function isNumeric(type: Type): boolean {
  return type === "number" || type === "float";
}

/** Types whose `format` uses strftime-style codes rather than `{:d}`. */
export function isFormatted(type: Type): boolean {
  return type === "time" || type === "date";
}

/** One generated local a `Source` reads its value off: a shared accessor (`activity`) or one complication. */
export interface Reader {
  name: string;
  call: string;
  monkeyc_type: string;
  module: string;
  nullable: boolean;
  requires: string[];
  requires_module: string | null;
  complication_type: string | null;
}

/** One addressable value. */
export interface Source {
  path: string;
  type: Type;
  reader: string;
  field_name: string | null;
  nullable: boolean;
  permissions: string[];
  requires: string[];
  unit: string | null;
  quantity: string | null;
  /**
   * The table naming each value the number takes, for a `:name`/`:short`
   * format spec: `weather_condition` for a `Weather.CONDITION_*`
   * (`data/complications.json`'s `weather_condition_text`). `null` for a
   * number that is a quantity.
   */
  enum: "weather_condition" | null;
  doc: string;
  source_ref: string;
  array_index: number | null;
  intermediate: string | null;
  cast: string | null;
  to_float: boolean;
  count: boolean;
  launch_complication: string | null;
  /** The barrel function the value is read through, `<call>(<reader>[, <extra readers>...])`; `null` reads a field. */
  call: string | null;
  /** Further readers the call takes, in parameter order after `reader`. */
  extra_readers: string[];
}

/** A catalogue entry as the JSON spells it: `call`, `extra_readers` and `enum` are optional there. */
type RawSource = Omit<Source, "call" | "extra_readers" | "enum"> & Partial<Pick<Source, "call" | "extra_readers" | "enum">>;

function withDefaults(raw: RawSource): Source {
  return { call: null, extra_readers: [], enum: null, ...raw };
}

export const READERS: ReadonlyMap<string, Reader> = new Map(Object.entries(data.readers as Record<string, Reader>));

/** One field of an indexed family: a `Source` less what the index decides. */
export interface IndexedField {
  type: Type;
  field_name: string;
  unit: string | null;
  quantity: string | null;
  enum: Source["enum"];
  doc: string;
  /** The complication `on_hold: auto` launches, keyed by the index it applies at. */
  launch_complications?: Record<string, string>;
}

/**
 * An array a reader returns, addressed `<family>[<n>].<field>`: the daily
 * and hourly weather forecasts. Entry `n` of the array is the `n`th day or
 * hour; the API promises no length, so an index past the end reads absent.
 */
export interface IndexedFamily {
  reader: string;
  /** What one entry is, for the docs: `day`, `hour`. */
  unit_label: string;
  /** The highest index a design may name: a typo guard, not the API's length. */
  max_index: number;
  source_ref: string;
  doc: string;
  fields: Record<string, IndexedField>;
}

export const INDEXED: ReadonlyMap<string, IndexedFamily> = new Map(Object.entries(data.indexed_sources as Record<string, IndexedFamily>));

const INDEXED_PATH = /^([A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*)\[(\d+)\]\.([A-Za-z_][A-Za-z0-9_]*)$/;

/** An indexed path's parts, or `null` for any other path. The family and field may still be unknown. */
export function parseIndexed(path: string): { family: string; index: number; field: string } | null {
  const m = INDEXED_PATH.exec(path);
  return m === null ? null : { family: m[1]!, index: Number(m[2]), field: m[3]! };
}

/** The path with its index written `[n]`, as the docs, the icon rules and the listings name a family's field. */
export function familyPath(path: string): string {
  return path.replace(/\[\d+\]/g, "[n]");
}

/** The catalogue entry an indexed path names, or `undefined` when its family, field or index is not one. */
function indexedSource(path: string): Source | undefined {
  const parts = parseIndexed(path);
  if (parts === null) return undefined;
  const family = INDEXED.get(parts.family);
  const field = family?.fields[parts.field];
  if (family === undefined || field === undefined || parts.index > family.max_index) return undefined;
  return {
    path, type: field.type, reader: family.reader, field_name: field.field_name, nullable: true, permissions: [], requires: [],
    unit: field.unit, quantity: field.quantity, enum: field.enum,
    doc: `${field.doc}, ${family.unit_label} ${parts.index} of the forecast`,
    source_ref: family.source_ref, array_index: parts.index, intermediate: null, cast: null, to_float: false, count: false,
    launch_complication: field.launch_complications?.[String(parts.index)] ?? null, call: null, extra_readers: [],
  };
}

/**
 * The catalogue: the fixed entries, iterated and listed, and every indexed
 * path, built when first asked for. `get` and `has` answer both; iteration
 * yields the fixed entries alone, so a listing names a family once
 * (`INDEXED`) rather than every index of it.
 */
class SourceCatalogue extends Catalogue<Source> {
  private readonly built = new Map<string, Source>();

  override get(path: string): Source | undefined {
    const fixed = super.get(path);
    if (fixed !== undefined) return fixed;
    let made = this.built.get(path);
    if (made === undefined) {
      made = indexedSource(path);
      if (made !== undefined) this.built.set(path, made);
    }
    return made;
  }

  override has(path: string): boolean {
    return this.get(path) !== undefined;
  }
}

export const CATALOG: Catalogue<Source> = new SourceCatalogue(Object.entries(data.sources as Record<string, RawSource>)
  .map(([path, raw]) => [path, withDefaults(raw)]));

/** Why an indexed-looking path names nothing, for the error: its family, field or index; `null` for any other path. */
export function indexedProblem(path: string): { message: string; notes: string[] } | null {
  const parts = parseIndexed(path);
  if (parts === null) return null;
  const family = INDEXED.get(parts.family);
  if (family === undefined) {
    return { message: `${parts.family} is not an indexed source`, notes: [`indexed sources: ${[...INDEXED.keys()].join(", ")}`] };
  }
  if (family.fields[parts.field] === undefined) {
    return { message: `${parts.family} entries have no field ${parts.field}`, notes: [`${parts.family}[n] has: ${Object.keys(family.fields).join(", ")}`] };
  }
  if (parts.index > family.max_index) {
    return {
      message: `${parts.family}[${parts.index}] is past the last ${family.unit_label} a design may name, [${family.max_index}]`,
      notes: [`[0] is the first ${family.unit_label}; the watch may send fewer, and an index past the end reads as absent`],
    };
  }
  return null;
}

/** The paths superseded by `complication.*`, so an old design is told the replacement. */
export const RENAMED_SOURCES: ReadonlyMap<string, string> = new Map(Object.entries(data.renamed_sources));

/** Permissions a watch face may declare (Core_Topics/Manifest_and_Permissions.html, the "Watch Face" column). */
export const WATCHFACE_PERMISSIONS: ReadonlySet<string> = new Set(data.watchface_permissions);

function readerNamed(name: string): Reader {
  const found = READERS.get(name);
  if (found === undefined) throw new Error(`no reader ${name}`);
  return found;
}

function reader(source: Source): Reader {
  return readerNamed(source.reader);
}

/** Every reader `source` reads through: the primary first, then `extra_readers` in order. */
export function readerNames(source: Source): string[] {
  return [source.reader, ...source.extra_readers];
}

/** `readerNames`, resolved. */
export function readersOf(source: Source): Reader[] {
  return readerNames(source).map(readerNamed);
}

/** The Monkey C expression reading `source` off its reader local(s): a field, or a barrel call taking every reader. */
export function readExpr(source: Source): string {
  const r = reader(source);
  const base = source.array_index === null ? r.name : `${r.name}[${source.array_index}]`;
  if (source.call !== null) return `${source.call}(${[base, ...source.extra_readers.map((name) => readerNamed(name).name)].join(", ")})`;
  return source.field_name === null ? base : `${base}.${source.field_name}`;
}

/** The bounds check an `array_index` needs beyond the reader's own nullability. */
export function arrayGuard(source: Source): string | null {
  return source.array_index === null ? null : `${reader(source).name}.size() > ${source.array_index}`;
}

/** Whether the generated code must null-check before using the value. */
export function guardNeeded(source: Source): boolean {
  return source.nullable || readersOf(source).some((r) => r.nullable);
}

/** The new path for a renamed source, or `undefined`. Checked before a fuzzy match: a renamed path is an exact former name. */
export function renamedTo(path: string): string | undefined {
  return RENAMED_SOURCES.get(path);
}

export function get(path: string): Source | undefined {
  return CATALOG.get(path);
}

/** Every namespace, and its paths, sorted. */
export function namespaces(): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const path of [...CATALOG.keys()].sort()) {
    const ns = path.split(".", 1)[0]!;
    const list = out.get(ns);
    if (list) list.push(path); else out.set(ns, [path]);
  }
  return out;
}

/** What a set of bound sources implies for the generated project. */
export class Requirements {
  permissions = new Set<string>();
  readers = new Set<string>();
  modules = new Set<string>();

  add(source: Source): void {
    for (const p of source.permissions) this.permissions.add(p);
    for (const name of readerNames(source)) {
      this.readers.add(name);
      this.modules.add(readerNamed(name).module);
    }
  }
}
