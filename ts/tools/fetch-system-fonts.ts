// Prefetches the free stand-ins for Garmin's system fonts that the given
// devices need.
//
// Each device's needed font names come from its installed `simulator.json`'s
// `ww` font set, else from the SDK device reference's default-language table
// (`deviceNeededNames`). Each name is resolved to a font-key of
// `src/data/font-registry.json` and its pinned source downloaded, unzipped
// when it is an archive member, hash-checked and installed into
// `ts/assets/system-fonts/` with its licence. Several keys can share one
// source, and several sources one archive: each archive is downloaded once.
// Re-running is cheap: a key already installed with its pinned bytes is left
// alone.
//
//   node ts/tools/fetch-system-fonts.ts [--device ID ...] [--all] [DEST]
//
// With no `--device`, every installed device's fonts; `--all`, every device
// the SDK device reference has a file for (the Docker build, which has no
// device definitions). `WFB_FONTS_MIRROR` swaps every source URL's scheme
// and host for a mirror's. Garmin's own font files are never installed here
// (`vendor/fonts/` is the user's licensed copy); this only says how many
// needed names that root already covers.
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { parseArgs } from "node:util";
import { unzipSync } from "fflate";
import { DEFAULT_DEVICE_ROOTS, DEVICE_REFERENCE } from "../src/devices/node.ts";
import { resolveRegistryKey } from "../src/fonts/files.ts";
import { deviceNeededNames, garminFontRoot, NodeFontFiles, SYSTEM_FONTS_DEST } from "../src/fonts/node.ts";
import registry from "../src/data/font-registry.json" with { type: "json" };
import { download, writeAtomic } from "./fetch-icon-font.ts";

interface Source { url: string; member?: string; sha256: string; license?: string; license_url?: string }
const SOURCES = registry.sources as Record<string, Source>;
const FONTS = registry.fonts as Record<string, { source: string }>;

const sha256 = (data: Uint8Array): string => createHash("sha256").update(data).digest("hex");

/** `url` with its scheme and host swapped for `WFB_FONTS_MIRROR`'s, when set. */
function mirrored(url: string): string {
  const mirror = process.env["WFB_FONTS_MIRROR"];
  if (!mirror) return url;
  const to = new URL(mirror.includes("//") ? mirror : `https://${mirror}`), from = new URL(url);
  return `${to.protocol}//${to.host}${from.pathname}${from.search}${from.hash}`;
}

/** `member` out of a zip: by its exact path, else by its file name outside `__MACOSX/`. */
function extract(data: Uint8Array, member: string): Uint8Array {
  const files = unzipSync(data);
  if (files[member] !== undefined) return files[member];
  const name = member.split("/").pop();
  for (const [path, content] of Object.entries(files)) {
    if (!path.endsWith("/") && !path.split("/").includes("__MACOSX") && path.split("/").pop() === name) return content;
  }
  throw new Error(`archive does not contain '${member}'`);
}

const licence = (source: Source): string =>
  [source.license ?? "unknown license", ...(source.license_url ? [`license: ${source.license_url}`] : []), `font source: ${source.url}`].join("\n") + "\n";

/** Install every key in `keys` into `dest`: `{key: installed}`, a failure's reason printed. */
async function install(keys: string[], dest: string): Promise<Record<string, boolean>> {
  const result: Record<string, boolean> = {};
  const fetched = new Map<string, Uint8Array | null>(); // url -> its bytes, or null when the download failed
  mkdirSync(dest, { recursive: true });
  for (const key of keys) {
    const sourceId = FONTS[key]!.source, source = SOURCES[sourceId]!;
    const target = join(dest, `${key}.ttf`);
    if (existsSync(target) && sha256(readFileSync(target)) === source.sha256) {
      result[key] = true;
      continue;
    }
    if (!fetched.has(source.url)) {
      try {
        fetched.set(source.url, await download(mirrored(source.url)));
      } catch (error) {
        console.error(`note: could not download ${source.url} for font '${key}' (${(error as Error).message})`);
        fetched.set(source.url, null);
      }
    }
    const data = fetched.get(source.url);
    if (data === null || data === undefined) {
      result[key] = false;
      continue;
    }
    try {
      const content = source.member ? extract(data, source.member) : data;
      if (sha256(content) !== source.sha256) throw new Error(`'${sourceId}' does not match its pinned SHA-256`);
      writeAtomic(target, content);
      writeAtomic(join(dest, `${sourceId}.LICENSE.txt`), licence(source));
      result[key] = true;
    } catch (error) {
      console.error(`note: ${source.url} did not verify (${(error as Error).message}); font '${key}' not installed`);
      result[key] = false;
    }
  }
  return result;
}

/** Name a handful of devices outright; count a fleet. */
const describe = (ids: string[]): string => (ids.length <= 4 ? ids.join(", ") : `${ids.length} devices`);

async function main(): Promise<number> {
  const { values, positionals } = parseArgs({
    options: { device: { type: "string", multiple: true }, all: { type: "boolean", default: false } },
    allowPositionals: true,
  });
  const dest = positionals[0] ?? SYSTEM_FONTS_DEST;
  const devicesRoot = [process.env["WFB_DEVICES"], ...DEFAULT_DEVICE_ROOTS]
    .find((path): path is string => Boolean(path) && existsSync(path!) && readdirSync(path!).length > 0) ?? null;
  let ids: string[];
  if (values.all) {
    ids = existsSync(DEVICE_REFERENCE) ? readdirSync(DEVICE_REFERENCE).filter((n) => n.endsWith(".json")).map((n) => n.slice(0, -5)).sort() : [];
  } else {
    ids = values.device ?? (devicesRoot === null ? [] : readdirSync(devicesRoot).filter((id) => existsSync(join(devicesRoot, id, "compiler.json"))).sort());
    if (ids.length === 0) {
      console.log("no device definitions installed: nothing to prefetch for (pass --device ID, or --all for every device in the SDK device reference)");
      return 0;
    }
  }
  const fontsRoot = garminFontRoot();
  console.log(fontsRoot !== null ? `Garmin font root: ${fontsRoot}` : "Garmin font root: not found (registry-only; see `wfb doctor`)");
  const garmin = new NodeFontFiles();
  // font-key -> the name that needs it. A name the Garmin root covers is
  // still prefetched: a machine without that root measures with the stand-in.
  const needed = new Map<string, string>();
  let covered = 0;
  for (const id of ids) {
    for (const [name, face] of deviceNeededNames(id, devicesRoot)) {
      if (fontsRoot !== null && garmin.garminPath(name, [".ttf", ".otf"]) !== undefined) covered++;
      const key = resolveRegistryKey(name, face);
      if (key !== null && !needed.has(key)) needed.set(key, name);
    }
  }
  if (needed.size === 0) {
    console.log(`nothing to prefetch for ${describe(ids)}`);
    return 0;
  }
  console.log(`prefetching ${needed.size} font(s) for ${describe(ids)} into ${dest}`);
  if (covered > 0) console.log(`  (${covered} needed name(s) are also covered by the Garmin font root, which wins at build time)`);
  const keys = [...needed.keys()].sort();
  const results = await install(keys, dest);
  for (const key of keys) console.log(`  ${(results[key] ? "ok" : "FAILED").padEnd(6)} ${key}  (${needed.get(key)})`);
  const failed = keys.filter((key) => !results[key]);
  if (failed.length > 0) {
    console.error(`error: ${failed.length} font(s) could not be fetched (see notes above)`);
    return 1;
  }
  return 0;
}

process.exit(await main());
