// The page's panels rendered with preact over a minimal DOM
// (`studio_dom.mjs`): each renders from a real face's summary, and its
// controls send the edits the worker expects. Nothing is drawn or laid out.
import assert from "node:assert/strict";
import { test } from "node:test";
import { appText, appUri, count, DEFERRED_FETCH, eq, faceFixture, has, htmPreactUri, instantiate, len, node, page, preactUri, render, repoText, run, summary, testUri } from "./page-harness.ts";
import { inspect } from "../src/studio/inspect.ts";
import { plain } from "../src/studio/json.ts";
import { installAssets } from "../src/node.ts";
import { db } from "./studio-client.ts";

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
      const { Layers } = await import(${JSON.stringify(appUri("layers.js"))});
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
      const { Layers } = await import(${JSON.stringify(appUri("layers.js"))});
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
      const { Diagnostics, diagnosticsLabel } = await import(${JSON.stringify(appUri("diagnostics.js"))});
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
  const script = `
      import { install } from ${JSON.stringify(testUri("studio_dom.mjs"))};
      const document = install();
      const focused = [];
      // Preact creates every element through createElementNS
      const makeNS = document.createElementNS;
      document.createElementNS = (ns, n) => { const e = makeNS(ns, n); e.focus = () => focused.push(e.attributes.placeholder ?? ""); return e; };
      const inspected = ${JSON.stringify(inspected)};
      // the worker, answering inspect from the payloads above
      globalThis.Worker = class {
        postMessage({ id, request }) {
          const { op, args } = request;
          const json = op === "inspect" ? inspected[args.element[args.element.length - 1]] : {};
          setTimeout(() => this.onmessage({ data: { id, response: { status: 200, json } } }), 0);
        }
      };
      const { html } = await import(${JSON.stringify(htmPreactUri)});
      const { render } = await import(${JSON.stringify(preactUri)});
      const { Inspector } = await import(${JSON.stringify(appUri("panels.js"))});
      const edits = [];
      const root = document.createElement("div");
      // quiet: a few timer turns, counted in turns so a loaded machine waits as long as it needs
      const settle = async () => { for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0)); };
      const cls = (e) => e.attributes.class || "";
      const show = async (id) => {
        render(html\`<\${Inspector} doc=\${${JSON.stringify(doc)}} element=\${{ path: ["elements", id] }} device="" vocab=\${{}}
          scope="all" onScope=\${() => {}} onEdit=\${(op) => { edits.push(op); return Promise.resolve(true); }}
          onError=\${(e) => { throw e; }} onReveal=\${() => {}} onSelect=\${() => {}} />\`, root);
        await settle(); await settle();
      };
      // the number box and unit select of the field named \`key\`
      const qty = (key) => {
        const field = root.all((e) => cls(e).startsWith("field") && e.childNodes[0] && e.childNodes[0].textContent === key)[0];
        const box = field.all((e) => e.localName === "input")[0];
        const select = field.all((e) => e.localName === "select")[0];
        return { box, select, units: select.all((e) => e.localName === "option").map((o) => o.textContent) };
      };
      const pick = async (q, unit) => { q.select.value = unit; q.select.dispatch("change", { target: q.select }); await settle(); };
      const type = async (q, text) => { q.box.value = text; q.box.dispatch("input", { target: q.box }); q.box.dispatch("blur", { target: q.box }); await settle(); };
      const out = (v) => console.log(JSON.stringify(v));

      await show("ring");
      await pick(qty("sweep"), "turn");
      out(edits.splice(0));
      await show("bar");
      out(qty("dx").units);
      let dx = qty("dx");
      await pick(dx, "px");
      dx = qty("dx");
      out([edits.length, dx.box.attributes.value ?? "", dx.box.attributes.placeholder, focused.splice(0)]);
      await type(dx, "-80");
      out(edits.splice(0));
      await show("clock");
      out(qty("dx").units);
    `;
  const done = node(script);
  assert.deepEqual(done.returncode, 0, done.stderr.slice(-1500));
  const [turned, barUnits, cleared, typed, clockUnits] = done.stdout.split("\n").filter(Boolean).map((l) => JSON.parse(l));
  assert.deepEqual(turned, [{ op: "set", element: ["elements", "ring"], path: ["sweep"], scope: "all", device: null, value: "1turn" }]);
  assert.deepEqual(barUnits, ["px", "%", "%r"], "a rectangle has no font for pt to measure against");
  assert.deepEqual(cleared, [0, "", "-50", ["-50"]], "nothing written; the old number is the placeholder of the focused, empty box");
  assert.deepEqual(typed, [{ op: "set", element: ["elements", "bar"], path: ["at", "dx"], scope: "all", device: null, value: "-80px" }]);
  assert.deepEqual(clockUnits, ["px", "%", "%r", "pt"]);
});

test("the scope buttons offer the display class as a fourth override, and a key overridden there says so", async () => {
  const text = instantiate("minimal", "T").replace("targets: [fenix8solar47mm]", "targets: [fenix847mm, fr955]").replace("    at: { anchor: center }\n    color: color.text\n",
    '    at: { anchor: center }\n    color: color.text\n    overrides: { "display:amoled": { at: { dy: 2px } } }\n');
  const doc = summary(text);
  installAssets();
  const inspected: Record<string, unknown> = {};
  for (const id of ["fenix847mm", "fr955"]) inspected[id] = plain(inspect(text, ["elements", "clock"], db.get(id)));
  const script = `
      import { install } from ${JSON.stringify(testUri("studio_dom.mjs"))};
      const document = install();
      const inspected = ${JSON.stringify(inspected)};
      // the worker, answering inspect for the device asked about
      globalThis.Worker = class {
        postMessage({ id, request }) {
          const { op, args } = request;
          const json = op === "inspect" ? inspected[args.device] : {};
          setTimeout(() => this.onmessage({ data: { id, response: { status: 200, json } } }), 0);
        }
      };
      const { html } = await import(${JSON.stringify(htmPreactUri)});
      const { render } = await import(${JSON.stringify(preactUri)});
      const { Inspector } = await import(${JSON.stringify(appUri("panels.js"))});
      const scopes = [];
      const root = document.createElement("div");
      // quiet: a few timer turns, counted in turns so a loaded machine waits as long as it needs
      const settle = async () => { for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0)); };
      const cls = (e) => e.attributes.class || "";
      const show = async (device, scope) => {
        render(html\`<\${Inspector} doc=\${${JSON.stringify(doc)}} element=\${{ path: ["elements", "clock"] }} device=\${device} vocab=\${{ devices: [] }}
          scope=\${scope} onScope=\${(s) => scopes.push(s)} onEdit=\${() => Promise.resolve(true)}
          onError=\${(e) => { throw e; }} onReveal=\${() => {}} onSelect=\${() => {}} />\`, root);
        await settle(); await settle();
      };
      const buttons = () => root.all((e) => cls(e) === "scope")[0].all((e) => e.localName === "button");
      const out = (v) => console.log(JSON.stringify(v));

      await show("fenix847mm", "all");
      out(buttons().map((b) => [b.textContent, b.attributes.title]));
      buttons()[3].dispatch("click"); await settle();
      out(scopes.splice(0));
      out(root.all((e) => cls(e) === "note").map((n) => n.textContent));
      await show("fr955", "all");
      out(buttons().map((b) => b.textContent));
      out(root.all((e) => cls(e) === "note").map((n) => n.textContent));
    `;
  const done = node(script);
  assert.deepEqual(done.returncode, 0, done.stderr.slice(-1500));
  const [amoledButtons, picked, amoledNotes, mipButtons, mipNotes] = done.stdout.split("\n").filter(Boolean).map((l) => JSON.parse(l));
  assert.deepEqual(amoledButtons, [
    ["all targets", "the element's own key, for every target"],
    ["fenix847mm", "an override for fenix847mm only"],
    ["round screens", "an override for every round watch"],
    ["AMOLED screens", "an override for every AMOLED watch"],
  ]);
  assert.deepEqual(picked, ["display"]);
  assert.deepEqual(amoledNotes, ["overridden on this display class"]);
  assert.deepEqual(mipButtons, ["all targets", "fr955", "round screens", "MIP screens"]);
  assert.deepEqual(mipNotes, []);
});
