// The SDK device reference: the per-device pages of the Connect IQ SDK's own
// offline docs (`doc/docs/Device_Reference/<id>.html`), parsed into one JSON
// file per device. The pages ship inside the SDK and are version-pinned to
// its release; the output is derived data, never committed. `./node.ts` reads
// it for the facts a device's own `compiler.json`/`simulator.json` omit --
// the real palette size and the per-font pixel metrics -- and
// `../fonts/node.ts` for font names. Node only.
//
// Output, under `out`: `devices/<id>.json` per device, `devices-index.json`,
// `source.txt` naming the pages it was extracted from, and `sdk-version.txt`
// that SDK's release.
import { existsSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { DEVICE_REFERENCE_PAGES, sdkVersion } from "../sdk.ts";

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

export type Json = Record<string, unknown>;

/** One device's page, `name` its file name (`fr955.html`), as the JSON `devices/<id>.json` holds. */
export function parseDevicePage(html: string, name: string): Json {
  const id = basename(name, ".html");
  const dev: Json = { id, source: `${DEVICE_REFERENCE_PAGES}/${basename(name)}` };
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



/** The folder of pages under an SDK root. */
export const referencePages = (sdkRoot: string): string => join(sdkRoot, ...DEVICE_REFERENCE_PAGES.split("/"));

/** The SDK release a reference at `out` was extracted from, or `null` when it records none. */
export function referenceVersion(out: string): string | null {
  try {
    return readFileSync(join(out, "sdk-version.txt"), "utf8").trim() || null;
  } catch {
    return null;
  }
}

/** Whether the reference at `out` was extracted from `sdkRoot`'s pages, at release `version`. */
export function referenceIsFrom(out: string, sdkRoot: string, version: string = sdkVersion(sdkRoot)): boolean {
  if (!existsSync(join(out, "devices"))) return false;
  let source: string;
  try {
    source = readFileSync(join(out, "source.txt"), "utf8").trim();
  } catch {
    return false;
  }
  return source === resolve(referencePages(sdkRoot)) && referenceVersion(out) === version;
}

/**
 * Extract the reference from the SDK at `sdkRoot` into `out`, whole: built
 * beside the target and swapped in, so a device dropped from a newer SDK
 * leaves no stale file and an interrupted run leaves the old reference.
 * `version` is the SDK's release when `sdkRoot` has no `bin/version.txt`
 * (an SDK pruned to its doc pages). Returns how many devices it parsed.
 */
export function extractDeviceReference(sdkRoot: string, out: string, version: string = sdkVersion(sdkRoot)): number {
  const pages = referencePages(sdkRoot);
  if (!existsSync(pages)) throw new Error(`no ${DEVICE_REFERENCE_PAGES} under ${sdkRoot}`);
  const staging = join(dirname(out), `${basename(out)}.tmp`);
  rmSync(staging, { recursive: true, force: true });
  mkdirSync(join(staging, "devices"), { recursive: true });
  const devices: Json[] = [];
  for (const name of readdirSync(pages).filter((n) => n.endsWith(".html")).sort()) {
    if (name.slice(0, -5).toLowerCase() === "overview") continue;
    const dev = parseDevicePage(readFileSync(join(pages, name), "utf8"), name); // a bad byte decodes as U+FFFD
    writeFileSync(join(staging, "devices", `${dev["id"]}.json`), JSON.stringify(dev, null, 2));
    devices.push(dev);
  }
  const index = devices.map((d) => ({ id: d["id"], name: d["name"] ?? "", ...(d["normalized"] as Json) }));
  writeFileSync(join(staging, "devices-index.json"), JSON.stringify(index, null, 2));
  writeFileSync(join(staging, "source.txt"), `${resolve(pages)}\n`);
  // The SDK release the pages came from, which `wfb build` compares with the SDK it compiles with.
  if (version) writeFileSync(join(staging, "sdk-version.txt"), `${version}\n`);
  rmSync(out, { recursive: true, force: true });
  renameSync(staging, out);
  return devices.length;
}
