// The tables in src/data/ that copy files elsewhere are up to date with them,
// and the hand-written ones hold together.
import assert from "node:assert/strict";
import { test } from "node:test";
import * as catalog from "../src/catalog.ts";
import icons from "../src/data/icons.json" with { type: "json" };
import { CATALOG } from "../src/icons.ts";
import { exportData } from "../tools/export-data.ts";

test("src/data's copies of runtime-lib/ and templates/ are fresh", () => {
  assert.deepEqual(exportData(true), [], "run node ts/tools/export-data.ts");
});

/** What is wrong with an `icons.json` `rules` table, one line per fault. */
function ruleProblems(rules: Record<string, Record<string, unknown>>): string[] {
  const out: string[] = [];
  const named = (rule: string, where: string, name: unknown): void => {
    if (typeof name !== "string" || !CATALOG.has(name)) out.push(`${rule}: ${where} ${JSON.stringify(name)} is not a catalogue name`);
  };
  const ruleOf = new Map<string, string>();
  for (const [name, rule] of Object.entries(rules)) {
    named(name, "plain", rule["plain"]);
    const sources = Array.isArray(rule["sources"]) ? rule["sources"] as unknown[] : [];
    if (sources.length === 0) out.push(`${name}: no sources`);
    const follows = Object.keys((rule["follows"] ?? {}) as Record<string, unknown>);
    for (const source of [...sources, ...follows]) {
      if (typeof source !== "string" || catalog.get(source) === undefined) out.push(`${name}: ${JSON.stringify(source)} is not a catalogue source`);
      else if (ruleOf.has(source)) out.push(`${name}: ${source} already follows the ${ruleOf.get(source)} rule`);
      else ruleOf.set(source, name);
    }
    for (const read of Object.values((rule["follows"] ?? {}) as Record<string, unknown>)) {
      if (typeof read !== "string" || !sources.includes(read)) out.push(`${name}: follows ${JSON.stringify(read)}, not one of its own sources`);
    }
    // An on/off source is read as 0 or 1: only a two-step rule at threshold 1
    // splits it, and its chooser takes a Lang.Boolean, so no other source may share it.
    const booleans = sources.filter((source) => typeof source === "string" && catalog.get(source)?.type === "boolean");
    if (booleans.length > 0) {
      if (booleans.length !== sources.length) out.push(`${name}: on/off sources share the rule with other readings`);
      if (rule["kind"] !== "steps" || JSON.stringify(rule["thresholds"]) !== "[1]") out.push(`${name}: an on/off source takes a steps rule with thresholds [1]`);
    }
    if (rule["kind"] === "steps") {
      const steps = rule["steps"];
      if (!Array.isArray(steps) || steps.length < 2) out.push(`${name}: a steps rule needs two steps or more`);
      else steps.forEach((step, i) => named(name, `steps[${i}]`, step));
      const range = rule["range"], thresholds = rule["thresholds"];
      if ((range === undefined) === (thresholds === undefined)) out.push(`${name}: a steps rule has exactly one of range or thresholds`);
      if (range !== undefined && !(Array.isArray(range) && range.length === 2 && range[0] < range[1])) out.push(`${name}: range is [lo, hi], lo below hi`);
      if (thresholds !== undefined && !(Array.isArray(thresholds) && Array.isArray(steps) && thresholds.length === steps.length - 1
        && thresholds.every((t, i) => typeof t === "number" && (i === 0 ? t > 0 : t > thresholds[i - 1]!)))) {
        out.push(`${name}: thresholds rise above 0, one fewer than the steps`);
      }
      if (rule["map"] !== undefined) out.push(`${name}: a steps rule has no map`);
      if (rule["cyclic"] !== undefined && range === undefined) out.push(`${name}: a cyclic rule wraps a range, so it needs one`);
    } else if (rule["kind"] === "table") {
      const map = rule["map"];
      if (map === null || typeof map !== "object" || Object.keys(map).length === 0) out.push(`${name}: a table rule needs a map`);
      else for (const [value, step] of Object.entries(map)) named(name, `map[${value}]`, step);
      for (const key of ["steps", "range", "thresholds", "cyclic"]) if (rule[key] !== undefined) out.push(`${name}: a table rule has no ${key}`);
    } else {
      out.push(`${name}: kind ${JSON.stringify(rule["kind"])} is neither steps nor table`);
    }
  }
  return out;
}

test("icons.json's rules name catalogue glyphs and sources, each rule one shape, each source one rule", () => {
  assert.deepEqual(ruleProblems(icons.rules as unknown as Record<string, Record<string, unknown>>), []);
});

test("a malformed rule is caught", () => {
  const steps = { kind: "steps", label: "L", plain: "battery", sources: ["system.battery"], range: [0, 100], steps: ["battery_level_0", "battery_level_1"] };
  assert.deepEqual(ruleProblems({ ok: steps }), []);
  const cases: [Record<string, unknown>, RegExp][] = [
    [{ ...steps, plain: "no_such_glyph" }, /plain "no_such_glyph" is not a catalogue name/],
    [{ ...steps, steps: ["battery_level_0", "nope"] }, /steps\[1\] "nope" is not a catalogue name/],
    [{ ...steps, thresholds: [1] }, /exactly one of range or thresholds/],
    [{ ...steps, range: undefined }, /exactly one of range or thresholds/],
    [{ ...steps, range: undefined, thresholds: [1, 2] }, /thresholds rise above 0/],
    [{ ...steps, sources: ["system.no_such_source"] }, /"system.no_such_source" is not a catalogue source/],
    [{ kind: "table", label: "L", plain: "weather_unknown", sources: ["weather.condition"] }, /a table rule needs a map/],
    [{ kind: "table", label: "L", plain: "weather_unknown", sources: ["weather.condition"], map: { 0: "nope" } }, /map\[0\] "nope"/],
    [{ kind: "table", label: "L", plain: "weather_unknown", sources: ["weather.condition"], map: { 0: "weather_sunny" },
      follows: { "complication.current_temperature": "weather.condition_today" } }, /follows "weather.condition_today", not one of its own sources/],
    [{ ...steps, kind: "ring" }, /neither steps nor table/],
    [{ ...steps, range: undefined, thresholds: [1], cyclic: true }, /a cyclic rule wraps a range/],
    [{ ...steps, sources: ["device.do_not_disturb"] }, /an on\/off source takes a steps rule with thresholds \[1\]/],
    [{ ...steps, range: undefined, thresholds: [1], sources: ["device.do_not_disturb", "device.alarm_count"] }, /on\/off sources share the rule/],
  ];
  for (const [rule, problem] of cases) assert.match(ruleProblems({ bad: rule }).join("\n"), problem);
  assert.match(ruleProblems({ ok: steps, again: steps }).join("\n"), /again: system.battery already follows the ok rule/);
});
