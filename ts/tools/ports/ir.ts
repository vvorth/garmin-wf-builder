// The IR in the oracle's JSON form (tools/oracle.py's `to_json`), and the
// ports of the stages that dump it: `face`, `diagnostics-load` and the
// `ir` pass of `load-cases`.
import { load } from "../../src/build.ts";
import { Bag, type Diagnostic } from "../../src/diagnostics.ts";
import { PyFloat, Timestamp } from "../../src/edit/yaml.ts";
import { Face, FontSpec } from "../../src/ir/model.ts";
import { REPO_ROOT } from "../../src/devices/node.ts";
import { installAssets, repoFileExists } from "../../src/node.ts";
import { floatRepr } from "../../src/py.ts";
import type { Case } from "../stages.ts";

installAssets();

/** The expression syntax tree's node kinds: Python's node classes carry no `kind` field. */
const EXPR_KINDS = new Set(["literal", "ref", "unary", "binary", "conditional", "call"]);

function number(value: number): unknown {
  return Number.isFinite(value) ? value : { $float: floatRepr(value) };
}

/** `value` as the oracle's `to_json` writes it: a class instance is its own fields, in declaration order. */
export function irJson(value: unknown, top = true): unknown {
  if (value === null || value === undefined) return null;
  if (typeof value === "boolean" || typeof value === "string") return value;
  if (typeof value === "number") return number(value);
  if (typeof value === "bigint") return Number(value);
  if (value instanceof PyFloat) return number(value.value);
  if (value instanceof Timestamp) return { $timestamp: value.iso };
  if (value instanceof Face && !top) return { $face: value.name };
  if (value instanceof FontSpec && value.source !== null && value.source.startsWith(REPO_ROOT + "/")) {
    // A path is dumped relative to the repository, as `Path.resolve().relative_to(ROOT)`.
    return irJson(Object.assign(Object.create(FontSpec.prototype), value, { source: value.source.slice(REPO_ROOT.length + 1) }), top);
  }
  if (Array.isArray(value)) return value.map((v) => irJson(v, false));
  if (value instanceof Map) {
    const out: Record<string, unknown> = {};
    for (const [k, v] of value) out[String(irJson(k, false))] = irJson(v, false);
    return out;
  }
  if (value instanceof Set) {
    return [...value].map((v) => irJson(v, false)).sort((a, b) => compare(JSON.stringify(a), JSON.stringify(b)));
  }
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    const plain = Object.getPrototypeOf(value) === Object.prototype;
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(record)) {
      if (plain && key === "kind" && EXPR_KINDS.has(record[key] as string)) continue;
      out[key] = irJson(record[key], false);
    }
    return out;
  }
  throw new TypeError(`irJson: no JSON form for ${typeof value}`);
}

const compare = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

export function diagnosticJson(d: Diagnostic): unknown {
  return {
    severity: d.severity, code: d.code, message: d.message,
    span: d.span === null ? null : { path: d.span.path, line: d.span.line, col: d.span.col },
    notes: d.notes, confidence: d.confidence,
  };
}

function loaded(input: Case): [Face | null, Bag] {
  const bag = new Bag();
  return [load(input.path, bag, input.text, repoFileExists), bag];
}

/** The port of `face`: `null` for a design that does not load, which the oracle does not dump. */
export function face(input: Case): unknown {
  const [built] = loaded(input);
  return built === null ? null : irJson(built);
}

/** The port of `diagnostics-load`. */
export function diagnosticsLoad(input: Case): unknown {
  const [, bag] = loaded(input);
  return bag.items.map(diagnosticJson);
}
