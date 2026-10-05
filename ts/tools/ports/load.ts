// Parity ports of the `load-*` stages: each case of `load-cases`
// (tools/oracle_cases.py) rebuilt from its splice, loaded pass by pass, and
// one pass's diagnostics written in the oracle's form.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { REPO_ROOT } from "../../src/devices/node.ts";
import { Bag, type Diagnostic } from "../../src/diagnostics.ts";
import { loadSchema, validate } from "../../src/validate.ts";
import { load } from "../../src/yamlsrc.ts";
import { PyError } from "../../src/py.ts";
import type { Case } from "../stages.ts";

loadSchema(JSON.parse(readFileSync(join(REPO_ROOT, "schema", "wfb-face-2.schema.json"), "utf8")));

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

function diagnosticJson(d: Diagnostic): unknown {
  return {
    severity: d.severity, code: d.code, message: d.message,
    span: d.span === null ? null : { path: d.span.path, line: d.span.line, col: d.span.col },
    notes: d.notes, confidence: d.confidence,
  };
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
