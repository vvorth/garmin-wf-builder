// The registry's answer for every scalable face the reference publishes:
// face name -> key -> match, licence, file; then each new source pinned.
//   node docs/research/data/40-vector-face-stand-ins/mapping.mjs [REFERENCE_DIR]
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
const r = JSON.parse(readFileSync("ts/src/data/font-registry.json", "utf8"));
const dir = process.argv[2] ?? ".cache/device-reference/devices";
const faces = new Map();
for (const f of readdirSync(dir).filter((n) => n.endsWith(".json"))) {
  const d = JSON.parse(readFileSync(join(dir, f), "utf8"));
  if (!d.app_types || !("Watch Face" in d.app_types)) continue;
  for (const g of Object.values(d.fonts ?? {})) for (const [name, e] of Object.entries(g.scalable ?? {})) {
    if (!faces.has(name)) faces.set(name, { devices: new Set(), files: new Set() });
    faces.get(name).devices.add(d.id); faces.get(name).files.add(e.font);
  }
}
const resolve = (name) => r.names[name] ?? r.patterns.find((p) => new RegExp(p.regex).test(name))?.key ?? null;
const file = (s) => (s.member ? s.member.split("/").pop() : decodeURIComponent(s.url.split("/").pop()));
console.log("| face name | devices | key (files resolve alike) | match | licence | stand-in file | size |\n|---|---|---|---|---|---|---|");
for (const [name, { devices, files }] of [...faces].sort((a, b) => b[1].devices.size - a[1].devices.size || a[0].localeCompare(b[0]))) {
  const key = resolve(name), font = r.fonts[key], s = r.sources[font.source];
  const fileKeys = new Set([...files].map(resolve));
  const same = fileKeys.size === 1 && fileKeys.has(key) ? "" : ` (files: ${[...fileKeys].join(", ")})`;
  console.log(`| \`${name}\` | ${devices.size} | \`${key}\`${same} | ${font.match} | ${s.license} | ${file(s)} | ${(s.size / 1024).toFixed(0)} KB |`);
}
