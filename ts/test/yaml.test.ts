// The composer reproduces ruamel's marks, tags and values. The corpus is
// held to ruamel by `npm run parity -- nodes`; these are the rules it found,
// each in a case that tells the right rule from the obvious one.
import assert from "node:assert/strict";
import { test } from "node:test";
import { indexFor, Refused, SpanIndex } from "../src/edit/spans.ts";
import { compose, parse, resolvePlain, Timestamp, type YamlNode } from "../src/edit/yaml.ts";

function value(root: YamlNode | null, key: string): YamlNode {
  assert.ok(root !== null && root.kind === "mapping");
  const pair = root.pairs.find(([k]) => k.kind === "scalar" && k.value === key);
  assert.ok(pair, key);
  return pair[1];
}

test("an empty value is a zero-width node at the next token", () => {
  const text = "a:\nb: 1\n";
  const a = value(compose(text), "a");
  assert.equal(a.start.index, 3);
  assert.equal(a.end.index, 3);
  assert.equal(a.tag, "tag:yaml.org,2002:null");
});

test("a block mapping ends where the next token starts, past comments", () => {
  const text = "top:\n  child: 1\n  # inside\n# outside\nnext: 2\n";
  assert.equal(value(compose(text), "top").end.index, text.indexOf("next"));
});

test("a block scalar ends at the start of the first line it does not take, not at that line's indent", () => {
  const text = "outer:\n  text: >-\n    one\n    two\n  font: x\n";
  const outer = value(compose(text), "outer");
  const scalar = value(outer, "text");
  assert.equal(scalar.end.index, text.indexOf("  font"));
  assert.equal(scalar.end.column, 0);
  assert.equal(scalar.kind === "scalar" && scalar.value, "one two");
});

test("plain scalars resolve by ruamel's YAML 1.2 rules, timestamps included", () => {
  assert.equal(resolvePlain("017"), "tag:yaml.org,2002:int");
  assert.equal(resolvePlain("yes"), "tag:yaml.org,2002:str");
  assert.equal(resolvePlain("2026-10-05"), "tag:yaml.org,2002:timestamp");
  assert.equal(resolvePlain("12:30"), "tag:yaml.org,2002:str");
  assert.equal(resolvePlain(".5"), "tag:yaml.org,2002:float");
});

test("integers read with a leading zero as decimal, and with underscores", () => {
  const data = parse("a: 017\nb: 1_000\nc: 0x1F\nd: 0o17\ne: 2026-10-05\n");
  assert.ok(data instanceof Map);
  assert.deepEqual([...data.values()].slice(0, 4), [17, 1000, 31, 15]);
  assert.ok(data.get("e") instanceof Timestamp);
});

test("mapping order survives integer-like keys", () => {
  const data = parse("b: 1\n10: 2\na: 3\n");
  assert.ok(data instanceof Map);
  assert.deepEqual([...data.keys()], ["b", 10, "a"]);
});

test("a duplicate key and invalid text are refused", () => {
  assert.throws(() => new SpanIndex("a: 1\na: 2\n"), Refused);
  assert.throws(() => new SpanIndex("key: [unclosed\n"), Refused);
});

test("an entry's range takes its leading comments at its own indent", () => {
  const text = "elements:\n  # the clock\n  clock: { type: text }\n  other: { type: text }\n";
  const index = indexFor(text);
  const clock = index.at(["elements", "clock"]);
  const [start, end] = index.entryRange(clock);
  assert.equal(text.slice(start, end), "  # the clock\n  clock: { type: text }\n");
});
