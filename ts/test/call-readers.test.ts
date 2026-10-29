// A source read through a barrel call (`call:` + `extra_readers`) is seen
// by every consumer that classifies a source by its reader, not only the
// hoisting: the partial-update-budget lint and the complication-type walk
// look at every reader the call takes.
import assert from "node:assert/strict";
import { test } from "node:test";
import * as availability from "../src/availability.ts";
import { CATALOG, type Source } from "../src/catalog.ts";
import { checked, db, face, MINIMAL } from "./designs.ts";

const installed = (...ids: string[]): boolean => ids.every((id) => db.ids().includes(id));

/** A synthetic call source: primary `clock` (never null, cheap), the extra reader is `extra`. */
function synthetic(extra: string): Source {
  return { ...CATALOG.get("position.latitude")!, path: "astro.test", reader: "clock", extra_readers: [extra], call: "WfbAstro.latitude", field_name: null };
}

const sleeping = (path: string): string => `${MINIMAL}
  reading:
    type: text
    text: "{${path}:.1f}"
    font: FONT_SMALL
    at: {anchor: center}
    color: color.fg
    sleep_update: true
    absent: {text: "--"}
`;

const codes = (text: string): string[] => checked(text).map((d) => d.code);

test("the partial-update-budget lint sees a weather reader taken as a call's extra reader", () => {
  if (!installed("fenix8solar47mm")) return;
  // The lint fires on the primary reader today: the contrast this test needs.
  assert.ok(codes(sleeping("position.latitude")).includes("partial-update-budget"), "primary weather reader");
  assert.ok(!codes(sleeping("time.utc_offset")).includes("partial-update-budget"), "a cheap read is not reported");
  const source = synthetic("weather_current");
  CATALOG.set(source.path, source);
  try {
    assert.ok(codes(sleeping("astro.test")).includes("partial-update-budget"), "the extra weather reader is as expensive as a primary one");
  } finally {
    CATALOG.delete(source.path);
  }
});

test("complicationTypesNamed sees a complication reader taken as a call's extra reader", () => {
  if (!installed("fenix8solar47mm")) return;
  const source = synthetic("complication_sleep_score");
  CATALOG.set(source.path, source);
  try {
    const named = availability.complicationTypesNamed(face(sleeping("astro.test")));
    assert.ok(named.has("sleep_score"), [...named].join(", "));
  } finally {
    CATALOG.delete(source.path);
  }
});
