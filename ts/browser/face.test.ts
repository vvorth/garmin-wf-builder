// The Face tab's sections against the real worker, each action the guide
// lists read back from the YAML text: targets, colours (a used colour's
// deletion refused with the friendly message), the colour settings, schemes,
// styles (`+ Layout` on a face whose styles name only schemes), hand sets,
// slots and fonts (a file that is not a font refused).

import assert from "node:assert/strict";
import { join } from "node:path";
import type { Locator } from "playwright";
import type { Summary } from "../src/studio/protocol.ts";
import { diffLines, EXAMPLES, type Session, suite } from "./harness.ts";

const h = await suite(import.meta.url);

async function written(s: Session, before: Summary): Promise<Summary> {
  const after = await s.waitVersion(before.version);
  await s.waitIdle();
  return after;
}

async function undoTo(s: Session, before: Summary, what: string): Promise<void> {
  const after = await s.undo();
  assert.equal(after.text, before.text, `undo after ${what}: ${diffLines(before.text, after.text).join(" ; ")}`);
}

/** Type `name` into the AddName input that `button` turned into, and confirm it with Enter. */
async function addNamed(s: Session, button: Locator, name: string): Promise<void> {
  await button.click();
  const input = s.page.locator(".add-name input.inline-name");
  await input.fill(name);
  await input.press("Enter");
}

/** Click an InlineName (`name`, the text shown) and give it `to`. */
async function renameInline(s: Session, name: Locator, to: string): Promise<void> {
  await name.click();
  const input = s.page.locator(".face-section-body input.inline-name, .inspector input.inline-name").first();
  await input.fill(to);
  await input.press("Enter");
}

h.test("Target devices: a watch added and removed; the strip and the Device select follow", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();
  await s.faceSection("Target devices");
  const section = s.page.locator(".face-section-body");
  assert.deepEqual(await section.locator("ul.rows li code").allTextContents(), ["fenix8solar47mm", "fenix8solar51mm", "fr955"]);
  // picking a watch in the add select adds it at once
  await section.locator("select[aria-label='add a target']").selectOption("fr255");
  let doc = await written(s, base);
  assert.match(doc.text, /^  targets:\n    - fenix8solar47mm\n    - fenix8solar51mm\n    - fr955\n    - fr255$/m, diffLines(base.text, doc.text).join(" ; "));
  assert.deepEqual(doc.targets, ["fenix8solar47mm", "fenix8solar51mm", "fr955", "fr255"]);
  await s.expectText(s.page.locator(".face-nav button", { hasText: "Target devices" }).locator(".count"), "4");
  assert.deepEqual(await s.page.locator(".controls select").first().locator("option").allTextContents(), doc.targets);
  assert.equal(await s.page.locator(".strip button").count(), 4);
  // remove it again with ×
  await section.locator("ul.rows li").filter({ hasText: "fr255" }).locator("button[aria-label='remove fr255']").click();
  doc = await written(s, doc);
  assert.equal(doc.text, base.text);
  assert.deepEqual(s.errors, []);
});

h.test("Colours: rename, recolour, add, remove unused, and a used colour's deletion refused", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();
  await s.faceSection("Colours");
  const rows = s.page.locator(".face-section-body .swatch-row");
  assert.equal(await rows.count(), 5);
  const row = (name: string) => rows.filter({ has: s.page.locator(".name", { hasText: new RegExp(`^${name}$`) }) });
  assert.match((await row("dim").locator(".note").textContent()) ?? "", /used by outer_arc, card_inner, rule/);

  // a used colour cannot be deleted; the message names its users
  const t = Date.now();
  await row("dim").locator("button[aria-label^='delete']").click();
  assert.equal(await s.waitToast(t, /dim/), "the colour dim is used by 3 elements: outer_arc, card_inner, rule; change them first");
  assert.equal((await s.doc()).text, base.text);

  // rename: every color.dim follows
  await renameInline(s, row("dim").locator(".name"), "faint");
  let doc = await written(s, base);
  assert.equal(doc.text.match(/color\.faint/g)?.length, 3);
  assert.doesNotMatch(doc.text, /\bdim\b/);
  assert.equal(doc.history.undo, "rename resources.palette.dim to faint");
  await undoTo(s, base, "the rename");

  // its chip recolours every user at once
  await row("cool").locator("button.chip-button").click();
  await s.page.locator(".popover-body.pop .pop-grid button[aria-label='Yellow']").click();
  doc = await written(s, base);
  assert.match(doc.text, /^    cool: "#FFFF00"$/m, diffLines(base.text, doc.text).join(" ; "));
  assert.equal(diffLines(base.text, doc.text).length, 2, "recolouring changed more than the swatch's value");
  await undoTo(s, base, "the recolour");

  // + Colour adds one of the 64, named; then it is unused, and Remove unused takes it
  await s.page.locator(".face-section-body .row .popover button", { hasText: "+ Colour" }).click();
  await s.page.locator(".popover-body.pop .pop-grid button[aria-label='Yellow']").click();
  doc = await written(s, base);
  assert.match(doc.text, /^    yellow: \{ value: "#FFFF00", label: Yellow \}$/m);
  await s.expectText(row("yellow").locator(".note"), /not used/);
  assert.equal(await row("yellow").locator(".tag").textContent(), "auto");
  const remove = s.page.locator(".face-section-body button", { hasText: "Remove unused" });
  assert.equal(await remove.getAttribute("title"), "remove yellow");
  await remove.click();
  await s.page.locator(".modal .ask", { hasText: "Remove yellow?" }).waitFor();
  await s.page.locator(".modal-foot button.primary").click();
  doc = await written(s, doc);
  assert.equal(doc.text, base.text, `Remove unused: ${diffLines(base.text, doc.text).join(" ; ")}`);
  assert.equal(await remove.isDisabled(), true);
  assert.deepEqual(s.errors, []);
});

h.test("Colour settings: an accent setting added, its choices, default and role, and ×; choices: any made a list", async (s) => {
  // a face with no accent swatch, since the setting binds the role `accent`
  await s.openExample("features/styles");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();
  await s.faceSection("Colour settings");
  const body = s.page.locator(".face-section-body");
  assert.match((await body.textContent()) ?? "", /Accent colour: none/);
  await body.locator("button", { hasText: "+ Accent colour" }).click();
  let doc = await written(s, base);
  assert.match(doc.text, /^  accent_color: \{ default: color\.black, choices: \[color\.black\] \}$/m, diffLines(base.text, doc.text).join(" ; "));
  const axis = body.locator(".axis").first();
  // tick a colour: the list is always written out
  await axis.locator(".axis-choices label", { hasText: "white" }).locator("input").click();
  doc = await written(s, doc);
  assert.match(doc.text, /accent_color: \{ default: color\.black, choices: \[color\.black, color\.white\] \}/);
  // the default: one of the listed, which then cannot be unticked
  await axis.locator("select").selectOption("color.white");
  doc = await written(s, doc);
  assert.match(doc.text, /accent_color: \{ default: color\.white, choices: \[color\.black, color\.white\] \}/);
  await s.page.waitForFunction(() => {
    const label = [...document.querySelectorAll(".axis .axis-choices label")].find((l) => /white/.test(l.textContent!));
    return label !== undefined && (label.querySelector("input") as HTMLInputElement).disabled;
  }, null, { timeout: 8000 });
  // the role it binds
  const role = axis.locator(".axis-head input");
  await role.fill("glow");
  await role.press("Enter");
  doc = await written(s, doc);
  assert.match(doc.text, /accent_color: \{ default: color\.white, choices: \[color\.black, color\.white\], role: glow \}/);
  // × removes the whole setting
  await axis.locator(".axis-head button.reset").click();
  doc = await written(s, doc);
  assert.doesNotMatch(doc.text, /accent_color/);
  for (let i = 0; i < 5; i++) doc = await s.undo();
  assert.equal(doc.text, base.text, diffLines(base.text, doc.text).join(" ; "));

  // choices: any is shown, not edited, until Make it a list; the list is the face's colours no target dithers
  const themed = await s.openTemplate("themed", "Any colour");
  await s.waitFace();
  await s.waitIdle();
  const any = await s.api("edit", { id: themed.id, version: themed.version, edit: { op: "set", path: ["config", "accent_color", "choices"], value: "any" } });
  // a change made through the hook is this tab's own, so the page reads it on a reload
  await s.page.reload();
  await s.page.waitForSelector(".editor", { timeout: 30_000 });
  await s.waitFace();
  await s.faceSection("Colour settings");
  const accent = s.page.locator(".face-section-body .axis").first();
  await s.expectText(accent.locator(".note"), /choices: any/);
  assert.equal(await accent.locator(".axis-choices").count(), 0);
  await accent.locator("button", { hasText: "Make it a list" }).click();
  doc = await written(s, any);
  assert.match(doc.text, /^    choices: \[color\.orange, color\.black, color\.white, color\.light_gray, color\.dark_gray, color\.amber, color\.cyan, color\.sky_blue, color\.lime\]$/m, diffLines(any.text, doc.text).join(" ; "));
  await accent.locator(".axis-choices").waitFor({ timeout: 8000 });
  await undoTo(s, any, "Make it a list");
  assert.deepEqual(s.errors, []);
});

h.test("Colour schemes: make switchable, the table, + Scheme, + Role, renames, deletes and Remove schemes", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();
  await s.faceSection("Colour schemes");
  const body = s.page.locator(".face-section-body");
  await body.locator(".axis-choices label", { hasText: "bg" }).locator("input").click();
  await body.locator(".axis-choices label", { hasText: "text" }).locator("input").click();
  await addNamed(s, body.locator("button", { hasText: "Make switchable…" }), "dark");
  let doc = await written(s, base);
  assert.match(doc.text, /^theme:\n  schemes:\n    dark:\n      colors:\n        bg: "#000000"\n        text: "#FFFFFF"\n\nconfig:\n  style:\n    default: dark\n    choices:\n      dark:\n        scheme: dark$/m, diffLines(base.text, doc.text).join(" ; "));
  assert.doesNotMatch(doc.text, /^    bg: "#000000"$/m, "bg stayed in the palette");
  assert.deepEqual(doc.globals.schemes, { names: ["dark"], roles: ["bg", "text"], colors: { dark: { bg: "#000000", text: "#FFFFFF" } } });
  assert.equal(doc.history.undo, "make bg, text switchable, in the scheme dark");

  // + Scheme: a copy of the first, and a style picking it
  await addNamed(s, body.locator("button", { hasText: "+ Scheme" }), "light");
  doc = await written(s, doc);
  assert.match(doc.text, /^    light: \{ colors: \{ bg: "#000000", text: "#FFFFFF" \} \}$/m);
  assert.match(doc.text, /^      light: \{ scheme: light \}$/m);
  // the table: light's bg through the picker (roles are not offered for a scheme's colour)
  const table = body.locator("table.schemes");
  assert.deepEqual(await table.locator("tr").first().locator("th .name").allTextContents(), ["dark", "light"]);
  await table.locator("tr").nth(1).locator("td").nth(2).locator("button.chip-button").click();
  assert.equal(await s.page.locator(".popover-body.pop .pop-roles").count(), 0);
  await s.page.locator(".popover-body.pop .pop-swatches button[aria-label=cool]").click();
  doc = await written(s, doc);
  // a reference written into a flow mapping is quoted
  assert.match(doc.text, /^    light: \{ colors: \{ bg: "?color\.cool"?, text: "#FFFFFF" \} \}$/m);
  // + Role: in every scheme, white
  await addNamed(s, body.locator("button", { hasText: "+ Role" }), "line");
  doc = await written(s, doc);
  assert.match(doc.text, /        text: "#FFFFFF"\n        line: "#FFFFFF"\n    light: \{ colors: \{ bg: "?color\.cool"?, text: "#FFFFFF", line: "#FFFFFF" \} \}/);
  // rename a role: every color.<role> follows
  await renameInline(s, table.locator("tr").nth(2).locator("td").first().locator(".name"), "ink");
  doc = await written(s, doc);
  assert.equal(doc.text.match(/color\.ink\b/g)?.length, 2, "the two color.text users did not follow");
  assert.doesNotMatch(doc.text, /color\.text\b/);
  assert.match(doc.text, /light: \{ colors: \{ bg: "?color\.cool"?, ink: "#FFFFFF", line: "#FFFFFF" \} \}/);
  // rename a scheme: the style naming it follows
  await renameInline(s, table.locator("tr").first().locator("th").nth(1).locator(".name"), "midnight");
  doc = await written(s, doc);
  assert.match(doc.text, /      dark:\n        scheme: midnight/);
  // a used role cannot be deleted; an unused one and a scheme (with its style) can
  const t = Date.now();
  await table.locator("tr").nth(1).locator("td").first().locator("button.reset").click();
  assert.match(await s.waitToast(t, /bg/), /^color\.bg is used by \d+ keys?: point them at another colour first$/);
  await table.locator("tr").nth(3).locator("td").first().locator("button.reset").click();
  doc = await written(s, doc);
  assert.doesNotMatch(doc.text, /^\s+line: /m);
  await table.locator("tr").first().locator("th").nth(2).locator("button.reset").click();
  doc = await written(s, doc);
  assert.doesNotMatch(doc.text, /light/);
  assert.deepEqual(doc.globals.styles.entries.map((e) => e.name), ["dark"]);
  // Remove schemes…: the kept scheme's colours become palette colours
  await body.locator("button", { hasText: "Remove schemes…" }).click();
  await s.page.locator(".modal .ask", { hasText: "Every role becomes a palette colour with midnight's value." }).waitFor();
  await s.page.locator(".modal-foot button.primary").click();
  doc = await written(s, doc);
  assert.doesNotMatch(doc.text, /theme:|schemes:|style:/);
  assert.match(doc.text, /^    bg: "#000000"\n    ink: "#FFFFFF"$/m);
  assert.equal(doc.text.match(/color\.ink/g)?.length, 2);
  assert.deepEqual(s.errors, []);
});

h.test("Styles: the starting style, label, layout and scheme, + Style, delete, and + Layout on a scheme-only face", async (s) => {
  await s.openExample("features/styles");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();
  await s.faceSection("Styles");
  // the matrix: one row per style, in the order the wearer's list shows
  const rows = s.page.locator(".face-section-body table.styles-matrix tr").filter({ has: s.page.locator("td") });
  assert.deepEqual(await rows.locator("td:first-child code").allTextContents(), ["big_dark", "big_light", "compact_dark"]);
  await s.page.locator("input[aria-label='open in compact_dark']").click();
  let doc = await written(s, base);
  assert.match(doc.text, /^    default: compact_dark$/m);
  const label = s.page.locator("input[aria-label='label of compact_dark']");
  await label.fill("Small");
  await label.press("Enter");
  doc = await written(s, doc);
  assert.match(doc.text, /compact_dark: \{ label: "Small", layout: compact, scheme: dark \}/, diffLines(base.text, doc.text).join(" ; "));
  await s.page.locator("select[aria-label='layout of compact_dark']").selectOption("big");
  doc = await written(s, doc);
  assert.match(doc.text, /compact_dark: \{ label: "Small", layout: big, scheme: dark \}/);
  await s.page.locator("select[aria-label='scheme of compact_dark']").selectOption("light");
  doc = await written(s, doc);
  assert.match(doc.text, /compact_dark: \{ label: "Small", layout: big, scheme: light \}/);
  // + Style is shaped like the others; × deletes it
  await addNamed(s, s.page.locator(".face-section-body button", { hasText: "+ Style" }), "compact_light");
  doc = await written(s, doc);
  assert.match(doc.text, /^      compact_light: \{ layout: (big|compact), scheme: (dark|light) \}$/m, diffLines(base.text, doc.text).join(" ; "));
  assert.equal(await rows.count(), 4);
  await s.page.locator("button[aria-label='delete style compact_light']").click();
  doc = await written(s, doc);
  assert.doesNotMatch(doc.text, /compact_light/);
  assert.deepEqual(await s.page.locator(".controls label", { hasText: "Style" }).locator("select option").allTextContents(), ["default", "Big · Dark", "Big · Light", "Small"]);
  for (let i = 0; i < 6; i++) doc = await s.undo();
  assert.equal(doc.text, base.text, diffLines(base.text, doc.text).join(" ; "));

  // + Layout on a face whose styles name only schemes: every style picks the new layout, as one change
  const themed = await s.openTemplate("themed", "Scheme only");
  await s.waitFace();
  await s.waitIdle();
  await s.faceSection("Styles");
  assert.deepEqual(themed.globals.layouts, []);
  await addNamed(s, s.page.locator(".face-section-body button", { hasText: "+ Layout" }), "alt");
  doc = await written(s, themed);
  assert.match(doc.text, /^layouts:\n  alt: \{\}$/m, diffLines(themed.text, doc.text).join(" ; "));
  assert.match(doc.text, /      dark: \{ scheme: dark, layout: alt \}\n      light: \{ scheme: light, layout: alt \}/);
  assert.equal(doc.history.undo, "add the layout alt, picked by dark, light");
  assert.equal(doc.loads, true, doc.diagnostics.filter((d) => d.severity === "error").map((d) => d.message).join("; "));
  assert.deepEqual(doc.globals.layouts, ["alt"]);
  // listed in Layers too, with nothing in it yet
  await s.leftTab("Layers");
  assert.ok((await s.page.locator(".layers .block").allTextContents()).some((b) => /alt/.test(b)), "the layout's blocks are not in Layers");
  await undoTo(s, themed, "+ Layout");
  assert.deepEqual(s.errors, []);
});

h.test("Hand sets: a preset added and placed, duplicated, renamed, deleted; a placed set's deletion refused", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();
  await s.faceSection("Hand sets");
  const body = s.page.locator(".face-section-body");
  await body.locator("select").selectOption("baton");
  await addNamed(s, body.locator("button", { hasText: "+ Hand set" }), "baton");
  let doc = await written(s, base);
  assert.match(doc.text, /^  hand_sets:\n    baton:\n      hour:\n        color: color\.\w+\n        parts:\n/m, diffLines(base.text, doc.text).join(" ; "));
  assert.match(doc.text, /^  new_hands:\n    type: hands\n    at:\n      anchor: center\n    set: baton$/m, "a face with no hands yet also places the set");
  assert.equal(doc.history.undo, "add the hand set baton (baton), placed at the centre");
  assert.deepEqual(doc.globals.hands.map((hs) => [hs.name, hs.placed_by]), [["baton", ["new_hands"]]]);
  await body.locator("li.hand-set img.hand-thumb").waitFor({ state: "visible", timeout: 15_000 });
  // placed: × is refused, naming the element
  const t = Date.now();
  await body.locator("li.hand-set button.reset").click();
  assert.equal(await s.waitToast(t, /baton/), "new_hands places the hand set baton: delete it or point them at another set first");
  // Duplicate: a copy, placed by nothing
  await body.locator("li.hand-set button", { hasText: "Duplicate" }).click();
  doc = await written(s, doc);
  assert.deepEqual(doc.globals.hands.map((hs) => [hs.name, hs.placed_by]), [["baton", ["new_hands"]], ["baton_copy", []]]);
  // rename: the element's set: follows
  await renameInline(s, body.locator("li.hand-set").first().locator(".name"), "sticks");
  doc = await written(s, doc);
  assert.match(doc.text, /    set: sticks\n/);
  assert.match(doc.text, /^    sticks:\n/m);
  // the copy, placed by nothing, deletes
  await body.locator("li.hand-set").nth(1).locator("button.reset").click();
  doc = await written(s, doc);
  assert.doesNotMatch(doc.text, /baton_copy/);
  // Edit in YAML selects the set's lines
  await body.locator("li.hand-set a", { hasText: "Edit in YAML" }).click();
  await s.page.waitForSelector(".cm-editor");
  assert.match((await s.yamlState()).selected, /^    sticks:\n/);
  // a hand set's thumbnail is a blob URL the page revokes when the set changes under it; an image
  // still loading then logs a resource error, which is not an error of the face or the editor
  assert.deepEqual(s.errors.filter((e) => !/ERR_FILE_NOT_FOUND/.test(e)), []);
});

h.test("Slots: + Slot, choices, the star, an icon, any type, the menu title, rename; deleting a drawn slot refused", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();
  await s.faceSection("Slots");
  const body = s.page.locator(".face-section-body");
  await body.locator("select").first().selectOption("steps");
  await addNamed(s, body.locator("button", { hasText: "+ Slot" }), "steps");
  let doc = await written(s, base);
  assert.match(doc.text, /^config:\n  slots:\n    steps:\n      default: steps\n      choices: any$/m, diffLines(base.text, doc.text).join(" ; "));
  assert.match(doc.text, /^  new_data:\n    type: data\n    at:\n      anchor: center\n    slot: steps\n    color: color\.\w+$/m, "no data element draws the new slot");
  assert.equal(doc.history.undo, "add the slot steps, showing Steps, and draw it");
  const card = body.locator(".slot-card").first();
  assert.deepEqual(await card.locator(".slot-line a").allTextContents(), ["new_data"]);

  // any type is on; off again, the list starts with what the slot shows
  const anyBox = card.locator("label.slot-line input[type=checkbox]");
  assert.equal(await anyBox.isChecked(), true);
  await anyBox.click();
  doc = await written(s, doc);
  assert.match(doc.text, /      choices: \[steps\]$/m);
  // tick a type; star another (which joins the list); pick an icon for one
  const row = (type: string) => card.locator(".slot-type").filter({ hasText: type });
  await row("Heart rate").locator("input[type=checkbox]").click();
  doc = await written(s, doc);
  assert.match(doc.text, /      choices: \[steps, heart_rate\]$/m);
  await row("Calories").locator("button.star").click();
  doc = await written(s, doc);
  await s.waitIdle();
  doc = await s.doc();
  assert.match(doc.text, /    steps:\n      default: calories\n      choices: \[steps, heart_rate, calories\]$/m, diffLines(base.text, doc.text).join(" ; "));
  await s.page.waitForFunction(() => {
    const rowEl = [...document.querySelectorAll(".slot-card .slot-type")].find((r) => /Calories/.test(r.textContent!));
    return rowEl !== undefined && (rowEl.querySelector("input[type=checkbox]") as HTMLInputElement).disabled;
  }, null, { timeout: 8000 });
  await row("Heart rate").locator("button.chip-button").click();
  await s.page.locator(".popover-body.pop button", { hasText: "none" }).click();
  doc = await written(s, doc);
  assert.match(doc.text, /      choices: \[steps, \{ type: heart_rate, icon: none \}, calories\]$/m);
  // any type again, and back: the list returns
  await anyBox.click();
  doc = await written(s, doc);
  assert.match(doc.text, /      choices: any$/m);
  await anyBox.click();
  doc = await written(s, doc);
  assert.match(doc.text, /      choices: \[steps, \{ type: heart_rate, icon: none \}, calories\]$/m, "unticking any did not bring the list back");
  // the menu title
  const title = card.locator(".slot-line", { hasText: "menu title" }).locator("input");
  await title.fill("Steps today");
  await title.press("Enter");
  doc = await written(s, doc);
  assert.match(doc.text, /^      label: Steps today$/m);
  // rename: the element's slot: follows
  await renameInline(s, card.locator(".slot-head .name"), "walking");
  doc = await written(s, doc);
  assert.match(doc.text, /^    walking:\n      default: calories/m);
  assert.match(doc.text, /    slot: walking\n/);
  // × while an element draws it is refused
  const t = Date.now();
  await card.locator(".slot-head button.reset").click();
  assert.equal(await s.waitToast(t, /walking/), "new_data draws the slot walking: delete it or point them at another slot first");
  assert.equal((await s.doc()).text, doc.text);
  // the same card above the data element's keys
  await s.selectLayer("new_data");
  assert.equal(await s.page.locator(".inspector .slot-card .slot-head .name").textContent(), "walking");
  assert.deepEqual(s.errors, []);
});

h.test("Fonts: a font added from a file, its size, replaced and deleted; a used font and a non-font file refused", async (s) => {
  await s.openExample("features/shapes");
  await s.waitFace();
  await s.waitIdle();
  const base = await s.doc();
  await s.faceSection("Fonts");
  const body = s.page.locator(".face-section-body");
  assert.equal(await body.locator("li.font").count(), 0);
  const inputs = body.locator("input[type=file]");

  // a file that is not a font is refused before anything is stored
  await inputs.first().setInputFiles({ name: "notafont.ttf", mimeType: "font/ttf", buffer: Buffer.from(base.text) });
  let name = body.locator(".add-name input.inline-name");
  assert.equal(await name.inputValue(), "notafont");
  let t = Date.now();
  await name.press("Enter");
  assert.equal(await s.waitToast(t, /notafont/), "notafont.ttf is not a TrueType or OpenType font file");
  let doc = await s.doc();
  assert.equal(doc.text, base.text);
  assert.deepEqual(doc.assets, []);

  // a real font: declared at 10%r, its file in assets/
  await inputs.first().setInputFiles(join(EXAMPLES, "showcase", "assets", "ChivoMono-Bold.ttf"));
  name = body.locator(".add-name input.inline-name");
  assert.equal(await name.inputValue(), "chivomono_bold");
  await name.fill("mono");
  await name.press("Enter");
  doc = await written(s, base);
  assert.match(doc.text, /^  fonts: \{ mono: \{ source: assets\/ChivoMono-Bold\.ttf, size: 10%r \} \}$/m, diffLines(base.text, doc.text).join(" ; "));
  assert.equal(doc.history.undo, "add the font mono from assets/ChivoMono-Bold.ttf");
  assert.deepEqual(doc.assets, ["assets/ChivoMono-Bold.ttf"]);
  // its size
  const size = body.locator("li.font .qty input");
  await size.fill("12");
  await size.press("Enter");
  doc = await written(s, doc);
  assert.match(doc.text, /size: 12%r \} \}$/m);
  // used by a text: deletion refused
  await s.selectLayer("label");
  await s.topField("font").locator("select").selectOption("font.mono");
  doc = await written(s, doc);
  assert.match(doc.text, /    font: font\.mono\n/);
  await s.waitFace();
  await s.faceSection("Fonts");
  t = Date.now();
  await body.locator("li.font button.reset").click();
  assert.equal(await s.waitToast(t, /mono/), "the font mono is used by 1 element: label; change them first");
  // Replace… swaps the file under the same name
  await body.locator("li.font button", { hasText: "Replace…" }).click();
  await inputs.nth(1).setInputFiles(join(EXAMPLES, "showcase", "assets", "Dynalight-Regular.ttf"));
  doc = await written(s, doc);
  assert.match(doc.text, /source: assets\/Dynalight-Regular\.ttf, size: 12%r/);
  assert.deepEqual(doc.assets, ["assets/Dynalight-Regular.ttf"]);
  await s.waitFace();
  // unused again, it deletes
  doc = await s.undo();
  doc = await s.undo();
  assert.match(doc.text, /    font: FONT_XTINY\n/);
  await body.locator("li.font button.reset").click();
  doc = await written(s, doc);
  assert.doesNotMatch(doc.text, /fonts:/);
  assert.deepEqual(s.errors, []);
});
