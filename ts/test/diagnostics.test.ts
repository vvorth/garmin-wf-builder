// Diagnostics: how they render for a terminal, and the load's own reports.
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { join } from "node:path";
import { REPO_ROOT } from "../src/devices/node.ts";
import { Bag, Diagnostic, Span } from "../src/diagnostics.ts";
import { generate } from "../src/emit/project.ts";
import { ICON_FONT } from "../src/emit/resources.ts";
import type { Face } from "../src/ir/model.ts";
import { readFontFile } from "../src/node.ts";
import * as term from "../src/term.ts";
import { db, face, load, MINIMAL, view } from "./designs.ts";

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

test("a schema error inside a group's child names the child's own mistake, as it does at the top level", () => {
  // The child's element oneOf sits inside the group's branch; it used to be merged into "needs one of children or text or …".
  const group = (child: string) => MINIMAL +
    `  card:\n    type: group\n    at: {anchor: center}\n    size: {width: 50%, height: 30%}\n    children:\n      dot:\n        type: circle\n        at: {anchor: center}\n${child}`;
  const key = errorsOf(group("        radius: 4px\n        colour: color.fg\n"));
  assert.equal(key.length, 1, key.map((d) => d.message).join("\n"));
  assert.ok(key[0]!.message.startsWith("elements.card.children.dot: unknown key") && key[0]!.message.includes("'colour'"), key[0]!.message);
  const value = errorsOf(group("        radius: true\n        color: color.fg\n"));
  assert.equal(value.length, 1, value.map((d) => d.message).join("\n"));
  assert.equal(value[0]!.message, "elements.card.children.dot.radius: expected number, got boolean");
  assert.equal(value[0]!.span!.line, MINIMAL.split("\n").length + 8);
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

// -- format 2 spellings: a superseded form is refused on its own line, naming the replacement --

const STEPS_TEXT = (absent: string): string => MINIMAL + `  steps:
    type: text
    text: "{activity.steps:d}"
    at: {anchor: center, dy: 20%}
    color: color.fg
    absent: ${absent}
`;
const GAUGE = (absent: string): string => MINIMAL + `  ring:
    type: gauge
    style: arc
    value: activity.steps
    max: activity.step_goal
    at: {anchor: center}
    radius: 50%r
    thickness: 10px
    start_angle: 180deg
    sweep: 340deg
    color: color.fg
    absent: ${absent}
`;
const DATA = (absent: string): string => MINIMAL.replace("elements:", "config:\n  slots:\n    top: {default: steps, choices: any}\nelements:") + `  reading:
    type: data
    slot: top
    at: {anchor: center}
    font: FONT_SMALL
    color: color.fg
    absent: ${absent}
`;
const PATTERN = (absent: string): string => MINIMAL + `  bars:
    type: pattern
    pattern: linear
    at: {anchor: center, dx: -20%r}
    count: 5
    step: {dx: 10%r}
    absent: ${absent}
    parts:
      - {type: rectangle, size: {width: 4%r, height: 4%r}, color: color.fg, visible: "copy <= activity.move_bar_level - 1"}
`;

test("absent: a bare placeholder string is refused naming {text:}; the tagged forms load and generate as before", () => {
  const bare = errorsOf(STEPS_TEXT('"--"'));
  assert.equal(bare.length, 1, bare.map((d) => d.message).join("\n"));
  assert.ok(bare[0]!.message.includes("absent: {text: \"--\"}"), bare[0]!.message);
  assert.ok(errorsOf(STEPS_TEXT('"0"'))[0]!.message.includes("absent: {text: \"0\"}"));
  const tagged = view(STEPS_TEXT('{text: "--"}'));
  // the placeholder is drawn, and the generated comment still spells the policy as `absent: "--"`
  assert.ok(tagged.includes('"--"') && tagged.includes('absent: "--"'), tagged);
  face(STEPS_TEXT("hide"));
  face(STEPS_TEXT("{value: 0}"));
  const both = errorsOf(STEPS_TEXT('{text: "--", value: 0}'));
  assert.equal(both.length, 1, both.map((d) => d.message).join("\n"));
  assert.ok(both[0]!.message.includes("one of"), both[0]!.message);
});

test("absent: each kind refuses the substitute it cannot draw, with the reason, and takes the ones it can", () => {
  const gauge = errorsOf(GAUGE('{text: "--"}'));
  assert.equal(gauge.length, 1, gauge.map((d) => d.message).join("\n"));
  assert.ok(gauge[0]!.message.includes("no placeholder text"), gauge[0]!.message);
  face(GAUGE("hide"));
  face(GAUGE("{value: 0.5}"));
  const data = errorsOf(DATA("{value: 0}"));
  assert.equal(data.length, 1, data.map((d) => d.message).join("\n"));
  assert.ok(data[0]!.message.includes("{text:"), data[0]!.message);
  face(DATA('{text: "--"}'));
  face(DATA("hide"));
  const pattern = errorsOf(PATTERN('{text: "--"}'));
  assert.equal(pattern.length, 1, pattern.map((d) => d.message).join("\n"));
  assert.ok(pattern[0]!.message.includes("'absent: hide'"), pattern[0]!.message);
  face(PATTERN("hide"));
});

test("the format 1 placeholder keys name the tagged absent:", () => {
  const notes = errorsOf(STEPS_TEXT("hide").replace("absent: hide", 'placeholder: "--"')).flatMap((d) => d.notes);
  assert.ok(notes.some((n) => n.includes("'absent: {text: \"--\"}'")), notes.join("\n"));
  const when = errorsOf(STEPS_TEXT("hide").replace("absent: hide", "when_absent: hide")).flatMap((d) => d.notes);
  assert.ok(when.some((n) => n.includes("{text: \"--\"}")), when.join("\n"));
});

const GRAPH = (range: string): string => MINIMAL + `  hr:
    type: graph
    series: steps
    range: ${range}
    at: {anchor: center}
    size: {width: 60%, height: 20%}
    color: color.fg
`;
const RADIAL = (keys: string): string => MINIMAL + `  ticks:
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 12
${keys}    color: color.fg
    parts:
      - {type: line, at: {dy: -90%r}, to: {dy: -80%r}, thickness: 2px}
`;
const LINEAR = (keys: string): string => MINIMAL + `  dots:
    type: pattern
    pattern: linear
    at: {anchor: center, dx: -20%r}
    count: 5
${keys}    color: color.fg
    parts:
      - {type: circle, radius: 3%r}
`;

test("graph range: a bare duration or count is refused naming the object form; the objects read as before", () => {
  const duration = errorsOf(GRAPH("4h"));
  assert.equal(duration.length, 1, duration.map((d) => d.message).join("\n"));
  assert.ok(duration[0]!.message.includes("range: {duration: \"4h\"}"), duration[0]!.message);
  const count = errorsOf(GRAPH("7"));
  assert.equal(count.length, 1, count.map((d) => d.message).join("\n"));
  assert.ok(count[0]!.message.includes("range: {samples: 7}"), count[0]!.message);
  const graph = (text: string): Record<string, unknown> => face(text).elements.find((e) => e.id === "hr") as unknown as Record<string, unknown>;
  const week = graph(GRAPH("{duration: 7d}"));
  assert.deepEqual([week["range_kind"], week["range_value"], week["sample_count"]], ["duration", 7 * 86400, 7]);
  const seven = graph(GRAPH("{samples: 7}"));
  assert.deepEqual([seven["range_kind"], seven["range_value"], seven["sample_count"]], ["count", 7, 7]);
  const both = errorsOf(GRAPH("{samples: 7, duration: 7d}"));
  assert.equal(both.length, 1, both.map((d) => d.message).join("\n"));
  assert.ok(both[0]!.message.includes("one of"), both[0]!.message);
});

test("pattern step: step_angle: turns a radial pattern and step: {dx, dy} moves a linear one; the wrong key names the right one", () => {
  const ticks = (text: string): Record<string, unknown> => face(text).elements.find((e) => e.id === "ticks") as unknown as Record<string, unknown>;
  assert.equal(ticks(RADIAL(""))["step_angle"], 30);
  assert.equal(ticks(RADIAL("    step_angle: 15deg\n"))["step_angle"], 15);
  const angle = errorsOf(RADIAL("    step: 30deg\n"));
  assert.equal(angle.length, 1, angle.map((d) => d.message).join("\n"));
  assert.ok(angle[0]!.message.includes("step_angle: 30deg"), angle[0]!.message);
  const offset = errorsOf(RADIAL("    step: {dx: 10%r}\n"));
  assert.equal(offset.length, 1, offset.map((d) => d.message).join("\n"));
  assert.ok(offset[0]!.message.includes("'step_angle:'"), offset[0]!.message);
  const turned = errorsOf(LINEAR("    step_angle: 30deg\n"));
  assert.equal(turned.length, 1, turned.map((d) => d.message).join("\n"));
  assert.ok(turned[0]!.message.includes("'step: {dx, dy}'"), turned[0]!.message);
  face(LINEAR("    step: {dx: 10%r}\n"));
});

// -- one spelling per idea: a removed spelling names its replacement --

const LABEL = MINIMAL + "  label:\n    type: text\n    text: \"Hi\"\n    font: FONT_SMALL\n    at: {anchor: center}\n    color: color.fg\n";

test("outline: is an object: a bare colour or 'none' on an element names '{color: ...}'; 'none' stays legal in aod:", () => {
  const bare = errorsOf(LABEL + "    outline: color.bg\n");
  assert.equal(bare.length, 1, bare.map((d) => d.message).join("\n"));
  assert.equal(bare[0]!.message, "elements.label.outline: write 'outline: {color: color.bg}' -- a 1px ring; add 'width: 2' or 3 for a wider one");
  assert.equal(LABEL.split("\n").length, bare[0]!.span!.line, "pointed at the outline: line");
  const none = errorsOf(LABEL + "    outline: none\n");
  assert.equal(none.length, 1, none.map((d) => d.message).join("\n"));
  assert.equal(none[0]!.message, "elements.label.outline: 'outline: none' is not accepted here -- omit 'outline:' to draw no ring");
  assert.ok(none[0]!.notes.some((n) => n.includes("aod:")), "the note says where 'none' still means something");
  // a pattern's text part takes the same object, and the same refusal
  const part = errorsOf(MINIMAL + "  ticks:\n    type: pattern\n    pattern: radial\n    at: {anchor: center}\n    count: 3\n    step_angle: 120deg\n    parts:\n"
    + "      - {type: text, text: \"1\", font: FONT_SMALL, at: {dy: -40%r}, color: color.fg, outline: color.bg}\n");
  assert.equal(part.length, 1, part.map((d) => d.message).join("\n"));
  assert.equal(part[0]!.message, "elements.ticks.parts[0].outline: write 'outline: {color: color.bg}' -- a 1px ring; add 'width: 2' or 3 for a wider one");
  const inAod = errorsOf(LABEL + "    aod: {outline: color.bg}\n");
  assert.equal(inAod.length, 1, inAod.map((d) => d.message).join("\n"));
  assert.equal(inAod[0]!.message, "elements.label.aod.outline: write 'outline: {color: color.bg}' -- a 1px ring; add 'width: 2' or 3 for a wider one");
  // the object form, width defaulting to 1; `none` inside `aod:` drops the awake ring
  const [built] = load(LABEL + "    outline: {color: color.bg}\n    aod: {outline: none}\n");
  assert.ok(built !== null);
  const label = built!.walk().find((e) => e.id === "label") as unknown as { outline: { width: number } | null; aod: { outline_none: boolean } | null };
  assert.equal(label.outline!.width, 1);
  assert.equal(label.aod!.outline_none, true);
});

const GLYPH = MINIMAL + "  glyph:\n    type: icon\n    size: 10%r\n    at: {anchor: center}\n    color: color.fg\n";
const SLOT = MINIMAL.replace("elements:\n", "config:\n  slots:\n    top:\n      default: steps\n      choices: [steps, ICON]\nelements:\n")
  + "  reading:\n    type: data\n    slot: top\n    font: FONT_SMALL\n    at: {anchor: center}\n    color: color.fg\n";

test("a codepoint is icon: {codepoint: \"U+XXXX\"}: the bare string names it, on an icon element and a slot choice alike", () => {
  const bare = errorsOf(GLYPH + "    icon: \"U+F21E\"\n");
  assert.equal(bare.length, 1, bare.map((d) => d.message).join("\n"));
  assert.equal(bare[0]!.message, "elements.glyph.icon: write 'icon: {codepoint: \"U+F21E\"}' -- a bare string is a catalogue name");
  assert.equal(GLYPH.split("\n").length, bare[0]!.span!.line, "pointed at the icon: line");
  const choice = errorsOf(SLOT.replace("ICON", "{type: heart_rate, icon: \"U+F05F6\"}"));
  assert.equal(choice.length, 1, choice.map((d) => d.message).join("\n"));
  assert.equal(choice[0]!.message, "config.slots.top.choices[1].icon: write 'icon: {codepoint: \"U+F05F6\"}' -- a bare string is a catalogue name, or 'none'");
  // the object form resolves to the glyph, spelled as the author wrote it
  const [built] = load(GLYPH + "    icon: {codepoint: \"U+f21e\"}\n");
  assert.ok(built !== null);
  const glyph = built!.walk().find((e) => e.id === "glyph") as unknown as { icon: string; codepoint: string };
  assert.equal(glyph.icon, "U+F21E");
  assert.equal(glyph.codepoint, "");
  const [slotted] = load(SLOT.replace("ICON", "{type: heart_rate, icon: {codepoint: \"U+F05F6\"}}"));
  assert.ok(slotted !== null);
  const top = slotted!.config_data.get("top") as unknown as { icon_overrides: Map<string, { codepoint: string } | null> };
  assert.equal(top.icon_overrides.get("heart_rate")!.codepoint, "\u{F05F6}");
  // a name stays a bare string, and {for:} stays
  assert.equal(errorsOf(GLYPH + "    icon: steps\n").length, 0);
  assert.equal(errorsOf(GLYPH + "    icon: {for: weather.condition}\n").length, 0);
});

// -- id-keyed parts --

const HANDS = (parts: string): string => MINIMAL.replace("  palette:", `  hand_sets:
    classic:
      hour:
        color: color.fg
        parts:
${parts}
  palette:`) + "  dial:\n    type: hands\n    set: classic\n    at: {anchor: center}\n";
const BLADE = "{ type: polygon, points: [{ dx: -3%r, dy: 8%r }, { dy: -46%r }, { dx: 3%r, dy: 8%r }] }";

test("parts: the mapping form names a part by its id, the list form by partN, and both build the same hand", () => {
  const named = face(HANDS(`          blade: ${BLADE}\n          hub: { type: circle, radius: 4%r }`));
  assert.deepEqual(named.hands.get("classic")!.hour!.parts.map((p) => p.id), ["blade", "hub"]);
  const listed = face(HANDS(`          - ${BLADE}\n          - { type: circle, radius: 4%r }`));
  assert.deepEqual(listed.hands.get("classic")!.hour!.parts.map((p) => p.id), ["part1", "part2"]);
  const strip = (hand: unknown): unknown => JSON.parse(JSON.stringify(hand, (k, v) => (k === "id" || k === "span" ? undefined : v)));
  assert.deepEqual(strip(named.hands.get("classic")!.hour), strip(listed.hands.get("classic")!.hour));
  // a part's error names the part, and points at the part's own line
  const lineOf = (text: string, needle: string): number => text.split("\n").findIndex((l) => l.includes(needle)) + 1;
  const namedBad = HANDS(`          blade: ${BLADE}\n          hub: { type: circle, radius: 4%r, to: { dy: 1px } }`);
  const byId = errorsOf(namedBad);
  assert.equal(byId.length, 1, byId.map((d) => d.message).join("\n"));
  assert.equal(byId[0]!.message, "hand_sets.classic.hour.parts.hub: 'to' is not used by a hand 'type: circle' part");
  assert.equal(byId[0]!.span!.line, lineOf(namedBad, "hub:"), "the hub's own line");
  const listedBad = HANDS(`          - ${BLADE}\n          - { type: circle, radius: 4%r, to: { dy: 1px } }`);
  const byIndex = errorsOf(listedBad);
  assert.equal(byIndex.length, 1, byIndex.map((d) => d.message).join("\n"));
  assert.equal(byIndex[0]!.message, "hand_sets.classic.hour.parts.part2: 'to' is not used by a hand 'type: circle' part");
  assert.equal(byIndex[0]!.span!.line, lineOf(listedBad, "- { type: circle"), "the second item's own line");
});

test("parts: a duplicate id is one error, 17 parts are refused, and a bad id is refused naming what a name is", () => {
  const dup = errorsOf(HANDS(`          blade: ${BLADE}\n          blade: { type: circle, radius: 4%r }`));
  assert.equal(dup.length, 1, dup.map((d) => d.message).join("\n"));
  assert.ok(dup[0]!.message.includes("duplicate key"), dup[0]!.message);
  const many = errorsOf(HANDS(Array.from({ length: 17 }, (_, i) => `          p${i}: { type: circle, radius: ${i + 1}px }`).join("\n")));
  assert.equal(many.length, 1, many.map((d) => d.message).join("\n"));
  assert.ok(many[0]!.message.includes("at most 16") && many[0]!.message.includes("17"), many[0]!.message);
  const manyListed = errorsOf(HANDS(Array.from({ length: 17 }, (_, i) => `          - { type: circle, radius: ${i + 1}px }`).join("\n")));
  assert.equal(manyListed.length, 1, manyListed.map((d) => d.message).join("\n"));
  assert.ok(manyListed[0]!.message.includes("at most 16"), manyListed[0]!.message);
  const bad = errorsOf(HANDS(`          my-blade: ${BLADE}`));
  assert.equal(bad.length, 1, bad.map((d) => d.message).join("\n"));
  assert.ok(bad[0]!.message.includes("'my-blade' is not a valid name"), bad[0]!.message);
  assert.ok(bad[0]!.notes.some((n) => n.includes("a letter or underscore")), bad[0]!.notes.join("\n"));
  // the part body is still checked under a mapping: a bad key is named by the part's id
  const key = errorsOf(HANDS(`          blade: { type: polygon, points: [{ dx: -3%r, dy: 8%r }, { dy: -46%r }, { dx: 3%r, dy: 8%r }], radius: 2px }`));
  assert.equal(key.length, 1, key.map((d) => d.message).join("\n"));
  assert.equal(key[0]!.message, "hand_sets.classic.hour.parts.blade: 'radius' is not used by a hand 'type: polygon' part");
});

const TICKS = (parts: string): string => MINIMAL + `  ticks:
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 12
    color: color.fg
    parts:
${parts}
`;
const NEEDLE = (parts: string): string => MINIMAL + `  battery:
    type: gauge
    style: needle
    value: system.battery
    max: 100
    at: {anchor: center}
    start_angle: 240deg
    sweep: 240deg
    color: color.fg
    needle:
${parts}
`;

test("parts: a pattern's parts and a gauge's needle take the mapping form too, and name their parts by id", () => {
  const ticks = face(TICKS("      tick: { type: line, at: { dy: -90%r }, to: { dy: -80%r }, thickness: 2px }\n      dot: { type: circle, at: { dy: -76%r }, radius: 1%r }"));
  const pattern = ticks.elements.find((e) => e.id === "ticks") as unknown as { parts: { id: string }[] };
  assert.deepEqual(pattern.parts.map((p) => p.id), ["tick", "dot"]);
  const partError = errorsOf(TICKS("      tick: { type: line, at: { dy: -90%r }, to: { dy: -80%r }, thickness: 2px, filled: true }"));
  assert.equal(partError.length, 1, partError.map((d) => d.message).join("\n"));
  assert.equal(partError[0]!.message, "ticks.parts.tick: 'filled' is not used by a pattern 'type: line' part");
  const listed = errorsOf(TICKS("      - { type: line, at: { dy: -90%r }, to: { dy: -80%r }, thickness: 2px, filled: true }"));
  assert.equal(listed[0]!.message, "ticks.parts.part1: 'filled' is not used by a pattern 'type: line' part");
  const battery = face(NEEDLE(`      blade: ${BLADE}\n      hub: { type: circle, radius: 4%r }`));
  const gauge = battery.elements.find((e) => e.id === "battery") as unknown as { needle: { id: string }[] };
  assert.deepEqual(gauge.needle.map((p) => p.id), ["blade", "hub"]);
  const needleError = errorsOf(NEEDLE(`      blade: ${BLADE}\n      hub: { type: circle, radius: 4%r, to: { dy: 1px } }`));
  assert.equal(needleError.length, 1, needleError.map((d) => d.message).join("\n"));
  assert.equal(needleError[0]!.message, "battery.needle.hub: 'to' is not used by a hand 'type: circle' part");
});

// -- mirror: x on a polygon part --

const pointsOf = (hand: unknown): [number, number][] =>
  (hand as { parts: { points: { dx: { value: number } | null; dy: { value: number } | null; angle: { degrees: number } | null; radius: { value: number } | null }[] }[] })
    .parts[0]!.points.map((p) => (p.angle !== null ? [p.angle.degrees, p.radius!.value] : [p.dx?.value ?? 0, p.dy?.value ?? 0]));

test("mirror: x lists one half of a polygon part: the other half is appended reflected, in reverse, a point on the axis shared", () => {
  // A, B, C with C on the axis -> A, B, C, B', A'
  const tip = face(HANDS("          blade: { type: polygon, mirror: x, points: [{ dx: -3%r, dy: 8%r }, { dx: -2%r, dy: -38%r }, { dy: -46%r }] }"));
  assert.deepEqual(pointsOf(tip.hands.get("classic")!.hour), [[-3, 8], [-2, -38], [0, -46], [2, -38], [3, 8]]);
  // the same hand written out in full resolves to the same IR
  const full = face(HANDS("          blade: { type: polygon, points: [{ dx: -3%r, dy: 8%r }, { dx: -2%r, dy: -38%r }, { dy: -46%r }, { dx: 2%r, dy: -38%r }, { dx: 3%r, dy: 8%r }] }"));
  assert.deepEqual(JSON.stringify(tip.hands.get("classic")!.hour, (k, v) => (k === "span" ? undefined : v)),
    JSON.stringify(full.hands.get("classic")!.hour, (k, v) => (k === "span" ? undefined : v)));
  // no point on the axis: every listed point comes back, A, B, B', A'
  const shaft = face(HANDS("          blade: { type: polygon, mirror: x, points: [{ dx: -3%r, dy: 11%r }, { dx: -2.5%r, dy: -27%r }] }"));
  assert.deepEqual(pointsOf(shaft.hands.get("classic")!.hour), [[-3, 11], [-2.5, -27], [2.5, -27], [3, 11]]);
  // a point on the axis at either end is shared, and an explicit dx: 0 counts as on the axis
  const diamond = face(HANDS("          blade: { type: polygon, mirror: x, points: [{ dx: 0%r, dy: 5%r }, { dx: -5%r, dy: -14%r }, { dy: -48%r }] }"));
  assert.deepEqual(pointsOf(diamond.hands.get("classic")!.hour), [[0, 5], [-5, -14], [0, -48], [5, -14]]);
  // a polar point reflects by negating its angle; one on the axis (0 or 180 degrees) is shared
  const polar = face(HANDS("          blade: { type: polygon, mirror: x, points: [{ angle: 180deg, radius: 6%r }, { angle: -20deg, radius: 30%r }, { angle: 0deg, radius: 44%r }] }"));
  assert.deepEqual(pointsOf(polar.hands.get("classic")!.hour), [[180, 6], [-20, 30], [0, 44], [20, 30]]);
  // a pattern part and a needle part take it the same way
  const ticks = face(TICKS("      tri: { type: polygon, mirror: x, points: [{ dx: -3%r, dy: -56%r }, { dy: -64%r }] }"));
  assert.deepEqual(pointsOf(ticks.elements.find((e) => e.id === "ticks")), [[-3, -56], [0, -64], [3, -56]]);
  const needle = face(NEEDLE("      blade: { type: polygon, mirror: x, points: [{ dx: -3%r, dy: 12%r }, { dy: -74%r }] }"));
  assert.deepEqual(pointsOf({ parts: (needle.elements.find((e) => e.id === "battery") as unknown as { needle: unknown[] }).needle }), [[-3, 12], [0, -74], [3, 12]]);
});

test("mirror: x is refused on any part but a polygon, and a mirrored polygon still needs three points in all", () => {
  for (const [design, label] of [
    [HANDS("          hub: { type: circle, radius: 4%r, mirror: x }"), "hand_sets.classic.hour.parts.hub"],
    [TICKS("      tick: { type: line, at: { dy: -90%r }, to: { dy: -80%r }, mirror: x }"), "ticks.parts.tick"],
    [NEEDLE("      bar: { type: rectangle, size: { width: 2%r, height: 40%r }, mirror: x }"), "battery.needle.bar"],
  ] as const) {
    const refused = errorsOf(design);
    assert.equal(refused.length, 1, refused.map((d) => d.message).join("\n"));
    assert.equal(refused[0]!.message, `${label}: 'mirror:' applies to a polygon part only`);
    assert.ok(refused[0]!.notes.some((n) => n.includes("one half")), refused[0]!.notes.join("\n"));
  }
  assert.ok(errorsOf(HANDS("          hub: { type: circle, radius: 4%r, mirror: y }"))[0]!.message.includes("not valid here"));
  // two listed points, both on the axis, mirror to two
  const thin = errorsOf(HANDS("          blade: { type: polygon, mirror: x, points: [{ dy: 8%r }, { dy: -46%r }] }"));
  assert.equal(thin.length, 1, thin.map((d) => d.message).join("\n"));
  assert.equal(thin[0]!.message, "hand_sets.classic.hour.parts.blade: a polygon part needs at least 3 points -- 2 listed, 2 once mirrored");
  const two = errorsOf(HANDS("          blade: { type: polygon, points: [{ dx: -3%r, dy: 8%r }, { dy: -46%r }] }"));
  assert.equal(two.length, 1, two.map((d) => d.message).join("\n"));
  assert.equal(two[0]!.message, "hand_sets.classic.hour.parts.blade: a polygon part needs at least 3 points -- 2 listed");
});

// -- a text's own font --

const OPEN_SANS_TTF = "ts/test/fixtures/slice/assets/OpenSans-Regular.ttf";
const lineWith = (text: string, needle: string): number => text.split("\n").findIndex((l) => l.includes(needle)) + 1;
/** A `text` element `id`, its `font:` written as the block `font` (indented six spaces per line). */
const OWN_FONT = (id: string, font: string, more = ""): string =>
  `  ${id}:\n    type: text\n    text: "{time.hour:02d}"\n    at: {anchor: center}\n    color: color.fg\n${more}    font:\n${font}`;
const DECLARED_FONT = (name: string, spec: string): string => MINIMAL.replace("  palette:", `  fonts:\n    ${name}:\n${spec}  palette:`);
/** Every generated file, bytes rendered comparably. */
function everyFile(text: string): Map<string, string> {
  const f = face(text);
  const out = new Map<string, string>();
  for (const [name, content] of generate(f, f.targets.map((id) => db.get(id)), (p) => readFontFile(p === ICON_FONT ? p : join(REPO_ROOT, p))).files()) {
    out.set(name, typeof content === "string" ? content : Buffer.from(content).toString("base64"));
  }
  return out;
}
const fontOf = (f: Face, id: string): [string, boolean] => {
  const element = f.elements.find((e) => e.id === id) as unknown as { font: string; font_is_custom: boolean };
  return [element.font, element.font_is_custom];
};

test("a text's own font: an inline {source, size} is a resources.fonts entry named after the element, generating the same files", () => {
  const spec = `      source: ${OPEN_SANS_TTF}\n      size: 20%r\n      monospace: true\n`;
  const inline = MINIMAL + OWN_FONT("clock", spec);
  const built = face(inline);
  assert.deepEqual([...built.fonts.keys()], ["clock_font"]);
  assert.deepEqual(fontOf(built, "clock"), ["clock_font", true]);
  assert.equal(built.fonts.get("clock_font")!.monospace, true);
  const declared = DECLARED_FONT("clock_font", spec) + OWN_FONT("clock", "").replace("    font:\n", "    font: font.clock_font\n");
  const [a, b] = [everyFile(inline), everyFile(declared)];
  assert.ok(a.has("resources-fenix8solar47mm/fonts/fonts.xml") && [...a.keys()].some((n) => n.endsWith(".fnt")) && [...a.keys()].some((n) => n.endsWith(".png")));
  assert.deepEqual([...a.keys()].sort(), [...b.keys()].sort());
  for (const [name, content] of a) assert.equal(content, b.get(name), name);
  // a vector face inline, the same way
  const vector = face(MINIMAL + OWN_FONT("brand", "      face: [RobotoCondensedBold, RobotoCondensedRegular]\n      size: 10%r\n      unsupported: hide\n"));
  assert.deepEqual(vector.fonts.get("brand_font")!.face, ["RobotoCondensedBold", "RobotoCondensedRegular"]);
  assert.equal(vector.fonts.get("brand_font")!.unsupported, "hide");
  // a pattern's text part: <element>_<part>_font
  const ticks = face(MINIMAL + "  ticks:\n    type: pattern\n    pattern: radial\n    at: {anchor: center}\n    count: 12\n    color: color.fg\n    parts:\n"
    + `      numeral:\n        type: text\n        text: "{(copy + 11) % 12 + 1}"\n        at: {dy: -40%r}\n        font: {source: ${OPEN_SANS_TTF}, size: 8%r}\n`);
  assert.deepEqual([...ticks.fonts.keys()], ["ticks_numeral_font"]);
  const part = (ticks.elements.find((e) => e.id === "ticks") as unknown as { parts: { font: string; font_is_custom: boolean }[] }).parts[0]!;
  assert.deepEqual([part.font, part.font_is_custom], ["ticks_numeral_font", true]);
  // the string forms are untouched
  assert.deepEqual(fontOf(face(MINIMAL + OWN_FONT("clock", "").replace("    font:\n", "    font: FONT_SMALL\n")), "clock"), ["FONT_SMALL", false]);
});

test("a text's own font: a bad size is reported on the inline size: line; identical fonts share one entry; a taken name gets _2", () => {
  const bad = MINIMAL + OWN_FONT("clock", `      source: ${OPEN_SANS_TTF}\n      size: 20\n`);
  const bare = errorsOf(bad);
  assert.equal(bare.length, 1, bare.map((d) => d.message).join("\n"));
  assert.ok(bare[0]!.message.startsWith("font 'clock_font': size must be a length"), bare[0]!.message);
  assert.equal(bare[0]!.span!.line, lineWith(bad, "size: 20"), "the inline size: line");
  const missing = MINIMAL + OWN_FONT("clock", "      source: assets/Nowhere.ttf\n      size: 20%r\n");
  const gone = errorsOf(missing);
  assert.equal(gone.length, 1, gone.map((d) => d.message).join("\n"));
  assert.equal(gone[0]!.message, "font 'clock_font': source file not found: assets/Nowhere.ttf");
  assert.equal(gone[0]!.span!.line, lineWith(missing, "source: assets/Nowhere.ttf"));
  // neither source nor face: the schema's word, the same one a declared entry gets, at the element's own key
  const neither = MINIMAL + OWN_FONT("clock", "      size: 20%r\n");
  const halves = errorsOf(neither);
  assert.equal(halves.length, 1, halves.map((d) => d.message).join("\n"));
  const declaredHalves = errorsOf(DECLARED_FONT("x", "      size: 20%r\n"));
  assert.equal(halves[0]!.message, declaredHalves[0]!.message.replace("resources.fonts.x", "elements.clock.font"));
  assert.equal(halves[0]!.span!.line, lineWith(neither, "size: 20%r"));
  // two elements writing the identical object share the first one's entry; a different object is its own
  const same = `      source: ${OPEN_SANS_TTF}\n      size: 20%r\n`;
  const shared = face(MINIMAL + OWN_FONT("hours", same) + OWN_FONT("minutes", same) + OWN_FONT("seconds", `      source: ${OPEN_SANS_TTF}\n      size: 10%r\n`));
  assert.deepEqual([...shared.fonts.keys()], ["hours_font", "seconds_font"]);
  assert.deepEqual([fontOf(shared, "hours")[0], fontOf(shared, "minutes")[0], fontOf(shared, "seconds")[0]], ["hours_font", "hours_font", "seconds_font"]);
  // a declared font already holding the name: the inline one takes the next free suffix
  const taken = face(DECLARED_FONT("clock_font", same) + OWN_FONT("clock", `      source: ${OPEN_SANS_TTF}\n      size: 10%r\n`));
  assert.deepEqual([...taken.fonts.keys()], ["clock_font", "clock_font_2"]);
  assert.equal(fontOf(taken, "clock")[0], "clock_font_2");
});

// -- base: on a scheme, label: on a layout --

/** `MINIMAL` with `theme: schemes:` (roles `paper`, `ink`, `dim`), a style per named scheme, and a text reading `color.ink`. */
const THEMED = (schemes: string, styled: string[] = ["dark", "light"]): string => MINIMAL.replace("elements:\n",
  `theme:\n  schemes:\n${schemes}config:\n  style:\n    default: ${styled[0]}\n    choices:\n${styled.map((s) => `      ${s}: {scheme: ${s}}\n`).join("")}elements:\n`)
  + "  clock:\n    type: text\n    text: \"a\"\n    at: {anchor: center}\n    color: color.ink\n    font: FONT_SMALL\n";
const DARK = "    dark:\n      colors: {paper: \"#000000\", ink: \"#FFFFFF\", dim: \"#AAAAAA\"}\n";
const schemeColors = (f: Face, name: string): [string, number][] => [...f.color_scheme.get(name)!.colors].map(([role, c]) => [role, c.value]);

test("base: a scheme inherits its base's roles, overriding the ones it lists, and generates what the written-out scheme does", () => {
  const derived = THEMED(DARK + "    light:\n      base: dark\n      colors: {paper: \"#FFFFFF\", ink: \"#000000\"}\n");
  const built = face(derived);
  assert.deepEqual(schemeColors(built, "light"), [["paper", 0xFFFFFF], ["ink", 0x000000], ["dim", 0xAAAAAA]]);
  assert.deepEqual(schemeColors(built, "dark"), [["paper", 0x000000], ["ink", 0xFFFFFF], ["dim", 0xAAAAAA]]);
  const written = THEMED(DARK + "    light:\n      colors: {paper: \"#FFFFFF\", ink: \"#000000\", dim: \"#AAAAAA\"}\n");
  const [a, b] = [everyFile(derived), everyFile(written)];
  assert.deepEqual([...a.keys()].sort(), [...b.keys()].sort());
  for (const [name, content] of a) assert.equal(content, b.get(name), name);
  // a base may itself derive; a derived scheme may add a role its base then lacks -- reported on the base, as any mismatch is
  const chained = face(THEMED(DARK + "    light:\n      base: dark\n      colors: {paper: \"#FFFFFF\", ink: \"#000000\"}\n    navy:\n      base: light\n      colors: {paper: \"#000055\"}\n", ["dark", "light", "navy"]));
  assert.deepEqual(schemeColors(chained, "navy"), [["paper", 0x000055], ["ink", 0x000000], ["dim", 0xAAAAAA]]);
  const extra = THEMED(DARK + "    light:\n      base: dark\n      colors: {paper: \"#FFFFFF\", glow: \"#FFAA00\"}\n");
  const mismatch = errorsOf(extra);
  assert.equal(mismatch.length, 1, mismatch.map((d) => d.message).join("\n"));
  assert.equal(mismatch[0]!.message, "theme.schemes.dark: missing role(s) glow -- every scheme must declare the same roles");
  // a layout's label: is the editor's, and changes nothing generated
  const LAYOUTS = (label: string): string => MINIMAL.replace("elements:\n", `layouts:\n  big:\n${label}    elements:\n      clock: {type: text, text: "a", at: {anchor: center}, color: color.fg, font: FONT_SMALL}\n`
    + "config:\n  style:\n    default: big\n    choices:\n      big: {layout: big}\nelements:\n");
  const [labelled, plain] = [everyFile(LAYOUTS("    label: \"Big clock\"\n")), everyFile(LAYOUTS(""))];
  assert.deepEqual([...labelled.keys()].sort(), [...plain.keys()].sort());
  for (const [name, content] of labelled) assert.equal(content, plain.get(name), name);
});

test("base: an unknown base and a circle are one error each, naming the scheme, and a derived scheme of a rejected one stays quiet", () => {
  const unknown = THEMED(DARK + "    light:\n      base: drak\n      colors: {paper: \"#FFFFFF\"}\n");
  const missing = errorsOf(unknown);
  assert.equal(missing.length, 1, missing.map((d) => d.message).join("\n"));
  assert.equal(missing[0]!.message, "theme.schemes.light: base 'drak' is not a declared scheme");
  assert.equal(missing[0]!.span!.line, lineWith(unknown, "base: drak"));
  assert.ok(missing[0]!.notes.some((n) => n.includes("dark")), "names the declared schemes");
  const circle = THEMED("    dark:\n      base: light\n      colors: {paper: \"#000000\", ink: \"#FFFFFF\"}\n    light:\n      base: dark\n      colors: {paper: \"#FFFFFF\", ink: \"#000000\"}\n");
  const round = errorsOf(circle);
  assert.equal(round.length, 1, round.map((d) => d.message).join("\n"));
  assert.equal(round[0]!.message, "theme.schemes.dark: 'base:' runs in a circle: dark -> light -> dark");
  assert.equal(round[0]!.span!.line, lineWith(circle, "base: light"));
  const self = errorsOf(THEMED(DARK + "    light:\n      base: light\n      colors: {paper: \"#FFFFFF\"}\n"));
  assert.equal(self.length, 1, self.map((d) => d.message).join("\n"));
  assert.equal(self[0]!.message, "theme.schemes.light: 'base:' runs in a circle: light -> light");
  // the base's own mistake is the one error: the scheme deriving from it, and the styles naming either, say nothing more
  const badBase = errorsOf(THEMED("    dark:\n      colors: {paper: \"#000000\", ink: color.nowhere, dim: \"#AAAAAA\"}\n    light:\n      base: dark\n      colors: {paper: \"#FFFFFF\"}\n"));
  assert.equal(badBase.length, 1, badBase.map((d) => d.message).join("\n"));
  assert.ok(badBase[0]!.message.includes("nowhere"), badBase[0]!.message);
});

// -- rule lists --

/** `MINIMAL` plus a circle whose `color:` is written as `color` (indented four spaces per line). */
const RULED = (color: string): string => MINIMAL + `  badge:\n    type: circle\n    at: {anchor: center}\n    radius: 10%r\n${color}`;
const exprText = (f: Face, id: string, key: string): string => ((f.elements.find((e) => e.id === id) as unknown as Record<string, { text: string } | null>)[key])!.text;
const RULES_ONE = "    color:\n      - when: device.notification_count > 0\n        value: color.fg\n      - else: color.bg\n";
const RULES_TWO = "    color:\n      - when: device.notification_count > 0\n        value: color.fg\n      - when: system.charging\n        value: color.bg\n      - else: color.fg\n";
/** The 1-based line whose text, trimmed at the end, is exactly `line`. */
const lineExactly = (text: string, line: string): number => text.split("\n").findIndex((l) => l.trimEnd() === line) + 1;

test("rule lists: a rule list is the nested ternary, and generates what that ternary written by hand does", () => {
  const one = face(RULED(RULES_ONE));
  assert.equal(exprText(one, "badge", "color"), "device.notification_count > 0 ? color.fg : color.bg");
  const two = face(RULED(RULES_TWO));
  assert.equal(exprText(two, "badge", "color"), "device.notification_count > 0 ? color.fg : system.charging ? color.bg : color.fg");
  for (const [rules, hand] of [
    [RULES_ONE, "    color: \"device.notification_count > 0 ? color.fg : color.bg\"\n"],
    [RULES_TWO, "    color: \"device.notification_count > 0 ? color.fg : system.charging ? color.bg : color.fg\"\n"],
  ] as const) {
    const [a, b] = [everyFile(RULED(rules)), everyFile(RULED(hand))];
    assert.deepEqual([...a.keys()].sort(), [...b.keys()].sort());
    for (const [name, content] of a) assert.equal(content, b.get(name), name);
  }
  // visible: takes booleans for its values; value:/max:/min: take numbers; aod: visible: and a part's visible: take a list too
  const shown = face(RULED("    color: color.fg\n    visible:\n      - when: device.notification_count > 0\n        value: true\n      - else: false\n"));
  assert.equal(exprText(shown, "badge", "visible"), "device.notification_count > 0 ? true : false");
  const gauge = face(MINIMAL + "  battery:\n    type: gauge\n    style: arc\n    at: {anchor: center}\n    radius: 40%r\n    thickness: 4px\n    start_angle: 0deg\n    sweep: 270deg\n    color: color.fg\n"
    + "    value:\n      - when: system.charging\n        value: 100\n      - else: system.battery\n    max: 100\n");
  assert.equal(exprText(gauge, "battery", "value"), "system.charging ? 100 : system.battery");
  const ticks = face(MINIMAL + "  ticks:\n    type: pattern\n    pattern: radial\n    at: {anchor: center}\n    count: 12\n    color: color.fg\n    parts:\n"
    + "      dot:\n        type: circle\n        at: {dy: -40%r}\n        radius: 2%r\n        visible:\n          - when: copy % 3 == 0\n            value: \"true\"\n          - else: \"false\"\n");
  const dot = (ticks.elements.find((e) => e.id === "ticks") as unknown as { parts: { visible: { text: string } | null }[] }).parts[0]!;
  assert.equal(dot.visible!.text, "copy % 3 == 0 ? true : false");
  // a piece that is a conditional itself is the one parenthesised; the chain needs none
  const nested = face(RULED("    color:\n      - when: \"system.charging ? device.notification_count > 0 : false\"\n        value: \"system.battery < 20 ? color.bg : color.fg\"\n      - else: color.fg\n"));
  assert.equal(exprText(nested, "badge", "color"), "(system.charging ? device.notification_count > 0 : false) ? (system.battery < 20 ? color.bg : color.fg) : color.fg");
  // an aod: block takes a rule list too
  const aod = face(RULED("    color: color.fg\n    aod:\n      color:\n        - when: system.charging\n          value: color.bg\n        - else: color.fg\n"));
  const aodColor = (aod.elements.find((e) => e.id === "badge") as unknown as { aod: { color: { text: string } | null } | null }).aod!.color!;
  assert.equal(aodColor.text, "system.charging ? color.bg : color.fg");
  // the string spelling is untouched: no parentheses are added to it
  assert.equal(exprText(face(RULED("    color: \"device.notification_count > 0 ? color.fg : color.bg\"\n")), "badge", "color"), "device.notification_count > 0 ? color.fg : color.bg");
});

test("rule lists: the shape is checked, and a mistake inside a rule is reported on that rule's own line", () => {
  const noElse = RULED("    color:\n      - when: device.notification_count > 0\n        value: color.fg\n");
  let found = errorsOf(noElse);
  assert.equal(found.length, 1, found.map((d) => d.message).join("\n"));
  assert.equal(found[0]!.message, "color: a rule list ends with an {else: ...} rule, the value when no 'when:' holds");
  assert.equal(found[0]!.span!.line, lineExactly(noElse, "    color:"));
  const twoElse = RULED("    color:\n      - when: device.notification_count > 0\n        value: color.fg\n      - else: color.bg\n      - else: color.fg\n");
  found = errorsOf(twoElse);
  assert.equal(found.length, 1, found.map((d) => d.message).join("\n"));
  assert.equal(found[0]!.message, "color: one {else: ...} rule, not two");
  assert.equal(found[0]!.span!.line, lineWith(twoElse, "- else: color.fg"));
  const elseFirst = RULED("    color:\n      - else: color.bg\n      - when: device.notification_count > 0\n        value: color.fg\n");
  found = errorsOf(elseFirst);
  assert.equal(found.length, 1, found.map((d) => d.message).join("\n"));
  assert.equal(found[0]!.message, "color: the {else: ...} rule comes last");
  assert.equal(found[0]!.span!.line, lineWith(elseFirst, "- else: color.bg"));
  const onlyElse = RULED("    color:\n      - else: color.bg\n");
  found = errorsOf(onlyElse);
  assert.equal(found.length, 1, found.map((d) => d.message).join("\n"));
  assert.equal(found[0]!.message, "color: a rule list needs a {when: ..., value: ...} rule before its else -- a value that never varies is written on its own");
  // a when: that is not boolean: the type error, on that rule's line, at its when:
  const notBoolean = RULED("    color:\n      - when: device.notification_count > 0\n        value: color.fg\n      - when: device.notification_count\n        value: color.bg\n      - else: color.fg\n");
  found = errorsOf(notBoolean);
  assert.equal(found.length, 1, found.map((d) => d.message).join("\n"));
  assert.equal(found[0]!.message, "color: ?: needs a boolean, got number");
  assert.equal(found[0]!.span!.line, lineExactly(notBoolean, "      - when: device.notification_count"));
  assert.equal(found[0]!.span!.col, notBoolean.split("\n")[found[0]!.span!.line - 1]!.indexOf("device.notification_count") + 1);
  // inside a piece the rewrite parenthesised, the column is still the author's
  const inner = RULED("    color:\n      - when: system.charging\n        value: color.bg\n      - else: \"system.battery > 20 ? color.fg : foo.bar\"\n");
  found = errorsOf(inner);
  assert.equal(found.length, 1, found.map((d) => d.message).join("\n"));
  assert.equal(found[0]!.message, "color: unknown data source 'foo.bar'");
  assert.equal(found[0]!.span!.line, lineWith(inner, "- else: \"system.battery"));
  assert.equal(found[0]!.span!.col, inner.split("\n")[found[0]!.span!.line - 1]!.indexOf("foo.bar") + 1);
  // a literal colour is not an expression: it is refused naming the palette, on its rule's line
  const literal = RULED("    color:\n      - when: device.notification_count > 0\n        value: color.fg\n      - else: \"#AAAAAA\"\n");
  found = errorsOf(literal);
  assert.equal(found.length, 1, found.map((d) => d.message).join("\n"));
  assert.equal(found[0]!.message, "color: a literal colour cannot be a rule's value -- add '#AAAAAA' to 'resources: palette:' and write 'color.<name>'");
  assert.equal(found[0]!.span!.line, lineWith(literal, "- else: \"#AAAAAA\""));
  // an unknown colour inside a value: on that rule's line
  const unknown = RULED("    color:\n      - when: device.notification_count > 0\n        value: color.fgg\n      - else: color.bg\n");
  found = errorsOf(unknown);
  assert.equal(found.length, 1, found.map((d) => d.message).join("\n"));
  assert.equal(found[0]!.message, "unknown colour 'color.fgg'");
  assert.equal(found[0]!.span!.line, lineWith(unknown, "value: color.fgg"));
  // a value of the wrong kind for the key: the schema's error, at the rule
  const wrongKind = RULED("    color:\n      - when: device.notification_count > 0\n        value: 5\n      - else: color.bg\n");
  found = errorsOf(wrongKind);
  assert.equal(found.length, 1, found.map((d) => d.message).join("\n"));
  assert.match(found[0]!.message, /^elements\.badge\.color\[0\]\.value: /);
  assert.equal(found[0]!.span!.line, lineWith(wrongKind, "value: 5"));
  const visibleNumber = RULED("    color: color.fg\n    visible:\n      - when: device.notification_count > 0\n        value: 5\n      - else: false\n");
  found = errorsOf(visibleNumber);
  assert.equal(found.length, 1, found.map((d) => d.message).join("\n"));
  assert.match(found[0]!.message, /^elements\.badge\.visible\[0\]\.value: /);
});
