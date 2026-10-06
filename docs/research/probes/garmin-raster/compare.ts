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
const FAMILIES = ["circles", "arcs", "lines", "polygons", "rects", "text", "swatches"];
const TOLERANCE = 96;
/** Capture pixels per device pixel: the simulator at 100% zoom on a Retina screen. A fitted scale came out 2.016-2.019, pulled by the model differences; 2 overlays the 1 px circles exactly. */
const SCALE = 2;
const SQUARE = 200; // the central square the faces draw in, with a margin
const ZOOM = 4;

installAssets();
process.env["WFB_NO_GARMIN_FONTS"] = "1";
const db = new DeviceDatabase(NodeDeviceFiles.discover(), new NodeFontFiles());

type Rgb = [number, number, number];
const hex = (c: Rgb): string => "#" + c.map((v) => v.toString(16).padStart(2, "0")).join("");
interface Screen { x0: number; y0: number; scale: number }

/**
 * Where the screen sits in a capture: the offset that best overlays the
 * preview's lit pixels on the capture's, at SCALE. The lit boxes' centres
 * give a first guess and a search refines it. The capture's own black is
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
  const misses = (s: Screen): number => {
    let n = 0;
    for (let y = pt!; y < pb!; y++) {
      for (let x = pl!; x < pr!; x++) {
        if (previewLit(x, y) !== capLit(Math.floor(s.x0 + (x + 0.5) * s.scale), Math.floor(s.y0 + (y + 0.5) * s.scale))) n++;
      }
    }
    return n;
  };
  const at = (dx: number, dy: number): Screen => ({ x0: ccx - pcx * SCALE + dx, y0: ccy - pcy * SCALE + dy, scale: SCALE });
  let best = at(0, 0), bestMiss = misses(best);
  for (let dy = -4; dy <= 4; dy += 0.25) {
    for (let dx = -4; dx <= 4; dx += 0.25) {
      const s = at(dx, dy), m = misses(s);
      if (m < bestMiss) [best, bestMiss] = [s, m];
    }
  }
  return best;
}

function compare(family: string, deviceId: string): string {
  const capturePath = join(HERE, "captures", `${family}-${deviceId}.png`);
  if (!existsSync(capturePath)) return `${family} ${deviceId}: no capture`;
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
  const lit = (c: Rgb): boolean => Math.max(...c) > 127;
  const screen = fitScreen(capture, (x, y) => lit(prev(x, y)), width, height);
  const sim = (x: number, y: number): Rgb => {
    const cx = Math.floor(screen.x0 + (x + 0.5) * screen.scale);
    const cy = Math.floor(screen.y0 + (y + 0.5) * screen.scale);
    const i = (cy * capture.width + cx) * 4;
    return [capture.pixels[i]!, capture.pixels[i + 1]!, capture.pixels[i + 2]!];
  };
  const left = Math.floor((width - SQUARE) / 2), top = Math.floor((height - SQUARE) / 2);
  const out = new Uint8Array(SQUARE * ZOOM * SQUARE * ZOOM * 3);
  let differ = 0, previewOnly = 0, simOnly = 0, colour = 0, both = 0;
  const pairs = new Map<string, number>();
  for (let y = 0; y < SQUARE; y++) {
    for (let x = 0; x < SQUARE; x++) {
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
        for (let dx = 0; dx < ZOOM; dx++) out.set(rgb, (((y * ZOOM + dy) * SQUARE * ZOOM) + x * ZOOM + dx) * 3);
      }
    }
  }
  mkdirSync(join(HERE, "diffs"), { recursive: true });
  writeFileSync(join(HERE, "diffs", `${family}-${deviceId}.png`), encodePng(SQUARE * ZOOM, SQUARE * ZOOM, out, 3));
  return `${family.padEnd(9)} ${deviceId.padEnd(16)} scale ${screen.scale.toFixed(3)}  lit both ${String(both).padStart(5)}`
    + `  differ ${String(differ).padStart(5)} (preview only ${previewOnly}, simulator only ${simOnly}, colour ${colour})`
    + [...pairs].filter(([, n]) => n >= 20).map(([k, n]) => `\n    colour ${k} x${n}`).join("");
}

const only = process.argv[2];
for (const family of FAMILIES.filter((f) => only === undefined || f === only)) {
  for (const device of ["fenix8solar47mm", "fenix8solar51mm", "fr955", "fenix847mm"]) console.log(compare(family, device));
}
