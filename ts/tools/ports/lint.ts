// The port of `diagnostics-lint`: device selection, resolving and the lint,
// over the design's targets and, apart, the AMOLED `fenix847mm`, each device
// with the oracle's baked fonts (its `fonts` dump), so a difference is the
// lint's, not the bake's.
import { existsSync } from "node:fs";
import { join } from "node:path";
import { load, resolveAll, selectDevices } from "../../src/build.ts";
import { Bag } from "../../src/diagnostics.ts";
import { REPO_ROOT } from "../../src/devices/node.ts";
import { repoFileExists } from "../../src/node.ts";
import type { Case } from "../stages.ts";
import { diagnosticJson } from "./ir.ts";
import { bakedFonts, deviceDatabase, readFont } from "./layout.ts";
import { bakeFonts } from "../../src/emit/resources.ts";

const AMOLED = "fenix847mm";

export function diagnosticsLint(input: Case): unknown {
  const face = load(input.path, new Bag(), input.text, repoFileExists);
  if (face === null) return null;
  const db = deviceDatabase(input);
  const sets: [string, string[]][] = [["targets", [...face.targets]]];
  if (db.ids().includes(AMOLED) && !face.targets.includes(AMOLED)) sets.push([AMOLED, [AMOLED]]);
  const out: Record<string, unknown> = {};
  for (const [name, wanted] of sets) {
    const bag = new Bag();
    const devices = selectDevices(face, db, bag, wanted);
    if (devices.length > 0) {
      resolveAll(face, devices, bag, (_face, device) => {
        // Where Python's bake failed there is no dump: bake here, which fails the same way.
        if (!existsSync(join(REPO_ROOT, ".cache", "oracle", input.design, device.id, "fonts.json"))) return bakeFonts(face, device, readFont);
        return bakedFonts({ ...input, device: device.id, oracle: (stage: never) => input.oracle(stage, device.id) } as Case);
      });
    }
    out[name] = bag.items.map(diagnosticJson);
  }
  return out;
}

/** An `aod-burn-in` diagnostic's measured figures set aside; its severity, anchor and wording stay compared. */
export function burnInFigures(value: unknown): unknown {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return value;
  return Object.fromEntries(Object.entries(value as Record<string, Record<string, unknown>[]>).map(([set, diags]) => [set,
    diags.map((d) => (d["code"] !== "aod-burn-in" ? d : {
      ...d,
      message: String(d["message"]).replace(/\d+(\.\d+)?%|phase \d, dx=\d dy=\d|\d\d:\d\d|top contributor: .*/g, "<measured>"),
      notes: (d["notes"] as string[]).map((n) => n.replace(/[\d,]+ lit pixels at \d\d:\d\d/, "<measured>")),
    }))]));
}
