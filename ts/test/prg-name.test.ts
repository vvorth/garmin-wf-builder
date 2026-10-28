// A built face's file name: `<stem>-<version>-<device>.prg`, for the CLI's
// build and the editor's download alike.
import assert from "node:assert/strict";
import { test } from "node:test";
import { prgName } from "../src/build.ts";

test("the version sits between the name and the device", () => {
  assert.equal(prgName("feature-shapes", "1.0.0", "fenix8solar47mm"), "feature-shapes-1.0.0-fenix8solar47mm.prg");
  assert.equal(prgName("my-face", "2.1.0-beta+3", "fr955"), "my-face-2.1.0-beta+3-fr955.prg");
});

test("a version keeps only what is safe in a file name, and one with nothing left is dropped", () => {
  assert.equal(prgName("f", "1.0 / rc 1", "fr955"), "f-1.0-rc-1-fr955.prg");
  assert.equal(prgName("f", "../../x", "fr955"), "f-x-fr955.prg");
  assert.equal(prgName("f", "", "fr955"), "f-fr955.prg");
  assert.equal(prgName("f", " / ", "fr955"), "f-fr955.prg");
});
