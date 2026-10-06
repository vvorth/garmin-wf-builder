// Decoding a PNG to RGBA: the subset the simulator skins use (8 or 16 bits
// a channel, not interlaced), over fflate's inflate. A 16-bit sample keeps
// its high byte, as Pillow's 8-bit modes read it. Anything else is
// declined (`null`) rather than guessed at.
import { unzlibSync, zlibSync } from "fflate";

export interface RgbaImage {
  width: number;
  height: number;
  /** Row-major RGBA, four bytes a pixel. */
  pixels: Uint8Array;
}

const SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10];
const CHANNELS: Record<number, number> = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 };

function paeth(a: number, b: number, c: number): number {
  const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
}

/** `bytes` decoded to RGBA, or `null` for a PNG outside the subset, or not a PNG. */
export function decodePng(bytes: Uint8Array): RgbaImage | null {
  try {
    if (SIGNATURE.some((b, i) => bytes[i] !== b)) return null;
    const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let width = 0, height = 0, depth = 0, colorType = 0, interlace = 0;
    let palette: Uint8Array | null = null, transparency: Uint8Array | null = null;
    const idat: Uint8Array[] = [];
    for (let at = 8; at + 8 <= bytes.length;) {
      const length = data.getUint32(at);
      const type = String.fromCharCode(...bytes.subarray(at + 4, at + 8));
      const body = bytes.subarray(at + 8, at + 8 + length);
      if (type === "IHDR") {
        width = data.getUint32(at + 8);
        height = data.getUint32(at + 12);
        depth = body[8]!;
        colorType = body[9]!;
        interlace = body[12]!;
      } else if (type === "PLTE") palette = body;
      else if (type === "tRNS") transparency = body;
      else if (type === "IDAT") idat.push(body);
      else if (type === "IEND") break;
      at += 12 + length;
    }
    const channels = CHANNELS[colorType];
    if ((depth !== 8 && !(depth === 16 && colorType !== 3)) || interlace !== 0 || channels === undefined) return null;
    const bytesPerSample = depth / 8;
    const joined = new Uint8Array(idat.reduce((n, c) => n + c.length, 0));
    let offset = 0;
    for (const chunk of idat) {
      joined.set(chunk, offset);
      offset += chunk.length;
    }
    const raw = unzlibSync(joined);
    const bpp = channels * bytesPerSample;
    const stride = width * bpp;
    const unfiltered = new Uint8Array(stride * height);
    for (let y = 0; y < height; y++) {
      const filter = raw[y * (stride + 1)]!;
      const src = y * (stride + 1) + 1, dst = y * stride;
      for (let x = 0; x < stride; x++) {
        const value = raw[src + x]!;
        const left = x >= bpp ? unfiltered[dst + x - bpp]! : 0;
        const up = y > 0 ? unfiltered[dst - stride + x]! : 0;
        const upLeft = y > 0 && x >= bpp ? unfiltered[dst - stride + x - bpp]! : 0;
        const predicted = filter === 0 ? 0 : filter === 1 ? left : filter === 2 ? up
          : filter === 3 ? Math.floor((left + up) / 2) : paeth(left, up, upLeft);
        unfiltered[dst + x] = (value + predicted) & 0xff;
      }
    }
    // One byte a sample: a 16-bit sample's high byte.
    const rows = bytesPerSample === 1 ? unfiltered : unfiltered.filter((_, i) => i % 2 === 0);
    const pixels = new Uint8Array(width * height * 4);
    for (let i = 0; i < width * height; i++) {
      const s = i * channels, d = i * 4;
      if (colorType === 6) pixels.set(rows.subarray(s, s + 4), d);
      else if (colorType === 2) {
        pixels.set(rows.subarray(s, s + 3), d);
        pixels[d + 3] = 255;
      } else if (colorType === 0 || colorType === 4) {
        pixels[d] = pixels[d + 1] = pixels[d + 2] = rows[s]!;
        pixels[d + 3] = colorType === 4 ? rows[s + 1]! : 255;
      } else {
        const index = rows[s]!;
        if (palette === null) return null;
        pixels.set(palette.subarray(index * 3, index * 3 + 3), d);
        pixels[d + 3] = transparency !== null && index < transparency.length ? transparency[index]! : 255;
      }
    }
    return { width, height, pixels };
  } catch {
    return null;
  }
}

const CRC_TABLE = Uint32Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(bytes: Uint8Array): number {
  let c = 0xffffffff;
  for (const b of bytes) c = CRC_TABLE[(c ^ b) & 0xff]! ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type: string, body: Uint8Array): Uint8Array {
  const out = new Uint8Array(12 + body.length);
  const view = new DataView(out.buffer);
  view.setUint32(0, body.length);
  for (let i = 0; i < 4; i++) out[4 + i] = type.charCodeAt(i);
  out.set(body, 8);
  view.setUint32(8 + body.length, crc32(out.subarray(4, 8 + body.length)));
  return out;
}

/**
 * An 8-bit greyscale (`L`), RGB or RGBA image as a PNG: no filter, zlib at level
 * 9, no metadata, so the same pixels give the same bytes everywhere.
 */
export function encodePng(width: number, height: number, pixels: Uint8Array, channels: 1 | 3 | 4 = 1): Uint8Array {
  const header = new Uint8Array(13);
  const view = new DataView(header.buffer);
  view.setUint32(0, width);
  view.setUint32(4, height);
  header[8] = 8;
  header[9] = channels === 1 ? 0 : channels === 3 ? 2 : 6;
  const stride = width * channels;
  const raw = new Uint8Array((stride + 1) * height);
  for (let y = 0; y < height; y++) raw.set(pixels.subarray(y * stride, (y + 1) * stride), y * (stride + 1) + 1);
  const parts = [Uint8Array.from(SIGNATURE), chunk("IHDR", header), chunk("IDAT", zlibSync(raw, { level: 9 })), chunk("IEND", new Uint8Array(0))];
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) {
    out.set(p, at);
    at += p.length;
  }
  return out;
}
