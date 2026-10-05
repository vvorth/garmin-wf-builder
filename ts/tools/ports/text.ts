// Parity ports of the text stages: `nodes`, `data` and `spans`, in the
// oracle's JSON form (tools/oracle.py). Offsets are converted from UTF-16
// code units to the code points Python counts.
import { Refused, SpanIndex } from "../../src/edit/spans.ts";
import { compose, type Data, PyFloat, Timestamp, type YamlNode, YamlError } from "../../src/edit/yaml.ts";
import type { Case } from "../stages.ts";

/** UTF-16 offset → code-point offset, for `text`. */
export function codePoints(text: string): (index: number) => number {
  if (!/[\uD800-\uDFFF]/.test(text)) return (index) => index;
  const table = new Int32Array(text.length + 1);
  let cp = 0;
  for (let i = 0; i <= text.length; i++) {
    table[i] = cp;
    const c = text.charCodeAt(i);
    if (!(c >= 0xd800 && c <= 0xdbff)) cp++;
  }
  return (index) => table[index]!;
}

/** `data` as tools/oracle.py's `to_json(ordered(data))`. */
export function oracleData(data: Data): unknown {
  if (data instanceof Map) return [...data].map(([k, v]) => [oracleData(k), oracleData(v)]);
  if (Array.isArray(data)) return data.map(oracleData);
  if (data instanceof Timestamp) return { $timestamp: data.iso };
  if (data instanceof PyFloat) return oracleData(data.value);
  if (typeof data === "number" && !Number.isFinite(data)) {
    return { $float: Number.isNaN(data) ? "nan" : data > 0 ? "inf" : "-inf" };
  }
  return data;
}

function nodeJson(node: YamlNode, cp: (i: number) => number): unknown {
  const mark = (m: { index: number; line: number; column: number }): number[] => [cp(m.index), m.line, m.column];
  const base = { tag: node.tag, start: mark(node.start), end: mark(node.end) };
  if (node.kind === "scalar") return { kind: "scalar", ...base, style: node.style, value: node.value };
  if (node.kind === "sequence") return { kind: "sequence", ...base, flow: node.flow, items: node.items.map((n) => nodeJson(n, cp)) };
  return { kind: "mapping", ...base, flow: node.flow, pairs: node.pairs.map(([k, v]) => [nodeJson(k, cp), nodeJson(v, cp)]) };
}

export function nodes(input: Case): unknown {
  try {
    const root = compose(input.text);
    return root === null ? null : nodeJson(root, codePoints(input.text));
  } catch (error) {
    if (error instanceof YamlError) return { $error: "yaml", message: error.message };
    throw error;
  }
}

export function data(input: Case): unknown {
  return oracleData(compose(input.text) === null ? null : new SpanIndex(input.text).data);
}

export function spans(input: Case): unknown {
  let index: SpanIndex;
  try {
    index = new SpanIndex(input.text);
  } catch (error) {
    if (error instanceof Refused) return { $error: error.message };
    throw error;
  }
  const cp = codePoints(input.text);
  return index.entries().map((e) => ({
    path: [...e.path], key: cp(e.key.start.index), value: cp(e.value.start.index), end: cp(index.valueEnd(e)),
  }));
}
