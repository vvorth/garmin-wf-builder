// A screen's visible area, read from the simulator skin..
//
// The skin PNG a device's `simulator.json` names is transparent exactly
// where the panel shows through: inside `display.location`, alpha 0 is lit
// panel and alpha 255 bezel. That is a per-device mask at the panel's own
// resolution, for every screen that is not round (round keeps its analytic
// circle). The lint allows one pixel of tolerance (`hidden`): the skins
// anti-alias their edges.
import type { Device } from "./devices/device.ts";
import { decodePng } from "./png.ts";

/** A skin pixel counts as panel below this alpha. */
export const ALPHA_VISIBLE_BELOW = 128;

interface MaskInk {
  bounds(): [number, number, number, number];
  contains(px: number, py: number): boolean;
}

/** One device's visible area: `visible` row-major, 1 where the panel shows; `hidden` the columns of each row the lint treats as hidden. */
export class VisibleMask {
  readonly width: number;
  readonly height: number;
  readonly visible: Uint8Array;
  readonly hidden: Map<number, number[]>;

  constructor(width: number, height: number, visible: Uint8Array, hidden: Map<number, number[]>) {
    this.width = width;
    this.height = height;
    this.visible = visible;
    this.hidden = hidden;
  }

  get visibleCount(): number {
    return this.visible.reduce((a, b) => a + b, 0);
  }

  /** Does no pixel the ink covers, tested at pixel centres, fall on a hidden pixel? */
  admits(ink: MaskInk): boolean {
    const [left, top, right, bottom] = ink.bounds();
    for (let y = Math.max(0, Math.trunc(top) - 1); y < Math.min(this.height, Math.trunc(bottom) + 2); y++) {
      for (const x of this.hidden.get(y) ?? []) {
        if (left - 1 <= x && x <= right + 1 && ink.contains(x + 0.5, y + 0.5)) return false;
      }
    }
    return true;
  }
}

/** The device's skin file name and the panel's `[x, y, width, height]` in it, when both fit the panel's size. */
export function skin(device: Device): [string, [number, number, number, number]] | null {
  const name = device.skinName, location = device.displayLocation;
  if (name === null || location === null) return null;
  if (location[2] !== device.width || location[3] !== device.height) return null;
  return [name, location];
}

const masks = new WeakMap<Device, VisibleMask | null>();

/** The device's mask, or `null` when its skin or panel location is missing or does not fit. */
export function visibleMask(device: Device): VisibleMask | null {
  if (!masks.has(device)) masks.set(device, load(device));
  return masks.get(device)!;
}

function load(device: Device): VisibleMask | null {
  const found = skin(device);
  if (found === null) return null;
  const [name, [x, y, width, height]] = found;
  const bytes = device.db.files.file(device.id, name);
  const image = bytes === undefined ? null : decodePng(bytes);
  if (image === null || x < 0 || y < 0 || x + width > image.width || y + height > image.height) return null;
  const covered = new Uint8Array(width * height);
  for (let row = 0; row < height; row++) {
    for (let col = 0; col < width; col++) {
      covered[row * width + col] = image.pixels[((y + row) * image.width + x + col) * 4 + 3]! < ALPHA_VISIBLE_BELOW ? 0 : 1;
    }
  }
  const visible = covered.map((v) => (v ? 0 : 1));
  // Hidden with tolerance: covered, and so is every 8-neighbour, edges replicated.
  const hidden = new Map<number, number[]>();
  const at = (r: number, c: number): number => covered[Math.min(height - 1, Math.max(0, r)) * width + Math.min(width - 1, Math.max(0, c))]!;
  for (let row = 0; row < height; row++) {
    for (let col = 0; col < width; col++) {
      let firm = 1;
      for (let dr = -1; dr <= 1 && firm; dr++) for (let dc = -1; dc <= 1 && firm; dc++) firm = at(row + dr, col + dc);
      if (firm) {
        const list = hidden.get(row);
        if (list) list.push(col); else hidden.set(row, [col]);
      }
    }
  }
  return new VisibleMask(width, height, visible, hidden);
}
