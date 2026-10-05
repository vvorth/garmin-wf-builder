// Runs each ported stage over the oracle's corpus and compares its output
// with Python's (tools/oracle.py), case by case.
//
//   npm run parity                         every stage
//   npm run parity -- spans data           these stages
//   npm run parity -- --design examples/showcase/face spans
//   npm run parity -- --allow-missing      exit 0 when the only gaps are unported stages
//
// Exits 1 when any case differs or fails, or, without --allow-missing, is
// missing a port.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { parseArgs } from "node:util";
import { NodeDeviceFiles, REPO_ROOT } from "../src/devices/node.ts";
import { compare, type Difference } from "./compare.ts";
import { type Case, isDeviceStage, ORACLE_FORMAT, PORTS, type Stage, STAGES } from "./stages.ts";

const ORACLE = join(REPO_ROOT, ".cache", "oracle");

interface DesignEntry {
  id: string;
  path: string;
  devices: string[];
  stages: string[];
}

interface Tally {
  cases: number;
  equal: number;
  differ: number;
  failed: number;
  missing: number;
  examples: string[];
}

function main(): number {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      design: { type: "string", multiple: true },
      "allow-missing": { type: "boolean", default: false },
      examples: { type: "string", default: "3" },
    },
  });
  const unknown = positionals.filter((s) => !(STAGES as readonly string[]).includes(s));
  if (unknown.length > 0) {
    console.error(`parity: unknown stage ${unknown.join(", ")}; stages are ${STAGES.join(", ")}`);
    return 2;
  }
  const stages = (positionals.length > 0 ? positionals : [...STAGES]) as Stage[];
  const indexPath = join(ORACLE, "index.json");
  if (!existsSync(indexPath)) {
    console.error("parity: no oracle at .cache/oracle; run ./.venv/bin/python tools/oracle.py first");
    return 2;
  }
  const index = JSON.parse(readFileSync(indexPath, "utf8")) as { format: number; revision: string; designs: DesignEntry[] };
  if (index.format !== ORACLE_FORMAT) {
    console.error(`parity: the oracle is format ${index.format}, this runner reads ${ORACLE_FORMAT}; rerun tools/oracle.py`);
    return 2;
  }
  const wanted = values.design ?? [];
  const designs = index.designs.filter((d) => wanted.length === 0 || wanted.includes(d.id));
  const files = NodeDeviceFiles.discover();
  const shown = Number(values.examples);
  const tallies = new Map<Stage, Tally>();

  for (const stage of stages) {
    const tally: Tally = { cases: 0, equal: 0, differ: 0, failed: 0, missing: 0, examples: [] };
    tallies.set(stage, tally);
    const port = PORTS[stage];
    for (const design of designs) {
      if (!design.stages.includes(stage)) continue;
      const devices = isDeviceStage(stage) ? design.devices : [undefined];
      const text = readFileSync(join(REPO_ROOT, design.path), "utf8");
      for (const device of devices) {
        tally.cases++;
        const label = device === undefined ? design.id : `${design.id} @ ${device}`;
        if (port === undefined) {
          tally.missing++;
          continue;
        }
        const input: Case = {
          design: design.id, path: design.path, text, device, files,
          oracle: (earlier, dev = device) => dump(design.id, earlier, isDeviceStage(earlier) ? dev : undefined),
        };
        let differences: Difference[];
        try {
          differences = compare(dump(design.id, stage, device), port(input));
        } catch (error) {
          tally.failed++;
          if (tally.examples.length < shown) tally.examples.push(`${label}: threw ${String(error)}`);
          continue;
        }
        if (differences.length === 0) {
          tally.equal++;
        } else {
          tally.differ++;
          if (tally.examples.length < shown) {
            const lines = differences.slice(0, 5).map((d) =>
              `    ${d.path}: expected ${brief(d.expected)}, got ${brief(d.actual)}`);
            tally.examples.push(`${label}:\n${lines.join("\n")}`);
          }
        }
      }
    }
  }

  console.log(`oracle ${index.revision}, ${designs.length} designs`);
  console.log(`${"stage".padEnd(18)}${["cases", "equal", "differ", "failed", "missing"].map((h) => h.padStart(8)).join("")}`);
  let bad = false;
  for (const [stage, t] of tallies) {
    console.log(`${stage.padEnd(18)}${[t.cases, t.equal, t.differ, t.failed, t.missing].map((n) => String(n).padStart(8)).join("")}`);
    if (t.differ > 0 || t.failed > 0 || (t.missing > 0 && !values["allow-missing"])) bad = true;
  }
  for (const [stage, t] of tallies) {
    for (const example of t.examples) console.log(`\n${stage}: ${example}`);
  }
  return bad ? 1 : 0;
}

function dump(design: string, stage: Stage, device: string | undefined): unknown {
  const path = device === undefined ? join(ORACLE, design, `${stage}.json`) : join(ORACLE, design, device, `${stage}.json`);
  return JSON.parse(readFileSync(path, "utf8"));
}

function brief(value: unknown): string {
  const text = JSON.stringify(value) ?? "undefined";
  return text.length > 80 ? `${text.slice(0, 77)}...` : text;
}

process.exitCode = main();
