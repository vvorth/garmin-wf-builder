// `wfb`, run as a user runs it: `node src/cli.ts …` from the repository's
// root, without the user's own Garmin fonts.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, test } from "node:test";
import { REPO_ROOT } from "../src/devices/node.ts";
import { decodePng } from "../src/png.ts";
import { formatBuilt } from "../src/cli.ts";
import * as series from "../src/series.ts";
import { db, MINIMAL } from "./designs.ts";

const CLI = join(REPO_ROOT, "ts", "src", "cli.ts");
const ESC = "\x1b";
const PNG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

interface Run { code: number; stdout: string; stderr: string; bytes: Buffer }

function wfb(args: string[], { cwd = REPO_ROOT, env = {} }: { cwd?: string; env?: Record<string, string | undefined> } = {}): Run {
  const done = spawnSync(process.execPath, [CLI, ...args], { cwd, env: { ...process.env, WFB_NO_GARMIN_FONTS: "1", ...env }, maxBuffer: 64 * 1024 * 1024 });
  return { code: done.status ?? -1, stdout: done.stdout.toString(), stderr: done.stderr.toString(), bytes: done.stdout };
}

const scratch = (): string => mkdtempSync(join(tmpdir(), "wfb-cli-"));
const plain = (text: string): string => text.replace(/\x1b\[[0-9;]*m/g, "");
const SUN = "examples/features/sun/face.yaml";

describe("the command line", { concurrency: true }, () => {
  test("doctor: ready here; names what is missing elsewhere; container advice", () => {
    const ok = wfb(["doctor"]);
    assert.equal(ok.code, 0, ok.stdout + ok.stderr);
    assert.ok(ok.stdout.includes("ready"));
    const home = scratch();
    const bare = wfb(["doctor"], { env: { WFB_DEVICES: join(home, "nothing-here"), HOME: home, CIQ_SDK: undefined } });
    assert.equal(bare.code, 1);
    assert.ok(bare.stdout.includes("not ready") && bare.stdout.includes("401") && bare.stdout.includes("Connect IQ SDK"));
    const fonts = join(scratch(), "fonts");
    const inContainer = wfb(["doctor"], { env: { WFB_FONTS: fonts, WFB_CONTAINER: "1" } }).stdout;
    assert.ok(inContainer.includes(`-v <SDK Manager's Fonts dir>:${fonts}:ro`) && !inContainer.includes("vendor/fonts/"));
    const onHost = wfb(["doctor"], { env: { WFB_FONTS: fonts, WFB_CONTAINER: undefined } }).stdout;
    assert.ok(onHost.includes("vendor/fonts/") && !onHost.includes(":ro"));
  });

  test("it works from an unrelated directory", () => {
    const r = wfb(["devices"], { cwd: scratch() });
    assert.equal(r.code, 0, r.stderr);
    assert.ok(r.stdout.includes("fenix8solar47mm"));
  });

  test("new: lists, refuses to overwrite, reads only its own templates, mints an id each", () => {
    const list = wfb(["new", "--list"]);
    assert.ok(list.code === 0 && list.stdout.includes("dashboard") && list.stdout.includes("minimal"));
    const dir = scratch();
    writeFileSync(join(dir, "taken.yaml"), "existing");
    const taken = wfb(["new", "Taken", "-o", join(dir, "taken.yaml")]);
    assert.equal(taken.code, 1);
    assert.ok(taken.stderr.includes("already exists"));
    assert.equal(readFileSync(join(dir, "taken.yaml"), "utf8"), "existing");
    writeFileSync(join(dir, "outside.yaml"), "format: 2\nface: {name: MARKER}\n");
    for (const name of [join(dir, "outside"), "../../outside"]) {
      const escape = wfb(["new", "Escape", "--template", name, "-o", join(dir, "out.yaml")]);
      assert.ok(escape.code !== 0 && escape.stderr.includes("no template"), name);
      assert.ok(!existsSync(join(dir, "out.yaml")));
    }
    const ids = ["One", "Two"].map((name) => {
      assert.equal(wfb(["new", name, "-o", join(dir, `${name}.yaml`)]).code, 0);
      return /id: (\S+)/.exec(readFileSync(join(dir, `${name}.yaml`), "utf8"))![1];
    });
    assert.notEqual(ids[0], ids[1]);
    assert.ok(!ids.includes("__UUID__"));
  });

  test("schema --path names a real file", () => {
    const r = wfb(["schema", "--path"]);
    assert.ok(r.code === 0 && existsSync(r.stdout.trim()));
  });

  test("fonts: the summary, one device, -d, both, a duplicate once, and nothing for an unknown name", () => {
    const device = db.get("fenix8solar47mm");
    const summary = wfb(["fonts", "--color", "never"]);
    assert.equal(summary.code, 0, summary.stderr);
    for (const id of db.ids()) assert.ok(summary.stdout.split("\n").some((l) => l.startsWith(`${id} (`)), id);
    const lines = summary.stdout.split("\n");
    const start = lines.findIndex((l) => l.startsWith(`${device.id} (`));
    const block = lines.slice(start, lines.findIndex((l, i) => i > start && !l.trim())).join("\n");
    assert.ok(block.includes("vector text:") && block.includes("drawRadialText") && device.scalableFaces.some((f) => block.includes(f)));
    for (const args of [[device.id], ["-d", device.id]]) {
      const one = wfb(["fonts", ...args, "--color", "never"]);
      assert.ok(one.stdout.includes("Scalable (vector) fonts"));
      for (const face of device.scalableFaces) assert.ok(one.stdout.includes(face));
      for (const metric of device.systemFonts.values()) assert.ok(one.stdout.includes(metric.symbol));
      for (const other of db.ids()) if (other !== device.id) assert.ok(!one.stdout.includes(`${other} (`), other);
    }
    const both = wfb(["fonts", device.id, "-d", "fr955", "--color", "never"]);
    assert.ok(both.stdout.split("\n").some((l) => l.startsWith(`${device.id} (`)) && both.stdout.split("\n").some((l) => l.startsWith("fr955 (")));
    const twice = wfb(["fonts", device.id, "-d", device.id, "--color", "never"]);
    assert.equal(twice.stdout.split("\n").filter((l) => l.startsWith(`${device.id} (`)).length, 1);
    const novector = db.ids().find((id) => !db.get(id).hasSymbol("Graphics.getVectorFont"));
    if (novector !== undefined) {
      const r = wfb(["fonts", novector, "--color", "never"]);
      assert.ok(r.stdout.includes("Graphics.getVectorFont: not available on this device"));
      assert.ok(!r.stdout.split("Scalable (vector) fonts")[1]!.split("System fonts")[0]!.includes("Face Name"));
    }
    const unknown = wfb(["fonts", device.id, "non_existent_device_xyz", "--color", "never"]);
    assert.equal(unknown.code, 1);
    assert.ok(unknown.stderr.includes("unknown device 'non_existent_device_xyz'"));
    assert.equal(unknown.stdout, "");
  });

  test("sources, complications and series list what they should", () => {
    const sources = wfb(["sources"]).stdout;
    assert.ok(!sources.includes("tier") && sources.includes("complication.body_battery") && sources.includes("complication.sleep_score"));
    assert.ok(sources.split("complication.").length - 1 >= 42);
    assert.ok(sources.includes("on_hold: auto -> heart_rate"));
    assert.ok(!sources.includes("body_battery.current") && !sources.includes("device.next_calendar_event"));
    const complications = wfb(["complications"]).stdout;
    assert.ok(complications.includes("42 complication types") && complications.includes("on_hold: auto") && !complications.includes("invalid"));
    const list = wfb(["series"]).stdout;
    for (const name of series.names()) assert.ok(list.includes(name), name);
    for (const word of ["solar", "pressure", "body_battery", "stress"]) assert.ok(!list.toLowerCase().includes(word), word);
    assert.ok(list.split("\n").find((l) => l.trim().startsWith("steps "))!.includes("max 7"));
  });

  test("help: bare, leading topic, trailing word, an unknown topic, and no command at all", () => {
    assert.equal(wfb(["help"]).stdout, wfb(["--help"]).stdout);
    assert.equal(wfb([]).code, 2);
    assert.equal(wfb(["help", "build"]).stdout, wfb(["build", "--help"]).stdout);
    assert.equal(wfb(["build", "help"]).stdout, wfb(["build", "--help"]).stdout);
    const nope = wfb(["help", "nope"]);
    assert.ok(nope.code === 1 && nope.stderr.includes("no such command 'nope'") && nope.stderr.includes("validate"));
  });

  test("preview: a bad time, a non-target device, stdout, -d, quiet, conflicts (a heat map is in slow/)", () => {
    const bad = wfb(["preview", "examples/features/analog/face.yaml", "--time", "not-a-time", "-d", "fenix8solar47mm", "-o", join(scratch(), "p")]);
    assert.ok(bad.code === 1 && bad.stderr.includes("not-a-time") && bad.stderr.includes("HH:MM"));
    const out = scratch();
    const other = wfb(["preview", SUN, "-d", "fenix7pro", "-o", out, "--color", "never"]);
    if (db.ids().includes("fenix7pro")) {
      assert.equal(other.code, 0, other.stderr);
      assert.ok(existsSync(join(out, "fenix7pro.png")) && (other.stdout + other.stderr).includes("not one of this design's targets"));
    }
    for (const marker of ["-", "--"]) {
      const r = wfb(["preview", SUN, "-o", marker]);
      assert.equal(r.code, 0, r.stderr);
      assert.ok(r.bytes.subarray(0, 8).equals(PNG));
      assert.equal(r.bytes.toString("latin1").split(PNG.toString("latin1")).length - 1, 1);
    }
    const size = (...extra: string[]): number[] => {
      const png = decodePng(new Uint8Array(wfb(["preview", SUN, "-o", "-", "--scale", "1", ...extra]).bytes))!;
      return [png.width, png.height];
    };
    assert.deepEqual(size(), [260, 260]);
    assert.deepEqual(size("-d", "fenix8solar51mm"), [280, 280]);
    const quietDir = scratch();
    const quiet = wfb(["preview", SUN, "-q", "-o", quietDir, "--color", "never"]);
    assert.ok(quiet.code === 0 && quiet.stdout === "" && existsSync(join(quietDir, "fenix8solar47mm.png")));
    for (const [extra, named] of [
      [["--time", "10:00", "--minute", "5"], "--time and --minute"], [["--heatmap", "--minute", "5"], "--minute and --heatmap"],
      [["--heatmap", "--time", "10:00"], "--time and --heatmap"], [["--style", "x", "--all-styles"], "--style and --all-styles"],
      [["--heatmap", "--all-styles"], "--all-styles"], [["--minute", "1440"], "--minute 1440"],
    ] as const) {
      const r = wfb(["preview", SUN, "-o", "--", ...extra]);
      assert.ok(r.code === 1 && r.stderr.includes(named), named);
    }
    const watch = wfb(["preview", SUN, "-o", "--", "--watch"]);
    assert.ok(watch.code === 1 && watch.stderr.includes("--watch"));
  });

  test("a stand-in font is warned of even with -o -, and --fonts silences it", () => {
    const dir = scratch();
    const design = join(dir, "face.yaml");
    writeFileSync(design, `
format: 2
face:
  id: 8f4c1e92-4a5b-4d81-9e6f-2b0c8d4a1f58
  name: FontWarningTest
build:
  targets: [fenix8solar47mm]
resources:
  palette:
    bg: "#000000"
    fg: "#FFFFFF"
elements:
  label:
    type: text
    text: "88"
    font: FONT_NUMBER_HOT
    align: center
    at: {anchor: center}
    color: color.fg
`);
    const warned = wfb(["preview", design, "-d", "fenix8solar47mm", "-o", "-"]);
    assert.equal(warned.code, 0, warned.stderr);
    assert.ok(warned.stderr.includes("drawn with a stand-in"), warned.stderr);
    const root = join(dir, "fonts");
    mkdirSync(root);
    writeFileSync(join(root, "Bionic_semibold.ttf"), readFileSync(join(REPO_ROOT, "ts/test/fixtures/slice/assets/OpenSans-Regular.ttf")));
    const quiet = wfb(["preview", design, "-d", "fenix8solar47mm", "-o", "-", "--fonts", root]);
    assert.ok(quiet.code === 0 && !quiet.stderr.includes("warning:"), quiet.stderr);
  });

  test("colour: always, never, NO_COLOR, before or after the command", () => {
    assert.ok(wfb(["doctor", "--color", "always"]).stdout.includes(ESC));
    assert.ok(!wfb(["doctor", "--color", "never"]).stdout.includes(ESC));
    assert.ok(!wfb(["doctor"], { env: { NO_COLOR: "1" } }).stdout.includes(ESC));
    assert.ok(wfb(["--color", "always", "doctor"]).stdout.includes(ESC));
    assert.ok(!wfb(["--color", "always", "doctor", "--color", "never"]).stdout.includes(ESC));
    for (const value of ["auto", "always", "never"]) for (const args of [["devices"], ["sources"], ["series"]]) assert.equal(wfb([...args, "--color", value]).code, 0);
  });

  test("validate and build summaries, coloured and plain", () => {
    const dir = scratch();
    const design = join(dir, "face.yaml");
    writeFileSync(design, MINIMAL);
    const okColour = wfb(["validate", design, "--color", "always"]);
    assert.ok(okColour.code === 0 && okColour.stdout.includes(ESC) && plain(okColour.stdout).includes("ok --"));
    const okPlain = wfb(["validate", design, "--color", "never"]);
    assert.ok(!okPlain.stdout.includes(ESC) && okPlain.stdout.includes(`${design}: ok -- no diagnostics`));
    const broken = join(dir, "broken.yaml");
    writeFileSync(broken, "not: valid: yaml: at: all: [");
    const invalid = wfb(["validate", broken, "--color", "always"]);
    assert.ok(invalid.code === 1 && invalid.stderr.includes(ESC) && plain(invalid.stderr).includes("invalid --"));
    const built = wfb(["build", design, "--no-compile", "-o", join(dir, "out"), "--color", "always"]);
    assert.ok(built.code === 0 && built.stdout.includes(ESC) && plain(built.stdout).includes("build succeeded --"), built.stderr);
    const builtPlain = wfb(["build", design, "--no-compile", "-o", join(dir, "out2")]);
    assert.ok(!builtPlain.stdout.includes(ESC) && builtPlain.stdout.includes("build succeeded --"));
  });
});

test("built lines align whatever the .prg names' lengths, and the share is coloured by how close it is", () => {
  const memory = { total: 1000, limit: 100000, data: 0, code: 0, prg: null };
  const lines = formatBuilt(new Map([["short", "a.prg"], ["long", "a-much-longer-device-name.prg"]]), new Map([["short", memory], ["long", memory]]), false);
  assert.equal(lines[0]!.indexOf("("), lines[1]!.indexOf("("));
  const share = (total: number): string => formatBuilt(new Map([["d", "a.prg"]]), new Map([["d", { ...memory, total, limit: 100 }]]), true)[0]!;
  assert.ok(share(50).includes(`${ESC}[32m`) && share(80).includes(`${ESC}[33m`) && share(95).includes(`${ESC}[31m`));
  assert.ok(formatBuilt(new Map([["d", "a.prg"]]), new Map([["d", { ...memory, total: 95, limit: 100 }]]), false)[0]!.endsWith("(95.0%)"));
});
