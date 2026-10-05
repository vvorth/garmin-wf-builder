// The ports of the `draw` and `preview` stages: the oracle's baked fonts
// (its `fonts` dump) laid out on the device, then drawn, so a difference
// here is the draw program's or the renderer's, not the bake's.
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { load } from "../../src/build.ts";
import { Bag } from "../../src/diagnostics.ts";
import { REPO_ROOT } from "../../src/devices/node.ts";
import { layers } from "../../src/draw/layers.ts";
import { resolve, type ResolvedFace } from "../../src/layout.ts";
import { repoFileExists } from "../../src/node.ts";
import { decodePng } from "../../src/png.ts";
import { previewOptions, render } from "../../src/preview.ts";
import type { Case } from "../stages.ts";
import { irJson } from "./ir.ts";
import { bakedFonts, deviceDatabase } from "./layout.ts";

function resolved(input: Case): ResolvedFace | null {
  const face = load(input.path, new Bag(), input.text, repoFileExists);
  if (face === null) return null;
  return resolve(face, deviceDatabase(input).get(input.device!), bakedFonts(input));
}

/** The port of `draw`: each layer's JSON ops and the fonts they name. */
export function draw(input: Case): unknown {
  const r = resolved(input);
  if (r === null) return null;
  return layers(r, previewOptions(), { paintAll: false, images: false }).map((layer) => ({
    id: layer.id, kind: layer.kind, ops: layer.ops === null ? null : irJson(layer.ops, false),
    fonts: irJson(layer.fonts, false),
  }));
}

/**
 * The port of `preview`: the rendered frame's hash, as the oracle dumps it.
 * When the frame differs, `outside_text` says whether every differing pixel
 * lies inside a system-font or vector-font run's box, the one difference
 * recorded as deliberate.
 */
export function preview(input: Case): unknown {
  const r = resolved(input);
  if (r === null) return null;
  const image = render(r, previewOptions());
  const rgb = new Uint8Array(image.width * image.height * 3);
  for (let i = 0, j = 0; i < image.data.length; i += 4, j += 3) {
    rgb[j] = image.data[i]!;
    rgb[j + 1] = image.data[i + 1]!;
    rgb[j + 2] = image.data[i + 2]!;
  }
  const sha256 = createHash("sha256").update(rgb).digest("hex");
  const out: Record<string, unknown> = { png: "preview.png", mode: "RGB", size: [image.width, image.height], sha256 };
  const expected = input.oracle("preview") as { sha256: string };
  if (expected.sha256 !== sha256) {
    const path = join(REPO_ROOT, ".cache", "oracle", input.design, input.device!, "preview.png");
    const png = existsSync(path) ? decodePng(readFileSync(path)) : null;
    if (png !== null && png.width === image.width && png.height === image.height) {
      const boxes = textBoxes(r);
      const scale = 2;
      let outside = 0;
      for (let y = 0; y < image.height; y++) {
        for (let x = 0; x < image.width; x++) {
          const i = (y * image.width + x) * 4;
          if (png.pixels[i] === image.data[i] && png.pixels[i + 1] === image.data[i + 1] && png.pixels[i + 2] === image.data[i + 2]) continue;
          const dx = Math.floor(x / scale), dy = Math.floor(y / scale);
          if (!boxes.some(([x0, y0, x1, y1]) => dx >= x0 && dx < x1 && dy >= y0 && dy < y1)) outside++;
        }
      }
      out["outside_text"] = outside === 0 ? "equal" : `${outside} pixels differ`;
    }
  }
  return out;
}

/**
 * Device-pixel boxes of every run drawn from a system or vector face's
 * outlines, grown by 2 px, or 4 px for a turned run: Pillow turns its run as
 * a bitmap (bicubic) and downsamples it (Lanczos, 3 px of support), which
 * leaves a faint halo past the ink.
 */
function textBoxes(r: ResolvedFace): [number, number, number, number][] {
  const out: [number, number, number, number][] = [];
  for (const layer of layers(r, previewOptions(), { paintAll: false, images: false })) {
    if (layer.ops === null) continue;
    for (const op of layer.ops) {
      if (op.op !== "text") continue;
      const ref = layer.fonts.get(op["font"] as string)!;
      if (ref.baked !== null && !ref.vector) continue;
      const tiles = layer.tiles!;
      const m = op["style"] === null ? 2 : 4;
      const x = op["x"] as number | { value: number; add: number }, y = op["y"] as number | { value: number; add: number };
      const ax = Math.floor(typeof x === "number" ? x : x.value + x.add), ay = Math.floor(typeof y === "number" ? y : y.value + y.add);
      for (const item of op["run"] as ({ tile: string; x: number; y: number } | { box: number[] })[]) {
        if (!("tile" in item)) continue;
        const tile = tiles.images.get(item.tile)!;
        out.push([ax + item.x - m, ay + item.y - m, ax + item.x + tile.width + m, ay + item.y + tile.height + m]);
      }
      // the line box too: Pillow's glyphs can fall where ours leave no ink
      const box = op["box"] as number[] | null;
      if (box !== null) out.push([box[0]! - 2, box[1]! - 2, box[0]! + box[2]! + 2, box[1]! + box[3]! + 2]);
    }
  }
  return out;
}

/** A preview whose only differences lie in system-font and vector-font runs, its hash set aside. */
export function outsideText(value: unknown): unknown {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return value;
  const { sha256: _, outside_text: outside, ...rest } = value as Record<string, unknown>;
  return { ...rest, outside_text: outside ?? "equal" };
}

/** A layer's runs drawn from a system or vector face, set aside, and every tile renumbered by first use. */
export function faceRuns(value: unknown): unknown {
  if (!Array.isArray(value)) return value;
  const ids = new Map<string, string>();
  return value.map((layer: Record<string, unknown>) => {
    const fonts = (layer["fonts"] ?? {}) as Record<string, { baked: string | null; vector: boolean }>;
    const ops = layer["ops"] as Record<string, unknown>[] | null;
    if (ops === null) return layer;
    return {
      ...layer,
      ops: ops.map((op) => {
        if (op["op"] !== "text" && op["op"] !== "glyph") return op;
        const ref = fonts[op["font"] as string];
        if (op["op"] === "text" && ref !== undefined && (ref.baked === null || ref.vector)) return { ...op, run: "<rasterised>" };
        return {
          ...op,
          run: (op["run"] as Record<string, unknown>[]).map((item) => {
            if (!("tile" in item)) return item;
            const id = item["tile"] as string;
            if (!ids.has(id)) ids.set(id, `t${ids.size}`);
            return { ...item, tile: ids.get(id) };
          }),
        };
      }),
    };
  });
}

/** Every non-integral number to 10 significant digits. */
export function lastBits(value: unknown): unknown {
  if (typeof value === "number") return Number.isInteger(value) ? value : Number(value.toPrecision(10));
  if (Array.isArray(value)) return value.map(lastBits);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, lastBits(v)]));
  }
  return value;
}
