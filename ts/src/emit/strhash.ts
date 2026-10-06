// Find string literals `monkeyc` would give the same assembler label. Port
// of wfb/emit/strhash.py.
//
// `monkeyc` 9.2.0 names each distinct string constant's data label
// `str___<N>`, `N` the string's Java `String.hashCode()`, so two different
// strings with the same hash crash the build ("Redefinition of label").
// A glyph above the BMP is two UTF-16 units `(hi, lo)`, whose hash is
// `31*hi + lo`, so two glyphs collide whenever they are 993 codepoints apart
// in the right range. This module only finds collisions.
import { repr } from "../py.ts";

const ESCAPES: Record<string, string> = { n: "\n", t: "\t", r: "\r", "\\": "\\", '"': '"', "'": "'" };

/** Java's `String.hashCode()`: over UTF-16 code units, as a signed 32-bit int. */
export function javaStringHash(text: string): number {
  let value = 0;
  for (let i = 0; i < text.length; i++) value = (Math.imul(31, value) + text.charCodeAt(i)) | 0;
  return value;
}

/** Every `"..."` literal in Monkey C `source`, unescaped; comments and `'x'` chars skipped. */
export function stringLiterals(source: string): string[] {
  const out: string[] = [];
  let i = 0;
  const n = source.length;
  while (i < n) {
    const c = source[i]!;
    if (source.startsWith("//", i)) {
      const end = source.indexOf("\n", i);
      i = end < 0 ? n : end + 1;
    } else if (source.startsWith("/*", i)) {
      const end = source.indexOf("*/", i + 2);
      i = end < 0 ? n : end + 2;
    } else if (c === '"' || c === "'") {
      let chars = "";
      i++;
      while (i < n && source[i] !== c) {
        if (source[i] === "\\" && i + 1 < n) {
          chars += ESCAPES[source[i + 1]!] ?? source[i + 1]!;
          i += 2;
        } else {
          chars += source[i]!;
          i++;
        }
      }
      i++;
      if (c === '"') out.push(chars);
    } else {
      i++;
    }
  }
  return out;
}

/** Two or more distinct strings that would share one `str___<hash>` label, each with the files it appears in. */
export interface Collision {
  hash: number;
  strings: Map<string, string[]>;
}

const byCodePoint = (a: string, b: string): number => {
  const x = [...a], y = [...b];
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    const d = x[i]!.codePointAt(0)! - y[i]!.codePointAt(0)!;
    if (d !== 0) return d;
  }
  return x.length - y.length;
};

/** Hash collisions among every string literal in `files` (path to source). */
export function collisions(files: ReadonlyMap<string, string>): Collision[] {
  const byHash = new Map<number, Map<string, Set<string>>>();
  for (const [path, text] of files) {
    for (const literal of stringLiterals(text)) {
      const h = javaStringHash(literal);
      if (!byHash.has(h)) byHash.set(h, new Map());
      const group = byHash.get(h)!;
      if (!group.has(literal)) group.set(literal, new Set());
      group.get(literal)!.add(path);
    }
  }
  return [...byHash].sort(([a], [b]) => a - b).filter(([, group]) => group.size > 1).map(([hash, group]) => ({
    hash,
    strings: new Map([...group].sort(([a], [b]) => byCodePoint(a, b)).map(([s, paths]) => [s, [...paths].sort(byCodePoint)])),
  }));
}

/** A literal as a reader can see it: non-ASCII characters as `U+XXXX`. */
export function describe(text: string): string {
  const chars = [...text];
  if (chars.every((ch) => ch.codePointAt(0)! >= 32 && ch.codePointAt(0)! < 127)) return repr(text);
  return '"' + chars.map((ch) => {
    const cp = ch.codePointAt(0)!;
    return cp >= 32 && cp < 127 ? ch : `<U+${cp.toString(16).toUpperCase().padStart(4, "0")}>`;
  }).join("") + '"';
}
