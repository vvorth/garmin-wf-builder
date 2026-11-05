// `wfb export`'s phone-settings line, through the function that composes it
// (the export itself needs `monkeyc`).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, test } from "node:test";
import { REPO_ROOT } from "../src/devices/node.ts";
import { phoneSettingsLine } from "../src/export_summary.ts";
import { db, face } from "./designs.ts";

const CONFIG = readFileSync(join(REPO_ROOT, "examples", "features", "config", "face.yaml"), "utf8");
const MINIMAL = readFileSync(join(REPO_ROOT, "examples", "features", "sun", "face.yaml"), "utf8");
const devices = (...ids: string[]) => ids.map((id) => db.get(id));

describe("the export's phone-settings line", () => {
  test("names the axes and the devices that use the settings menu", () => {
    const f = face(CONFIG);
    assert.equal(phoneSettingsLine(f, devices("fenix8solar47mm", "fr955")), "phone settings: 3 axes on fr955");
  });
  test("none when every device has the native editor", () => {
    const f = face(CONFIG);
    assert.equal(phoneSettingsLine(f, devices("fenix8solar47mm", "fenix8solar51mm")), "phone settings: none (every device has the native editor)");
  });
  test("none without config:", () => {
    assert.equal(phoneSettingsLine(face(MINIMAL), devices("fr955")), "phone settings: none (no config:)");
  });
});
