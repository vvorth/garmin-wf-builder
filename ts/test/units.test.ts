// Lengths, angles, durations and boxes: the units every placement resolves.
import assert from "node:assert/strict";
import { test } from "node:test";
import { ANCHORS, Angle, Box, Duration, IntBox, Length, pixelSize, SIZE_UNITS, UnitError } from "../src/units.ts";

test("length parsing", () => {
  for (const [raw, value, unit] of [["12px", 12, "px"], [12, 12, "px"], [-4.5, -4.5, "px"], ["30%", 30, "%"], ["38%r", 38, "%r"], ["1.5pt", 1.5, "pt"], ["  -4 % ", -4, "%"]] as const) {
    const length = Length.parse(raw);
    assert.deepEqual([length.value, length.unit], [value, unit], String(raw));
  }
  for (const raw of ["banana", "12em", true, null, "%"]) assert.throws(() => Length.parse(raw), UnitError, String(raw));
});

test("duration parsing and its text", () => {
  for (const [raw, seconds] of [["30m", 1800], ["4h", 14400], ["7d", 604800], ["1d", 86400], ["0m", 0]] as const) assert.equal(Duration.parse(raw).seconds, seconds);
  for (const raw of ["banana", "4", "4s", "-4h", "4.5h", true, null, 4]) assert.throws(() => Duration.parse(raw), UnitError, String(raw));
  assert.equal(String(Duration.parse("4h")), "4h");
  assert.equal(String(Duration.parse("240m")), "4h");
  assert.equal(String(Duration.parse("90m")), "90m");
  assert.equal(String(Duration.parse("7d")), "7d");
});

test("percent resolves per axis; %r against the minor radius; pt needs a font", () => {
  const box = new Box(0, 0, 200, 100);
  assert.equal(Length.parse("50%").resolve(box, "x", 50), 100);
  assert.equal(Length.parse("50%").resolve(box, "y", 50), 50);
  assert.equal(Length.parse("50%").resolve(box, "minor", 50), 50);
  for (const b of [new Box(0, 0, 260, 260), new Box(0, 0, 400, 260)]) assert.equal(Length.parse("50%r").resolve(b, "x", 130), 65);
  assert.throws(() => Length.parse("2pt").resolve(new Box(0, 0, 10, 10), "x", 5), UnitError);
  assert.equal(Length.parse("2pt").resolve(new Box(0, 0, 10, 10), "x", 5, 30), 60);
});

test("angles: the author's convention to Garmin's, and their units", () => {
  for (const [author, garmin] of [[0, 90], [90, 0], [180, 270], [270, 180], [45, 45], [360, 90]]) {
    assert.ok(Math.abs(Angle.parse(`${author}deg`).toGarmin() - garmin!) < 1e-9, String(author));
  }
  assert.equal(Angle.parse("0.25turn").degrees, 90);
  assert.ok(Math.abs(Angle.parse(`${Math.PI}rad`).degrees - 180) < 1e-9);
});

test("anchors land inside their box, and an unknown one names the rest", () => {
  const box = new Box(10, 20, 100, 50);
  for (const name of ANCHORS.keys()) {
    const [x, y] = box.anchorPoint(name);
    assert.ok(box.left <= x && x <= box.right && box.top <= y && y <= box.bottom, name);
  }
  assert.deepEqual(box.anchorPoint("center"), [60, 45]);
  assert.deepEqual(box.anchorPoint("bottom_right"), [110, 70]);
  assert.throws(() => new Box(0, 0, 1, 1).anchorPoint("middle"), (e: Error) => e instanceof UnitError && e.message.includes("center"));
});

test("int boxes: union, clamp, and an off-screen box clamps empty", () => {
  const [a, b] = [new IntBox(0, 0, 10, 10), new IntBox(20, 5, 10, 10)];
  assert.deepEqual(a.union(b), new IntBox(0, 0, 30, 15));
  assert.deepEqual(new IntBox(-5, -5, 20, 20).clampTo(10, 10), new IntBox(0, 0, 10, 10));
  assert.equal(a.area, 100);
  // A negative extent would reach a generated dc.setClip.
  for (const box of [new IntBox(-100, 10, 50, 20), new IntBox(300, 10, 50, 20), new IntBox(10, -100, 20, 50)]) assert.equal(box.clampTo(260, 260).area, 0);
  assert.deepEqual(new IntBox(200, 200, 100, 100).clampTo(260, 260), new IntBox(200, 200, 60, 60));
});

test("sizes resolved before layout", () => {
  for (const [spec, r, want] of [["8%r", 130, 10], ["24px", 130, 24], ["50%r", 200, 100]] as const) assert.equal(pixelSize(Length.parse(spec), r), want);
  assert.equal(pixelSize(null, 130), 24);
  assert.equal(pixelSize(Length.parse("0.1%r"), 130), 1);
  assert.deepEqual(new Set(SIZE_UNITS), new Set(["px", "%r"]));
});
