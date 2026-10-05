// Parity ports of the `load-*` stages: each case of `load-cases`
// (tools/oracle_cases.py) rebuilt from its splice, loaded pass by pass, and
// one pass's diagnostics written in the oracle's form.
import { Bag } from "../../src/diagnostics.ts";
import { desugar } from "../../src/desugar.ts";
import { build as buildIr } from "../../src/ir/builder/index.ts";
import { installAssets, repoFileExists } from "../../src/node.ts";
import { lower } from "../../src/lower.ts";
import { validate } from "../../src/validate.ts";
import { diagnosticJson } from "./ir.ts";
import { oracleData } from "./text.ts";
import { load } from "../../src/yamlsrc.ts";
import { PyError } from "../../src/py.ts";
import type { Case } from "../stages.ts";

installAssets();

export const PASSES = ["yaml", "validate", "lower", "desugar", "ir"] as const;
export type Pass = (typeof PASSES)[number];

interface OracleCase {
  splice: [number, number, string] | null;
  what: string;
}

/** The case's text: the design's, with the recorded splice (code-point offsets) applied. */
function caseText(text: string, splice: [number, number, string] | null): string {
  if (splice === null) return text;
  const points = Array.from(text);
  const [at, cut, insert] = splice;
  return points.slice(0, at).join("") + insert + points.slice(at + cut).join("");
}


/** Each pass's diagnostics up to `last`, as tools/oracle_cases.py's `load_passes` records them. */
function loadPasses(path: string, text: string, last: Pass): Record<Pass, unknown> {
  const out: Record<Pass, unknown> = { yaml: null, validate: null, lower: null, desugar: null, ir: null };
  const bag = new Bag();
  const doc = load(path, bag, text);
  out.yaml = bag.items.map(diagnosticJson);
  if (doc === null || last === "yaml") return out;
  const steps: [Pass, () => boolean][] = [
    ["validate", () => validate(doc, bag)],
    ["lower", () => lower(doc, bag)],
    ["desugar", () => desugar(doc, bag)],
    ["ir", () => buildIr(doc, bag, repoFileExists) !== null],
  ];
  for (const [name, step] of steps) {
    const start = bag.items.length;
    let ok: boolean;
    try {
      ok = step();
    } catch (error) {
      if (error instanceof PyError) { out[name] = { crash: error.pyType }; return out; }
      throw error;
    }
    out[name] = bag.items.slice(start).map(diagnosticJson);
    if (!ok || name === last) return out;
  }
  return out;
}

/** The port of the `load-<pass>` stage. */
export function loadPass(pass: Pass): (input: Case) => unknown {
  return (input) => (input.oracle("load-cases") as OracleCase[]).map((c) => ({
    what: c.what,
    [pass]: loadPasses(input.path, caseText(input.text, c.splice), pass)[pass],
  }));
}

/** The port of `lowered` or `desugared`: the document after that pass, as `to_json(ordered(doc.data))`. */
export function documentAfter(pass: "lower" | "desugar"): (input: Case) => unknown {
  return (input) => {
    const bag = new Bag();
    const doc = load(input.path, bag, input.text);
    if (doc === null || !validate(doc, bag) || !lower(doc, bag)) return null;
    if (pass === "desugar" && !desugar(doc, bag)) return null;
    return oracleData(doc.data);
  };
}
