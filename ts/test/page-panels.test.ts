// The page's panels rendered with preact over a minimal DOM
// (`studio_dom.mjs`): each renders from a real face's summary, and its
// controls send the edits the worker expects. Nothing is drawn or laid out.
import assert from "node:assert/strict";
import { test } from "node:test";
import { appText, appUri, count, DEFERRED_FETCH, eq, faceFixture, has, htmPreactUri, instantiate, len, node, page, preactUri, render, repoText, run, summary, testUri } from "./page-harness.ts";
import { inspect } from "../src/studio/inspect.ts";
import { plain } from "../src/studio/json.ts";
import { installAssets } from "../src/node.ts";
import { db, newStudio } from "./studio-client.ts";
import { bundle } from "../src/studio/bundle.ts";

test("the colours say who uses them and a pick changes the swatch", async () => {
  const text = summary(instantiate("minimal", "T"));
  const printed = await render(text, "\n      await openSection(\"Colours\");\n      out(root.textContent.includes(\"used by background\"));\n      const chips = find((e) => cls(e).includes(\"chip-button\"));\n      out(chips.map((c) => c.textContent));\n      await click(chips[0]);                                  // bg's own picker\n      const grid = find((e) => cls(e).includes(\"swatch\") && e.parentNode && cls(e.parentNode) === \"pop-grid\");\n      out(grid.length);\n      out(find((e) => cls(e) === \"pop-title\").map((t) => t.textContent));\n      await click(grid[1]);                                   // shalimar, #FFFFAA\n      out(edits);\n    ");
  assert.equal(printed[0], true);
  assert.deepEqual(printed[1], ["#000000", "#FFFFFF", "#AAAAAA", "+ Colour"]);
  assert.deepEqual(printed[2], 64);
  assert.deepEqual(printed[3], ["MIP 64", "Custom"]);
  assert.deepEqual(printed[4], [{"op": "set_swatch", "name": "bg", "value": "#FFFFAA"}]);
});

test("every Face-tab section offers an unintrusive link to its guide chapter", async () => {
  const text = summary(instantiate("minimal", "T"));
  const printed = await render(text, "\n      const fetched = [];\n      globalThis.fetch = (url) => { fetched.push(url); return Promise.resolve({ ok: false, text: async () => \"\" }); };\n      const opened = [];\n      for (const title of [\"Target devices\", \"Colours\", \"Colour settings\", \"Colour schemes\", \"Styles\", \"Hand sets\", \"Slots\", \"Fonts\"]) {\n        await openSection(title);\n        const link = find((e) => cls(e) === \"face-section-guide\")[0];\n        await click(link);\n        await settle();\n        opened.push(find((e) => e.localName === \"strong\" && e.textContent === \"Help\").length > 0);\n        const close = find((e) => e.localName === \"button\" && e.attributes[\"aria-label\"] === \"Close\")[0];\n        if (close) await click(close);\n      }\n      out(opened);\n      out(fetched);\n    ");
  assert.deepEqual(printed[0], [true, true, true, true, true, true, true, true]);
  assert.deepEqual(printed[1], [
    "/help/docs/guide/getting-started.md", "/help/docs/guide/colors.md", "/help/docs/guide/configuration.md",
    "/help/docs/guide/colors.md", "/help/docs/guide/styles-and-layouts.md", "/help/docs/guide/analog-hands.md",
    "/help/docs/guide/configuration.md", "/help/docs/guide/fonts.md",
  ]);
});

test("add a colour and an accent setting", async () => {
  const text = summary(instantiate("minimal", "T"));
  const printed = await render(text, "\n      await openSection(\"Colours\");\n      const add = find((e) => cls(e).includes(\"chip-button\") && e.textContent === \"+ Colour\")[0];\n      await click(add);\n      const grid = find((e) => cls(e).includes(\"swatch\") && cls(e.parentNode) === \"pop-grid\");\n      await click(grid[15]);                                  // red\n      await openSection(\"Colour settings\");\n      await click(find((e) => e.localName === \"button\" && e.textContent === \"+ Accent colour\")[0]);\n      out(edits);\n    ");
  assert.deepEqual(printed[0], [{"op": "add_swatch", "value": "#FF0000"}, {"op": "set", "path": ["config", "accent_color"], "value": {"default": "color.bg", "choices": ["color.bg"]}}]);
});

test("an axis lists the palette as ticks and any offers a list", async () => {
  const base = instantiate("minimal", "T");
  const listed = summary((base + "\nconfig:\n  accent_color:\n    default: color.text\n    choices: [color.text, color.dim]\n"));
  let printed = await render(listed, "\n      await openSection(\"Colour settings\");\n      const boxes = find((e) => e.localName === \"input\" && e.attributes.type === \"checkbox\" && within(e, \"axis\"));\n      const on = (b, k) => b[k] === true || k in b.attributes;\n      out(boxes.map((b) => on(b, \"checked\")));\n      out(boxes.map((b) => on(b, \"disabled\")));\n      boxes[0].dispatch(\"change\"); await settle();\n      out(edits);\n    ");
  assert.deepEqual(printed[0], [false, true, true]);
  assert.deepEqual(printed[1], [false, true, false]);
  assert.deepEqual(printed[2], [{"op": "set", "path": ["config", "accent_color", "choices"], "value": ["color.text", "color.dim", "color.bg"]}]);
  const any_ = summary((base + "\nconfig:\n  accent_color:\n    default: color.text\n    choices: any\n"));
  printed = await render(any_, "\n      await openSection(\"Colour settings\");\n      out(root.textContent.includes(\"every colour in the palette\"));\n      await click(find((e) => e.localName === \"button\" && e.textContent === \"Make it a list\")[0]);\n      out(edits);\n    ");
  assert.equal(printed[0], true);
  assert.deepEqual(printed[1], [{"op": "set", "path": ["config", "accent_color", "choices"], "value": ["color.text", "color.bg", "color.dim"]}]);
});

test("a scheme cell picks through use color", async () => {
  const text = summary((instantiate("minimal", "T") + "\ntheme:\n  schemes:\n    dark:\n      colors: { ink: color.text }\n\nconfig:\n  style:\n    default: d\n    choices: { d: { scheme: dark } }\n"));
  const printed = await render(text, "\n      await openSection(\"Colour schemes\");\n      const cell = find((e) => cls(e).includes(\"chip-button\") && e.textContent === \"text\")[0];\n      await click(cell);\n      out(find((e) => cls(e) === \"pop-roles\").length);        // no roles in a scheme's value\n      await click(find((e) => cls(e).includes(\"swatch\") && cls(e.parentNode) === \"pop-swatches\")[2]);\n      out(edits);\n    ");
  assert.deepEqual(printed[0], 0);
  assert.deepEqual(printed[1], [{"op": "use_color", "path": ["theme", "schemes", "dark", "colors", "ink"], "value": "color.dim"}]);
});

test("colours are made switchable from the schemes section", async () => {
  const text = summary(instantiate("minimal", "T"));
  const printed = await render(text, "\n      await openSection(\"Colour schemes\");\n      const boxes = find((e) => e.localName === \"input\" && e.attributes.type === \"checkbox\");\n      boxes[0].dispatch(\"change\"); await settle();           // bg\n      boxes[1].dispatch(\"change\"); await settle();           // text\n      await click(find((e) => e.localName === \"button\" && e.textContent === \"Make switchable…\")[0]);\n      out(find((e) => cls(e).startsWith(\"inline-name\"))[0].attributes.value);   // suggested\n      await typeName(\"night\");\n      out(edits);\n    ");
  assert.deepEqual(printed[0], "dark");
  assert.deepEqual(printed[1], [{"op": "make_switchable", "names": ["bg", "text"], "scheme": "night"}]);
});

test("the schemes table adds renames and removes", async () => {
  const text = summary((instantiate("minimal", "T") + "\ntheme:\n  schemes:\n    dark:\n      colors: { ink: color.text }\n    light:\n      colors: { ink: color.bg }\n\nconfig:\n  style:\n    default: d\n    choices: { d: { scheme: dark }, l: { scheme: light } }\n"));
  const printed = await render(text, "\n      await openSection(\"Colour schemes\");\n      let asked = \"\";\n      globalThis.confirm = (m) => { asked = m; return true; };\n      const button = (label) => find((e) => e.localName === \"button\" && e.textContent === label)[0];\n      const name = (text) => find((e) => cls(e) === \"name renamable\" && e.textContent === text)[0];\n      await click(button(\"+ Scheme\")); await typeName(\"dusk\");\n      await click(button(\"+ Role\")); await typeName(\"hot\");\n      await click(name(\"light\")); await typeName(\"day\");\n      await click(name(\"ink\")); await typeName(\"pen\");\n      // Escape keeps the name, and an invalid one is not sent\n      await click(name(\"dark\"));\n      let input = find((e) => cls(e).startsWith(\"inline-name\"))[0];\n      input.value = \"night\"; input.dispatch(\"keydown\", { key: \"Escape\", target: input }); await settle();\n      input.dispatch(\"blur\", { target: input }); await settle();\n      await click(name(\"dark\")); await typeName(\"2nd\");\n      await click(button(\"Remove schemes…\"));\n      out(edits);\n      out(asked);\n    ");
  assert.deepEqual(printed[0], [{"op": "add_scheme", "name": "dusk"}, {"op": "add_role", "name": "hot", "value": "#FFFFFF"}, {"op": "rename_scheme", "name": "light", "to": "day"}, {"op": "rename_role", "name": "ink", "to": "pen"}, {"op": "remove_theme", "keep": "dark"}]);
  assert.deepEqual(printed[1], "Every role becomes a palette colour with dark's value.\n2 styles naming only a scheme will go.");
});

test("a styles label is set and cleared", async () => {
  const text = summary((instantiate("minimal", "T") + "\ntheme:\n  schemes:\n    dark:\n      colors: { ink: color.text }\n    light:\n      colors: { ink: color.bg }\n\nconfig:\n  style:\n    default: d\n    choices: { d: { scheme: dark, label: Night }, l: { scheme: light } }\n"));
  const printed = await render(text, "\n      await openSection(\"Styles\");\n      const inputs = find((e) => e.localName === \"input\" && e.attributes.placeholder === \"label\");\n      out(inputs.map((i) => i.attributes.value));\n      const type = (input, value) => { input.value = value; input.dispatch(\"blur\", { target: input }); };\n      type(inputs[1], \" Day \"); await settle();\n      type(inputs[0], \"\"); await settle();\n      type(inputs[1], \"\"); await settle();                    // no label to remove: nothing sent\n      out(edits);\n    ");
  assert.deepEqual(printed[0], ["Night", ""]);
  assert.deepEqual(printed[1], [{"op": "set", "path": ["config", "style", "choices", "l", "label"], "value": "Day"}, {"op": "remove", "path": ["config", "style", "choices", "d", "label"]}]);
});

test("+ Layout adds a layout from the Styles section", async () => {
  const text = summary(instantiate("minimal", "T"));
  const printed = await render(text, "\n      await openSection(\"Styles\");\n      await click(find((e) => e.localName === \"button\" && e.textContent.startsWith(\"+ Layout\"))[0]);\n      await typeName(\"layout\");\n      out(edits);\n    ");
  assert.deepEqual(printed[0], [{"op": "add_layout", "name": "layout"}]);
});

test("hand sets are listed added and shown in the yaml", async () => {
  const text = summary(instantiate("analog", "T"));
  const printed = await render(text, "\n      await openSection(\"Hand sets\");\n      const thumb = find((e) => e.localName === \"img\" && cls(e) === \"hand-thumb\")[0];\n      const args = JSON.parse(thumb.attributes[\"data-args\"]);\n      out([args.name, args.device]);\n      out(root.textContent.includes(\"placed by\"));\n      await click(find((e) => e.localName === \"a\" && e.textContent === \"Edit in YAML\")[0]);\n      const select = find((e) => e.localName === \"select\" && e.textContent.startsWith(\"from a preset\"))[0];\n      select.value = \"baton\"; select.dispatch(\"change\", { target: select }); await settle();\n      await click(find((e) => e.localName === \"button\" && e.textContent === \"+ Hand set\")[0]);\n      await typeName(find((e) => cls(e).startsWith(\"inline-name\"))[0].attributes.value);\n      await click(find((e) => e.localName === \"button\" && e.textContent === \"Duplicate\")[0]);\n      out(edits);\n    ");
  assert.deepEqual(printed[0], ["classic", "fenix8solar47mm"]);
  assert.equal(printed[1], true);
  const [reveal, ...rest] = printed[2];
  assert.ok(reveal["reveal"][0] < reveal["reveal"][1]);
  assert.deepEqual(rest, [{"op": "add_hand_set", "name": "baton", "preset": "baton"}, {"op": "duplicate_hand_set", "name": "classic"}]);
});

test("a slot card ticks stars and opens to every type", async () => {
  const text = summary(repoText("examples/features/slot-gauge/face.yaml"));
  const printed = await render(text, "\n      await openSection(\"Slots\");\n      const card = find((e) => cls(e) === \"slot-card\")[0];\n      const row = (label) => card.all((e) => [\"slot-type\", \"slot-type off\"].includes(cls(e))\n                                       && e.textContent.includes(label))[0];\n      const box = (label) => row(label).all((e) => e.localName === \"input\")[0];\n      out([\"Steps\", \"Floors climbed\", \"Heart rate\"].map((l) => \"checked\" in box(l).attributes || box(l).checked === true));\n      box(\"Floors climbed\").dispatch(\"change\"); await settle();\n      await click(row(\"Calories\").all((e) => cls(e).startsWith(\"star\"))[0]);\n      const anyBox = card.all((e) => e.localName === \"input\" && e.parentNode.localName === \"label\")[0];\n      anyBox.dispatch(\"change\"); await settle();\n      out(edits);\n    ");
  assert.deepEqual(printed[0], [true, true, false]);
  const top = ["config", "slots", "top"];
  assert.deepEqual(printed[1], [{"op": "set", "path": [...top, ...["choices"]], "value": ["steps", "intensity_minutes", "battery", "body_battery", "stress"]}, {"op": "set", "path": [...top, ...["choices"]], "value": ["steps", "floors_climbed", "intensity_minutes", "battery", "body_battery", "stress", "calories"]}, {"op": "set", "path": [...top, ...["default"]], "value": "calories"}, {"op": "set", "path": [...top, ...["choices"]], "value": "any"}]);
});

test("a new slot asks what it shows first", async () => {
  const text = summary(instantiate("minimal", "T"));
  const printed = await render(text, "\n      await openSection(\"Slots\");\n      const select = find((e) => e.localName === \"select\" && e.textContent.startsWith(\"a new slot\"))[0];\n      select.value = \"heart_rate\"; select.dispatch(\"change\"); await settle();\n      await click(find((e) => e.localName === \"button\" && e.textContent === \"+ Slot\")[0]);\n      await typeName(find((e) => cls(e).startsWith(\"inline-name\"))[0].attributes.value);\n      out(edits);\n    ");
  assert.deepEqual(printed[0], [{"op": "add_slot", "name": "heart", "default": "heart_rate"}]);
});

test("a drop on the layers moves a row and ignores anything else", async () => {
  // A row dragged onto a block is moved there; text or a file dragged
  // in from elsewhere is ignored, not parsed as a path (it used to throw).
  const doc = summary(instantiate("minimal", "T"));
  const script = `
      import { install } from ${JSON.stringify(testUri("studio_dom.mjs"))};
      const document = install();
      const { html } = await import(${JSON.stringify(htmPreactUri)});
      const { render } = await import(${JSON.stringify(preactUri)});
      const { Layers } = await import(${JSON.stringify(appUri("layers.ts"))});
      const ops = [];
      const root = document.createElement("div");
      render(html\`<\${Layers} doc=\${${JSON.stringify(doc)}} vocab=\${{}} selected=\${null} extra=\${[]}
        drawn=\${null} onSelect=\${() => {}} onStructure=\${(op) => ops.push(op)} />\`, root);
      const cls = (e) => e.attributes.class || "";
      const block = (label) => root.all((e) => cls(e).startsWith("block") && e.textContent.trim() === label)[0];
      const row = root.all((e) => cls(e).startsWith("item") && e.textContent.startsWith("clock"))[0];
      const data = {};
      const transfer = { types: [], setData(t, v) { data[t] = v; this.types.push(t); },
                         getData: (t) => data[t] ?? "" };
      const foreign = { types: ["text/plain", "Files"], getData: (t) => (t === "text/plain" ? "hello" : "") };
      block("static").dispatch("dragover", { dataTransfer: foreign });
      block("static").dispatch("drop", { dataTransfer: foreign });
      row.dispatch("drop", { dataTransfer: foreign });
      const afterForeign = ops.length;
      row.dispatch("dragstart", { dataTransfer: transfer });
      block("static").dispatch("drop", { dataTransfer: transfer });
      console.log(JSON.stringify({ afterForeign, ops }));
    `;
  const done = node(script);
  assert.deepEqual(done.returncode, 0, done.stderr.slice(-1500));
  const result = JSON.parse(done.stdout);
  assert.deepEqual(result["afterForeign"], 0);
  assert.deepEqual(result["ops"], [{"op": "move", "path": ["elements", "clock"], "block": ["static"], "before": null}]);
});

test("the layers list in draw order and down brings forward", async () => {
  const doc = summary(instantiate("minimal", "T"));
  const elements = doc["tree"].find((b: any) => eq(b["label"], "elements"))["children"];
  const first = elements[0]["id"];
  const script = `
      import { install } from ${JSON.stringify(testUri("studio_dom.mjs"))};
      const document = install();
      const { html } = await import(${JSON.stringify(htmPreactUri)});
      const { render } = await import(${JSON.stringify(preactUri)});
      const { Layers } = await import(${JSON.stringify(appUri("layers.ts"))});
      const ops = [];
      const root = document.createElement("div");
      render(html\`<\${Layers} doc=\${${JSON.stringify(doc)}} vocab=\${{}} selected=\${${JSON.stringify(first)}} extra=\${[]}
        drawn=\${null} onSelect=\${() => {}} onStructure=\${(op) => ops.push(op)} />\`, root);
      const cls = (e) => e.attributes.class || "";
      const rows = root.all((e) => cls(e).startsWith("item")).map((e) => e.textContent.trim());
      root.all((e) => e.localName === "button" && e.textContent === "↓")[0].click();
      root.all((e) => e.localName === "button" && e.textContent === "↑")[0].click();
      console.log(JSON.stringify({ rows, ops }));
    `;
  const done = node(script);
  assert.deepEqual(done.returncode, 0, done.stderr.slice(-1500));
  const result = JSON.parse(done.stdout);
  const shown = elements.map((e: any) => e["id"]);
  assert.ok(len(shown) > 1);
  assert.deepEqual(result["rows"].slice(-len(shown)), elements.map((e: any) => (e["id"] + e["type"])));
  assert.deepEqual(result["ops"], [{"op": "move", "path": ["elements", first], "block": ["elements"], "before": (len(shown) > 2 ? shown[2] : null)}]);
});

test("the thumbnails wait for the face to settle", async () => {
  const script = `
      import { install } from ${JSON.stringify(testUri("studio_dom.mjs"))};
      const document = install();
      const { html } = await import(${JSON.stringify(htmPreactUri)});
      const { render } = await import(${JSON.stringify(preactUri)});
      const { Strip, STRIP_SETTLE_MS } = await import(${JSON.stringify(appUri("canvas.ts"))});
      const root = document.createElement("div");
      const doc = (version) => ({ id: "f", version, targets: ["a", "b"] });
      const show = (version, view = {}) => render(html\`<\${Strip} doc=\${doc(version)} view=\${{ device: "a", ...view }}
                                                               picks=\${null} onDevice=\${() => {}} />\`, root);
      const versions = () => root.all((e) => e.localName === "img")
        .map((e) => String(JSON.parse(e.attributes["data-args"]).v));
      const wait = (ms) => new Promise((r) => setTimeout(r, ms));
      const out = [];
      show(1); await wait(5); out.push(versions());
      show(2); await wait(5); show(3); await wait(5); out.push(versions());       // a run of drags
      show(3, { style: "night" }); await wait(5);
      out.push(JSON.parse(root.all((e) => e.localName === "img")[0].attributes["data-args"]).style === "night");
      await wait(STRIP_SETTLE_MS + 100); out.push(versions());
      console.log(JSON.stringify(out));
    `;
  const done = node(script);
  assert.deepEqual(done.returncode, 0, done.stderr.slice(-1500));
  const [first, during, style_now, settled] = JSON.parse(done.stdout);
  assert.deepEqual(first, ["1", "1"]);
  assert.deepEqual(during, ["1", "1"]);
  assert.equal(style_now, true);
  assert.deepEqual(settled, ["3", "3"]);
});

test("the diagnostics filter by severity and the tab counts each", async () => {
  const items = [{"severity": "note", "code": "n", "message": "a note", "notes": [], "line": null}, {"severity": "warning", "code": "w", "message": "first warning", "notes": [], "line": null}, {"severity": "error", "code": "e", "message": "an error", "notes": [], "line": null}, {"severity": "warning", "code": "w", "message": "second warning", "notes": [], "line": null}];
  const script = `
      import { install } from ${JSON.stringify(testUri("studio_dom.mjs"))};
      const document = install();
      const { html } = await import(${JSON.stringify(htmPreactUri)});
      const { render } = await import(${JSON.stringify(preactUri)});
      const { Diagnostics, diagnosticsLabel } = await import(${JSON.stringify(appUri("diagnostics.ts"))});
      const root = document.createElement("div");
      render(html\`<\${Diagnostics} items=\${${JSON.stringify(items)}} tree=\${[]} onSelect=\${() => {}} />\`, root);
      const cls = (e) => e.attributes.class || "";
      const rows = () => root.all((e) => e.localName === "li").map((li) => li.textContent.trim());
      const chips = () => root.all((e) => e.localName === "button").map((b) => b.textContent.trim());
      // quiet: a few timer turns, counted in turns so a loaded machine waits as long as it needs
      const settle = async () => { for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0)); };
      const out = [chips(), rows()];
      root.all((e) => e.localName === "button" && e.textContent.startsWith("warnings"))[0].click();
      await settle();
      out.push(rows());
      const label = (filter) => {
        const host = document.createElement("div");
        render(diagnosticsLabel(${JSON.stringify(items)}, filter), host);
        return host.textContent;
      };
      out.push(label(), label("warning"), label("note"));
      const noNotes = ${JSON.stringify(items.filter((i: any) => !eq(i["severity"], "note")).map((i: any) => i))};
      const host = document.createElement("div");
      render(diagnosticsLabel(noNotes, "note"), host);
      out.push(host.textContent);
      // held by the editor: a chip asks it, and its filter is what shows
      const held = document.createElement("div");
      const asked = [];
      render(html\`<\${Diagnostics} items=\${${JSON.stringify(items)}} tree=\${[]} onSelect=\${() => {}}
                   filter="error" onFilter=\${(f) => asked.push(f)} />\`, held);
      held.all((e) => e.localName === "button" && e.textContent.startsWith("notes"))[0].click();
      await settle();
      out.push(held.all((e) => e.localName === "li").map((li) => li.textContent.trim()), asked);
      console.log(JSON.stringify(out));
    `;
  const done = node(script);
  assert.deepEqual(done.returncode, 0, done.stderr.slice(-1500));
  const [chips, every, warnings, label, warnings_only, notes_only, no_notes, held, asked] = JSON.parse(done.stdout);
  assert.deepEqual(chips, ["all 4", "errors 1", "warnings 2", "notes 1"]);
  assert.deepEqual(every, ["erroran error", "warningfirst warning", "warningsecond warning", "notea note"]);
  assert.deepEqual(warnings, ["warningfirst warning", "warningsecond warning"]);
  assert.deepEqual(label, "Diagnostics ✕ 1⚠ 2ℹ 1");
  assert.deepEqual(warnings_only, "Diagnostics ✕ 1⚠ 2ℹ 1 · warnings only");
  assert.deepEqual(notes_only, "Diagnostics ✕ 1⚠ 2ℹ 1 · notes only");
  assert.deepEqual(no_notes, "Diagnostics ✕ 1⚠ 2", "a filter on an absent severity is not claimed");
  assert.ok((eq(held, ["erroran error"]) && eq(asked, ["note"])));
});

// -- the Properties panel: the generic form over the worker's field tree --

/** `Inspector` rendered over `doc` with the field tree `ins` (the real `inspect()`, as the worker answers), then `body` run with `edits`, `field`, `commit`, `click`, `settle` and `out`: what it printed, one JSON value a line. */
function inspector(doc: unknown, ins: unknown, props: { target?: string; vocab?: unknown } = {}, body = ""): string {
  return `
      import { install } from ${JSON.stringify(testUri("studio_dom.mjs"))};
      const document = install();
      const focused = [];
      // Preact creates every element through createElementNS
      const makeNS = document.createElementNS;
      document.createElementNS = (ns, n) => { const e = makeNS(ns, n); e.focus = () => focused.push(e.attributes.placeholder ?? ""); return e; };
      const { html } = await import(${JSON.stringify(htmPreactUri)});
      const { render } = await import(${JSON.stringify(preactUri)});
      const { Inspector } = await import(${JSON.stringify(appUri("panels.ts"))});
      const edits = [];
      const root = document.createElement("div");
      // quiet: a few timer turns, counted in turns so a loaded machine waits as long as it needs
      const settle = async () => { for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0)); };
      const cls = (e) => e.attributes.class || "";
      const doc = ${JSON.stringify(doc)};
      let ins = ${JSON.stringify(ins)};
      let target = ${JSON.stringify(props.target ?? "all")};
      const show = async () => {
        render(html\`<\${Inspector} doc=\${doc} element=\${{ path: ins.element }} ins=\${ins} target=\${target} vocab=\${${JSON.stringify(props.vocab ?? {})}}
          onEdit=\${(op) => { edits.push(op); return Promise.resolve(true); }} onReveal=\${() => {}} onSelect=\${() => {}} />\`, root);
        await settle(); await settle();
      };
      await show();
      // the field row whose key is \`key\`, among \`within\` (the whole panel by default): the row its name belongs to
      const rowOf = (k) => { let p = k.parentNode; while (p && !cls(p).startsWith("field")) p = p.parentNode; return p; };
      const field = (key, within = root) => within.all((e) => cls(e).startsWith("field") && e.all((k) => cls(k) === "key").some((k) => k.textContent === key && rowOf(k) === e))[0];
      // a box's text: its value once anything set it, else the attribute it was rendered with
      const boxText = (box) => (box.value !== undefined ? box.value : box.attributes.value ?? "");
      const badge = (f) => f.all((e) => cls(e) === "badge").map((e) => e.textContent).join("");
      const notes = (f) => f.all((e) => cls(e) === "note").map((e) => e.textContent);
      const click = async (e) => { e.click(); await settle(); };
      // text typed into the first input (or textarea) of \`f\`, then committed by leaving it
      const commit = async (f, text) => { const box = f.all((e) => e.localName === "input" || e.localName === "textarea")[0];
        box.value = text; box.dispatch("input", { target: box }); box.dispatch("blur", { target: box }); await settle(); };
      const out = (v) => console.log(JSON.stringify(v));
      ${body}
    `;
}

/** `ins` without its descriptions, which the form shows only as titles: the trees travel inside the script's text, which has a size limit. */
function slim<T>(ins: T): T {
  if (Array.isArray(ins)) return ins.map(slim) as T;
  if (ins !== null && typeof ins === "object") return Object.fromEntries(Object.entries(ins).filter(([k]) => k !== "description").map(([k, v]) => [k, slim(v)])) as T;
  return ins;
}

/** What `script` printed, one JSON value a line; it must exit cleanly. */
function printedBy(script: string): any[] {
  const done = node(script);
  if (done.returncode !== 0) throw new Error(done.stderr.slice(-2500));
  return done.stdout.split("\n").filter(Boolean).map((l) => JSON.parse(l));
}

/** `text` opened as the worker opens it, `op` applied through its `Document`: the text after. */
async function applied(text: string, op: Record<string, unknown>): Promise<string> {
  const studio = await newStudio();
  const doc = studio.create(bundle("T", text), "new");
  doc.edit(op, doc.version);
  return doc.text;
}

/** The lines of `before` that `after` changed, as [line number, before, after] (a reorder or a one-line change leaves every other line as it was). */
function changedLines(before: string, after: string): [number, string | undefined, string | undefined][] {
  const a = before.split("\n"), b = after.split("\n");
  const out: [number, string | undefined, string | undefined][] = [];
  for (let i = 0; i < Math.max(a.length, b.length); i++) if (a[i] !== b[i]) out.push([i + 1, a[i], b[i]]);
  return out;
}

const CLOCK = ["elements", "clock"];

test("the icon picker writes a codepoint as {codepoint: \"U+XXXX\"} and shows one written that way", async () => {
  // A codepoint is an object in the format; the picker used to write the bare string, which the gate now refuses.
  const text = instantiate("minimal", "T") + `
  glyph:
    type: icon
    icon: { codepoint: "U+E241" }
    size: 10%r
    at: { anchor: center }
    color: color.dim
`;
  const doc = summary(text);
  installAssets();
  const printed = printedBy(inspector(doc, plain(inspect(text, ["elements", "glyph"], null)), { vocab: { icon_glyphs: { heart: 1 } } }, `
      const icon = field("icon");
      if (!icon) throw new Error("no icon field among " + JSON.stringify(root.all((e) => cls(e) === "key").map((e) => e.textContent)));
      const chip = icon.all((e) => cls(e) === "chip-button")[0];
      out(chip.textContent);
      await click(chip);
      const box = icon.all((e) => e.localName === "input" && cls(e).includes("codepoint"))[0];
      box.value = "U+F0004"; box.dispatch("input", { target: box }); await settle();
      await click(icon.all((e) => e.localName === "button" && e.textContent === "Use")[0]);
      out(edits);
    `));
  assert.equal(printed[0], "U+E241", "a codepoint written as an object shows as its code");
  assert.deepEqual(printed[1], [{ op: "set", element: ["elements", "glyph"], path: ["icon"], scope: "all", device: null, value: { codepoint: "U+F0004" } }]);
});

test("a unit change converts an angle, asks for a length, and offers pt only where a font is in scope", async () => {
  // Switching the unit select used to write the old number in the new
  // unit (`360deg` became `360turn`, `-50%r` became `-50px`). Degrees and
  // turns convert; a length in another unit clears the number box,
  // showing the old value as its placeholder, and writes nothing until a
  // number is typed. `pt` is a font's own unit, so a rectangle is not
  // offered it.
  const text = instantiate("minimal", "T") + `
  bar:
    type: rectangle
    at: { anchor: center, dx: -50%r }
    size: { width: 60%r, height: 3%r }
    color: color.dim

  ring:
    type: arc
    at: { anchor: center }
    radius: 40%r
    thickness: 4px
    start_angle: 0deg
    sweep: 360deg
    color: color.dim
`;
  const doc = summary(text);
  installAssets();
  const inspected: Record<string, unknown> = {};
  for (const id of ["bar", "ring", "clock"]) inspected[id] = plain(inspect(text, ["elements", id], null));
  const printed = printedBy(inspector(doc, inspected["ring"], {}, `
      const inspected = ${JSON.stringify(inspected)};
      // the number box and unit select of the field named \`key\` (a nested one under \`parent\`)
      const qty = (key, parent) => {
        const f = field(key, parent ? field(parent) : root);
        const box = f.all((e) => e.localName === "input")[0];
        const select = f.all((e) => e.localName === "select")[0];
        return { box, select, units: select.all((e) => e.localName === "option").map((o) => o.textContent) };
      };
      const pick = async (q, unit) => { q.select.value = unit; q.select.dispatch("change", { target: q.select }); await settle(); };
      const type = async (q, text) => { q.box.value = text; q.box.dispatch("input", { target: q.box }); q.box.dispatch("blur", { target: q.box }); await settle(); };

      await pick(qty("sweep"), "turn");
      out(edits.splice(0));
      ins = inspected.bar; await show();
      out(qty("dx", "at").units);
      let dx = qty("dx", "at");
      await pick(dx, "px");
      dx = qty("dx", "at");
      out([edits.length, dx.box.attributes.value ?? "", dx.box.attributes.placeholder, focused.splice(0)]);
      await type(dx, "-80");
      out(edits.splice(0));
      ins = inspected.clock; await show();
      out(qty("dx", "at").units);
    `));
  const [turned, barUnits, cleared, typed, clockUnits] = printed;
  assert.deepEqual(turned, [{ op: "set", element: ["elements", "ring"], path: ["sweep"], scope: "all", device: null, value: "1turn" }]);
  assert.deepEqual(barUnits, ["px", "%", "%r"], "a rectangle has no font for pt to measure against");
  assert.deepEqual(cleared, [0, "", "-50", ["-50"]], "nothing written; the old number is the placeholder of the focused, empty box");
  assert.deepEqual(typed, [{ op: "set", element: ["elements", "bar"], path: ["at", "dx"], scope: "all", device: null, value: "-80px" }]);
  assert.deepEqual(clockUnits, ["px", "%", "%r", "pt"]);
});

test("an object is a fieldset whose child writes its nested path, collapsed while empty until + opens it", async () => {
  const text = instantiate("minimal", "T");
  const doc = summary(text);
  installAssets();
  const printed = printedBy(inspector(doc, plain(inspect(text, CLOCK, null)), {}, `
      const at = field("at");
      out([cls(at), at.all((e) => cls(e) === "key").map((e) => e.textContent)]);
      await commit(field("dx", at), "10");
      out(edits.splice(0));
      // an absent, optional object shows its name and a + until opened; a required child is starred once it is
      const curve = field("curve");
      out([cls(curve), curve.all((e) => cls(e) === "key").map((e) => e.textContent), curve.all((e) => e.localName === "select").length]);
      await click(curve.all((e) => e.localName === "button" && e.textContent === "+ curve")[0]);
      out([curve.all((e) => cls(e) === "key").map((e) => e.textContent), curve.all((e) => cls(e) === "req").length, curve.all((e) => e.localName === "select").length > 0]);
      // nothing says the YAML is the place to edit anything
      out(root.textContent.includes("in the YAML"));
      // a scope chooser no longer heads the panel
      out(root.all((e) => cls(e) === "scope").length);
    `));
  assert.deepEqual(printed[0], ["field object", ["at", "anchor", "dx", "dy", "angle", "radius"]]);
  assert.deepEqual(printed[1], [{ op: "set", element: CLOCK, path: ["at", "dx"], scope: "all", device: null, value: "10px" }]);
  assert.deepEqual(printed[2], ["field object absent folded", ["curve"], 0], "an empty optional object is folded");
  assert.deepEqual(printed[3], [["curve", "style", "angle", "radius", "direction"], 2, true]);
  assert.equal(printed[4], false);
  assert.equal(printed[5], 0);
});

test("a list's arrows, × and + add send move_item, remove_item and insert_item, and a move leaves every other line alone", async () => {
  const text = repoText("examples/features/profile/face.yaml");
  const doc = summary(text);
  installAssets();
  const path = ["layouts", "plain", "elements", "tri_plain"];
  const printed = printedBy(inspector(doc, plain(inspect(text, path, null)), {}, `
      const points = field("points");
      const items = points.all((e) => cls(e).startsWith("list-item"));
      out(items.length);
      const control = (item, label) => item.all((e) => e.localName === "button" && e.attributes["aria-label"] === label)[0];
      await click(control(items[1], "move up"));
      await click(control(items[2], "remove"));
      await click(points.all((e) => e.localName === "button" && e.textContent === "+ add")[0]);
      out(edits);
    `));
  assert.equal(printed[0], 3);
  const base = { element: path, scope: "all", device: null };
  assert.deepEqual(printed[1], [
    { op: "move_item", ...base, path: ["points"], from: 1, to: 0 },
    { op: "remove_item", ...base, path: ["points"], at: 2 },
    { op: "insert_item", ...base, path: ["points"], at: 3, value: {} },
  ]);
  // the reorder, through the worker's document: the two lines swap, nothing else moves
  const after = await applied(text, printed[1][0]!);
  const changed = changedLines(text, after);
  assert.deepEqual(changed.map(([line]) => line), [128, 129]);
  assert.deepEqual(changed.map(([, before]) => before), ["          - { anchor: center, dx: 21%, dy: -1% }", "          - { anchor: center, dx: 27%, dy: -9% }"]);
  assert.deepEqual(changed.map(([, , now]) => now), ["          - { anchor: center, dx: 27%, dy: -9% }", "          - { anchor: center, dx: 21%, dy: -1% }"]);
});

test("a choice is a segmented control with the written branch on; switching writes the new branch's seed in one set", async () => {
  const showcase = repoText("examples/showcase/face.yaml");
  const minimal = instantiate("minimal", "T");
  installAssets();
  const register = ["elements", "left_register"];
  const printed = printedBy(inspector(summary(showcase), plain(inspect(showcase, register, null)), {}, `
      const inspected = { minimal: ${JSON.stringify(plain(inspect(minimal, CLOCK, null)))} };
      let absent = field("absent");
      const seg = (f) => f.all((e) => cls(e).startsWith("seg"))[0].all((e) => e.localName === "button").map((b) => [b.textContent, cls(b)]);
      out(seg(absent));
      // the chosen branch's own field renders below: its text, editable
      out([field("text", absent) !== undefined, field("text", absent).all((e) => e.localName === "input")[0].attributes.value]);
      await click(absent.all((e) => cls(e).startsWith("seg"))[0].all((e) => e.localName === "button")[0]);
      out(edits.splice(0));
      // nothing written yet: no branch is on, and nothing renders below until one is picked
      ins = inspected.minimal; await show();
      absent = field("absent");
      out([seg(absent), field("text", absent) === undefined]);
      await click(absent.all((e) => cls(e).startsWith("seg"))[0].all((e) => e.localName === "button")[1]);
      out(edits.splice(0));
    `));
  assert.deepEqual(printed[0], [["hide", ""], ["text", "on"], ["value", ""]]);
  assert.deepEqual(printed[1], [true, "--"]);
  assert.deepEqual(printed[2], [{ op: "set", element: register, path: ["absent"], scope: "all", device: null, value: "hide" }]);
  assert.deepEqual(printed[3], [[["hide", ""], ["text", ""], ["value", ""]], true]);
  assert.deepEqual(printed[4], [{ op: "set", element: CLOCK, path: ["absent"], scope: "all", device: null, value: { text: "" } }]);
  // the switch, through the worker's document: one line changes
  const changed = changedLines(showcase, await applied(showcase, printed[2][0]!));
  assert.deepEqual(changed, [[342, "    absent: {text: \"--\"}", "    absent: hide"]]);
});

test("a scalar key holding a mapping is edited as its YAML in a text box, never sent to the YAML tab", async () => {
  const showcase = repoText("examples/showcase/face.yaml");
  installAssets();
  const path = ["layouts", "digital", "elements", "weather_icon"];
  const printed = printedBy(inspector(summary(showcase), plain(inspect(showcase, path, null)), {}, `
      const icon = field("icon");
      const box = icon.all((e) => e.localName === "textarea")[0];
      out([box ? cls(box) : null, box ? box.attributes.value ?? box.value : null, root.textContent.includes("edit this in the YAML")]);
      await commit(icon, "{for: weather.condition}");
      await commit(icon, "{for: weather.condition");       // not YAML: nothing sent
      out(edits);
    `));
  assert.deepEqual(printed[0], ["mono", "{\"for\": \"weather.condition_today\"}", false]);
  assert.deepEqual(printed[1], [{ op: "set", element: path, path: ["icon"], scope: "all", device: null, value: { for: "weather.condition" } }]);
});

test("in the AOD frame the restyled keys write the aod: block, the others are read-only, and the badge names where a value comes from", async () => {
  const text = repoText("examples/features/aod/face.yaml");
  const doc = summary(text);
  installAssets();
  const aod = { frame: "aod", style: null } as const;
  const device = db.get("fenix847mm");
  const inspected = {
    clock: slim(plain(inspect(text, CLOCK, device, aod))),
    dot: slim(plain(inspect(text, ["elements", "accent_dot"], device, aod))),
    date: slim(plain(inspect(text, ["elements", "info", "children", "date_text"], device, aod))),
  };
  const printed = printedBy(inspector(doc, inspected.clock, {}, `
      const inspected = ${JSON.stringify(inspected)};
      const keys = () => root.all((e) => cls(e).startsWith("field") && e.parentNode === root.all((e) => cls(e) === "inspector")[0]).map((f) => f.all((k) => cls(k) === "key")[0].textContent);
      out(keys());
      const color = field("color");
      out([badge(color), color.all((e) => cls(e) === "value")[0].attributes.title, color.all((e) => cls(e) === "chip-button")[0].textContent]);
      await click(color.all((e) => cls(e) === "chip-button")[0]);
      await click(color.all((e) => cls(e).includes("swatch") && cls(e.parentNode) === "pop-swatches")[2]);   // gray
      await commit(field("text"), "{time.clock:%H.%M}");
      // a key the kind does not restyle in AOD is shown, not edited
      const at = field("at");
      out([cls(at), at.all((e) => e.localName === "input" || e.localName === "select").length, notes(at)]);
      // visible and dim are every kind's, shown even when the block does not write them
      out([boxText(field("visible").all((e) => e.localName === "select")[0]), badge(field("visible")), boxText(field("dim").all((e) => e.localName === "input")[0]), badge(field("dim"))]);
      out(edits.splice(0));
      // the cascade: a face default, a group's block, and no badge where the awake value is read
      ins = inspected.dot; await show();
      out([boxText(field("dim").all((e) => e.localName === "input")[0]), badge(field("dim")), badge(field("filled")), badge(field("color"))]);
      ins = inspected.date; await show();
      out([boxText(field("visible").all((e) => e.localName === "select")[0]), badge(field("visible"))]);
    `));
  assert.ok(!printed[0].includes("aod") && printed[0].includes("dim") && printed[0].includes("visible"), `the aod: block is the frame, not a fieldset: ${printed[0]}`);
  assert.deepEqual(printed[1], ["aod", "writes aod: color on this element", "black"]);
  assert.deepEqual(printed[2], ["field object readonly", 0, ["not restyled in AOD; edit it in the awake frame"]]);
  assert.deepEqual(printed[3], ["true", "aod", "1", "aod"]);
  assert.deepEqual(printed[4], [
    { op: "use_color", element: CLOCK, path: ["color"], scope: "aod", device: "fenix847mm", value: "color.gray" },
    { op: "set", element: CLOCK, path: ["text"], scope: "aod", device: "fenix847mm", value: "{time.clock:%H.%M}" },
  ]);
  assert.deepEqual(printed[5], ["0.6", "defaults", "aod", ""]);
  assert.deepEqual(printed[6], ["false", "from info"]);
  // the colour, through the worker's document: the aod: block's own line, nothing else
  const changed = changedLines(text, await applied(text, printed[4][0]!));
  assert.deepEqual(changed, [[141, "      color: color.black", "      color: color.gray"]]);
});

test("awake, an override the watch reads is shown with its selector, and Edit for decides where a geometry edit lands", async () => {
  const text = instantiate("minimal", "T").replace("targets: [fenix8solar47mm]", "targets: [fenix847mm, fr955]").replace("    at: { anchor: center }\n    color: color.text\n",
    '    at: { anchor: center }\n    color: color.text\n    overrides: { "display:amoled": { at: { anchor: center, dy: 2px } } }\n');
  const doc = summary(text);
  installAssets();
  const inspected: Record<string, unknown> = {};
  for (const id of ["fenix847mm", "fr955"]) inspected[id] = plain(inspect(text, CLOCK, db.get(id)));
  const printed = printedBy(inspector(doc, inspected["fenix847mm"], {}, `
      const inspected = ${JSON.stringify(inspected)};
      const dy = () => field("dy", field("at"));
      const shownDy = () => [boxText(dy().all((e) => e.localName === "input")[0]), badge(dy()), dy().all((e) => cls(e) === "value")[0].attributes.title];
      out(shownDy());
      // Edit for this display: the override itself, whose × removes the override
      target = "display"; await show();
      out(shownDy());
      await commit(dy(), "6");
      await click(dy().all((e) => e.localName === "button" && e.attributes["aria-label"] === "remove the override")[0]);
      // Edit for this shape: no override there yet, so the number box is empty and says what it inherits
      target = "shape"; await show();
      out([shownDy(), notes(field("anchor", field("at")))]);
      // Edit for all watches writes the element's own key, whatever the watch reads
      target = "all"; await show();
      await commit(dy(), "4");
      out(edits.splice(0));
      // a MIP watch reads no override: no badge, plain titles
      ins = inspected.fr955; target = "all"; await show();
      out(shownDy());
    `));
  assert.deepEqual(printed[0], ["2", "display:amoled", "writes at.dy on this element, for every watch; fenix847mm reads its display:amoled override"]);
  assert.deepEqual(printed[1], ["2", "display:amoled", "writes the display:amoled override's at.dy"]);
  assert.deepEqual(printed[2], [["", "", "writes the shape:round override's at.dy"], ["inherits \"center\""]]);
  assert.deepEqual(printed[3], [
    { op: "set", element: CLOCK, path: ["at", "dy"], scope: "display", device: "fenix847mm", value: "6px" },
    // the override replaces at: whole, so × on its dy removes the override's at
    { op: "remove", element: CLOCK, path: ["at"], scope: "display", device: "fenix847mm" },
    { op: "set", element: CLOCK, path: ["at", "dy"], scope: "all", device: "fenix847mm", value: "4px" },
  ]);
  assert.deepEqual(printed[4], ["", "", ""]);
});
