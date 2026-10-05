// Font files from disk, found where wfb/fonts/fetch_system.py finds them:
// the Garmin font root (`--fonts`, `WFB_FONTS`, `vendor/fonts/`, the SDK
// Manager's folders) and the registry's installed or cached stand-ins.
// Node only: the browser bundle never imports this module.
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { extname, join } from "node:path";
import { REPO_ROOT } from "../devices/node.ts";
import { expectedSha, type FontFile, type FontFiles } from "./files.ts";

/** The Garmin font root: the first existing, non-empty candidate; with `WFB_NO_GARMIN_FONTS=1` only `override`. */
export function garminFontRoot(override: string | null = null): string | null {
  const candidates: string[] = [];
  if (override) candidates.push(override);
  if (process.env["WFB_NO_GARMIN_FONTS"] !== "1") {
    const env = process.env["WFB_FONTS"];
    if (env) candidates.push(env);
    candidates.push(join(REPO_ROOT, "vendor", "fonts"));
    candidates.push(join(homedir(), ".Garmin", "ConnectIQ", "Fonts"));
    candidates.push(join(homedir(), "Library", "Application Support", "Garmin", "ConnectIQ", "Fonts"));
    const appdata = process.env["APPDATA"];
    if (appdata) candidates.push(join(appdata, "Garmin", "ConnectIQ", "Fonts"));
  }
  for (const path of candidates) {
    try {
      if (statSync(path).isDirectory() && readdirSync(path).length > 0) return path;
    } catch {
      // not there
    }
  }
  return null;
}

/** Where a prefetch installs the registry's stand-ins, and the runtime cache. */
export const SYSTEM_FONTS_DEST = join(REPO_ROOT, "wfb", "assets", "system-fonts");

export function cacheDir(): string {
  const base = process.env["XDG_CACHE_HOME"] || join(homedir(), ".cache");
  return join(base, "wfb", "fonts");
}

function read(path: string): FontFile {
  const bytes = readFileSync(path);
  return { path, bytes: new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength) };
}

export class NodeFontFiles implements FontFiles {
  readonly root: string | null;
  private index: Map<string, string[]> | null = null;
  private readonly hashes = new Map<string, string>();

  /** `fontsRoot` is the `--fonts DIR` override; `null` for the ordinary search order. */
  constructor(fontsRoot: string | null = null) {
    this.root = garminFontRoot(fontsRoot);
  }

  /** Lower-cased file stem to every file under the root with it, built once. */
  private stems(): Map<string, string[]> {
    if (this.index !== null) return this.index;
    const index = new Map<string, string[]>();
    const walk = (dir: string): void => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const path = join(dir, entry.name);
        if (entry.isDirectory()) walk(path);
        else if (entry.isFile()) {
          const stem = entry.name.slice(0, entry.name.length - extname(entry.name).length).toLowerCase();
          const list = index.get(stem);
          if (list) list.push(path); else index.set(stem, [path]);
        }
      }
    };
    if (this.root !== null) walk(this.root);
    this.index = index;
    return index;
  }

  garmin(name: string, suffixes: readonly string[]): FontFile | undefined {
    if (this.root === null) return undefined;
    const path = (this.stems().get(name.toLowerCase()) ?? []).find((p) => suffixes.includes(extname(p).toLowerCase()));
    return path === undefined ? undefined : read(path);
  }

  registry(key: string): FontFile | undefined {
    const expected = expectedSha(key);
    if (expected === null) return undefined;
    for (const base of [SYSTEM_FONTS_DEST, cacheDir()]) {
      const path = join(base, `${key}.ttf`);
      if (!existsSync(path) || !statSync(path).isFile()) continue;
      const file = read(path);
      let sha = this.hashes.get(path);
      if (sha === undefined) {
        sha = createHash("sha256").update(file.bytes).digest("hex");
        this.hashes.set(path, sha);
      }
      if (sha === expected) return file;
    }
    return undefined;
  }
}
