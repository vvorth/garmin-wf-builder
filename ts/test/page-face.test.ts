// The Face tab's sections over the face as a whole (Face, Target devices,
// Defaults, Layouts, the Styles matrix) and the reorder controls on its
// lists, rendered from a real face's summary over the minimal DOM
// (`studio_dom.mjs`): each control sends the edit the worker expects, with
// the exact path and position. Nothing is drawn or laid out.
import assert from "node:assert/strict";
import { test } from "node:test";
import { appUri, htmPreactUri, instantiate, node, preactUri, render, repoText, summary, testUri } from "./page-harness.ts";

/**
 * The Face panel rendered over `summary` with `vocab` and `onEdit` (a
 * JavaScript expression for the callback, which may answer a refusal), then
 * `body` run with the harness's helpers (`root`, `find`, `click`, `settle`,
 * `openSection`, `typeName`, `out`, `edits`): what it printed.
 */
async function renderFace(summary: unknown, { vocab = {}, onEdit = "(op) => edits.push(op)" }: { vocab?: unknown; onEdit?: string }, body: string): Promise<any[]> {
  const script = `
      import { install } from ${JSON.stringify(testUri("studio_dom.mjs"))};
      const document = install();
      const { html } = await import(${JSON.stringify(htmPreactUri)});
      const { render } = await import(${JSON.stringify(preactUri)});
      const { FacePanel } = await import(${JSON.stringify(appUri("panels.ts"))});
      const edits = [];
      const root = document.createElement("div");
      render(html\`<\${FacePanel} doc=\${${JSON.stringify(summary)}} vocab=\${${JSON.stringify(vocab)}}
        onEdit=\${${onEdit}} onSelect=\${(id) => edits.push({select: id})}
        onUpload=\${() => {}} onStructure=\${() => {}}
        onReveal=\${(line, end) => edits.push({reveal: [line, end]})} />\`, root);
      const cls = (e) => e.attributes.class || "";
      const find = (pred) => root.all(pred);
      const settle = async () => { for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0)); };
      const click = async (e) => { e.click(); await settle(); };
      const openSection = async (title) => { await click(find((e) => e.localName === "button" && e.textContent.startsWith(title))[0]); };
      const typeName = async (value) => {
        const inputs = find((e) => e.localName === "input" && cls(e).startsWith("inline-name"));
        const input = inputs[inputs.length - 1];
        input.value = value; input.dispatch("input", { target: input }); await settle();
        input.dispatch("keydown", { key: "Enter", target: input }); await settle();
      };
      const out = (v) => console.log(JSON.stringify(v));
      ${body}
    `;
  const done = node(script);
  if (done.returncode !== 0) throw new Error(done.stderr.slice(-2000));
  return done.stdout.split("\n").filter((l) => l !== "").map((l) => JSON.parse(l));
}

// The helpers a body uses on the controls: the button with an aria-label,
// a text typed into an input and committed by leaving it, a select changed.
const CONTROLS = `
      const labelled = (label) => find((e) => e.localName === "button" && e.attributes["aria-label"] === label)[0];
      const press = async (label) => { const b = labelled(label); if (!b) throw new Error("no button " + label); await click(b); };
      const disabled = (label) => { const b = labelled(label); return "disabled" in b.attributes || b.disabled === true; };
      const type = async (input, value) => { input.value = value; input.dispatch("blur", { target: input }); await settle(); };
      const choose = async (select, value) => { select.value = value; select.dispatch("change", { target: select }); await settle(); };
      const input = (label) => find((e) => e.localName === "input" && e.attributes["aria-label"] === label)[0];
      const select = (label) => find((e) => e.localName === "select" && e.attributes["aria-label"] === label)[0];
`;

// Two layouts, two schemes and three styles: the fixture the Layouts and Styles sections are tested on.
const STYLED = instantiate("minimal", "T").replace("elements:\n  clock:", "layouts:\n  digital:\n    static:\n      frame: { type: rectangle, at: { anchor: center }, size: { width: 90%, height: 90% }, color: color.dim }\n    elements:\n      big: { type: text, text: \"{time.clock:%H:%M}\", font: FONT_NUMBER_HOT, at: { anchor: center }, color: color.text }\n      small: { type: text, text: \"{time.second:02d}\", font: FONT_SMALL, at: { anchor: center, dy: 30%r }, color: color.dim }\n  analog:\n    elements:\n      pin: { type: circle, at: { anchor: center }, radius: 3%r, color: color.text }\n\ntheme:\n  schemes:\n    dark:\n      colors: { ink: color.text }\n    light:\n      colors: { ink: color.bg }\n\nconfig:\n  style:\n    default: d\n    choices:\n      d: { layout: digital, scheme: dark, label: Digital }\n      a: { layout: analog, scheme: dark }\n      l: { layout: digital, scheme: light }\n\nelements:\n  clock:");

test("the Face section comes first and commits the name, version and id", async () => {
  const text = summary(instantiate("minimal", "T"));
  const printed = await renderFace(text, {}, CONTROLS + `
      const nav = find((e) => e.localName === "button" && e.parentNode && cls(e.parentNode) === "tabs face-nav");
      out(nav.map((b) => b.textContent.replace(/\\d+$/, "")).slice(0, 2));
      await openSection("Face");
      out([input("face name").attributes.value, input("face version").attributes.value, input("face id").attributes.value.length]);
      await type(input("face name"), "Tea");
      await type(input("face version"), "1.1.0");
      await type(input("face id"), "not-a-uuid");                       // not sent: the watch needs a UUID
      await type(input("face id"), "0f8fad5b-d9cb-469f-a165-70867728950e");
      await type(input("face name"), "   ");                            // not sent: a name is required
      out(edits);
      out(root.textContent.includes("different app"));
    `);
  assert.deepEqual(printed[0], ["Face", "Target devices"]);
  assert.deepEqual(printed[1], ["T", "1.0.0", 36]);
  assert.deepEqual(printed[2], [
    { op: "set", path: ["face", "name"], value: "Tea" },
    { op: "set", path: ["face", "version"], value: "1.1.0" },
    { op: "set", path: ["face", "id"], value: "0f8fad5b-d9cb-469f-a165-70867728950e" },
  ]);
  assert.equal(printed[3], true, "the id's row says what changing it does");
});

test("the targets reorder, go and come as list items", async () => {
  const text = summary(instantiate("minimal", "T"));
  const devices = ["fenix8solar47mm", "fenix8solar51mm", "fr955", "fenix847mm"].map((id) => ({ id, name: id, shape: "round", size: "260x260", width: 260, height: 260, ppi: null, skin: false, display: "mip", fonts: [] }));
  const printed = await renderFace(text, { vocab: { devices } }, CONTROLS + `
      await openSection("Target devices");
      out([disabled("move fenix8solar47mm up"), disabled("move fr955 down"), disabled("move fenix8solar51mm up")]);
      await press("move fenix8solar51mm up");
      await press("move fenix8solar47mm down");
      await press("remove fr955");
      const add = select("add a target");
      out(add.all((e) => e.localName === "option").map((o) => o.attributes.value));
      await choose(add, "fenix847mm");
      out(edits);
    `);
  assert.deepEqual(printed[0], [true, true, false], "the first cannot move up, nor the last down");
  assert.deepEqual(printed[1], ["", "fenix847mm"], "only a watch not yet a target is offered");
  assert.deepEqual(printed[2], [
    { op: "move_item", path: ["build", "targets"], from: 1, to: 0 },
    { op: "move_item", path: ["build", "targets"], from: 0, to: 1 },
    { op: "remove_item", path: ["build", "targets"], at: 2 },
    { op: "insert_item", path: ["build", "targets"], at: 3, value: "fenix847mm" },
  ]);
});

test("the Defaults section shows an absent key greyed with its schema default, and writes set and remove", async () => {
  const rows = `
      const rows = () => find((e) => e.localName === "li" && e.parentNode && cls(e.parentNode).includes("defaults"));
      const absent = () => rows().map((r) => cls(r).includes("absent"));
      const shownDefaults = () => rows().map((r) => { const s = r.all((e) => e.localName === "select")[0];
        return s ? s.all((e) => e.localName === "option" && e.attributes.value === "").map((o) => o.textContent)[0] : r.all((e) => e.localName === "input")[0].attributes.placeholder; });
      const resets = () => rows().flatMap((r) => r.all((e) => e.localName === "button" && cls(e) === "reset")).length;
  `;
  let printed = await renderFace(summary(instantiate("minimal", "T")), {}, CONTROLS + rows + `
      await openSection("Defaults");
      out(rows().map((r) => r.all((e) => cls(e) === "key")[0].textContent));
      out([absent(), shownDefaults(), resets()]);
      await choose(select("antialias"), "true");
      await type(input("aod.dim"), "0.5");
      await type(input("aod.dim"), "1.5");                               // not sent: dim is 0 to 1
      await choose(select("aod.mask"), "false");
      out(edits);
    `);
  assert.deepEqual(printed[0], ["antialias", "min_1px", "aod.visible", "aod.dim", "aod.mask"]);
  assert.deepEqual(printed[1], [[true, true, true, true, true], ["default (false)", "default (false)", "default (false)", "1", "default (true)"], 0]);
  assert.deepEqual(printed[2], [
    { op: "set", path: ["defaults", "antialias"], value: true },
    { op: "set", path: ["defaults", "aod", "dim"], value: 0.5 },
    { op: "set", path: ["defaults", "aod", "mask"], value: false },
  ]);
  const written = summary(instantiate("minimal", "T").replace("\nbuild:", "\ndefaults:\n  antialias: true\n  aod: { visible: true, dim: 0.4 }\n\nbuild:"));
  printed = await renderFace(written, {}, CONTROLS + rows + `
      await openSection("Defaults");
      out([absent(), resets(), input("aod.dim").attributes.value]);
      await press("remove aod.visible");
      await choose(select("antialias"), "");                             // back to the default: the key goes
      out(edits);
    `);
  assert.deepEqual(printed[0], [[false, true, false, false, true], 3, "0.4"]);
  assert.deepEqual(printed[1], [
    { op: "remove", path: ["defaults", "aod", "visible"] },
    { op: "remove", path: ["defaults", "antialias"] },
  ]);
});

test("the Layouts section counts each layout's elements and styles, renames, reorders and deletes", async () => {
  const doc = summary(STYLED);
  assert.deepEqual(doc.globals.layout_entries.map((l: any) => [l.name, l.elements, l.static, l.styles]), [["digital", 2, 1, ["d", "l"]], ["analog", 1, 0, ["a"]]]);
  const printed = await renderFace(doc, {}, CONTROLS + `
      await openSection("Layouts");
      const rows = find((e) => e.localName === "li" && cls(e).includes("layout"));
      out(rows.map((r) => r.all((e) => cls(e).split(" ").includes("counts"))[0].textContent));
      out(rows.map((r) => r.all((e) => cls(e) === "picked-by")[0].textContent));
      out([disabled("move digital up"), disabled("move analog down")]);
      await click(find((e) => cls(e) === "name renamable" && e.textContent === "analog")[0]);
      await typeName("round");
      await press("move digital down");
      await press("move analog up");
      await press("delete analog");
      out(edits);
      out(find((e) => e.localName === "select" && e.attributes["aria-label"] === "style to start in instead").length);
    `);
  assert.deepEqual(printed[0], ["2 elements · 1 static", "1 element · 0 static"]);
  assert.deepEqual(printed[1], ["styles d, l", "style a"]);
  assert.deepEqual(printed[2], [true, true]);
  assert.deepEqual(printed[3], [
    { op: "rename_layout", name: "analog", to: "round" },
    { op: "move_key", path: ["layouts", "digital"], to: 1 },
    { op: "move_key", path: ["layouts", "analog"], to: 0 },
    { op: "delete_layout", name: "analog" },
  ]);
  assert.equal(printed[4], 0, "a delete the worker took asks nothing more");
});

test("deleting the default style's layout, once refused, offers the style to start in instead and resends with also_default", async () => {
  const doc = summary(STYLED);
  // the worker refuses the delete while the default style picks the layout: `null`, as the store answers a refusal
  const onEdit = `(op) => { edits.push(op); return Promise.resolve(op.op === "delete_layout" && !op.also_default ? null : {}); }`;
  const printed = await renderFace(doc, { onEdit }, CONTROLS + `
      await openSection("Layouts");
      await press("delete digital");
      const pick = select("style to start in instead");
      out(pick ? pick.all((e) => e.localName === "option").map((o) => o.attributes.value) : null);
      out(root.textContent.includes("the default style d picks it"));
      await choose(pick, "a");
      out(edits);
      out(find((e) => e.localName === "select" && e.attributes["aria-label"] === "style to start in instead").length);
    `);
  assert.deepEqual(printed[0], ["", "a"], "only a style that stays is offered");
  assert.equal(printed[1], true);
  assert.deepEqual(printed[2], [
    { op: "delete_layout", name: "digital" },
    { op: "delete_layout", name: "digital", also_default: "a" },
  ]);
  assert.equal(printed[3], 0, "the offer goes once taken");
});

test("the Styles matrix lists the entries in order, picks their layout and scheme, stars the default and reorders", async () => {
  const doc = summary(STYLED);
  const printed = await renderFace(doc, {}, CONTROLS + `
      await openSection("Styles");
      const table = find((e) => e.localName === "table" && cls(e) === "styles-matrix")[0];
      const rows = table.all((e) => e.localName === "tr" && e.all((c) => c.localName === "td").length > 0);
      out(rows.map((r) => r.all((e) => e.localName === "code")[0].textContent));
      out(rows.map((r) => r.all((e) => e.localName === "select").map((s) => s.value ?? s.attributes.value)));
      out(rows.map((r) => r.all((e) => e.localName === "input" && e.attributes.type === "radio")[0]).map((i) => "checked" in i.attributes || i.checked === true));
      rows[1].all((e) => e.localName === "input" && e.attributes.type === "radio")[0].dispatch("change");
      await settle();
      await choose(rows[1].all((e) => e.localName === "select")[0], "digital");
      await choose(rows[0].all((e) => e.localName === "select")[1], "light");
      await choose(rows[2].all((e) => e.localName === "select")[1], "");
      out([disabled("move style d up"), disabled("move style l down"), disabled("move style a up")]);
      await press("move style l up");
      await press("move style d down");
      await press("delete style a");
      out(edits);
    `);
  assert.deepEqual(printed[0], ["d", "a", "l"]);
  assert.deepEqual(printed[1], [["digital", "dark"], ["analog", "dark"], ["digital", "light"]]);
  assert.deepEqual(printed[2], [true, false, false]);
  assert.deepEqual(printed[3], [true, true, false]);
  assert.deepEqual(printed[4], [
    { op: "set_default_style", name: "a" },
    { op: "set", path: ["config", "style", "choices", "a", "layout"], value: "digital" },
    { op: "set", path: ["config", "style", "choices", "d", "scheme"], value: "light" },
    { op: "remove", path: ["config", "style", "choices", "l", "scheme"] },
    { op: "move_key", path: ["config", "style", "choices", "l"], to: 1 },
    { op: "move_key", path: ["config", "style", "choices", "d"], to: 1 },
    { op: "remove", path: ["config", "style", "choices", "a"] },
  ]);
});

test("palette colours and a slot's choices reorder with move_key and move_item", async () => {
  let printed = await renderFace(summary(instantiate("minimal", "T")), {}, CONTROLS + `
      await openSection("Colours");
      out([disabled("move bg up"), disabled("move dim down")]);
      await press("move text up");
      await press("move bg down");
      out(edits);
    `);
  assert.deepEqual(printed[0], [true, true]);
  assert.deepEqual(printed[1], [
    { op: "move_key", path: ["resources", "palette", "text"], to: 0 },
    { op: "move_key", path: ["resources", "palette", "bg"], to: 1 },
  ]);
  const doc = summary(repoText("examples/features/slot-gauge/face.yaml"));
  const slot = doc.globals.slots[0];
  const [first, second] = slot.choices.map((c: any) => c.type);
  printed = await renderFace(doc, {}, CONTROLS + `
      await openSection("Slots");
      const order = find((e) => cls(e) === "choice-order")[0];
      out(order.all((e) => e.localName === "li").map((li) => li.childNodes[0].textContent));
      await press(${JSON.stringify(`move ${second} up`)});
      await press(${JSON.stringify(`move ${first} down`)});
      out(edits);
    `);
  assert.deepEqual(printed[0], slot.choices.map((c: any) => c.type), "the choices in the order the wearer's list shows");
  assert.deepEqual(printed[1], [
    { op: "move_item", path: ["config", "slots", slot.name, "choices"], from: 1, to: 0 },
    { op: "move_item", path: ["config", "slots", slot.name, "choices"], from: 0, to: 1 },
  ]);
});

test("the new sections link to their guide chapters", async () => {
  const text = summary(instantiate("minimal", "T"));
  const printed = await render(text, `
      const fetched = [];
      globalThis.fetch = (url) => { fetched.push(url); return Promise.resolve({ ok: false, text: async () => "" }); };
      for (const title of ["Face", "Defaults", "Layouts"]) {
        await openSection(title);
        await click(find((e) => cls(e) === "face-section-guide")[0]);
        await settle();
        const close = find((e) => e.localName === "button" && e.attributes["aria-label"] === "Close")[0];
        if (close) await click(close);
      }
      out(fetched);
    `);
  assert.deepEqual(printed[0], ["/help/docs/guide/design-file.md", "/help/docs/guide/design-file.md", "/help/docs/guide/styles-and-layouts.md"]);
});

test("a layout's label is typed in its row, set and removed, and names it in the Styles matrix", async () => {
  const labelled = STYLED.replace("  analog:\n    elements:", "  analog:\n    label: Round dial\n    elements:");
  const doc = summary(labelled);
  const printed = await renderFace(doc, {}, CONTROLS + `
      await openSection("Layouts");
      out([input("label of digital").attributes.value, input("label of analog").attributes.value]);
      await type(input("label of digital"), " Big clock ");
      await type(input("label of analog"), "");
      out(edits.splice(0));
      await openSection("Styles");
      out(select("layout of a").all((e) => e.localName === "option").map((o) => o.textContent));
    `);
  assert.deepEqual(printed[0], ["", "Round dial"]);
  assert.deepEqual(printed[1], [
    { op: "set", path: ["layouts", "digital", "label"], value: "Big clock" },
    { op: "remove", path: ["layouts", "analog", "label"] },
  ]);
  assert.deepEqual(printed[2], ["no layout", "digital", "Round dial (analog)"]);
});

test("a scheme's base is a select over the other schemes, and the roles it inherits are greyed from it until one is set", async () => {
  const text = instantiate("minimal", "T") + "\ntheme:\n  schemes:\n    dark:\n      colors: { ink: color.text, paper: color.bg }\n    light:\n      base: dark\n      colors: { ink: color.bg }\n\nconfig:\n  style:\n    default: d\n    choices: { d: { scheme: dark }, l: { scheme: light } }\n";
  const doc = summary(text);
  assert.deepEqual([doc.globals.schemes.base, doc.globals.schemes.inherited], [{ dark: null, light: "dark" }, { dark: [], light: ["paper"] }]);
  const printed = await renderFace(doc, {}, CONTROLS + `
      await openSection("Colour schemes");
      out([select("base of dark").value ?? select("base of dark").attributes.value, select("base of light").attributes.value,
           select("base of light").all((e) => e.localName === "option").map((o) => o.textContent)]);
      const cells = find((e) => e.localName === "td" && e.all((c) => cls(c).includes("chip-button")).length > 0);
      out(cells.map((c) => [cls(c), c.textContent.replace(/\\s+/g, " ").trim()]));
      // an inherited cell's pick sets the role on this scheme; ↺ inherits an own one again
      const inherited = cells.find((c) => cls(c) === "inherited");
      await click(inherited.all((e) => cls(e).includes("chip-button"))[0]);
      await click(inherited.all((e) => cls(e).includes("swatch") && cls(e.parentNode) === "pop-swatches")[0]);
      await press("inherit ink from dark");
      await choose(select("base of light"), "");
      await choose(select("base of dark"), "light");
      out(edits);
    `);
  assert.deepEqual(printed[0], ["", "dark", ["no base", "base: dark"]]);
  assert.deepEqual(printed[1], [["", "text"], ["", "bg↺"], ["", "bg"], ["inherited", "bgfrom dark"]]);
  assert.deepEqual(printed[2], [
    { op: "use_color", path: ["theme", "schemes", "light", "colors", "paper"], value: "color.bg" },
    { op: "remove", path: ["theme", "schemes", "light", "colors", "ink"] },
    { op: "remove", path: ["theme", "schemes", "light", "base"] },
    { op: "set", path: ["theme", "schemes", "dark", "base"], value: "light" },
  ]);
});
