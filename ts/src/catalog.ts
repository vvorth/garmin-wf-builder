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

/** A catalogue entry as the JSON spells it: `call` and `extra_readers` are optional there. */
type RawSource = Omit<Source, "call" | "extra_readers"> & Partial<Pick<Source, "call" | "extra_readers">>;

function withDefaults(raw: RawSource): Source {
  return { call: null, extra_readers: [], ...raw };
}

export const READERS: ReadonlyMap<string, Reader> = new Map(Object.entries(data.readers as Record<string, Reader>));

export const CATALOG: Catalogue<Source> = new Catalogue(Object.entries(data.sources as Record<string, RawSource>)
  .map(([path, raw]) => [path, withDefaults(raw)]));

/** The paths superseded by `complication.*`, so an old design is told the replacement. */
export const RENAMED_SOURCES: ReadonlyMap<string, string> = new Map(Object.entries(data.renamed_sources));

/** The only sources `icon: {for:}` may bind to: a Weather.CONDITION_* value. */
export const WEATHER_CONDITION_SOURCES: ReadonlySet<string> = new Set(data.weather_condition_sources);

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
