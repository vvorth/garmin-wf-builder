// Node-only helpers over the repository's own files: whether a design's
// font source exists, the icon font's character map and the published
// schema. The browser hands each in instead. Only Node entry points import
// this module.
import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import type { FontFile } from "./fonts/files.ts";
import { ICON_FONT as ICON_FONT_PATH } from "./emit/resources.ts";
import opentype from "opentype.js";
import { REPO_ROOT } from "./devices/node.ts";
import { setIconFontGlyphs } from "./icons.ts";
import { loadSchema } from "./validate.ts";

/** Whether a repository-relative path names an existing file. */
export function repoFileExists(path: string): boolean {
  return existsSync(path.startsWith("/") ? path : join(REPO_ROOT, path));
}

/** Whether a path, relative to the working directory, names an existing file. */
export function cwdFileExists(path: string): boolean {
  return existsSync(resolve(path));
}

const fontFiles = new Map<string, FontFile>();

/** A font file a design names, relative to the working directory, or the icon font, relative to the repository. */
export function readFontFile(path: string): FontFile {
  let file = fontFiles.get(path);
  if (file === undefined) {
    const bytes = readFileSync(path === ICON_FONT_PATH ? join(REPO_ROOT, path) : resolve(path));
    fontFiles.set(path, file = { path, bytes: new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength) });
  }
  return file;
}

/** The icon font's file, fetched by tools/fetch-icon-font.py. */
export const ICON_FONT = join(REPO_ROOT, "wfb", "assets", "icons", "SymbolsNerdFont-Regular.ttf");

/** Read the icon font's best character map and hand it to `icons.fontHas`. */
export function installIconFont(path = ICON_FONT): void {
  if (!existsSync(path)) {
    setIconFontGlyphs(`the icon font is not installed (${path}); run tools/setup-env.sh, or python3 tools/fetch-icon-font.py`);
    return;
  }
  const bytes = readFileSync(path);
  const font = opentype.parse(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
  const map = (font.tables["cmap"] as { glyphIndexMap: Record<string, number> }).glyphIndexMap;
  setIconFontGlyphs(new Set(Object.keys(map).map((cp) => String.fromCodePoint(Number(cp)))));
}

/** The published schema, which `validate` checks against. */
export const SCHEMA = join(REPO_ROOT, "schema", "wfb-face-2.schema.json");

export function installSchema(path = SCHEMA): void {
  loadSchema(JSON.parse(readFileSync(path, "utf8")));
}

/** Everything a Node entry point hands the compiler before it loads a design. */
export function installAssets(): void {
  installSchema();
  installIconFont();
}
