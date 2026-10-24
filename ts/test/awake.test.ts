// `system.awake`: true while the watch is awake, false while it sleeps, so
// a digital seconds reading can hide asleep instead of freezing.
import assert from "node:assert/strict";
import { test } from "node:test";
import { previewOptions, render, sampleValues } from "../src/preview.ts";
import type { Image } from "../src/raster/pillow.ts";
import { MINIMAL, method, resolved, view } from "./designs.ts";

const SECONDS = (visible: string): string => MINIMAL + `  seconds:
    type: text
    text: "{time.second:02d}"
    font: FONT_SMALL
    at: {anchor: center}
    color: color.fg
${visible}`;
const HIDDEN_ASLEEP = SECONDS("    visible: system.awake\n");

/** The pixels two frames differ at, as a bounding box `[left, top, right, bottom]`, or null. */
function changed(a: Image, b: Image): [number, number, number, number] | null {
  let box: [number, number, number, number] | null = null;
  for (let y = 0; y < a.height; y++) {
    for (let x = 0; x < a.width; x++) {
      const i = (y * a.width + x) * 4;
      if (a.data[i] === b.data[i] && a.data[i + 1] === b.data[i + 1] && a.data[i + 2] === b.data[i + 2]) continue;
      box = box === null ? [x, y, x, y] : [Math.min(box[0], x), Math.min(box[1], y), Math.max(box[2], x), Math.max(box[3], y)];
    }
  }
  return box;
}

test("the view keeps an asleep flag, set by the sleep hooks, and reads system.awake off it each frame", () => {
  const source = view(HIDDEN_ASLEEP);
  assert.match(source, /private var _sleeping as Boolean = false;/);
  assert.match(method(source, "onUpdate"), /var awake = !_sleeping;/);
  assert.match(method(source, "onEnterSleep"), /_sleeping = true;/);
  assert.match(method(source, "onExitSleep"), /_sleeping = false;/);
  assert.match(method(source, "drawSeconds"), /if \(!\(systemAwake\)\)/);
  // a face that never reads it keeps no flag
  assert.doesNotMatch(view(SECONDS("")), /_sleeping/);
});

test("the preview hides it asleep and in the always-on frame, and nothing else", () => {
  const options = { time: [10, 9, 42] as [number, number, number], scale: 1, quantise: false, mask_shape: false };
  const face = resolved(HIDDEN_ASLEEP);
  const awake = render(face, previewOptions(options));
  const asleep = render(face, previewOptions({ ...options, asleep: true }));
  const seconds = face.items.find((p) => p.id === "seconds")!.box;
  const box = changed(awake, asleep);
  assert.ok(box !== null, "the seconds still draw asleep");
  assert.ok(box[0] >= seconds.x && box[1] >= seconds.y && box[2] < seconds.x + seconds.width && box[3] < seconds.y + seconds.height,
    `asleep changed pixels outside the seconds' box: ${box} against ${JSON.stringify(seconds)}`);
  // without the binding, sleeping changes nothing
  const plain = resolved(SECONDS(""));
  assert.equal(changed(render(plain, previewOptions(options)), render(plain, previewOptions({ ...options, asleep: true }))), null);
  // and an explicit sample still wins, as for any reading
  const sampled = render(face, previewOptions({ ...options, asleep: true, sample: new Map([["system.awake", true]]) }));
  assert.equal(changed(awake, sampled), null);
  // the always-on frame is a sleeping one too
  assert.equal(sampleValues(face, previewOptions({ aod: true }), null).get("system.awake"), false);
  assert.equal(sampleValues(face, previewOptions(), null).get("system.awake"), true);
});
