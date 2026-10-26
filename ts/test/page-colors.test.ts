// The colour picker's 64: six hue families and the grays, each family the
// same block of tones.
import assert from "node:assert/strict";
import { test } from "node:test";
import { mipFamilies } from "../app/values.ts";
import { MIP64_NAMED } from "../src/palette.ts";

const MIP = MIP64_NAMED.map(([name, value, label]) => ({ name, value, label, note: null }));

/** A family's rows as hex, a gap as "------". */
const shown = (rows: ({ value: string } | null)[][]): string => rows.map((row) => row.map((c) => (c ? c.value.slice(1) : "------")).join(" ")).join(" / ");

test("the 64 lay out as six families of ten and four grays, each block light to dark", () => {
  const families = mipFamilies(MIP)!;
  assert.deepEqual(Object.fromEntries(families.map((f) => [f.name, shown(f.rows)])), {
    Red: "FF55AA FFAAAA FF5555 / FF0055 FF0000 FF5500 / AA0055 AA5555 AA0000 / ------ 550000 ------",
    Yellow: "FFAA55 FFFFAA FFFF55 / FFAA00 FFFF00 AAFF00 / AA5500 AAAA55 AAAA00 / ------ 555500 ------",
    Green: "AAFF55 AAFFAA 55FF55 / 55FF00 00FF00 00FF55 / 55AA00 55AA55 00AA00 / ------ 005500 ------",
    Cyan: "55FFAA AAFFFF 55FFFF / 00FFAA 00FFFF 00AAFF / 00AA55 55AAAA 00AAAA / ------ 005555 ------",
    Blue: "55AAFF AAAAFF 5555FF / 0055FF 0000FF 5500FF / 0055AA 5555AA 0000AA / ------ 000055 ------",
    Magenta: "AA55FF FFAAFF FF55FF / AA00FF FF00FF FF00AA / 5500AA AA55AA AA00AA / ------ 550055 ------",
    Gray: "FFFFFF / AAAAAA / 555555 / 000000",
  });
  // every colour once, carrying its name and label through
  const placed = families.flatMap((f) => f.rows.flat()).filter((c) => c !== null);
  assert.equal(new Set(placed.map((c) => c.value)).size, 64);
  assert.ok(placed.every((c) => MIP.some((m) => m.name === c.name && m.value === c.value && m.label === c.label)));
});

test("a list that is not the 64 has no family layout", () => {
  assert.equal(mipFamilies(MIP.slice(1)), null);
  assert.equal(mipFamilies([...MIP.slice(1), { name: "x", value: "#123456", label: "X", note: null }]), null);
});
