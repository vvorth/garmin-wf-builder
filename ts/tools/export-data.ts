// Regenerates the tables in src/data/ that are copies of files elsewhere,
// so the browser has them without a file system: the support barrel
// (`runtime-lib/*.mc`), the starters `wfb new` and the editor's New offer
// (`templates/*.yaml`, with `templates/blurbs.json`, and any binary assets a
// template needs under `templates/assets/<name>/`, base64), and the hand
// presets (`templates/hands/sets.yaml`). The other tables in src/data/ are
// the source themselves.
//
//   node ts/tools/export-data.ts           # rewrite them
//   node ts/tools/export-data.ts --check   # exit 1, naming the stale ones
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { REPO_ROOT } from "../src/devices/node.ts";

const TS = join(REPO_ROOT, "ts");
const TEMPLATES = join(TS, "templates");
const read = (path: string): string => readFileSync(path, "utf8");
const yamlNames = (dir: string): string[] => readdirSync(dir).filter((n) => n.endsWith(".yaml")).sort();

/** `assets/<filename>` -> base64, for a template's own asset directory, if it has one. */
function templateFiles(name: string): Record<string, string> | undefined {
  const dir = join(TEMPLATES, "assets", name);
  if (!existsSync(dir)) return undefined;
  return Object.fromEntries(readdirSync(dir).sort()
    .map((n) => [`assets/${n}`, readFileSync(join(dir, n)).toString("base64")]));
}

export function tables(): Record<string, unknown> {
  const blurbs = JSON.parse(read(join(TEMPLATES, "blurbs.json"))) as Record<string, string>;
  return {
    "runtime-lib.json": Object.fromEntries(readdirSync(join(REPO_ROOT, "runtime-lib")).filter((n) => n.endsWith(".mc")).sort()
      .map((n) => [n, read(join(REPO_ROOT, "runtime-lib", n))])),
    "templates.json": Object.fromEntries(yamlNames(TEMPLATES).map((n) => {
      const name = n.slice(0, -5);
      const files = templateFiles(name);
      return [name, { blurb: blurbs[name] ?? "", text: read(join(TEMPLATES, n)), ...(files ? { files } : {}) }];
    })),
    "hand-sets.json": { text: read(join(TEMPLATES, "hands", "sets.yaml")) },
  };
}

/** The stale tables' names, after rewriting them unless `check`. */
export function exportData(check: boolean): string[] {
  const stale: string[] = [];
  for (const [name, value] of Object.entries(tables())) {
    const path = join(TS, "src", "data", name), text = JSON.stringify(value, null, 1) + "\n";
    if (existsSync(path) && read(path) === text) continue;
    stale.push(name);
    if (!check) writeFileSync(path, text);
  }
  return stale;
}

if (import.meta.filename === process.argv[1]) {
  const check = process.argv.includes("--check");
  const stale = exportData(check);
  if (check && stale.length > 0) {
    console.error(`stale: ${stale.join(", ")} -- run node ts/tools/export-data.ts`);
    process.exit(1);
  }
}
