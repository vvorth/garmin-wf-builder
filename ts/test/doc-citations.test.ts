// What a doc may cite (`docs/CLAUDE.md`, "What a doc may cite"). Records --
// `docs/research/`, `docs/plans/`, `docs/adr/` -- carry history and may cite
// each other. Everything else states what is true now:
//   - no plan citations anywhere outside the records: not in a doc, a
//     `CLAUDE.md`, the schema, an example, or a code comment;
//   - no research citations in the guide, the schema, a README, an example
//     face or a `CLAUDE.md`, which point to the guide or
//     `docs/limitations.md` instead. `docs/limitations.md`, `docs/lore/` and
//     code comments may cite research as evidence, so they are not checked.
// A citation that wraps across a line break counts: the patterns allow any
// whitespace inside one.
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { extname, join, relative } from "node:path";
import { test } from "node:test";
import { REPO_ROOT } from "../src/devices/node.ts";

/** "plan 14", "slice 2", "plans 01-02", a link into `docs/plans/`. */
const PLAN = /\b[Pp]lans?\s+\d+|\b[Ss]lices?\s+\d+|docs\/plans\//g;
/** "research 11", a numbered research file, a probe. The research index (`research/00-summary.md`) is a pointer, not a citation. */
const RESEARCH = /\b[Rr]esearch\s+\d+|research\/(?!00-summary)\d{2}|research\/probes/g;
const RECORDS = ["docs/research/", "docs/plans/", "docs/adr/"];

/** Passages that name the records rather than cite them: the rules themselves and the index pointing at them. */
const ALLOWED: [string, string][] = [
  ["CLAUDE.md", "`docs/plans/README.md` (open plans, and how to read deleted ones)"],
  ["CLAUDE.md", "probes), `docs/plans/` and `docs/adr/`: they carry history"],
  ["CLAUDE.md", "`docs/plans/` links). **Research may be cited only"],
  ["CLAUDE.md", "| 0 research (`docs/research/00`–`12`) | complete, reviewed |"],
  ["docs/CLAUDE.md", 'no "plan 14 §4.3",'],
  ["docs/CLAUDE.md", '"slice 2", decision ids (D3, R2.1, A5), `docs/plans/` links'],
  ["docs/CLAUDE.md", "| `research/NN-*.md` | investigations"],
  ["docs/CLAUDE.md", "| `research/probes/` | minimal Monkey C projects"],
];

const SUFFIXES = new Set([".md", ".ts", ".mc", ".js", ".json", ".yaml", ".yml", ".sh"]);
const SKIP = ["/vendor/", "/node_modules/", "/dist/", "ts/test/corpus/", "ts/test/goldens/", "ts/test/doc-citations.test.ts"];

function files(...roots: string[]): string[] {
  const out: string[] = [];
  const walk = (path: string): void => {
    const rel = relative(REPO_ROOT, path);
    if (RECORDS.some((r) => rel.startsWith(r)) || SKIP.some((s) => `/${rel}`.includes(s) || rel.startsWith(s))) return;
    if (statSync(path).isDirectory()) for (const name of readdirSync(path)) walk(join(path, name));
    else if (SUFFIXES.has(extname(path))) out.push(rel);
  };
  for (const root of roots) if (existsSync(join(REPO_ROOT, root))) walk(join(REPO_ROOT, root));
  return [...new Set(out)].sort();
}

function claudeFiles(): string[] {
  return files(".").filter((f) => f.endsWith("CLAUDE.md") && !f.startsWith("build/") && !f.startsWith("vendor/") && !f.startsWith(".venv/"));
}

function offences(pattern: RegExp, paths: string[]): string[] {
  const found: string[] = [];
  for (const rel of paths) {
    const text = readFileSync(join(REPO_ROOT, rel), "utf8"), lines = text.split("\n");
    for (const m of text.matchAll(pattern)) {
      const line = text.slice(0, m.index).split("\n").length - 1, shown = lines[line]!;
      if (ALLOWED.some(([path, part]) => rel === path && shown.includes(part))) continue;
      found.push(`${rel}:${line + 1}: '${m[0]}' in '${shown.trim()}'`);
    }
  }
  return found;
}

test("nothing outside the records cites a plan", () => {
  const found = offences(PLAN, files("docs", "README.md", "ts/src", "ts/app", "ts/tools", "ts/test", "runtime-lib", "tools", "schema", "examples", "docker", ...claudeFiles()));
  assert.deepEqual(found, [], "plans are never cited outside docs/research, docs/plans and docs/adr; state the fact instead");
});

test("the guide, READMEs, schema, examples and CLAUDE.md files cite no research", () => {
  const found = offences(RESEARCH, files("docs/guide", "README.md", "docs/README.md", "schema", "examples", ...claudeFiles()));
  assert.deepEqual(found, [], "point to the guide or docs/limitations.md instead of citing research");
});
