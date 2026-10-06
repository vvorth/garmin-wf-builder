// Downloads the Nerd Fonts "Symbols Only" icon font that `icon:` elements use.
//
// The font is not committed: this fetches the pinned release, checks every
// byte against the hashes below, and installs the font and its licence into
// `ts/assets/icons/` (or the directory given as the first argument).
// Re-running it is cheap: files that already match are left alone and
// nothing is downloaded. The release's .zip, not its .tar.xz: Node reads a
// zip (fflate), and not every machine has xz.
//
//   node ts/tools/fetch-icon-font.ts [DEST_DIR]
//
// `WFB_NERD_FONTS_BASE_URL` overrides the download host, for a mirror.
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { unzipSync } from "fflate";

const VERSION = "v3.5.1";
const ARCHIVE = "NerdFontsSymbolsOnly.zip";
const ARCHIVE_SHA256 = "fdca3682534f6f65e1ccb2345b0362ccf67d9b8eca7c8025330946e93e2473bc";
const BASE_URL = process.env["WFB_NERD_FONTS_BASE_URL"] || "https://github.com/ryanoasis/nerd-fonts/releases/download";

/** Archive member -> [installed name, SHA-256]. */
const FILES: Record<string, [string, string]> = {
  "SymbolsNerdFont-Regular.ttf": ["SymbolsNerdFont-Regular.ttf", "2839f0a572d4559f3f17a6fb74b8772e183f0c0a47150998ab194932cad55829"],
  LICENSE: ["LICENSE-nerd-fonts.txt", "84a7a98c82140fb12c37fe42b93805baa16024cb3e5acc599b7ffe612c55d847"],
};

const sha256 = (data: Uint8Array): string => createHash("sha256").update(data).digest("hex");

/** A URL's bytes, with three tries. */
export async function download(url: string, attempts = 3): Promise<Uint8Array> {
  for (let attempt = 1; ; attempt++) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(120_000) });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return new Uint8Array(await response.arrayBuffer());
    } catch (error) {
      if (attempt === attempts) throw error;
      console.log(`  attempt ${attempt} failed (${(error as Error).message}); retrying`);
      await new Promise((done) => setTimeout(done, 2000 * attempt));
    }
  }
}

/** `path` written whole or not at all. */
export function writeAtomic(path: string, data: Uint8Array | string): void {
  const partial = join(resolve(path, ".."), `.${path.split("/").pop()}.partial`);
  writeFileSync(partial, data);
  renameSync(partial, path);
}

async function main(): Promise<number> {
  const dest = process.argv[2] ?? resolve(import.meta.dirname, "..", "assets", "icons");
  if (Object.values(FILES).every(([name, digest]) => existsSync(join(dest, name)) && sha256(readFileSync(join(dest, name))) === digest)) {
    console.log(`icon font ${VERSION} already installed in ${dest}`);
    return 0;
  }
  const url = `${BASE_URL}/${VERSION}/${ARCHIVE}`;
  console.log(`fetching ${url}`);
  let data: Uint8Array;
  try {
    data = await download(url);
  } catch (error) {
    console.error(`error: could not download the icon font: ${(error as Error).message}`);
    return 1;
  }
  if (sha256(data) !== ARCHIVE_SHA256) {
    console.error(`error: ${ARCHIVE} does not match its pinned SHA-256`);
    return 1;
  }
  const members = unzipSync(data, { filter: (file) => file.name in FILES });
  for (const [member, [, digest]] of Object.entries(FILES)) {
    if (members[member] === undefined || sha256(members[member]) !== digest) {
      console.error(`error: ${member} does not match its pinned SHA-256`);
      return 1;
    }
  }
  mkdirSync(dest, { recursive: true });
  for (const [member, [name]] of Object.entries(FILES)) writeAtomic(join(dest, name), members[member]!);
  console.log(`installed icon font ${VERSION} into ${dest}`);
  return 0;
}

if (import.meta.filename === process.argv[1]) process.exit(await main());
