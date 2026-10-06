// Freeze the designs the Python test suite wrote, captured by
// tools/capture_designs.py, into a committed corpus: each design's files,
// every file stored once by its hash, and the devices its test resolved it
// on (from tools/oracle.py's index, when it has them). Run once.
//   node tools/pack-corpus.ts            # .cache/test-designs -> test/corpus/designs.json.gz (the goldens')
//   node tools/pack-corpus.ts slow       # .cache/slow-designs -> test/corpus/slow-designs.json.gz (slow/build.test.ts)
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";
import { REPO_ROOT } from "../src/devices/node.ts";

const index = JSON.parse(readFileSync(join(REPO_ROOT, ".cache", "oracle", "index.json"), "utf8")) as { designs: { id: string; devices: string[] }[] };
const blobs: Record<string, { text: string } | { base64: string } | { repo: string }> = {};

/** Every binary file the examples and fixtures already hold, by hash: a copy is stored as a reference. */
const inRepo = new Map<string, string>();
for (const top of ["examples", "tests/fixtures"]) {
  const walkRepo = (dir: string): void => {
    for (const name of readdirSync(join(REPO_ROOT, dir))) {
      const rel = `${dir}/${name}`;
      if (statSync(join(REPO_ROOT, rel)).isDirectory()) walkRepo(rel);
      else if (!rel.endsWith(".yaml")) inRepo.set(createHash("sha256").update(readFileSync(join(REPO_ROOT, rel))).digest("hex").slice(0, 32), rel);
    }
  };
  walkRepo(top);
}
const decoder = new TextDecoder("utf-8", { fatal: true });
function blob(bytes: Buffer, sha: string): { text: string } | { base64: string } | { repo: string } {
  const repo = inRepo.get(sha);
  if (repo !== undefined) return { repo };
  try {
    // A test that named a repository file by its absolute path: `_repo_/` stands for the root anywhere.
    return { text: decoder.decode(bytes).replaceAll(REPO_ROOT + "/", "_repo_/") };
  } catch {
    return { base64: bytes.toString("base64") };
  }
}
const designs: { id: string; design: string; devices: string[]; files: Record<string, string> }[] = [];

function walk(dir: string, prefix = "", out: Record<string, string> = {}): Record<string, string> {
  for (const name of readdirSync(dir).sort()) {
    if (name === ".design") continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, `${prefix}${name}/`, out);
    else {
      const bytes = readFileSync(path);
      const sha = createHash("sha256").update(bytes).digest("hex").slice(0, 32);
      blobs[sha] ??= blob(bytes, sha);
      out[prefix + name] = sha;
    }
  }
  return out;
}

const slow = process.argv[2] === "slow";
const source = slow ? "slow-designs" : "test-designs";
const entries = slow
  ? readdirSync(join(REPO_ROOT, ".cache", source)).sort().map((id) => ({ id: `.cache/${source}/${id}/face`, devices: [] as string[] }))
  : index.designs.filter((e) => e.id.startsWith(`.cache/${source}/`));
for (const entry of entries) {
  const id = entry.id.split("/")[2]!;
  const dir = join(REPO_ROOT, ".cache", source, id);
  const design = readFileSync(join(dir, ".design"), "utf8").trim();
  designs.push({ id, design, devices: entry.devices, files: walk(dir) });
}
designs.sort((a, b) => (a.id < b.id ? -1 : 1));
const out = gzipSync(JSON.stringify({ blobs, designs }), { level: 9 });
writeFileSync(join(REPO_ROOT, "ts", "test", "corpus", slow ? "slow-designs.json.gz" : "designs.json.gz"), out);
console.log(`${designs.length} designs, ${Object.keys(blobs).length} files, ${out.length} bytes`);
