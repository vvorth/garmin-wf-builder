// Diagnostics: how they render for a terminal, and the load's own reports.
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { Bag, Diagnostic, Span } from "../src/diagnostics.ts";
import * as term from "../src/term.ts";
import { load, MINIMAL } from "./designs.ts";

afterEach(() => term.setMode("auto"));

test("a plain render has no ANSI; a coloured one keeps the codes", () => {
  const bag = new Bag();
  bag.error("bad-thing", "something is wrong");
  bag.warning("meh", "a minor issue", null, { notes: ["consider X"] });
  assert.ok(!bag.render().includes("\x1b"));
  const coloured = bag.render({ color: true });
  assert.ok(coloured.includes("\x1b[") && coloured.includes("[bad-thing]") && coloured.includes("[meh]"));
});

test("the header, the gutter and the caret are styled", () => {
  const bag = new Bag();
  bag.registerSource("face.yaml", "a: 1\nb: 2\n");
  bag.error("bad-thing", "boom", new Span("face.yaml", 2, 3));
  const text = bag.render({ color: true });
  for (const piece of [
    term.style("face.yaml", ["bold"], true), term.style("error", term.SEVERITY_STYLE["error"]!, true), term.style("[bad-thing]", ["dim"], true),
    term.style("boom", ["bold"], true), term.style("    2 | ", ["dim"], true), term.style("^", term.SEVERITY_STYLE["error"]!, true),
  ]) assert.ok(text.includes(piece), piece);
});

test("blank lines between diagnostics, notes first and errors last, the bag's order untouched", () => {
  let bag = new Bag();
  bag.error("e1", "first");
  bag.error("e2", "second");
  assert.equal(bag.render().split("\n\n").filter((p) => p.trim()).length, 2);
  bag = new Bag();
  bag.error("e", "an error");
  bag.warning("w", "a warning");
  bag.note("n", "a note");
  const text = bag.render();
  assert.ok(text.indexOf("note[n]") < text.indexOf("warning[w]") && text.indexOf("warning[w]") < text.indexOf("error[e]"));
  assert.deepEqual(bag.items.map((d) => d.severity), ["error", "warning", "note"]);
});

test("identical notes collapse; differing ones, bare duplicates and other codes do not", () => {
  let bag = new Bag();
  for (const d of "ABC") bag.warning("dup", `on device ${d}`, null, { notes: ["do X", "do Y"], confidence: "estimate" });
  let text = bag.render();
  assert.deepEqual([text.split("do X").length - 1, text.split("do Y").length - 1, text.split("estimate").length - 1], [1, 1, 1]);
  assert.equal(text.split("same notes as the earlier [dup] above").length - 1, 2);
  assert.equal(text.split("warning[dup]").length - 1, 3);
  bag = new Bag();
  bag.warning("dup", "on device A", null, { notes: ["do X"] });
  bag.warning("dup", "on device B", null, { notes: ["do Z"] });
  text = bag.render();
  assert.ok(text.includes("do X") && text.includes("do Z") && !text.includes("same notes as the earlier"));
  bag = new Bag();
  bag.warning("w", "identical message");
  bag.warning("w", "identical message");
  assert.ok(!bag.render().includes("same notes as the earlier"));
  bag = new Bag();
  bag.warning("a", "message one", null, { notes: ["shared note"] });
  bag.warning("b", "message two", null, { notes: ["shared note"] });
  assert.equal(bag.render().split("shared note").length - 1, 2);
});

test("a note wraps at a width under its label; a snippet never rewraps", () => {
  const words = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima";
  const lines = new Diagnostic("warning", "w", "msg", null, { notes: [words] }).render(null, { width: 30 }).split("\n").slice(1);
  assert.ok(lines.length > 1 && lines[0]!.startsWith("      note: "));
  for (const line of lines) assert.ok(line.length <= 30, line);
  for (const line of lines.slice(1)) assert.ok(line.startsWith(" ".repeat(12)) && line[12] !== " ", line);
  assert.deepEqual([lines[0]!.slice(12), ...lines.slice(1).map((l) => l.slice(12))].join(" ").split(" "), words.split(" "));
  assert.deepEqual(new Diagnostic("warning", "w", "msg", null, { notes: [words] }).render().split("\n"), ["warning[w]: msg", `      note: ${words}`]);
  const snippet = new Diagnostic("warning", "w", "msg", null, { notes: ["suggested fix:\n    color: color.fg\n    size: 10px"] }).render(null, { width: 10 }).split("\n");
  assert.deepEqual(snippet.slice(1), ["      note: suggested fix:", " ".repeat(12) + "    color: color.fg", " ".repeat(12) + "    size: 10px"]);
});

test("the summary, plain and coloured", () => {
  const bag = new Bag();
  bag.error("e", "boom");
  bag.warning("w", "meh");
  assert.equal(bag.summary(), "1 error, 1 warning");
  bag.note("n", "fyi");
  const text = bag.summary({ color: true });
  for (const [count, severity] of [["1 error", "error"], ["1 warning", "warning"], ["1 note", "note"]]) {
    assert.ok(text.includes(term.style(count!, term.SEVERITY_STYLE[severity!]!, true)));
  }
});

test("whether to colour: --color, then NO_COLOR, then FORCE_COLOR, then a TTY", () => {
  const saved = { ...process.env };
  try {
    for (const k of ["NO_COLOR", "FORCE_COLOR", "CLICOLOR_FORCE", "TERM"]) delete process.env[k];
    term.setMode("auto");
    const tty = { isTTY: true }, plain = { isTTY: false };
    assert.equal(term.shouldColor(tty), true);
    assert.equal(term.shouldColor(plain), false);
    process.env["TERM"] = "dumb";
    assert.equal(term.shouldColor(tty), false);
    delete process.env["TERM"];
    process.env["FORCE_COLOR"] = "1";
    assert.equal(term.shouldColor(plain), true);
    delete process.env["FORCE_COLOR"];
    process.env["CLICOLOR_FORCE"] = "1";
    assert.equal(term.shouldColor(plain), true);
    delete process.env["CLICOLOR_FORCE"];
    process.env["NO_COLOR"] = "1";
    process.env["FORCE_COLOR"] = "1";
    assert.equal(term.shouldColor(tty), false);
    delete process.env["NO_COLOR"];
    delete process.env["FORCE_COLOR"];
    term.setMode("always");
    assert.equal(term.shouldColor(plain), true);
    term.setMode("never");
    process.env["FORCE_COLOR"] = "1";
    assert.equal(term.shouldColor(tty), false);
  } finally {
    for (const k of Object.keys(process.env)) if (!(k in saved)) delete process.env[k];
    Object.assign(process.env, saved);
  }
});

// -- the load's own reports --

const errorsOf = (text: string) => load(text)[1].errors;

test("spans point at the offending line; unknown keys and formats are errors", () => {
  const design = MINIMAL.replace("color: color.bg", "color: color.missing");
  const [first] = errorsOf(design);
  assert.ok(design.split("\n")[first!.span!.line - 1]!.includes("color.missing"));
  assert.ok(errorsOf(MINIMAL.replace("    color: color.bg", "    colour: color.bg")).some((d) => d.message.toLowerCase().includes("unknown key")));
  assert.ok(errorsOf(MINIMAL.replace("format: 2", "format: 9")).some((d) => d.code === "format-version"));
  const [one] = errorsOf(MINIMAL.replace("format: 2", "format: 1")).filter((d) => d.code === "format-version");
  assert.ok(one!.message.includes("format 1") && one!.notes[0]!.includes("'format: 2'") && !one!.notes[0]!.includes("migrate"));
  assert.ok(errorsOf(MINIMAL.replace("format: 2\n", "")).length > 0);
  const yaml = errorsOf("format: 2\nface:\n  id: [unclosed\n");
  assert.ok(yaml.some((d) => d.code === "yaml") && yaml[0]!.span !== null);
});

test("duplicate ids, the source line rendered, one error for a missing required key", () => {
  const dup = MINIMAL + "\n  panel:\n    type: group\n    children:\n      background:\n        type: circle\n        radius: 10px\n        color: color.fg\n";
  assert.ok(errorsOf(dup).some((d) => d.code === "duplicate-id"));
  const [, bag] = load(MINIMAL.replace("color.bg", "color.nope"));
  const text = bag.render();
  assert.ok(text.includes("^") && text.includes("color.nope"));
  const missing = errorsOf(MINIMAL + "\n  label:\n    type: text\n    at: {anchor: center}\n");
  assert.equal(missing.length, 1);
  assert.ok(missing[0]!.message.includes("missing required key 'text'"));
});

test("diagnostics that differ only in the device they name show once, saying where else they hold", () => {
  const span = new Span("face.yaml", 3, 1);
  const bag = new Bag();
  bag.devices = ["fenix8solar47mm", "fenix8solar51mm", "fr955"];
  bag.warning("api-gated", "x needs 'sec', which fenix8solar47mm lacks", span, { notes: ["checked against fenix8solar47mm's own file"] });
  bag.warning("api-gated", "x needs 'sec', which fenix8solar51mm lacks", span, { notes: ["checked against fenix8solar51mm's own file"] });
  bag.note("graphics-pool", "67,600 B on fenix8solar47mm", span);
  bag.note("graphics-pool", "78,400 B on fenix8solar51mm", span);
  bag.warning("api-gated", "x needs 'sec', which fr955 lacks", span, { notes: ["checked against fr955's own file"] });
  // the same words at another line, or naming two devices, or a longer id, stay apart
  bag.warning("api-gated", "x needs 'sec', which fr955 lacks", new Span("face.yaml", 9, 1), { notes: ["checked against fr955's own file"] });
  bag.note("pair", "fr955 and fenix8solar47mm differ", span);
  bag.note("pair", "fr955s is not fr955", span);
  assert.deepEqual(bag.shown().map((d) => d.message), [
    "x needs 'sec', which fenix8solar47mm lacks -- and the same on fenix8solar51mm, fr955",
    "67,600 B on fenix8solar47mm",
    "78,400 B on fenix8solar51mm",
    "x needs 'sec', which fr955 lacks",
    "fr955 and fenix8solar47mm differ",
    "fr955s is not fr955",
  ]);
  assert.deepEqual(bag.shown()[0]!.notes, ["checked against fenix8solar47mm's own file"]);
  assert.equal(bag.summary(), "2 warnings, 4 notes");
  assert.equal(bag.items.length, 8);
  // one device: nothing to merge
  bag.devices = ["fr955"];
  assert.equal(bag.shown().length, 8);
});
