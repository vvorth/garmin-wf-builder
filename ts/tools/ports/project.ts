// The port of `project`: every generated file for the design's targets,
// resolved with the oracle's baked fonts (its `fonts` dump), so a
// difference is codegen's, not the bake's. A PNG is compared by its pixels.
import { createHash } from "node:crypto";
import { load, resolveAll, selectDevices } from "../../src/build.ts";
import { Bag } from "../../src/diagnostics.ts";
import { generate } from "../../src/emit/project.ts";
import { repoFileExists } from "../../src/node.ts";
import { decodePng } from "../../src/png.ts";
import type { Case } from "../stages.ts";
import { bakedFonts, deviceDatabase, readFont } from "./layout.ts";

export function project(input: Case): unknown {
  const face = load(input.path, new Bag(), input.text, repoFileExists);
  if (face === null) return null;
  const db = deviceDatabase(input);
  const bag = new Bag();
  const devices = selectDevices(face, db, bag, [...face.targets]);
  if (devices.length === 0) return null;
  const [resolved] = resolveAll(face, devices, bag, (_face, device) =>
    bakedFonts({ ...input, device: device.id, oracle: (stage: never) => input.oracle(stage, device.id) } as Case));
  if (resolved.size === 0 || !bag.ok()) return null;
  const generated = generate(face, devices, readFont, { resolved });
  const out: Record<string, unknown> = {};
  for (const [path, content] of [...generated.files()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) {
    if (typeof content === "string") {
      out[path] = { text: content };
    } else if (path.endsWith(".png")) {
      const image = decodePng(content)!;
      out[path] = { png: createHash("sha256").update(image.pixels).digest("hex"), size: [image.width, image.height] };
    } else {
      out[path] = { sha256: createHash("sha256").update(content).digest("hex"), length: content.length };
    }
  }
  return out;
}

/** A text's estimated width constant in a `Layout.mc` set aside: `layout` parity compares every width, recorded deviation included. */
export function estimatedWidths(value: unknown): unknown {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return value;
  return Object.fromEntries(Object.entries(value as Record<string, { text?: string }>).map(([path, file]) => [path,
    !path.endsWith("/Layout.mc") || file.text === undefined ? file
      : { ...file, text: file.text.replace(/(const \w+_WIDTH as Number = )\d+(;\s+\/\/ widest rendering ".*" is )\d+( px \(estimated\))/g, "$1<w>$2<w>$3") }]));
}
