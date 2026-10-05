// Ajv (Draft 2020-12, allErrors) against jsonschema on every example face
// and 40 seeded mutations of each (dump_schema.py): validity agreement,
// leaf-error agreement, and time.
//   node schema.mjs schema_cases.json
import Ajv2020 from "ajv/dist/2020.js";
import { readFileSync } from "node:fs";

const { schema, cases } = JSON.parse(readFileSync(process.argv[2], "utf8"));
let t = performance.now();
const validate = new Ajv2020({ allErrors: true, strict: false }).compile(schema);
console.log(`compile ${(performance.now() - t).toFixed(0)} ms`);
let agree = 0, leafSame = 0, leafCovered = 0, ajvMs = 0, pyMs = 0;
const disagreements = [];
for (const c of cases) {
  t = performance.now();
  const ok = validate(c.data);
  ajvMs += performance.now() - t; pyMs += c.ms;
  if (ok === c.valid) agree++; else disagreements.push(`${c.face} ${c.what}: ajv ${ok}, jsonschema ${c.valid}`);
  // jsonschema writes the root as "/", Ajv as "".
  const mine = new Set((validate.errors || []).map((e) => JSON.stringify([e.instancePath || "/", e.keyword])));
  const theirs = c.leaves.map(([p, k]) => JSON.stringify([p, k]));
  if (theirs.length === mine.size && theirs.every((x) => mine.has(x))) leafSame++;
  if (theirs.every((x) => mine.has(x))) leafCovered++;
}
console.log(JSON.stringify({
  cases: cases.length, validity_agree: agree, leaf_sets_equal: leafSame,
  jsonschema_leaves_all_in_ajv: leafCovered, ajv_ms_total: Math.round(ajvMs), jsonschema_ms_total: Math.round(pyMs),
}));
console.log(disagreements.join("\n"));
