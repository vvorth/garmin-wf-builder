// The native config editor's preview keeps the active frame's rate: a face
// started by the editor redraws itself once a second while awake.
import assert from "node:assert/strict";
import { test } from "node:test";
import { generated, method, MINIMAL } from "./designs.ts";

const SECONDS = `
  seconds:
    type: text
    text: "{time.clock:%S}"
    font: FONT_SMALL
    at: {anchor: center}
    color: color.fg
`;

const SLOTS = MINIMAL.replace("resources:", `config:
  slots:
    top: { default: battery, choices: [battery, steps] }
resources:`) + SECONDS + `
  top_reading:
    type: data
    slot: top
    at: {anchor: center, dy: -30%}
    font: FONT_SMALL
    color: color.fg
    absent: hide
`;

const ACCENT = MINIMAL.replace("resources:", `config:
  accent_color: { default: color.fg, choices: [color.fg, color.bg] }
resources:`) + SECONDS;

const file = (files: Map<string, string>, suffix: string): string => [...files].find(([name]) => name.endsWith(suffix))![1];

test("a face the editor started ticks once a second while awake", () => {
  for (const design of [SLOTS, ACCENT]) {
    const files = generated(design, ["fenix8solar47mm", "fr955"]);
    const app = file(files, "App.mc"), view = file(files, "View.mc");
    assert.match(app, /state\[:launchedFromWatchFaceSettingsEditor\]/);
    assert.match(app, /new TestView\(_editMode\)/);
    assert.match(view, /^import Toybox\.Timer;$/m);
    assert.match(method(view, "initialize"), /_editMode = editMode;/);
    // started only in edit mode, only while awake, never twice
    const start = method(view, "startEditTicks");
    assert.match(start, /if \(_editMode && _editAwake && _editTimer == null\)/);
    assert.match(start, /timer\.start\(method\(:onEditTick\), 1000, true\);/);
    assert.match(method(view, "onEditTick"), /WatchUi\.requestUpdate\(\);/);
    assert.match(method(view, "onShow"), /startEditTicks\(\);/);
    assert.match(method(view, "onHide"), /stopEditTicks\(\);/);
    // Timer.start crashes a watch face in low power: stopped before it, restarted after
    assert.match(method(view, "onEnterSleep"), /_editAwake = false;\s*stopEditTicks\(\);/);
    assert.match(method(view, "onExitSleep"), /_editAwake = true;\s*startEditTicks\(\);/);
  }
});

test("a tick's redraw keeps skipping the slot the editor animates", () => {
  const view = file(generated(SLOTS, ["fenix8solar47mm"]), "View.mc");
  assert.match(method(view, "onEditTick"), /_editTick = true;/);
  assert.match(method(view, "setPulsing"), /_pulseFresh = unique != 0;/);
  // decided before anything draws: the editor's own redraw after asking for the
  // drawable keeps the skip, its next one (the move to "Done") lifts it
  const update = method(view, "onUpdate");
  assert.match(update, /^[^]*?\{\s*(?:\/\/[^\n]*\n\s*)*if \(!_editTick\) \{\s*if \(_pulseFresh\) \{\s*_pulseFresh = false;\s*\}\s*else \{\s*_pulsing = 0;\s*\}\s*\}\s*_editTick = false;\s*dc\.clearClip\(\);/);
  assert.doesNotMatch(update.split("dc.clearClip();")[1]!, /_pulsing = 0;/);
});

test("a face with no config has no ticker", () => {
  const files = generated(MINIMAL + SECONDS, ["fenix8solar47mm"]);
  for (const text of files.values()) assert.doesNotMatch(text, /Timer|_editMode|onEditTick/);
});

test("--trace opens every lifecycle and editor callback with a println, and nothing else changes", () => {
  const plain = generated(SLOTS, ["fenix8solar47mm", "fr955"]);
  const traced = generated(SLOTS, ["fenix8solar47mm", "fr955"], { trace: true });
  const line = (text: string, fn: string): RegExp => new RegExp(`function ${fn}\\([^]*?\\{\\n\\s*System\\.println\\("wfb " \\+ System\\.getTimer\\(\\) \\+ " [A-Za-z]+\\.${fn}"`);
  const app = file(traced, "App.mc"), view = file(traced, "View.mc"), delegate = file(traced, "Delegate.mc");
  assert.match(app, line(app, "onStart"));
  assert.match(app, /^import Toybox\.System;$/m);
  for (const fn of ["initialize", "onLayout", "onShow", "onHide", "onUpdate", "onEnterSleep", "onExitSleep", "startEditTicks", "onEditTick", "setPulsing", "drawableFor"]) {
    assert.match(view, line(view, fn), fn);
  }
  assert.match(method(view, "onUpdate"), /" pulsing=" \+ _pulsing/);
  // a multi-line signature: the line lands in the body, past the options' own brace
  assert.match(delegate, /:committed as \$\.Toybox\.Lang\.Boolean\}\) as Void \{\n\s*System\.println\([^\n]*onWatchFaceConfigEdited" \+ " type=" \+ options\[:type\]/);
  assert.match(file(traced, "SlotDrawable.mc"), /System\.println\([^\n]*SlotDrawable\.draw"/);
  // the config menu's delegates are not traced, and removing the lines gives back the plain build
  assert.doesNotMatch(file(traced, "ConfigMenuDelegate.mc"), /println/);
  for (const [name, text] of traced) {
    const untraced = text.split("\n").filter((l) => !/System\.println\("wfb "/.test(l)).join("\n");
    assert.equal(untraced.replace(/\nimport Toybox\.System;/, plain.get(name)!.includes("import Toybox.System;") ? "\nimport Toybox.System;" : ""), plain.get(name), name);
  }
  for (const text of plain.values()) assert.doesNotMatch(text, /println\("wfb /);
});
