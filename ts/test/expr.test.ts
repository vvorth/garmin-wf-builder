// The expression language: parsing, typing, folding, Monkey C emission and
// the preview's evaluation, which must compute what the watch computes.
import assert from "node:assert/strict";
import { test } from "node:test";
import { compileExpression, evaluate, ExprError, type ExprValue, parse, Scope, Value } from "../src/expr.ts";
import { WholeFloat } from "../src/edit/yaml.ts";

function scope(): Scope {
  const s = new Scope();
  s.define("activity.steps", { value: new Value("number", true), code: "activitySteps" });
  s.define("activity.step_goal", { value: new Value("number", true), code: "activityStepGoal" });
  s.define("system.battery", { value: new Value("float"), code: "systemBattery" });
  s.define("device.phone_connected", { value: new Value("boolean"), code: "devicePhoneConnected" });
  s.define("color.hot", { value: new Value("color"), code: "Palette.HOT", constant: 0xFF5500 });
  s.define("color.text", { value: new Value("color"), code: "Palette.TEXT", constant: 0xFFFFFF });
  return s;
}

const code = (text: string): string => compileExpression(text, scope())[0];
const value = (text: string): Value => compileExpression(text, scope())[1];
const num = (v: ExprValue): number => (v instanceof WholeFloat ? v.value : Number(v));
const run = (text: string, values: Record<string, ExprValue>): ExprValue => evaluate(parse(text), new Map(Object.entries(values)));
const refused = (text: string, reason: RegExp, s = scope()): void => {
  assert.throws(() => compileExpression(text, s), (e: Error) => e instanceof ExprError && reason.test(e.message), text);
};

test("emission", () => {
  for (const [text, want] of [
    ["activity.steps", "activitySteps"], ["2 * 3 + 4", "10"], ["system.battery / 2", "(systemBattery / 2)"],
    ["min(activity.steps, 10000)", "WfbMath.min(activitySteps, 10000)"],
    ["percent(activity.steps, activity.step_goal)", "WfbMath.percent(activitySteps, activityStepGoal)"],
    ["round(system.battery)", "Math.round(systemBattery).toNumber()"],
    ["not device.phone_connected", "(!devicePhoneConnected)"], ["device.phone_connected and true", "(devicePhoneConnected && true)"],
  ]) assert.equal(code(text!), want, text);
});

test("constants fold at build time; palette references stay named", () => {
  assert.equal(code("clamp(2 + 3, 0, 100) * 2"), "10");
  assert.equal(code("activity.steps > activity.step_goal ? color.hot : color.text"), "((activitySteps > activityStepGoal) ? Palette.HOT : Palette.TEXT)");
  assert.equal(value("activity.steps > activity.step_goal ? color.hot : color.text").type, "color");
});

test("nullability propagates; division yields a float", () => {
  assert.equal(value("activity.steps + 1").nullable, true);
  assert.equal(value("system.battery + 1").nullable, false);
  assert.equal(value("4 / 2").type, "float");
});

test("a number divided on the watch is coerced to float, and nothing else is", () => {
  assert.equal(code("activity.steps / 1000"), "(activitySteps.toFloat() / 1000)");
  assert.equal(value("activity.steps / 1000").type, "float");
  assert.equal(code("system.battery / 2"), "(systemBattery / 2)");
  assert.equal(code("activity.steps / 100000.0"), "(activitySteps / 100000.0f)");
  assert.equal(code("10 / 4"), "2.5f");
});

test("a divisor read on the watch is guarded; a literal one is not", () => {
  assert.equal(code("10 / activity.steps"), "WfbMath.div(10, activitySteps)");
  assert.equal(code("activity.steps % (activity.step_goal - 1)"), "WfbMath.mod(activitySteps, (activityStepGoal - 1))");
  assert.equal(code("activity.steps % 7"), "(activitySteps % 7)");
  assert.equal(num(run("100 / (x - 60)", { x: 60 })), 0);
  assert.equal(num(run("x % (x - 60)", { x: 60 })), 0);
});

test("a divisor that is always zero is refused", () => {
  for (const text of ["activity.steps / 0", "activity.steps % 0", "10 / (3 - 3)", "activity.steps / 0.0", "activity.steps % zero"]) {
    const s = scope();
    s.define("zero", { value: new Value("number"), code: "ZERO", constant: 0 });
    refused(text, /by zero/, s);
  }
});

test("a constant past 32 bits is refused; a float one is not", () => {
  for (const text of ["2000000000 + 2000000000", "65536 * 65536", "-2147483647 - 2", "2147483648"]) refused(text, /too large for a whole number/);
  assert.equal(code("65536.0 * 65536"), "4294967296.0f");
  assert.equal(code("-2147483647 - 1"), "(-2147483647 - 1)");
});

test("the preview wraps a number at 32 bits", () => {
  for (const [text, values, want] of [
    ["x + 1", { x: 2147483647 }, -2147483648], ["x * 100000", { x: 100000 }, 1410065408], ["x * x", { x: 65536 }, 0], ["-x", { x: -2147483648 }, -2147483648],
  ] as const) assert.equal(num(run(text, values)), want, text);
});

test("refusals say why", () => {
  assert.throws(() => code("activity.stps"), (e: ExprError) => e.notes.join(" ").includes("activity.steps"));
  assert.throws(() => code("color.hot + 1"), (e: ExprError) => e.message.includes("color"));
  assert.throws(() => code("1 ? 2 : 3"), ExprError);
  assert.throws(() => code("device.phone_connected ? color.hot : 5"), ExprError);
  assert.throws(() => code("sqrt(4)"), (e: ExprError) => ["min", "max", "clamp", "round", "floor", "abs", "percent"].every((n) => e.notes.join(" ").includes(n)));
  assert.throws(() => code("clamp(1, 2)"), (e: ExprError) => e.message.includes("3 argument"));
  assert.throws(() => code("1 + color.hot"), (e: ExprError) => e.offset > 0);
  for (const text of ["var x = 1", "x = 1", "while (true) {}", "function f() {}"]) assert.throws(() => code(text), ExprError, text);
});

test("evaluation matches the compiled semantics", () => {
  assert.ok(Math.abs(num(run("percent(activity.steps, activity.step_goal)", { "activity.steps": 8432, "activity.step_goal": 10000 })) - 84.32) < 1e-9);
  assert.equal(run("activity.steps + 1", { "activity.steps": null }), null);
  for (const goal of [0, -5]) assert.equal(num(run("percent(activity.steps, activity.step_goal)", { "activity.steps": 100, "activity.step_goal": goal })), 0);
});

test("round is half up toward +infinity, as the watch's Math.round is: -2.5 is -2", () => {
  for (const [x, want] of [[2.5, 3], [72.5, 73], [0.5, 1], [2.4999, 2], [2.0, 2], [3, 3], [0.49999999999999994, 0], [-2.4, -2], [-2.6, -3],
    [-2.5, -2], [-1.5, -1], [-0.5, 0]] as const) {
    assert.equal(num(run("round(x)", { x: Number.isInteger(x) && x !== 3 ? new WholeFloat(x) : x })), want, String(x));
  }
  assert.equal(code("round(2.5)"), "3");
  assert.equal(code("round(72.5)"), "73");
  assert.equal(code("round(-2.5)"), "-2");
  assert.equal(code("round(-2.6)"), "-3");
});

test("percent matches WfbMath", () => {
  for (const [steps, goal, want] of [[12000, 10000, 100], [8432, 10000, 84.32], [-50, 100, 0], [100, 0, 0]] as const) {
    assert.ok(Math.abs(num(run("percent(activity.steps, activity.step_goal)", { "activity.steps": steps, "activity.step_goal": goal })) - want) < 1e-9);
  }
  assert.equal(code("percent(150, 100)"), "100.0f");
  assert.equal(code("percent(5, 0)"), "0.0f");
});

test("clamp checks lo before hi, like WfbMath", () => {
  assert.equal(code("clamp(50, 10, 0)"), "0");
  assert.equal(code("clamp(5, 10, 0)"), "10");
  assert.equal(num(run("clamp(x, 10, 0)", { x: 50 })), 0);
});

test("modulo truncates like Monkey C, and refuses a float", () => {
  for (const [text, want] of [["-7 % 3", "-1"], ["7 % -3", "1"], ["7 % 3", "1"], ["-7 % -3", "-1"]]) assert.equal(code(text!), want, text);
  assert.equal(num(run("x % 3", { x: -7 })), -1);
  for (const text of ["system.battery % 10", "activity.steps % 2.5", "7.5 % 2"]) refused(text, /%/);
});
