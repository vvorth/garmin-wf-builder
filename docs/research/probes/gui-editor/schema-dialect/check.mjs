import pkg from "json-schema-library"; const { Draft04, Draft07 } = pkg;
import fs from "fs";
const out = [];
const { schema, cases } = JSON.parse(fs.readFileSync(new URL("./cases.json", import.meta.url)));
for (const [name, D] of [["Draft04 (validation, hover)", Draft04], ["Draft07 (completion)", Draft07]]) {
  const draft = new D(schema);
  let falsePos = 0, missed = 0, agree = 0, crash = 0; const ex = [];
  for (const c of cases) {
    let n;
    try { n = draft.validate(c.doc).length; } catch (e) { crash++; if (ex.length < 3) ex.push("crash " + c.name + ": " + e.message); continue; }
    if (c.py_errors === 0 && n > 0) { falsePos++; if (ex.length < 4) ex.push("false error: " + c.name + " -> " + JSON.stringify(draft.validate(c.doc)[0]?.message)); }
    else if (c.py_errors > 0 && n === 0) { missed++; if (ex.length < 6) ex.push("missed: " + c.name); }
    else agree++;
  }
  const dep = cases.filter((c) => c.name.includes("dependentRequired"));
  const depMissed = dep.filter((c) => c.py_errors > 0 && draft.validate(c.doc).length === 0).length;
  out.push(`${name}: ${cases.length} cases, agree ${agree}, false errors on valid ${falsePos}, missed errors ${missed} (dependentRequired: ${depMissed}/${dep.length} missed), crashes ${crash}`);
  for (const e of ex) out.push("  " + e);
}
console.log(out.join("\n"));
fs.writeFileSync(new URL("./results.txt", import.meta.url), out.join("\n") + "\n");
