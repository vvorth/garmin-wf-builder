// A slot's count: whole below 10,000, thousands with one decimal above; with
// `short: true`, thousands from 1,000 already, so the reading stays short.
import assert from "node:assert/strict";
import { test } from "node:test";
import { formatReading } from "../src/complications.ts";
import { WholeFloat } from "../src/edit/yaml.ts";
import { generated, MINIMAL } from "./designs.ts";

test("short counts go to thousands from 1,000; long ones from 10,000", () => {
  const read = (value: unknown, short: boolean, unit: unknown = null): string | null => formatReading("steps", value, unit, { short });
  assert.deepEqual([143, 765, 999, 1000, 1500, 7849, 9999, 12879].map((v) => read(v, true)),
    ["143", "765", "999", "1.0K", "1.5K", "7.8K", "10.0K", "12.9K"]);
  assert.deepEqual([143, 999, 1500, 7849, 9999, 12879].map((v) => read(v, false)),
    ["143", "999", "1500", "7849", "9999", "12.9K"]);
  // the device's own thousands are kept either way
  assert.equal(read(new WholeFloat(12.879), true, "K"), "12.9K");
  assert.equal(formatReading("calories", 2345, null, { short: true }), "2.3K");
});

test("the watch's count follows the element's short:", () => {
  const face = MINIMAL.replace("resources:", `config:
  slots:
    top: { default: steps, choices: [steps, vo2max_run] }
resources:`) + `
  top_reading:
    type: data
    slot: top
    short: true
    at: {anchor: center}
    font: FONT_SMALL
    color: color.fg
    absent: hide
`;
  const files = generated(face, ["fenix8solar47mm"]);
  const slotText = [...files].find(([name]) => name.endsWith("SlotText.mc"))![1];
  assert.match(slotText, /WfbReading\.count\(value, c\.unit, short\)/);
  // VO2 max is never thousands
  assert.match(slotText, /WfbReading\.count\(value, c\.unit, false\)/);
});
