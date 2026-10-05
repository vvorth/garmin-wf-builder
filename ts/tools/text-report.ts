// How the TS preview's face-drawn text compares with Python's (Pillow's),
// over every frame the oracle rendered: per run of a system or vector face,
// the ink overlap of the two frames inside the run's box (intersection over
// union) and how far the ink's bounding box moved.
//   node tools/text-report.ts
//
// Ink is a frame pixel with a channel at 128 or more inside the run's box, grown
// by 4 device pixels; the frames are the 2x previews, so offsets are in
// preview pixels (half a device pixel each). Whatever else lies in the box
// is identical in both frames (preview parity), so it only adds to both.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { load } from "../src/build.ts";
import { Bag } from "../src/diagnostics.ts";
import { NodeDeviceFiles, REPO_ROOT } from "../src/devices/node.ts";
import { layers } from "../src/draw/layers.ts";
import { resolve } from "../src/layout.ts";
import { installAssets, repoFileExists } from "../src/node.ts";
import { decodePng } from "../src/png.ts";
import { previewOptions, render } from "../src/preview.ts";
import type { Case } from "./stages.ts";
import { bakedFonts, deviceDatabase } from "./ports/layout.ts";

installAssets();
const ORACLE = join(REPO_ROOT, ".cache", "oracle");
const index = JSON.parse(readFileSync(join(ORACLE, "index.json"), "utf8")) as { designs: { id: string; path: string; devices: string[] }[] };
const files = NodeDeviceFiles.discover();
const SCALE = 2;

interface Row { runs: number; iou: number[]; offset: number[] }
const rows = new Map<string, Row>();
const lowest: [number, string][] = [];

for (const design of index.designs) {
  if (design.devices.length === 0) continue;
  const text = readFileSync(join(REPO_ROOT, design.path), "utf8");
  const face = load(design.path, new Bag(), text, repoFileExists);
  if (face === null) continue;
  for (const device of design.devices) {
    const input = {
      design: design.id, path: design.path, text, device, files,
      oracle: (stage: string) => JSON.parse(readFileSync(join(ORACLE, design.id, device, `${stage}.json`), "utf8")),
    } as unknown as Case;
    const resolved = resolve(face, deviceDatabase(input).get(device), bakedFonts(input));
    const ours = render(resolved, previewOptions());
    const theirs = decodePng(readFileSync(join(ORACLE, design.id, device, "preview.png")))!;
    for (const layer of layers(resolved, previewOptions(), { paintAll: false, images: false })) {
      for (const op of layer.ops ?? []) {
        if (op.op !== "text") continue;
        const ref = layer.fonts.get(op["font"] as string)!;
        if (ref.baked !== null && !ref.vector) continue;
        const key = `${ref.vector ? "vector" : "system"} ${(op["style"] as string | null) ?? "upright"}`;
        const xy = (n: unknown): number => Math.floor(typeof n === "number" ? n : (n as { value: number; add: number }).value + (n as { add: number }).add);
        const ax = xy(op["x"]), ay = xy(op["y"]);
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        for (const item of op["run"] as ({ tile: string; x: number; y: number } | { box: number[] })[]) {
          if (!("tile" in item)) continue;
          const tile = layer.tiles!.images.get(item.tile)!;
          x0 = Math.min(x0, ax + item.x); y0 = Math.min(y0, ay + item.y);
          x1 = Math.max(x1, ax + item.x + tile.width); y1 = Math.max(y1, ay + item.y + tile.height);
        }
        if (x1 < x0) continue;
        const inked = (data: Uint8Array | Uint8ClampedArray, i: number): boolean => Math.max(data[i]!, data[i + 1]!, data[i + 2]!) >= 128;
        let both = 0, either = 0;
        const boxes = [[Infinity, Infinity, -Infinity, -Infinity], [Infinity, Infinity, -Infinity, -Infinity]];
        for (let y = Math.max(0, (y0 - 4) * SCALE); y < Math.min(ours.height, (y1 + 4) * SCALE); y++) {
          for (let x = Math.max(0, (x0 - 4) * SCALE); x < Math.min(ours.width, (x1 + 4) * SCALE); x++) {
            const i = (y * ours.width + x) * 4;
            const flags = [inked(ours.data, i), inked(theirs.pixels, i)];
            if (flags[0] && flags[1]) both++;
            if (flags[0] || flags[1]) either++;
            flags.forEach((f, k) => {
              if (!f) return;
              const b = boxes[k]!;
              b[0] = Math.min(b[0]!, x); b[1] = Math.min(b[1]!, y); b[2] = Math.max(b[2]!, x); b[3] = Math.max(b[3]!, y);
            });
          }
        }
        if (either === 0) continue;
        const iou = both / either;
        const [a, b] = boxes as [number[], number[]];
        const offset = Math.hypot((a[0]! + a[2]!) / 2 - (b[0]! + b[2]!) / 2, (a[1]! + a[3]!) / 2 - (b[1]! + b[3]!) / 2);
        const row = rows.get(key) ?? { runs: 0, iou: [], offset: [] };
        rows.set(key, row);
        row.runs++;
        row.iou.push(iou);
        if (Number.isFinite(offset)) row.offset.push(offset);
        lowest.push([iou, `${design.id} @ ${device}: ${layer.id} ${JSON.stringify(op["text"])} (${key})`]);
      }
    }
  }
}

const mean = (xs: number[]): number => xs.reduce((s, x) => s + x, 0) / Math.max(1, xs.length);
const median = (xs: number[]): number => [...xs].sort((p, q) => p - q)[Math.floor(xs.length / 2)] ?? NaN;
console.log("kind                runs   mean IoU  median IoU  min IoU   mean offset  max offset (preview px)");
for (const [key, row] of [...rows].sort()) {
  console.log(`${key.padEnd(18)}${String(row.runs).padStart(6)}${mean(row.iou).toFixed(3).padStart(11)}${median(row.iou).toFixed(3).padStart(12)}`
    + `${Math.min(...row.iou).toFixed(3).padStart(9)}${mean(row.offset).toFixed(2).padStart(13)}${Math.max(...row.offset).toFixed(2).padStart(12)}`);
}
console.log("\nlowest overlap:");
for (const [iou, what] of lowest.sort((p, q) => p[0] - q[0]).slice(0, 10)) console.log(`  ${iou.toFixed(3)}  ${what}`);
