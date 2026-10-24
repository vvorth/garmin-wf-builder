// The patch engine on a YAML `&anchor` and its `*alias`es: an edit to the
// anchored value keeps the anchor and changes every alias with it; an
// edit through an alias writes the alias out first and changes that key
// alone; removing an anchor something still repeats is refused.
import assert from "node:assert/strict";
import { test } from "node:test";
import { insertItem, moveItem, type Patch, remove, removeItem, setValue } from "../src/edit/patch.ts";
import { parse, Refused, sameData, SpanIndex } from "../src/edit/spans.ts";

const TEXT = `config:
  slots:
    top: { default: steps, choices: &rim [steps, heart_rate, calories] }
    bottom: { default: calories, choices: *rim }
    side:
      default: steps
      choices: *rim
`;

/**
 * The `choices:` of each slot after a patch, and the patched text's own
 * lines for them; the patch's expected data must be what its text reads
 * as, the check the editor refuses an edit on.
 */
function after(result: Patch): { choices: Record<string, unknown>; lines: string[] } {
  const text = result.text;
  assert.ok(sameData(parse(text), result.expected), `${result.what}: the text does not read as the patch expects`);
  const data = parse(text) as Map<string, Map<string, Map<string, Map<string, unknown>>>>;
  const slots = data.get("config")!.get("slots")!;
  return {
    choices: Object.fromEntries([...slots].map(([name, slot]) => [name, slot.get("choices")])),
    lines: text.split("\n").filter((line) => line.includes("choices")).map((line) => line.trim()),
  };
}

const index = (): SpanIndex => new SpanIndex(TEXT);
const SHARED = ["steps", "heart_rate", "calories"];

test("replacing the anchored list keeps &rim, and every *rim reads the new list", () => {
  const out = after(setValue(index(), ["config", "slots", "top", "choices"], ["steps", "battery"]));
  assert.deepEqual(out.choices, { top: ["steps", "battery"], bottom: ["steps", "battery"], side: ["steps", "battery"] });
  assert.deepEqual(out.lines, ["top: { default: steps, choices: &rim [steps, battery] }", "bottom: { default: calories, choices: *rim }", "choices: *rim"]);
});

test("an item edit on the anchored list changes the shared list", () => {
  const added = after(insertItem(index(), ["config", "slots", "top", "choices"], 3, "battery"));
  assert.deepEqual(added.choices.side, [...SHARED, "battery"]);
  assert.match(added.lines[0]!, /&rim \[steps, heart_rate, calories, battery\]/);
  assert.deepEqual(after(moveItem(index(), ["config", "slots", "top", "choices"], 0, 2)).choices.bottom, ["heart_rate", "calories", "steps"]);
  assert.deepEqual(after(setValue(index(), ["config", "slots", "top", "choices", 1], "stress")).choices.side, ["steps", "stress", "calories"]);
  assert.deepEqual(after(removeItem(index(), ["config", "slots", "top", "choices"], 1)).choices.bottom, ["steps", "calories"]);
});

test("an edit through *rim writes that alias out and changes only its key", () => {
  // the whole list, an item added, one removed, one moved, one changed: each on the flow alias and the block one
  for (const slot of ["bottom", "side"]) {
    const path = ["config", "slots", slot, "choices"];
    const cases: [Patch, unknown][] = [
      [setValue(index(), path, ["battery"]), ["battery"]],
      [insertItem(index(), path, 0, "battery"), ["battery", ...SHARED]],
      [removeItem(index(), path, 0), ["heart_rate", "calories"]],
      [moveItem(index(), path, 2, 0), ["calories", "steps", "heart_rate"]],
      [setValue(index(), [...path, 0], "stress"), ["stress", "heart_rate", "calories"]],
    ];
    for (const [result, expected] of cases) {
      const out = after(result);
      assert.deepEqual(out.choices[slot], expected, result.text);
      for (const other of ["top", "bottom", "side"]) if (other !== slot) assert.deepEqual(out.choices[other], SHARED, `${slot} changed ${other}`);
      assert.match(out.lines[0]!, /&rim \[steps, heart_rate, calories\]/);
    }
  }
});

test("removing what holds &rim is refused while an alias repeats it; removing an alias is not", () => {
  assert.throws(() => remove(index(), ["config", "slots", "top"]),
    (e: unknown) => e instanceof Refused && /config\.slots\.top holds &rim, which config\.slots\.bottom\.choices, config\.slots\.side\.choices repeat as \*rim/.test(e.message));
  assert.throws(() => remove(index(), ["config", "slots", "top", "choices"]), Refused);
  const out = after(remove(index(), ["config", "slots", "bottom"]));
  assert.deepEqual(out.choices, { top: SHARED, side: SHARED });
});
