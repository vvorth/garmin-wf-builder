// Extracts the per-device reference from the Connect IQ SDK's offline docs.
//
// Source of truth: `$CIQ_SDK/doc/docs/Device_Reference/<id>.html`, which ships
// inside the SDK zip and is therefore version-pinned to the SDK release. The
// output is derived data, never committed: `tools/setup-env.sh` (and the
// Dockerfile) regenerate it into `.cache/device-reference/` whenever it is
// missing or the SDK changes. `src/devices/` reads it for the facts a
// device's own `compiler.json`/`simulator.json` omit -- the real palette size
// and the per-font pixel metrics -- and `src/fonts/node.ts` for font names.
//
// Output: `<out>/devices/<id>.json` per device, `<out>/devices-index.json`,
// `<out>/source.txt` naming the SDK it was extracted from, and
// `<out>/sdk-version.txt` that SDK's release (its `bin/version.txt`).
//
//   node ts/tools/extract-device-reference.ts --sdk ~/ciq/sdks/9.2.0
import { existsSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { parseArgs } from "node:util";

const REPO_ROOT = resolve(import.meta.dirname, "..", "..");

const TAG_RE = /<[^>]+>/g;
const ROW_RE = /<tr[^>]*>([\s\S]*?)<\/tr>/g;
const CELL_RE = /<t[dh][^>]*>([\s\S]*?)<\/t[dh]>/g;
// A section is a bold paragraph label immediately preceding its table.
const SECTION_RE = /<p[^>]*>\s*<strong[^>]*>([\s\S]*?)<\/strong>\s*<\/p>/g;
const TABLE_RE = /<table[^>]*>[\s\S]*?<\/table>/g;
const TITLE_RE = /<h1[^>]*class="title[^"]*"[^>]*>([\s\S]*?)<\/h1>/;

// ponytail: the entities the SDK's pages use; Python's html.unescape knows every HTML5 name
const ENTITIES: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " ", "#39": "'" };
const unescape = (s: string): string => s.replace(/&(#x[0-9a-f]+|#\d+|\w+);/gi, (whole, name: string) => {
  if (name[0] === "#") return String.fromCodePoint(name[1]?.toLowerCase() === "x" ? parseInt(name.slice(2), 16) : parseInt(name.slice(1), 10));
  return ENTITIES[name] ?? whole;
});

/** Strip tags and collapse whitespace. */
const text = (fragment: string): string => unescape(fragment.replace(TAG_RE, " ")).replace(/\s+/g, " ").trim();

function tableRows(table: string): string[][] {
  const rows: string[][] = [];
  for (const [, row] of table.matchAll(ROW_RE)) {
    const cells = [...row!.matchAll(CELL_RE)].map((m) => text(m[1]!));
    if (cells.some((c) => c !== "")) rows.push(cells);
  }
  return rows;
}

const asInt = (value: string): number | null => (/^\s*[+-]?\d+\s*$/.test(value.replaceAll(",", "")) ? parseInt(value.replaceAll(",", ""), 10) : null);
const parseBool = (value: string): boolean | null => ({ true: true, false: false } as Record<string, boolean>)[value.trim().toLowerCase()] ?? null;

/** `[label, table]` per table, the label empty for the unlabelled attribute table that opens every page. */
function splitSections(html: string): [string, string][] {
  const tables = [...html.matchAll(TABLE_RE)].map((m) => [m.index, m[0]] as const);
  const labels = [...html.matchAll(SECTION_RE)].map((m) => [m.index, text(m[1]!)] as const);
  return tables.map(([pos, table]) => {
    // The nearest bold label before this table, unless another table sits between them.
    const preceding = labels.filter(([lp]) => lp < pos);
    const last = preceding.at(-1);
    const label = last === undefined || tables.some(([op]) => last[0] < op && op < pos) ? "" : last[1];
    return [label, table];
  });
}

type Json = Record<string, unknown>;

function parseDevice(path: string): Json {
  const html = readFileSync(path, "utf8"); // a bad byte decodes as U+FFFD
  const id = basename(path, ".html");
  const dev: Json = { id, source: `doc/docs/Device_Reference/${basename(path)}` };
  const title = TITLE_RE.exec(html);
  if (title) dev["name"] = text(title[1]!);

  const fontsByLang: Json = {};
  const fieldLayouts: Json = {};
  // Language lists sit in a bare paragraph between Fonts tables, labelled in
  // <em> (not <strong>), their codes comma-separated. Missing either quirk
  // puts every language's table on one "default" key, and whichever language
  // sorts last (Thai, Korean) wins over English.
  const langBlocks = [...html.matchAll(/<p[^>]*>\s*<(?:strong|em)[^>]*>\s*Languages\s*<\/(?:strong|em)>\s*<\/p>([\s\S]*?)(?=<p[^>]*>\s*<(?:strong|em)[^>]*>)/g)].map((m) => m[1]!);
  const langQueue = langBlocks.map((b) => text(b).split(",").map((t) => t.trim()).filter((t) => /^[a-z]{3}$/.test(t)));

  for (const [label, table] of splitSections(html)) {
    const rows = tableRows(table);
    if (rows.length === 0) continue;
    const header = rows[0]!.map((c) => c.toLowerCase());
    if (label === "" && header.includes("attribute")) {
      for (const r of rows.slice(1)) if (r.length >= 2) ((dev["attributes"] ??= {}) as Json)[r[0]!] = r[1];
    } else if (label === "App Types" || header.join(" ").includes("memory limit")) {
      const limits: Json = {};
      for (const r of rows.slice(1)) if (r.length >= 2) limits[r[0]!] = { memory_limit_bytes: asInt(r[1]!), notes: r.length > 2 ? r[2] : "" };
      dev["app_types"] = limits;
    } else if (label.endsWith("Layout")) {
      fieldLayouts[label] = rows.slice(1).filter((r) => r.length === rows[0]!.length).map((r) => Object.fromEntries(rows[0]!.map((h, i) => [h, r[i]])));
    } else if (label === "Fonts" || header.join(" ").includes("font symbol")) {
      const langs = langQueue.shift() ?? [];
      const entry = { fixed: {} as Json, scalable: {} as Json };
      for (const r of rows.slice(1)) {
        if (r.length < 4) continue;
        const [symbol, face, size, font] = r as [string, string, string, string];
        if (size.trim().toLowerCase() === "scalable") entry.scalable[symbol] = { face, font };
        else entry.fixed[symbol] = { face, font, size_px: asInt(size) };
      }
      fontsByLang[langs.length > 0 ? langs.join(",") : "default"] = entry;
      // The devices read exactly the "default" key: English, kept under its own key too.
      if (langs.includes("eng")) fontsByLang["default"] = entry;
    }
  }
  if (Object.keys(fontsByLang).length > 0) dev["fonts"] = fontsByLang;
  if (Object.keys(fieldLayouts).length > 0) dev["data_field_layouts"] = fieldLayouts;

  // The handful of attributes read most, normalised.
  const attrs = (dev["attributes"] ?? {}) as Record<string, string>;
  const norm: Json = {};
  if ("Screen Shape" in attrs) norm["screen_shape"] = attrs["Screen Shape"];
  if ("Screen Size" in attrs) {
    const m = /^(\d+)\s*x\s*(\d+)/.exec(attrs["Screen Size"]!);
    if (m) [norm["screen_width"], norm["screen_height"]] = [Number(m[1]), Number(m[2])];
  }
  if ("Display Colors" in attrs) norm["display_colors"] = asInt(attrs["Display Colors"]!);
  if ("Touch" in attrs) norm["touch"] = parseBool(attrs["Touch"]!);
  if ("Buttons" in attrs) norm["buttons"] = attrs["Buttons"]!.split(",").map((b) => b.trim()).filter((b) => b !== "");
  const watchFace = ((dev["app_types"] ?? {}) as Record<string, Json>)["Watch Face"];
  if (watchFace !== undefined && Object.keys(watchFace).length > 0) norm["watchface_memory_bytes"] = watchFace["memory_limit_bytes"];
  dev["normalized"] = norm;
  return dev;
}

const expand = (p: string): string => (p.startsWith("~") ? join(homedir(), p.slice(1)) : p);

const { values } = parseArgs({
  options: {
    sdk: { type: "string", default: process.env["CIQ_SDK"] ?? "" },
    // The SDK release, when --sdk has no bin/version.txt (the Docker build keeps only the doc pages).
    "sdk-version": { type: "string", default: "" },
    out: { type: "string", default: join(REPO_ROOT, ".cache", "device-reference") },
  },
});
const sdk = expand(values.sdk!);
const ref = join(sdk, "doc", "docs", "Device_Reference");
if (!existsSync(ref)) {
  console.error(`error: no Device_Reference at ${ref}`);
  process.exit(1);
}
const out = expand(values.out!);
// Built beside the target and swapped in whole, so a device dropped from a
// newer SDK leaves no stale file and an interrupted run leaves the old one.
const staging = join(dirname(out), basename(out) + ".tmp");
rmSync(staging, { recursive: true, force: true });
mkdirSync(join(staging, "devices"), { recursive: true });
const devices: Json[] = [];
for (const name of readdirSync(ref).filter((n) => n.endsWith(".html")).sort()) {
  if (name.slice(0, -5).toLowerCase() === "overview") continue;
  const dev = parseDevice(join(ref, name));
  writeFileSync(join(staging, "devices", `${dev["id"]}.json`), JSON.stringify(dev, null, 2));
  devices.push(dev);
}
const index = devices.map((d) => ({ id: d["id"], name: d["name"] ?? "", ...(d["normalized"] as Json) }));
writeFileSync(join(staging, "devices-index.json"), JSON.stringify(index, null, 2));
writeFileSync(join(staging, "source.txt"), `${resolve(ref)}\n`);
// The SDK release the pages came from, which `wfb build` compares with the SDK it compiles with.
const versionFile = join(sdk, "bin", "version.txt");
const version = values["sdk-version"] || (existsSync(versionFile) ? readFileSync(versionFile, "utf8").trim() : "");
if (version) writeFileSync(join(staging, "sdk-version.txt"), `${version}\n`);
rmSync(out, { recursive: true, force: true });
renameSync(staging, out);
console.log(`parsed ${devices.length} devices -> ${out}`);
