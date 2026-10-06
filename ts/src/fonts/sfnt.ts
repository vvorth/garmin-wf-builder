// The four tables of a TrueType/OpenType font that measuring text needs:
// `head` (units per em), `hhea` (ascent, descent), `hmtx` (each glyph's
// advance) and `cmap` (character to glyph). Read directly from the bytes.

/** What a font says about laying a line out. */
export interface Sfnt {
  unitsPerEm: number;
  /** `hhea.ascent`, and `hhea.descent` signed (negative below the baseline), as fontTools reads them. */
  ascent: number;
  descent: number;
  /** Codepoint to glyph index, from the subtable fontTools' `getBestCmap` picks. */
  cmap: Map<number, number>;
  /** Each glyph's advance width, in font units; glyphs past `hhea.numberOfHMetrics` take the last one. */
  advances: number[];
}

/** The two sfnt versions read here: TrueType outlines and OpenType/CFF ones. */
const VERSIONS = [0x00010000, 0x4f54544f];

/** fontTools' `getBestCmap` order of `(platform, encoding)` subtables. */
const CMAP_PREFERENCE: readonly (readonly [number, number])[] = [[3, 10], [0, 6], [0, 4], [3, 1], [0, 3], [0, 2], [0, 1], [0, 0]];

/** The tables `(offset, length)` by tag, or `null` for bytes that are not an sfnt. */
function tables(data: DataView): Map<string, number> | null {
  if (data.byteLength < 12 || !VERSIONS.includes(data.getUint32(0))) return null;
  const count = data.getUint16(4);
  const out = new Map<string, number>();
  for (let i = 0; i < count; i++) {
    const record = 12 + i * 16;
    const tag = String.fromCharCode(data.getUint8(record), data.getUint8(record + 1), data.getUint8(record + 2), data.getUint8(record + 3));
    out.set(tag, data.getUint32(record + 8));
  }
  return out;
}

/** `[unitsPerEm, hhea.ascent, hhea.descent]`, or `null` when the file is not an sfnt with both tables. Never throws. */
export function headHhea(bytes: Uint8Array): [number, number, number] | null {
  try {
    const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const found = tables(data);
    const head = found?.get("head"), hhea = found?.get("hhea");
    if (head === undefined || hhea === undefined) return null;
    const upm = data.getUint16(head + 18);
    if (upm <= 0) return null;
    return [upm, data.getInt16(hhea + 4), data.getInt16(hhea + 6)];
  } catch {
    return null;
  }
}

/** Read a font's metrics, or `null` when it cannot be read. Never throws. */
export function readSfnt(bytes: Uint8Array): Sfnt | null {
  try {
    const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const found = tables(data);
    if (found === null) return null;
    const head = found.get("head"), hhea = found.get("hhea"), hmtx = found.get("hmtx"), maxp = found.get("maxp"), cmap = found.get("cmap");
    if (head === undefined || hhea === undefined || hmtx === undefined || maxp === undefined) return null;
    const numGlyphs = data.getUint16(maxp + 4);
    const numberOfHMetrics = data.getUint16(hhea + 34);
    const advances: number[] = [];
    let last = 0;
    for (let i = 0; i < numGlyphs; i++) {
      if (i < numberOfHMetrics) last = data.getUint16(hmtx + 4 * i);
      advances.push(last);
    }
    return {
      unitsPerEm: data.getUint16(head + 18),
      ascent: data.getInt16(hhea + 4),
      descent: data.getInt16(hhea + 6),
      cmap: cmap === undefined ? new Map() : bestCmap(data, cmap),
      advances,
    };
  } catch {
    return null;
  }
}

function bestCmap(data: DataView, offset: number): Map<number, number> {
  const count = data.getUint16(offset + 2);
  const subtables = new Map<string, number>();
  for (let i = 0; i < count; i++) {
    const record = offset + 4 + i * 8;
    const key = `${data.getUint16(record)},${data.getUint16(record + 2)}`;
    if (!subtables.has(key)) subtables.set(key, offset + data.getUint32(record + 4));
  }
  for (const [platform, encoding] of CMAP_PREFERENCE) {
    const at = subtables.get(`${platform},${encoding}`);
    if (at !== undefined) {
      const map = readSubtable(data, at);
      if (map !== null) return map;
    }
  }
  return new Map();
}

/** One cmap subtable of format 0, 4, 6 or 12; `null` for another format. */
function readSubtable(data: DataView, at: number): Map<number, number> | null {
  const format = data.getUint16(at);
  const out = new Map<number, number>();
  if (format === 0) {
    for (let c = 0; c < 256; c++) {
      const glyph = data.getUint8(at + 6 + c);
      if (glyph !== 0) out.set(c, glyph);
    }
    return out;
  }
  if (format === 4) {
    const segments = data.getUint16(at + 6) / 2;
    const ends = at + 14, starts = ends + 2 * segments + 2, deltas = starts + 2 * segments, ranges = deltas + 2 * segments;
    for (let s = 0; s < segments; s++) {
      const end = data.getUint16(ends + 2 * s), start = data.getUint16(starts + 2 * s);
      const delta = data.getInt16(deltas + 2 * s), rangeOffset = data.getUint16(ranges + 2 * s);
      for (let c = start; c <= end && c !== 0xffff; c++) {
        let glyph: number;
        if (rangeOffset === 0) {
          glyph = (c + delta) & 0xffff;
        } else {
          const raw = data.getUint16(ranges + 2 * s + rangeOffset + 2 * (c - start));
          glyph = raw === 0 ? 0 : (raw + delta) & 0xffff;
        }
        if (glyph !== 0) out.set(c, glyph);
      }
    }
    return out;
  }
  if (format === 6) {
    const first = data.getUint16(at + 6), count = data.getUint16(at + 8);
    for (let i = 0; i < count; i++) {
      const glyph = data.getUint16(at + 10 + 2 * i);
      if (glyph !== 0) out.set(first + i, glyph);
    }
    return out;
  }
  if (format === 12) {
    const groups = data.getUint32(at + 12);
    for (let g = 0; g < groups; g++) {
      const record = at + 16 + 12 * g;
      const start = data.getUint32(record), end = data.getUint32(record + 4), glyph = data.getUint32(record + 8);
      for (let c = start; c <= end; c++) out.set(c, glyph + (c - start));
    }
    return out;
  }
  return null;
}

/**
 * The first `name` record with `nameId`, in file order, decoded as fontTools'
 * `toUnicode` does: UTF-16BE for the Unicode and Windows platforms, one byte
 * a character otherwise. `null` when there is none or the file is not an sfnt.
 */
export function nameRecord(bytes: Uint8Array, nameId: number): string | null {
  try {
    const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const at = tables(data)?.get("name");
    if (at === undefined) return null;
    const count = data.getUint16(at + 2), storage = at + data.getUint16(at + 4);
    for (let i = 0; i < count; i++) {
      const record = at + 6 + i * 12;
      if (data.getUint16(record + 6) !== nameId) continue;
      const platform = data.getUint16(record), length = data.getUint16(record + 8), offset = storage + data.getUint16(record + 10);
      const raw = bytes.subarray(offset, offset + length);
      if (platform === 0 || platform === 3) {
        let text = "";
        for (let j = 0; j + 1 < raw.length; j += 2) text += String.fromCharCode((raw[j]! << 8) | raw[j + 1]!);
        return text;
      }
      return String.fromCharCode(...raw);
    }
    return null;
  } catch {
    return null;
  }
}
