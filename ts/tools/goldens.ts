// What the compiler produces for the frozen corpus, the examples and the
// fixtures, in the form test/goldens.test.ts compares with the committed
// goldens (test/goldens/*.json). After an intended output change:
//   WFB_UPDATE_GOLDENS=1 npm test     # or: node tools/goldens.ts
// and review the diff of test/goldens/ before committing it.
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, normalize } from "node:path";
import { gunzipSync } from "node:zlib";
import { load, resolveAll, selectDevices } from "../src/build.ts";
import { DeviceDatabase } from "../src/devices/device.ts";
import { NodeDeviceFiles, REPO_ROOT } from "../src/devices/node.ts";
import { Bag } from "../src/diagnostics.ts";
import { generate } from "../src/emit/project.ts";
import { bakeFonts, ICON_FONT } from "../src/emit/resources.ts";
import type { FontFile } from "../src/fonts/files.ts";
import { NodeFontFiles } from "../src/fonts/node.ts";
import { installAssets } from "../src/node.ts";
import { pngBytes, previewOptions, type PreviewOptions, render, renderAllStyles, UnknownStyleError } from "../src/preview.ts";
import { decodePng } from "../src/png.ts";

installAssets();
// Never the user's own Garmin font files: what is frozen must come out the
// same on every machine, measured with the registry's stand-ins.
process.env["WFB_NO_GARMIN_FONTS"] = "1";
export const db = new DeviceDatabase(NodeDeviceFiles.discover(), new NodeFontFiles());
export const GOLDENS = join(REPO_ROOT, "ts", "test", "goldens");

const sha = (bytes: Uint8Array | string): string => createHash("sha256").update(bytes).digest("hex").slice(0, 32);
const iconFont = (): FontFile => {
  const bytes = readFileSync(join(REPO_ROOT, ICON_FONT));
  return { path: ICON_FONT, bytes: new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength) };
};

/** A design's files: whether a path exists and its bytes, the design's folder being `folder`. */
interface Files {
  exists(path: string): boolean;
  read(path: string): FontFile;
}

/** Diagnostics as text, without colour, every note in full. */
const rendered = (bag: Bag): string => bag.render({ verbose: true });

/** One design loaded, resolved and linted on `devices` (its targets when null): its diagnostics. */
function diagnose(path: string, text: string, files: Files, devices: string[] | null): string {
  const bag = new Bag();
  bag.registerSource(path, text);
  const face = load(path, bag, text, files.exists);
  if (face !== null && (devices === null || devices.length > 0)) {
    const chosen = selectDevices(face, db, bag, devices);
    if (chosen.length > 0) resolveAll(face, chosen, bag, (f, d) => bakeFonts(f, d, files.read));
  }
  return rendered(bag);
}

// -- the corpus --

interface Corpus {
  blobs: Record<string, { text: string } | { base64: string } | { repo: string }>;
  designs: { id: string; design: string; devices: string[]; files: Record<string, string> }[];
}

/** Every corpus design's diagnostics, by id. */
export function corpusDiagnostics(only: (id: string) => boolean = () => true): Record<string, string> {
  const corpus = JSON.parse(gunzipSync(readFileSync(join(REPO_ROOT, "ts", "test", "corpus", "designs.json.gz"))).toString()) as Corpus;
  const bytesOf = (key: string): Uint8Array => {
    const blob = corpus.blobs[key]!;
    if ("text" in blob) return new TextEncoder().encode(blob.text);
    if ("base64" in blob) return Uint8Array.from(Buffer.from(blob.base64, "base64"));
    return new Uint8Array(readFileSync(join(REPO_ROOT, blob.repo)));
  };
  const out: Record<string, string> = {};
  for (const design of corpus.designs) {
    if (!only(design.id)) continue;
    const folder = design.id;
    const inside = (p: string): string | undefined => {
      const rel = normalize(p).replace(/^\.\//, "");
      return rel.startsWith(folder + "/") ? design.files[rel.slice(folder.length + 1)] : undefined;
    };
    /** A path the design wrote as `_repo_/...`: the repository's own file. */
    const repo = (p: string): string | null => {
      const at = p.indexOf("_repo_/");
      return at < 0 ? null : join(REPO_ROOT, p.slice(at + "_repo_/".length));
    };
    const files: Files = {
      exists: (p) => inside(p) !== undefined || (repo(p) !== null && existsSync(repo(p)!)),
      read: (p) => {
        if (p === ICON_FONT) return iconFont();
        const key = inside(p);
        if (key !== undefined) return { path: p, bytes: bytesOf(key) };
        const file = repo(p);
        if (file === null) throw new Error(`${p} is not in the design`);
        return { path: p, bytes: new Uint8Array(readFileSync(file)) };
      },
    };
    const path = `${folder}/${design.design}`;
    const text = new TextDecoder().decode(bytesOf(design.files[design.design]!));
    out[design.id] = diagnose(path, text, files, design.devices);
  }
  return out;
}

// -- the examples and fixtures --

/** Every example and fixture design, by its path. */
export function exampleDesigns(): string[] {
  const out: string[] = [];
  const walk = (dir: string): void => {
    for (const name of readdirSync(join(REPO_ROOT, dir)).sort()) {
      const rel = `${dir}/${name}`;
      if (statSync(join(REPO_ROOT, rel)).isDirectory()) walk(rel);
      else if (name.endsWith(".yaml")) out.push(rel);
    }
  };
  walk("examples");
  walk("ts/test/fixtures");
  return out;
}

const diskFiles: Files = {
  exists: (p) => existsSync(join(REPO_ROOT, p)),
  read: (p) => {
    const bytes = readFileSync(join(REPO_ROOT, p));
    return { path: p, bytes: new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength) };
  },
};

/** Device sets each design is built for beyond its own targets. */
export const MIXES: Record<string, string[] | null> = {
  targets: null,
  "amoled-mix": ["fenix847mm", "fenix8solar47mm", "fr245", "fenix6"],
  "fenix9-mix": ["fenix947mm", "fr955"],
};

/** The preview's variants, as the snapshot tool renders them. */
export const VARIANTS: Record<string, Partial<PreviewOptions> & { device?: string; allStyles?: boolean }> = {
  default: {},
  asleep: { asleep: true },
  time: { time: [3, 41, 17] },
  "all-styles": { allStyles: true },
  aod: { device: "fenix847mm", aod: true },
  "aod-minute-7": { device: "fenix847mm", aod: true, time: [0, 7, 0] },
};

/** One example design's goldens: its diagnostics, its projects' files by hash, and its previews' pixels by hash. */
export function exampleGoldens(path: string): Record<string, unknown> {
  const text = readFileSync(join(REPO_ROOT, path), "utf8");
  const out: Record<string, unknown> = { diagnostics: diagnose(path, text, diskFiles, null) };
  const bag = new Bag();
  const face = load(path, bag, text, diskFiles.exists);
  if (face === null) return out;
  const projects: Record<string, unknown> = {};
  for (const [mix, ids] of Object.entries(MIXES)) {
    const devices = selectDevices(face, db, new Bag(), ids);
    if (devices.length === 0) continue;
    const mixBag = new Bag();
    const [resolved] = resolveAll(face, devices, mixBag, (f, d) => bakeFonts(f, d, diskFiles.read));
    if (!mixBag.ok()) {
      projects[mix] = { refused: mixBag.errors.map((d) => `${d.code}: ${d.message}`) };
      continue;
    }
    const files: Record<string, string> = {};
    for (const [file, content] of generate(face, devices, diskFiles.read, { resolved }).files()) {
      files[file] = typeof content === "string" ? sha(content) : sha(decodePng(content)?.pixels ?? content);
    }
    projects[mix] = files;
  }
  out["projects"] = projects;
  const previews: Record<string, Record<string, string>> = {};
  const targets = selectDevices(face, db, new Bag());
  const [resolvedTargets] = resolveAll(face, targets, new Bag(), (f, d) => bakeFonts(f, d, diskFiles.read));
  for (const [variant, { device, allStyles, ...options }] of Object.entries(VARIANTS)) {
    let resolved = resolvedTargets;
    if (device !== undefined) {
      const chosen = selectDevices(face, db, new Bag(), [device]);
      resolved = resolveAll(face, chosen, new Bag(), (f, d) => bakeFonts(f, d, diskFiles.read))[0];
    }
    const shots: Record<string, string> = {};
    for (const [id, r] of resolved) {
      try {
        const image = allStyles ? renderAllStyles(r, previewOptions(options)) : render(r, previewOptions(options));
        shots[id] = sha(new Uint8Array(image.data.buffer, image.data.byteOffset, image.data.byteLength));
      } catch (error) {
        if (!(error instanceof UnknownStyleError)) throw error;
        shots[id] = `refused: ${error.message}`;
      }
    }
    previews[variant] = shots;
  }
  out["previews"] = previews;
  return out;
}

export function write(name: string, value: unknown): void {
  mkdirSync(GOLDENS, { recursive: true });
  writeFileSync(join(GOLDENS, name), JSON.stringify(value, null, 1) + "\n");
}

export function read(name: string): unknown {
  const path = join(GOLDENS, name);
  return existsSync(path) ? JSON.parse(readFileSync(path, "utf8")) : null;
}

if (process.argv[1] !== undefined && import.meta.filename === process.argv[1]) {
  write("corpus-diagnostics.json", corpusDiagnostics());
  write("examples.json", Object.fromEntries(exampleDesigns().map((p) => [p, exampleGoldens(p)])));
  console.log(`goldens written to ${GOLDENS}`);
}


