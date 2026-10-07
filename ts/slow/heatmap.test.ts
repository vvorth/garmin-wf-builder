// `wfb preview --heatmap`, run as a user runs it: an AOD heat map renders
// every minute of the hour, about fifteen seconds, too slow for the fast
// suite (`test/cli.test.ts` keeps its flag conflicts).
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { REPO_ROOT } from "../src/devices/node.ts";
import { decodePng } from "../src/png.ts";

test("preview --heatmap writes one PNG to stdout and nothing to the working directory", () => {
  const cwd = mkdtempSync(join(tmpdir(), "wfb-heat-"));
  const done = spawnSync(process.execPath, [join(REPO_ROOT, "ts", "src", "cli.ts"), "preview",
    join(REPO_ROOT, "examples/features/aod/face.yaml"), "-d", "fenix847mm", "--heatmap", "--scale", "1", "-o", "-"],
  { cwd, env: { ...process.env, WFB_NO_GARMIN_FONTS: "1" }, maxBuffer: 64 * 1024 * 1024 });
  assert.equal(done.status, 0, done.stderr.toString());
  const png = decodePng(new Uint8Array(done.stdout))!;
  assert.deepEqual([png.width, png.height], [454, 454]);
  assert.deepEqual(readdirSync(cwd), []);
});
