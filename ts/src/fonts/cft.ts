// Garmin's `.cft` bitmap-font container. A port of the decode logic in markw65/monkeyc-optimizer's `src/cftinfo.ts`
// (commit cea919a92da74de1f5d277064caa6f7920554af7, MIT), credited in
// README.md.
//
// Everything is big-endian. The header (36 bytes, or 40 for the
// maybe-zlib variant) holds the flags (byte 3: bit 1 RLE, bit 2 two bits
// per pixel), the cmap, glyph-info and glyph-data offsets (4, 8, 12, 16)
// and the height, ascent and internal leading (22, 24, 26). The cmap is a
// u32 group count at cmap + 12, then `(start, end, startGlyph)` u32
// triples; a later group wins an overlapping codepoint, and a codepoint no
// group covers is glyph 0. A glyph's info word holds its advance (low
// byte, also its cell width) and its data offset. Pixels are row-major,
// packed least significant bit first; RLE and zlib as `cftinfo.ts`.
import { unzlibSync } from "fflate";

const FLAG_RLE = 0x02;
const FLAG_2BPP = 0x04;
const ZLIB_MAGIC_LENGTH_PREFIXED = 0xcd00000d;
const ZLIB_MAGIC_RAW = 0xd000000d;

/** One decoded glyph cell: `levels` is row-major, one byte a pixel, `0..maxLevel`. */
export interface CftGlyph {
  advance: number;
  height: number;
  levels: Uint8Array;
}

/** A decoded `.cft` font; build with `loadCft`. */
export class CftFont {
  readonly path: string;
  /** The line box height, and the baseline down from its top, in pixels. */
  readonly height: number;
  readonly ascent: number;
  readonly internalLeading: number;
  readonly bpp: number;
  readonly maxLevel: number;
  private readonly rle: boolean;
  private readonly align: number;
  private readonly cmap: readonly (readonly [number, number, number])[];
  private readonly glyphInfo: number;
  private readonly raw: DataView;
  private readonly glyphData: Uint8Array;
  private readonly base: number;
  private readonly decoded = new Map<number, CftGlyph>();

  constructor(path: string, fields: {
    height: number; ascent: number; internalLeading: number; bpp: number; rle: boolean; align: number;
    cmap: [number, number, number][]; glyphInfo: number; raw: DataView; glyphData: Uint8Array; base: number;
  }) {
    this.path = path;
    this.height = fields.height;
    this.ascent = fields.ascent;
    this.internalLeading = fields.internalLeading;
    this.bpp = fields.bpp;
    this.maxLevel = (1 << fields.bpp) - 1;
    this.rle = fields.rle;
    this.align = fields.align;
    this.cmap = fields.cmap;
    this.glyphInfo = fields.glyphInfo;
    this.raw = fields.raw;
    this.glyphData = fields.glyphData;
    this.base = fields.base;
  }

  /** `ch`'s glyph index, or 0 (the "missing" box) when no group covers it; a later group wins. */
  glyphIndex(ch: string): number {
    const codepoint = ch.codePointAt(0)!;
    let result = 0;
    for (const [start, end, startGlyph] of this.cmap) if (start <= codepoint && codepoint <= end) result = startGlyph + (codepoint - start);
    return result;
  }

  private word(index: number): number {
    const offset = this.glyphInfo + 4 * index;
    return offset >= 0 && offset + 4 <= this.raw.byteLength ? this.raw.getUint32(offset) : 0;
  }

  /** `ch`'s pen advance, in pixels: the glyph-info word alone. */
  advance(ch: string): number {
    return this.word(this.glyphIndex(ch)) & 0xff;
  }

  advances(text: string): number[] {
    return Array.from(text, (ch) => this.advance(ch));
  }

  /** `ch`'s decoded cell, cached per glyph index. */
  glyph(ch: string): CftGlyph {
    const index = this.glyphIndex(ch);
    let glyph = this.decoded.get(index);
    if (glyph === undefined) {
      glyph = this.decode(index);
      this.decoded.set(index, glyph);
    }
    return glyph;
  }

  private decode(index: number): CftGlyph {
    try {
      const word = this.word(index);
      const advance = word & 0xff;
      let glyphOffset = ((word >>> 16) & 0xffff) + ((word & 0xff00) << 8);
      if (this.rle) glyphOffset &= 0x7fffff;
      const ppb = this.bpp === 2 ? 4 : 8;
      const byteWidth = Math.ceil(Math.ceil(advance / ppb) / this.align) * this.align;
      const size = byteWidth * this.height;
      const start = this.base + glyphOffset;
      let packed: Uint8Array;
      if (this.rle) {
        packed = rleDecode(this.glyphData, start, size);
      } else {
        // A short read is padded with background: a missing glyph still draws a sane cell.
        packed = new Uint8Array(size);
        packed.set(this.glyphData.subarray(start, start + size));
      }
      const levels = new Uint8Array(advance * this.height);
      let pos = 0;
      for (let row = 0; row < this.height; row++) {
        const rowOffset = row * byteWidth;
        for (let x = 0; x < advance; x++) {
          const byte = packed[rowOffset + Math.floor(x / ppb)];
          if (byte === undefined) throw new RangeError("glyph data past the end");
          levels[pos++] = (byte >> ((x % ppb) * this.bpp)) & this.maxLevel;
        }
      }
      return { advance, height: this.height, levels };
    } catch {
      return { advance: 0, height: this.height, levels: new Uint8Array(0) };
    }
  }
}

/** Decode a `.cft`, or `null` when it is malformed or truncated. Never throws. */
export function loadCft(path: string, bytes: Uint8Array): CftFont | null {
  try {
    const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    if (bytes.length < 36) return null;
    const headerSize = data.getUint16(0);
    if ((headerSize !== 36 && headerSize !== 40) || bytes.length < headerSize) return null;
    const flags = bytes[3]!;
    const cmapOffset = data.getUint32(8), glyphInfo = data.getUint32(12), glyphDataOffset = data.getUint32(16);
    const height = data.getUint16(22), ascent = data.getUint16(24), internalLeading = data.getUint16(26);
    const align = headerSize === 40 ? bytes[36]! : 1;
    const [glyphData, base] = glyphDataSegment(bytes, data, glyphDataOffset, headerSize);
    if (cmapOffset + 16 > bytes.length) return null;
    const groups = data.getUint32(cmapOffset + 12);
    const groupsStart = cmapOffset + 16;
    if (groupsStart + 12 * groups > bytes.length) return null;
    const cmap: [number, number, number][] = [];
    for (let i = 0; i < groups; i++) {
      const at = groupsStart + 12 * i;
      cmap.push([data.getUint32(at), data.getUint32(at + 4), data.getUint32(at + 8)]);
    }
    return new CftFont(path, {
      height, ascent, internalLeading, bpp: flags & FLAG_2BPP ? 2 : 1, rle: Boolean(flags & FLAG_RLE), align,
      cmap, glyphInfo, raw: data, glyphData, base,
    });
  } catch {
    return null;
  }
}

/** The bytes glyph offsets are relative to, and the base within them: the 40-byte header's maybe-zlib layout. */
function glyphDataSegment(bytes: Uint8Array, data: DataView, offset: number, headerSize: number): [Uint8Array, number] {
  if (headerSize !== 40) return [bytes, offset];
  const first = data.getUint32(offset);
  if (first === ZLIB_MAGIC_RAW) return [bytes, offset + 4];
  if (first === ZLIB_MAGIC_LENGTH_PREFIXED) offset += 4;
  offset += 4; // the length word
  return [unzlibSync(bytes.subarray(offset)), 0];
}

/** The RLE glyph-data codec: bits least significant first; see `cftinfo.ts`. */
function rleDecode(data: Uint8Array, offset: number, size: number): Uint8Array {
  const out = new Uint8Array(Math.max(0, size));
  if (size <= 0) return out;
  let pos = offset, acc = 0n, nbits = 0;
  const get = (n: number): number => {
    while (nbits < n) {
      const byte = data[pos++];
      if (byte === undefined) throw new RangeError("RLE data past the end");
      acc |= BigInt(byte) << BigInt(nbits);
      nbits += 8;
    }
    const result = Number(acc & ((1n << BigInt(n)) - 1n));
    acc >>= BigInt(n);
    nbits -= n;
    return result;
  };
  let runBits = 1;
  while (get(1) === 0) runBits++;
  const chunkSize = get(5) + 1;
  const escape = get(chunkSize);
  let outPos = 0, outAcc = 0n, outBits = 0, prev = -1;
  while (outPos + (outBits >> 3) < size) {
    const val = get(chunkSize);
    let value: number, count: number;
    if (val !== escape) {
      prev = val;
      value = val;
      count = 1;
    } else {
      const run = get(runBits);
      if (run === 0) {
        prev = val;
        value = val;
        count = 1;
      } else {
        value = prev;
        count = run + 1;
      }
    }
    for (let i = 0; i < count; i++) {
      outAcc |= BigInt(value) << BigInt(outBits);
      outBits += chunkSize;
      while (outBits >= 8) {
        if (outPos < size) out[outPos] = Number(outAcc & 0xffn);
        outPos++;
        outAcc >>= 8n;
        outBits -= 8;
      }
    }
  }
  if (outBits && outPos < size) out[outPos] = Number(outAcc & 0xffn);
  return out;
}
