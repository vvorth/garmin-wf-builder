// The `yaml` package (eemeli) against ruamel on every example YAML
// (dump_spans.py):
// 1. the text round-trips byte for byte through the CST (the lossless
//    layer; `toString()` re-serialises, and is counted separately);
// 2. the data equals ruamel's;
// 3. every `key: value` entry's key start, value start and value end (as
//    wfb.edit.spans.SpanIndex.value_end derives it) match ruamel's.
//   node yaml.mjs spans.json <repo>
import YAML from "yaml";
import { readFileSync } from "node:fs";
import { isDeepStrictEqual } from "node:util";

const [spansPath, repo] = process.argv.slice(2);
const ref = JSON.parse(readFileSync(spansPath, "utf8"));
const lineStart = (t, i) => t.lastIndexOf("\n", i - 1) + 1;
const lineEnd = (t, i) => { const e = t.indexOf("\n", i); return e < 0 ? t.length : e + 1; };
// SpanIndex.value_end, fed `yaml`'s valueEnd instead of ruamel's end mark.
function valueEnd(t, node, keyStart) {
  const end = node.range[1];
  const head = lineStart(t, end);
  if (t.slice(head, end).trim() === "" && end > keyStart) return head;
  return lineEnd(t, Math.max(end - 1, 0));
}
// ruamel's side is `wfb.edit.spans.ordered`: a mapping as a list of pairs.
const pairs = (x) => (Array.isArray(x) ? x.map(pairs)
  : x && typeof x === "object" ? Object.entries(x).map(([k, val]) => [k, pairs(val)]) : x);
const totals = { files: 0, cst_roundtrip: 0, tostring_roundtrip: 0, data: 0, entries: 0, key: 0, value: 0, end: 0 };
const misses = [];
for (const [file, r] of Object.entries(ref)) {
  const text = readFileSync(`${repo}/${file}`, "utf8");
  const doc = YAML.parseDocument(text, { keepSourceTokens: true, uniqueKeys: true });
  totals.files++;
  if ([...new YAML.Parser().parse(text)].map((tok) => YAML.CST.stringify(tok)).join("") === text) totals.cst_roundtrip++;
  else misses.push(`${file}: CST round trip differs`);
  if (doc.toString() === text) totals.tostring_roundtrip++;
  if (isDeepStrictEqual(pairs(JSON.parse(JSON.stringify(doc.toJS({ maxAliasCount: -1 })))), r.data)) totals.data++;
  else misses.push(`${file}: data differs`);
  const mine = new Map();
  const walk = (node, path) => {
    if (YAML.isMap(node)) for (const pair of node.items) {
      const p = [...path, String(pair.key.value)];
      mine.set(JSON.stringify(p), pair);
      walk(pair.value, p);
    } else if (YAML.isSeq(node)) node.items.forEach((n, i) => walk(n, [...path, String(i)]));
  };
  walk(doc.contents, []);
  for (const e of r.entries) {
    totals.entries++;
    const pair = mine.get(JSON.stringify(e.path));
    const where = `${file} ${e.path.join(".")}`;
    if (!pair || !pair.value) { misses.push(`${where}: no value node`); continue; }
    if (pair.key.range[0] === e.key) totals.key++; else misses.push(`${where}: key ${pair.key.range[0]} vs ${e.key}`);
    if (pair.value.range[0] === e.value) totals.value++; else misses.push(`${where}: value ${pair.value.range[0]} vs ${e.value}`);
    const end = valueEnd(text, pair.value, e.key);
    if (end === e.value_end) totals.end++; else misses.push(`${where}: end ${end} vs ruamel ${e.value_end}`);
  }
  if (file === "examples/showcase/face.yaml") {
    let best = 1e9;
    for (let i = 0; i < 5; i++) {
      const s = performance.now(); YAML.parseDocument(text, { keepSourceTokens: true }); best = Math.min(best, performance.now() - s);
    }
    console.log(`showcase parse: yaml ${best.toFixed(1)} ms (best of 5); ruamel ${r.ruamel_ms} ms (one run)`);
  }
}
console.log(JSON.stringify(totals));
console.log(misses.join("\n"));
