// Compares each simulator capture (captures/<family>-<device>.png) with the
// preview's frame of the same face on the same device, pixel for pixel.
//
//   node docs/research/probes/garmin-raster/compare.ts [family]
//
// The simulator draws the screen at 2x and smoothed, so the screen's offset
// is fitted to the content (fitScreen), each device pixel
// is read at its centre, and a pixel
// differs when any channel is off by more than TOLERANCE. It prints one
// line per capture and writes diffs/<family>-<device>.png: the central
// square at 4x, white where both light a pixel, red where only the preview
// does, green where only the simulator does.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { load, resolveAll, selectDevices } from "../../../../ts/src/build.ts";
import { DeviceDatabase } from "../../../../ts/src/devices/device.ts";
import { NodeDeviceFiles } from "../../../../ts/src/devices/node.ts";
import { Bag } from "../../../../ts/src/diagnostics.ts";
import { bakeFonts } from "../../../../ts/src/emit/resources.ts";
import { NodeFontFiles } from "../../../../ts/src/fonts/node.ts";
import { installAssets, readFontFile } from "../../../../ts/src/node.ts";
import { decodePng, encodePng } from "../../../../ts/src/png.ts";
import { previewOptions, render } from "../../../../ts/src/preview.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const FAMILIES = ["circles", "arcs", "lines", "polygons", "rects", "text", "swatches", "ellipses", "lines2", "rects2", "rotated",
  "big_circles", "big_fills", "big_ellipses", "big_lines", "big_rects", "big_arcs"];
const TOLERANCE = 96;
/** Capture pixels per device pixel: the simulator at 100% zoom on a Retina screen. A fitted scale came out 2.016-2.019, pulled by the model differences; 2 overlays the 1 px circles exactly. */
const SCALE = 2;
const SQUARE = 200; // the central square the small faces draw in, with a margin

/** The device pixels compared: the central square, or for a `big_` face the whole round screen but its outermost 2 px. */
function region(family: string, width: number, height: number): { left: number; top: number; size: number; inside: (x: number, y: number) => boolean } {
  if (!family.startsWith("big_")) {
    const left = Math.floor((width - SQUARE) / 2), top = Math.floor((height - SQUARE) / 2);
    return { left, top, size: SQUARE, inside: () => true };
  }
  const r = width / 2 - 2;
  return { left: 0, top: 0, size: width, inside: (x, y) => (x + 0.5 - width / 2) ** 2 + (y + 0.5 - height / 2) ** 2 <= r * r };
}

/** The devices a probe face targets. */
function targets(family: string): string[] {
  const text = readFileSync(join(HERE, "faces", family, "face.yaml"), "utf8");
  return /^ {2}targets: \[(.*)\]$/m.exec(text)![1]!.split(",").map((d) => d.trim());
}
const ZOOM = 4;

installAssets();
process.env["WFB_NO_GARMIN_FONTS"] = "1";
const db = new DeviceDatabase(NodeDeviceFiles.discover(), new NodeFontFiles());

type Rgb = [number, number, number];
const hex = (c: Rgb): string => "#" + c.map((v) => v.toString(16).padStart(2, "0")).join("");
interface Screen { x0: number; y0: number; scale: number }

/**
 * Where the screen sits in a capture, at SCALE: the 2x2 blocks' phase from
 * the capture alone, then the whole-pixel offset that best overlays the
 * preview's lit pixels on the capture's. The capture's own black is
 * too noisy (bezel and screen both near 0) to find the disk by.
 */
function fitScreen(capture: { width: number; height: number; pixels: Uint8Array }, previewLit: (x: number, y: number) => boolean,
  width: number, height: number): Screen {
  const capLit = (x: number, y: number): boolean => {
    if (x < 0 || y < 0 || x >= capture.width || y >= capture.height) return false;
    const i = (y * capture.width + x) * 4;
    return Math.max(capture.pixels[i]!, capture.pixels[i + 1]!, capture.pixels[i + 2]!) > 127;
  };
  const box = (w: number, h: number, lit: (x: number, y: number) => boolean, x0: number, y0: number): number[] => {
    let [l, t, r, b] = [Infinity, Infinity, -Infinity, -Infinity];
    for (let y = y0; y < h; y++) for (let x = x0; x < w; x++) if (lit(x, y)) { l = Math.min(l, x); t = Math.min(t, y); r = Math.max(r, x + 1); b = Math.max(b, y + 1); }
    return [l, t, r, b];
  };
  const [pl, pt, pr, pb] = box(width, height, previewLit, 0, 0);
  // Search the window's middle, as wide as the content at up to 2.6x: not the bezel's numerals or the window's white margin.
  const hw = Math.round(((pr! - pl!) / 2 + 4) * 2.6), hh = Math.round(((pb! - pt!) / 2 + 4) * 2.6);
  const wx = Math.round(capture.width / 2), wy = Math.round(capture.height / 2);
  const [cl, ct, cr, cb] = box(wx + hw, wy + hh, capLit, wx - hw, wy - hh);
  const pcx = (pl! + pr!) / 2, pcy = (pt! + pb!) / 2, ccx = (cl! + cr!) / 2, ccy = (ct! + cb!) / 2;
  // The block phase from the capture alone: a device pixel is a 2x2 block, so pairs inside a block differ least.
  const lum = (x: number, y: number): number => {
    const i = (y * capture.width + x) * 4;
    return capture.pixels[i]! + capture.pixels[i + 1]! + capture.pixels[i + 2]!;
  };
  const phase = (across: boolean): number => {
    const cost = [0, 0];
    for (let y = ct!; y < cb!; y++) {
      for (let x = cl!; x < cr!; x++) {
        const k = across ? x : y;
        cost[k % 2]! += Math.abs(lum(x, y) - (across ? lum(x + 1, y) : lum(x, y + 1)));
      }
    }
    return cost[0]! <= cost[1]! ? 0 : 1;
  };
  const [px, py] = [phase(true), phase(false)];
  const misses = (s: Screen): number => {
    let n = 0;
    for (let y = pt!; y < pb!; y++) {
      for (let x = pl!; x < pr!; x++) if (previewLit(x, y) !== capLit(s.x0 + x * SCALE + 1, s.y0 + y * SCALE + 1)) n++;
    }
    return n;
  };
  // The whole-pixel offset, from two starts, each refined by full misses: the lit boxes' centres
  // (right for a small face, whose own box the bezel stays clear of), and a search of the whole window
  // for the offset where a sample of the preview's pixels, lit and dark alike, agrees most with the
  // capture (right for a face reaching the rim, where the centred box takes in the bezel's ticks).
  const refine = (start: Screen, reach: number): [Screen, number] => {
    let best = start, bestMiss = misses(start);
    for (let dy = -reach; dy <= reach; dy++) {
      for (let dx = -reach; dx <= reach; dx++) {
        const s = { x0: start.x0 + dx * SCALE, y0: start.y0 + dy * SCALE, scale: SCALE }, m = misses(s);
        if (m < bestMiss) [best, bestMiss] = [s, m];
      }
    }
    return [best, bestMiss];
  };
  const snap = (v: number, p: number): number => Math.round((v - p) / SCALE) * SCALE + p;
  const centred = refine({ x0: snap(ccx - pcx * SCALE, px), y0: snap(ccy - pcy * SCALE, py), scale: SCALE }, 3);
  const lit: [number, number][] = [], dark: [number, number][] = [];
  for (let y = pt!; y < pb!; y++) for (let x = pl!; x < pr!; x++) (previewLit(x, y) ? lit : dark).push([x, y]);
  const every = <T>(list: T[], n: number): T[] => list.filter((_, i) => i % Math.max(1, Math.floor(list.length / n)) === 0);
  const probe = [...every(lit, 200), ...every(dark, 200)].map(([x, y]) => [x, y, previewLit(x, y)] as const);
  let found: Screen = { x0: px, y0: py, scale: SCALE }, bestAgree = -1;
  for (let y0 = py - pt! * SCALE; y0 + pb! * SCALE <= capture.height; y0 += 4 * SCALE) {
    for (let x0 = px - pl! * SCALE; x0 + pr! * SCALE <= capture.width; x0 += 4 * SCALE) {
      let agree = 0;
      for (const [x, y, on] of probe) if (capLit(x0 + x * SCALE + 1, y0 + y * SCALE + 1) === on) agree++;
      if (agree > bestAgree) [found, bestAgree] = [{ x0, y0, scale: SCALE }, agree];
    }
  }
  const searched = refine(found, 4);
  const best = searched[1] < centred[1] ? searched[0] : centred[0];
  return best;
}

/** A capture overlaid on the preview: the preview's frame, and each device pixel's colour in the capture. */
export function overlay(family: string, deviceId: string): { width: number; height: number; prev: (x: number, y: number) => Rgb; sim: (x: number, y: number) => Rgb } | null {
  const capturePath = join(HERE, "captures", `${family}-${deviceId}.png`);
  if (!existsSync(capturePath)) return null;
  const capture = decodePng(new Uint8Array(readFileSync(capturePath)))!;
  const path = join(HERE, "faces", family, "face.yaml");
  const bag = new Bag();
  const face = load(path, bag, readFileSync(path, "utf8"), existsSync)!;
  const devices = selectDevices(face, db, bag, [deviceId]);
  const [resolved] = resolveAll(face, devices, bag, (f, d) => bakeFonts(f, d, readFontFile));
  const frame = render(resolved.get(deviceId)!, previewOptions({ scale: 1, mask_shape: false }));
  const { width, height } = frame;
  const prev = (x: number, y: number): Rgb => {
    const i = (y * width + x) * 4;
    return [frame.data[i]!, frame.data[i + 1]!, frame.data[i + 2]!];
  };
  const screen = fitScreen(capture, (x, y) => lit(prev(x, y)), width, height);
  // A device pixel's colour: its 2x2 block's mean, which the smoothing bleeds into least.
  const sim = (x: number, y: number): Rgb => {
    const out: Rgb = [0, 0, 0];
    for (let dy = 0; dy < SCALE; dy++) {
      for (let dx = 0; dx < SCALE; dx++) {
        const i = ((screen.y0 + y * SCALE + dy) * capture.width + screen.x0 + x * SCALE + dx) * 4;
        for (let k = 0; k < 3; k++) out[k]! += capture.pixels[i + k]! / (SCALE * SCALE);
      }
    }
    return out.map(Math.round) as Rgb;
  };
  return { width, height, prev, sim };
}

export const lit = (c: Rgb): boolean => Math.max(...c) > 127;

/** The pixels lit in one of the capture and the preview but not the other, in the compared region. */
export function misses(family: string, deviceId: string): number {
  const { width, height, prev, sim } = overlay(family, deviceId)!;
  const { left, top, size, inside } = region(family, width, height);
  let n = 0;
  for (let y = top; y < top + size; y++) for (let x = left; x < left + size; x++) if (inside(x, y) && lit(prev(x, y)) !== lit(sim(x, y))) n++;
  return n;
}

function compare(family: string, deviceId: string): string {
  const o = overlay(family, deviceId);
  if (o === null) return `${family} ${deviceId}: no capture`;
  const { width, height, prev, sim } = o;
  const { left, top, size, inside } = region(family, width, height);
  const out = new Uint8Array(size * ZOOM * size * ZOOM * 3);
  let differ = 0, previewOnly = 0, simOnly = 0, colour = 0, both = 0;
  const pairs = new Map<string, number>();
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      if (!inside(left + x, top + y)) continue;
      const p = prev(left + x, top + y), s = sim(left + x, top + y);
      const off = p.some((v, k) => Math.abs(v - s[k]!) > TOLERANCE);
      let rgb: Rgb = [0, 0, 0];
      if (lit(p) && lit(s)) { both++; rgb = [255, 255, 255]; }
      if (off) {
        differ++;
        if (lit(p) && !lit(s)) { previewOnly++; rgb = [255, 0, 0]; }
        else if (!lit(p) && lit(s)) { simOnly++; rgb = [0, 255, 0]; }
        else {
          colour++;
          rgb = [255, 160, 0];
          const key = `${hex(p)}->${hex(s)}`;
          pairs.set(key, (pairs.get(key) ?? 0) + 1);
        }
      }
      for (let dy = 0; dy < ZOOM; dy++) {
        for (let dx = 0; dx < ZOOM; dx++) out.set(rgb, (((y * ZOOM + dy) * size * ZOOM) + x * ZOOM + dx) * 3);
      }
    }
  }
  mkdirSync(join(HERE, "diffs"), { recursive: true });
  writeFileSync(join(HERE, "diffs", `${family}-${deviceId}.png`), encodePng(size * ZOOM, size * ZOOM, out, 3));
  return `${family.padEnd(9)} ${deviceId.padEnd(16)}  lit both ${String(both).padStart(5)}`
    + `  differ ${String(differ).padStart(5)} (preview only ${previewOnly}, simulator only ${simOnly}, colour ${colour})`
    + [...pairs].filter(([, n]) => n >= 20).map(([k, n]) => `\n    colour ${k} x${n}`).join("");
}

if (import.meta.filename === process.argv[1]) {
  const only = process.argv[2];
  for (const family of FAMILIES.filter((f) => only === undefined || f === only)) {
    for (const device of targets(family)) console.log(compare(family, device));
  }
}
