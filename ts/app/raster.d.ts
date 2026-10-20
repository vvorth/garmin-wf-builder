// `dist/raster.js` (src/raster/canvas.ts, bundled by the server) as the
// page's type check sees it: the exports the canvas draws with, declared
// to the real signatures by hand, with the two `raster/pillow.ts` types
// they take. Hand-written so the compiler's sources stay out of the page's
// programs: tsconfig.app-js.json checks whatever it reaches with strict
// off, and misreads code written for strict. test/page-modules.test.ts
// holds this declaration to the real module.
import type { JsonOp, LiveHandle } from "../src/studio/protocol.ts";

/** `raster/pillow.ts`'s `Image`: RGBA bytes, a row at a time. */
export interface Image {
  width: number;
  height: number;
  data: Uint8ClampedArray;
}

/** `raster/pillow.ts`'s `Tile`: a tile to paste, a "mask" tinted through its alpha, or an "rgba" image through its own alpha. RGBA bytes. */
export interface Tile {
  width: number;
  height: number;
  kind: "mask" | "rgba";
  data: Uint8Array | Uint8ClampedArray;
}

export type Rgb = readonly [number, number, number] | [number, number, number];

/** A frame's packed tiles (`protocol.ts`'s `Tiles`): base64 zlib data and each tile's offset, width, height and kind. */
export interface PackedTiles {
  data: string;
  index: Record<string, [number, number, number, "mask" | "rgba"]>;
}

/** A blank image of `ground` (black when absent). */
export function image(width: number, height: number, ground?: Rgb): Image;
/** `ops` drawn on `im` at `scale`. */
export function drawOps(im: Image, ops: readonly JsonOp[], tiles: Record<string, Tile>, scale: number): void;
/** `rgba` pasted on `im` at (x, y) through its own alpha. */
export function composite(im: Image, rgba: { width: number; height: number; data: Uint8Array | Uint8ClampedArray }, x: number, y: number): void;
/** The frame's packed tiles inflated, by tile id. */
export function inflateTiles(packed: PackedTiles): Promise<Record<string, Tile>>;
/** `ops` moved by whole device pixels. */
export function translateOps(ops: readonly JsonOp[], dx: number, dy: number): JsonOp[];
/** Where `ops` leave ink: `box` in frame pixels (exclusive ends, `null` for none), `mask` one byte a pixel over it. */
export function inkOf(ops: readonly JsonOp[], tiles: Record<string, Tile>, width: number, height: number, scale: number): { box: [number, number, number, number] | null; mask: Uint8Array };
/** `ops` as they will be once a live handle has been dragged `delta` pixels of extent, or to `degrees` (12 o'clock, clockwise). */
export function liveOps(ops: readonly JsonOp[], live: LiveHandle, change?: { delta?: number; degrees?: number }): JsonOp[];
