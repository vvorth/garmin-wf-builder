import { decodePng, pngSize, type RgbaImage } from "./png.ts";
import type { Tile } from "./raster/pillow.ts";

/** Embedded PNGs keep a design portable through the browser and the build server. */
export function readBitmap(png: string): RgbaImage {
  if (png.length > 8 * 1024 * 1024 || !/^[A-Za-z0-9+/]+={0,2}$/.test(png)) throw new Error("png must be base64-encoded PNG data, up to 8 MB");
  const bytes = Uint8Array.from(atob(png), (c) => c.charCodeAt(0));
  const size = pngSize(bytes);
  if (!size || size.some((n) => n < 1 || n > 1024)) throw new Error("PNG must be non-interlaced, 8/16-bit, and at most 1024×1024 pixels");
  const image = decodePng(bytes);
  if (!image) throw new Error("PNG could not be decoded");
  return image;
}

/** Nearest-neighbour zoom preserves the bitmap's alpha as well as its colours. */
export function bitmapTile(image: RgbaImage, scale: number): Tile {
  const width = Math.round(image.width * scale), height = Math.round(image.height * scale);
  if (scale === 1) return { width, height, data: image.pixels, kind: "rgba" };
  const data = new Uint8Array(width * height * 4);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const from = (Math.floor(y / scale) * image.width + Math.floor(x / scale)) * 4;
    data.set(image.pixels.subarray(from, from + 4), (y * width + x) * 4);
  }
  return { width, height, data, kind: "rgba" };
}
