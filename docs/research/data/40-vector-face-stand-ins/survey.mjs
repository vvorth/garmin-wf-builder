// Surveys every scalable (vector) face the SDK device reference publishes:
// face name, family, file stems and how many watch-face-capable devices
// list it, across all language groups.
//   node docs/research/data/40-vector-face-stand-ins/survey.mjs [REFERENCE_DIR]
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const dir = process.argv[2] ?? ".cache/device-reference/devices";
const ids = readdirSync(dir).filter((n) => n.endsWith(".json")).sort();
let faceCapable = 0, withScalable = 0;
const faces = new Map(); // name -> {families:Set, stems:Map(stem->Set(dev)), devices:Set}
for (const file of ids) {
  const d = JSON.parse(readFileSync(join(dir, file), "utf8"));
  if (!d.app_types || !("Watch Face" in d.app_types)) continue;
  faceCapable++;
  let any = false;
  for (const group of Object.values(d.fonts ?? {})) {
    for (const [name, e] of Object.entries(group.scalable ?? {})) {
      any = true;
      let f = faces.get(name);
      if (!f) faces.set(name, (f = { families: new Set(), stems: new Map(), devices: new Set() }));
      f.families.add(e.face);
      f.devices.add(d.id);
      if (!f.stems.has(e.font)) f.stems.set(e.font, new Set());
      f.stems.get(e.font).add(d.id);
    }
  }
  if (any) withScalable++;
}
console.log(`${ids.length} devices, ${faceCapable} watch-face-capable, ${withScalable} publish a scalable face, ${faces.size} face names`);
console.log("| face name | family | file stems (devices) | devices |");
console.log("|---|---|---|---|");
const rows = [...faces].sort((a, b) => b[1].devices.size - a[1].devices.size || a[0].localeCompare(b[0]));
for (const [name, f] of rows) {
  const stems = [...f.stems].sort((a, b) => b[1].size - a[1].size || a[0].localeCompare(b[0])).map(([s, ds]) => `\`${s}\` (${ds.size})`).join(", ");
  console.log(`| \`${name}\` | ${[...f.families].join(" / ")} | ${stems} | ${f.devices.size} |`);
}
const families = new Set(rows.flatMap(([, f]) => [...f.families]));
console.log(`\n${families.size} families: ${[...families].sort().join(", ")}`);
