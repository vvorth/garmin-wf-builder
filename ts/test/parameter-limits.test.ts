// Connect IQ 3.x devices (fenix6, fr245) reject a function declared with
// more than 9 parameters, where newer devices build it fine, so nothing else
// would catch a 10th: every hand-written barrel function and every function
// the emitter generates for a sample of examples is checked from its text.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { REPO_ROOT } from "../src/devices/node.ts";
import { generated } from "./designs.ts";

const MAX_PARAMETERS = 9;

/** `[name, parameter count]` for every `function name(...)`, commas counted at bracket depth 0. */
function signatures(text: string): [string, number][] {
  const out: [string, number][] = [];
  for (const m of text.matchAll(/\bfunction\s+(\w+)\s*\(/g)) {
    let depth = 1, i = m.index + m[0].length, commas = 0, any = false;
    for (; i < text.length && depth > 0; i++) {
      const c = text[i]!;
      if ("([{".includes(c)) depth++;
      else if (")]}".includes(c)) depth--;
      else if (c === "," && depth === 1) commas++;
      if (depth > 0 && !/\s/.test(c)) any = true;
    }
    out.push([m[1]!, any ? commas + 1 : 0]);
  }
  return out;
}

const over = (file: string, text: string): string[] =>
  signatures(text).filter(([, n]) => n > MAX_PARAMETERS).map(([name, n]) => `${file}: ${name} takes ${n}`);

test("no barrel function takes more than 9 parameters", () => {
  const dir = join(REPO_ROOT, "runtime-lib");
  const found = readdirSync(dir).filter((f) => f.endsWith(".mc")).flatMap((f) => over(f, readFileSync(join(dir, f), "utf8")));
  assert.deepEqual(found, []);
});

test("no generated function takes more than 9 parameters", () => {
  for (const example of ["features/analog", "features/patterns", "showcase"]) {
    const files = generated(readFileSync(join(REPO_ROOT, "examples", example, "face.yaml"), "utf8").replaceAll("source: assets/", `source: examples/${example}/assets/`));
    for (const [file, text] of files) assert.deepEqual(over(`${example}/${file}`, text), []);
  }
});

test("the count reads a dictionary-typed parameter as one", () => {
  assert.deepEqual(signatures("function f(a, options as {:x as Number, :y as Number}, c) {}"), [["f", 3]]);
  assert.deepEqual(signatures("function g() {}"), [["g", 0]]);
});
