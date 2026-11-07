// Where a system font's real file comes from: the user's own Garmin font
// root first, then a pinned free stand-in from the registry. Downloading a
// stand-in is `tools/fetch-system-fonts.ts`'s job, not the compiler's.
import registry from "../data/font-registry.json" with { type: "json" };

/** A located font file. */
export interface FontFile {
  /** Where it is: what a diagnostic or a cache keys on. */
  path: string;
  bytes: Uint8Array;
}

/**
 * The font files a build may measure with, read synchronously. In Node
 * from the disk (`./node.ts`); in the browser from what the server sent.
 */
export interface FontFiles {
  /**
   * A file under the Garmin font root whose stem is `name`, ignoring case:
   * a `.ttf`/`.otf` first, then a `.cft`. `undefined` when there is no
   * root, or no such file.
   */
  garmin(name: string, suffixes: readonly string[]): FontFile | undefined;
  /** A registry stand-in's file, installed or cached and matching its pinned hash; `undefined` when absent. */
  registry(key: string): FontFile | undefined;
}

interface Registry {
  sources: Record<string, { sha256: string; license?: string }>;
  fonts: Record<string, { source: string; match: string; tabular_digits?: boolean }>;
  names: Record<string, string>;
  patterns: { regex: string; key: string }[];
  faces: Record<string, string>;
}

export const REGISTRY = registry as Registry;
const PATTERNS = REGISTRY.patterns.map((p) => ({ regex: new RegExp(p.regex), key: p.key }));

/** A system-font name (a `simulator.json` filename or a scraped `font`) to a registry key: names, then patterns, then the face. */
export function resolveRegistryKey(name: string, face: string | null = null): string | null {
  if (Object.hasOwn(REGISTRY.names, name)) return REGISTRY.names[name]!;
  for (const { regex, key } of PATTERNS) if (regex.test(name)) return key;
  if (face !== null && Object.hasOwn(REGISTRY.faces, face)) return REGISTRY.faces[face]!;
  return null;
}

/** A `face:` font's `fallback: auto` stand-in: the registry key of the first listed face the registry maps. */
export interface StandIn {
  /** The listed face it stands in for. */
  face: string;
  key: string;
  /** `exact`, `family` or `substitute`. */
  match: string;
  /** The SPDX-style licence of the key's source, or `null` when the registry records none. */
  license: string | null;
  /** The face's digits share one advance and the key's file's do not: an `auto` sheet bakes them tabular to match. */
  tabular_digits: boolean;
}

/** The stand-in for the first of `faces`, in order, that the registry maps; `null` when it maps none. */
export function standIn(faces: readonly string[]): StandIn | null {
  for (const face of faces) {
    const key = resolveRegistryKey(face);
    const font = key === null ? undefined : REGISTRY.fonts[key];
    if (key === null || font === undefined) continue;
    return { face, key, match: font.match, license: REGISTRY.sources[font.source]?.license || null, tabular_digits: font.tabular_digits === true };
  }
  return null;
}

/** The pinned SHA-256 of a registry key's file. */
export function expectedSha(key: string): string | null {
  const font = REGISTRY.fonts[key];
  return font === undefined ? null : REGISTRY.sources[font.source]?.sha256 ?? null;
}

/**
 * The Garmin-root lookup: a `.ttf`/`.otf` named `name`, else a `.cft`, else
 * (for a name not already prefixed) a `.cft` named `FNT_<name>`, as the
 * scraped reference drops that prefix.
 */
export function garminAnyFile(files: FontFiles, name: string): FontFile | undefined {
  let found = files.garmin(name, [".ttf", ".otf"]) ?? files.garmin(name, [".cft"]);
  if (found === undefined && !name.toUpperCase().startsWith("FNT_")) found = files.garmin(`FNT_${name}`, [".cft"]);
  return found;
}

/** A located file and how well it matches: `"garmin"`, the registry's own level, or `"none"` with no file. */
export function locate(files: FontFiles, name: string, face: string | null = null): [FontFile | null, string] {
  const found = garminAnyFile(files, name);
  if (found !== undefined) return [found, "garmin"];
  const key = resolveRegistryKey(name, face);
  if (key !== null) {
    const file = files.registry(key);
    if (file !== undefined) return [file, REGISTRY.fonts[key]!.match];
  }
  return [null, "none"];
}
