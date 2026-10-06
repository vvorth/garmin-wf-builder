// Colours: parsing, what each panel can show, the nearest it shows, and the
// preview's snapping, which must agree with the lint's "nearest" exactly.
import assert from "node:assert/strict";
import { test } from "node:test";
import { mip64Name, MIP64_NAMED } from "../src/palette.ts";
import { BLACK, Color, ColorError, hasPaletteRule, MIP64_LEVELS, WHITE } from "../src/palette.ts";
import { quantise } from "../src/preview.ts";
import { commentText, controlCharacter, stringLiteral } from "../src/mcsource.ts";
import { javaStringHash } from "../src/emit/strhash.ts";
import { errors, face } from "./designs.ts";

test("parsing and refusing", () => {
  for (const [raw, value] of [["#FF5500", 0xFF5500], ["FF5500", 0xFF5500], ["#f50", 0xFF5500], [0x00AA55, 0x00AA55]] as const) assert.equal(Color.parse(raw).value, value);
  for (const raw of ["#GGGGGG", "orange", "#FF55", null, true]) assert.throws(() => Color.parse(raw), ColorError, String(raw));
});

test("what a 64-colour and a 2-colour panel show", () => {
  for (const [hex, legal] of [["#000000", true], ["#FFFFFF", true], ["#FF5500", true], ["#55AAFF", true], ["#FF5501", false], ["#123456", false], ["#808080", false]] as const) {
    assert.equal(Color.parse(hex).isPaletteLegal(64), legal, hex);
  }
  const nearest = Color.parse("#808080").nearestLegal(64);
  assert.ok([nearest.r, nearest.g, nearest.b].every((c) => (MIP64_LEVELS as readonly number[]).includes(c)));
  assert.equal(Color.parse("#123456").isPaletteLegal(null), true);
  for (const [hex, legal] of [["#000000", true], ["#FFFFFF", true], ["#FF0000", false], ["#555555", false], ["#AAAAAA", false]] as const) {
    assert.equal(Color.parse(hex).isPaletteLegal(2), legal, hex);
    assert.equal(Color.parse(hex).isPaletteLegal(64), true, hex);
  }
  for (const [hex, want] of [["#777777", "#FFFFFF"], ["#707070", "#000000"], ["#FF0000", "#FFFFFF"], ["#5555AA", "#000000"]]) {
    const color = Color.parse(hex);
    assert.equal(String(color.nearestLegal(2)), want, hex);
    assert.equal(String(color.contrastRatio(BLACK) < color.contrastRatio(WHITE) ? BLACK : WHITE), want, hex);
  }
  for (const [colors, known] of [[2, true], [64, true], [65536, true], [8, false], [14, false], [null, false]] as const) assert.equal(hasPaletteRule(colors), known);
  assert.ok(Math.abs(WHITE.contrastRatio(BLACK) - 21) < 1e-9 && Math.abs(WHITE.contrastRatio(WHITE) - 1) < 1e-9);
});

test("the preview snaps every colour where the lint says", () => {
  // Every red and green in steps of 3 against 16 blues: dense enough to straddle the black/white crossover many times.
  const colours: [number, number, number][] = [];
  for (let b = 0; b < 256; b += 17) for (let g = 0; g < 256; g += 3) for (let r = 0; r < 256; r += 3) colours.push([r, g, b]);
  const data = new Uint8ClampedArray(colours.length * 4);
  colours.forEach(([r, g, b], i) => data.set([r, g, b, 255], i * 4));
  for (const colors of [2, 64]) {
    const snapped = quantise({ width: colours.length, height: 1, data }, colors);
    const disagree = colours.filter(([r, g, b], i) => {
      const want = new Color(r, g, b).nearestLegal(colors);
      return snapped.data[i * 4] !== want.r || snapped.data[i * 4 + 1] !== want.g || snapped.data[i * 4 + 2] !== want.b;
    });
    assert.deepEqual(disagree.slice(0, 3), [], `${disagree.length} colours disagree on ${colors}`);
  }
});

test("the named MIP table is the 64", () => {
  assert.equal(MIP64_NAMED.length, 64);
  assert.equal(new Set(MIP64_NAMED.map(([, v]) => v)).size, 64);
  for (const [name, value] of MIP64_NAMED) assert.equal(mip64Name(value), name);
});

const HEAD = `format: 2
face:
  id: 7f3c1e92-4a5b-4d81-9e6f-2b0c8d4a1f57
  name: Test
build:
  targets: [fr955]
`;
const BODY = `elements:
  background:
    type: rectangle
    at: { anchor: center }
    size: { width: 100%, height: 100% }
    color: color.bg
`;

test("a swatch's long form: its label, and a literal value", () => {
  const long = face(`${HEAD}resources:\n  palette:\n    bg: { value: "#00FFFF", label: "Aqua" }\n${BODY}`);
  assert.ok(long.palette.get("bg")!.equals(Color.parse("#00FFFF")));
  assert.deepEqual(Object.fromEntries(long.palette_labels), { bg: "Aqua" });
  assert.equal(face(`${HEAD}resources:\n  palette:\n    bg: { value: "#00FFFF" }\n${BODY}`).palette_labels.size, 0);
  const missing = `${HEAD}resources:\n  palette:\n    bg: { label: "Aqua" }\n${BODY}`;
  const schema = errors(missing).find((d) => d.code === "schema")!;
  assert.ok(missing.split("\n")[schema.span!.line - 1]!.includes("bg:"));
  const reference = `${HEAD}resources:\n  palette:\n    bg: { value: color.accent }\n${BODY}`;
  const all = errors(reference);
  assert.deepEqual(all.map((d) => d.code), ["schema"]);
  assert.ok(all[0]!.message.includes("palette.bg.value"));
  assert.ok(all[0]!.notes.join(" ").includes("a palette swatch's own value is always a literal"));
});

// -- Monkey C source --

test("a string literal escapes what would end or break it; a comment stays on its line", () => {
  assert.equal(stringLiteral('say "hi" \\ ok'), '"say \\"hi\\" \\\\ ok"');
  assert.equal(stringLiteral("a\nb\tc\rd\x01"), '"a\\nb\\tc\\rd\\u0001"');
  assert.equal(stringLiteral("é ✓"), '"é ✓"');
  assert.equal(commentText('widest "a\nb"'), 'widest "a\\nb"');
  assert.ok(!commentText("x\r\n\ty").includes("\n"));
  assert.equal(controlCharacter("fine"), null);
  assert.equal(controlCharacter("a\tb"), "\\t");
});

test("Java's string hash, as monkeyc labels a string", () => {
  assert.equal(javaStringHash(""), 0);
  assert.equal(javaStringHash("hello"), 99162322);
  assert.equal(javaStringHash("polygenelubricants"), -2147483648);
});
