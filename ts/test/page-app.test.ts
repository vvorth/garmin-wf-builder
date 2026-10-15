// The whole page (`app/main.ts`, rendering `app/app.ts`) with preact over the minimal DOM
// against a stand-in worker answering from a real face's summary: the home
// screen and the editor render, and their menus send what the worker
// expects. Nothing is drawn or laid out.
import assert from "node:assert/strict";
import { test } from "node:test";
import { appText, appUri, count, DEFERRED_FETCH, eq, faceFixture, has, instantiate, len, node, page, render, repoText, run, summary, testUri } from "./page-harness.ts";

test("one frame is on its way at a time, and only the newest is shown", async () => {
  const face = faceFixture();
  face.summary.targets = ["fr955"];
  const printed = await page(face, `#/face/${face.summary.id}`, `
      const frames = () => requests.filter(([op]) => op === "frame").map(([, a]) => a.scale);
      // three zoom steps while the first frame is still being drawn
      for (let i = 0; i < 3; i++) { press("=", { ctrlKey: true }); await settle(); }
      out(frames());
      unanswered.shift()({ status: 400, json: { error: "an old frame failed" } });
      await settle(); await settle();
      out([frames(), app.textContent.includes("an old frame failed")]);
    `);
  assert.deepEqual(printed, [[2], [[2, 4], false]]);
});

test("deleting a face asks in the page's own dialog first", async () => {
  const printed = await page(faceFixture(), "#/", `
      const asked = () => app.textContent.includes("Are you sure?");
      await click(button("Delete"));
      out(asked());
      await click(button("Cancel"));
      out([asked(), sent().length]);
      await click(button("Delete"));
      await click(find((e) => e.localName === "button" && cls(e) === "primary" && e.textContent === "Delete")[0]);
      out([asked(), sent().map(([op]) => op)]);
    `);
  assert.deepEqual(printed, [true, [false, 0], [false, ["delete"]]]);
});

test("the library shows each face with its picture and renames it", async () => {
  const face = faceFixture();
  const printed = await page(face, "#/", "\n      const img = find((e) => e.localName === \"img\" && e.parentNode && cls(e.parentNode) === \"cover\")[0];\n      out(img.attributes[\"data-op\"] === \"cover\");\n      await click(button(\"Rename\"));\n      const input = find((e) => e.localName === \"input\" && cls(e).startsWith(\"inline-name\"))[0];\n      out(input.attributes.value);\n      input.value = \"Evening\"; input.dispatch(\"input\", { target: input }); await settle();\n      input.dispatch(\"keydown\", { key: \"Enter\", target: input }); await settle();\n      out(sent().map(([op, a]) => `${op} ${a.name}`));\n    ");
  assert.equal(printed[0], true);
  assert.deepEqual(printed[1], "Morning");
  assert.deepEqual(printed[2], ["rename Evening"]);
});

test("the editor folds its controls away and names what undo takes back", async () => {
  const face = faceFixture();
  const doc = face["summary"];
  const printed = await page(face, `#/face/${doc["id"]}`, "\n      const text = app.textContent;\n      // the toolbar keeps the device and zoom; the rest is behind Preview\n      out([text.includes(\"Device\"), text.includes(\"Zoom\"), text.includes(\"asleep\")]);\n      await click(button(\"Preview\"));\n      out(app.textContent.includes(\"asleep\") && app.textContent.includes(\"AOD\"));\n      out(button(\"↶ Undo\").attributes.title);\n      // the history menu lists the changes and goes to one in one step\n      await click(find((e) => e.localName === \"button\" && e.textContent === \"▾\" && e.attributes.title.startsWith(\"Go back\"))[0]);\n      const states = find((e) => e.localName === \"button\" && cls(e) === \"state\");\n      out(states.map((b) => b.textContent.split(/\\d/)[0].trim()));\n      await click(states[states.length - 1]);\n      out(sent().map(([op, a]) => `${op} ${a.seq}`));\n      // one keyboard listener for the editor's life: Ctrl+Z undoes, an\n      // arrow with nothing selected is the browser's\n      out([(listeners.keydown || []).length, press(\"z\", { ctrlKey: true }), press(\"ArrowLeft\")]);\n      await settle();\n      out(sent().map(([op]) => op));\n      // the error count opens Diagnostics on the errors\n      await click(find((e) => e.localName === \"button\" && cls(e) === \"errors\")[0]);\n      out(app.textContent.includes(\"errors only\"));\n      // the Properties section folds away\n      await click(find((e) => e.localName === \"h3\" && cls(e) === \"fold\")[0]);\n      out(cls(find((e) => cls(e).startsWith(\"panel right\"))[0]));\n    ");
  assert.deepEqual(printed[0], [true, true, false]);
  assert.equal(printed[1], true);
  assert.deepEqual(printed[2], "Undo: edit the text (Ctrl+Z)");
  assert.ok((eq(printed[3][0], "edit the text") && printed[3].at(-1).startsWith("new")));
  const seq = doc["history"]["states"].at(-1)["seq"];
  assert.deepEqual(printed[4], [`goto ${seq}`]);
  const [_, undo_prevented, arrow_prevented] = printed[5];
  assert.ok((undo_prevented === true && arrow_prevented === false));
  assert.deepEqual(printed[6], ["goto", "undo"]);
  assert.equal(printed[7], true);
  assert.ok(has(printed[8], "props-folded"));
});

test("an answer for a face left behind never replaces the face opened", async () => {
  const face = faceFixture();
  const doc = face["summary"];
  const printed = await page(face, `#/face/${doc["id"]}`, (DEFERRED_FETCH + "\n      const other = { ...summary, id: \"b\".repeat(32), name: \"Evening\", version: 1 };\n      answers[`get ${other.id}`] = other;\n      press(\"z\", { ctrlKey: true }); await settle();        // face A's undo, on its way\n      location.hash = `#/face/${other.id}`;\n      for (const f of listeners.hashchange || []) f();\n      await settle(); await settle();\n      const name = () => find((e) => cls(e).startsWith(\"name renamable\"))[0].textContent;\n      out(name());\n      await release(0);                                     // A's answer arrives late\n      out(name());\n      // the next change is aimed at B's version, not A's\n      press(\"z\", { ctrlKey: true }); await settle();\n      out(sent().map(([op, a]) => [a.id, op, a.version]));\n    "));
  assert.deepEqual(printed[0], "Evening");
  assert.deepEqual(printed[1], "Evening");
  assert.deepEqual(printed[2], [[doc["id"], "undo", doc["version"]], ["b".repeat(32), "undo", 1]]);
});

test("a refused change says how many queued behind it were not sent", async () => {
  const face = faceFixture();
  const doc = face["summary"];
  const printed = await page(face, `#/face/${doc["id"]}`, (DEFERRED_FETCH + "\n      press(\"z\", { ctrlKey: true }); press(\"z\", { ctrlKey: true }); press(\"z\", { ctrlKey: true });\n      await settle();\n      await release(0, 400);\n      out(find((e) => cls(e).startsWith(\"toast\"))[0].textContent);\n      out(sent().length);\n    "));
  assert.deepEqual(printed[0], "refused for the test (2 later changes were not sent)");
  assert.deepEqual(printed[1], 1);
});

test("shortcuts group open the list and copy and paste elements as yaml", async () => {
  const face = faceFixture();
  const doc = face["summary"];
  const printed = await page(face, `#/face/${doc["id"]}`, "\n      const structured = [];\n      const serve = respond;\n      respond = (request, reply) => {\n        if (request.op !== \"structure\") return serve(request, reply);\n        structured.push(request.args.edit);\n        reply({ status: 200, json: summary });\n      };\n      const row = (id) => find((e) => cls(e).startsWith(\"item\") && e.textContent.startsWith(id))[0];\n      await click(row(\"clock\"));\n      // Ctrl+G groups the selection, Ctrl+] brings it forward\n      out([press(\"g\", { ctrlKey: true }), press(\"]\", { ctrlKey: true })]);\n      await settle(); await settle();\n      // ? lists the shortcuts; Escape closes the list before it deselects\n      press(\"?\", { shiftKey: true }); await settle();\n      out(app.textContent.includes(\"Keyboard shortcuts\") && app.textContent.includes(\"Ctrl+G\"));\n      press(\"Escape\"); await settle();\n      out(app.textContent.includes(\"Keyboard shortcuts\"));\n      // copy writes the selection's YAML; paste sends what is on the clipboard\n      const clip = {};\n      const event = (data) => ({ target: { closest: () => null }, preventDefault() { this.prevented = true; },\n                                 clipboardData: { setData: (t, v) => { clip[t] = v; }, getData: () => data } });\n      const copy = event(\"\");\n      for (const f of listeners.copy || []) f(copy);\n      out([copy.prevented === true, clip[\"text/plain\"]]);\n      for (const f of listeners.paste || []) f(event(clip[\"text/plain\"]));\n      await settle(); await settle();\n      out(structured);\n    ");
  assert.deepEqual(printed[0], [true, true]);
  assert.ok((printed[1] === true && printed[2] === false));
  const [prevented, text] = printed[3];
  assert.ok((prevented && text.startsWith("clock:\n  type: ")));
  const [group, forward, paste] = printed[4];
  assert.deepEqual(group, {"op": "group", "paths": [["elements", "clock"]]});
  assert.ok((eq(forward["op"], "move") && eq(forward["path"], ["elements", "clock"])));
  assert.ok((eq(paste["op"], "paste") && eq(paste["text"], text) && eq(paste["block"], ["elements"])));
});

test("Ctrl+K finds an element by a substring of its id and selects it, exactly as clicking it would", async () => {
  const face = faceFixture();
  const doc = face["summary"];
  const printed = await page(face, `#/face/${doc["id"]}`, "\n      out(press(\"k\", { ctrlKey: true }));\n      await settle();\n      out(app.textContent.includes(\"Jump to\"));\n      const input = find((e) => e.localName === \"input\" && e.attributes.placeholder && e.attributes.placeholder.includes(\"element\"))[0];\n      input.value = \"seco\"; input.dispatch(\"input\", { target: input }); await settle();\n      input.dispatch(\"keydown\", { key: \"Enter\", target: input }); await settle();\n      out(app.textContent.includes(\"Jump to\"));\n      out(requests.find(([op, args]) => op === \"inspect\" && JSON.stringify(args.element) === JSON.stringify([\"elements\", \"seconds\"])) !== undefined);\n    ");
  assert.equal(printed[0], true);        // the key press was handled, not left to the browser
  assert.equal(printed[1], true);        // the palette opened
  assert.equal(printed[2], false);       // ...and closed once a result was chosen
  assert.equal(printed[3], true);        // the seconds element was selected, as a click on it would be
});

test("Ctrl+K also finds a slot, jumping to its Face-tab section", async () => {
  const text = instantiate("minimal", "T") + "\nconfig:\n  slots:\n    top: { default: steps, choices: any }\n";
  const face = { summary: summary(text), vocabulary: {}, home: { templates: [], store: "this browser", shared: true, documents: [] } };
  const doc = face["summary"];
  const printed = await page(face, `#/face/${doc["id"]}`, "\n      press(\"k\", { ctrlKey: true }); await settle();\n      const input = find((e) => e.localName === \"input\" && e.attributes.placeholder && e.attributes.placeholder.includes(\"element\"))[0];\n      input.value = \"top\"; input.dispatch(\"input\", { target: input }); await settle();\n      input.dispatch(\"keydown\", { key: \"Enter\", target: input }); await settle();\n      out(storage.get(\"wfb-face-section\"));\n      out(find((e) => e.localName === \"button\" && e.textContent.startsWith(\"Face\")).some((b) => cls(b) === \"on\"));\n    ");
  assert.equal(printed[0], "slots");
  assert.equal(printed[1], true);
});

test("renaming an element in Properties, the same way a colour renames, keeps it selected under its new name", async () => {
  const face = faceFixture();
  const doc = face["summary"];
  const printed = await page(face, `#/face/${doc["id"]}`, "\n      answers.inspect = { element: [\"elements\", \"clock\"], id: \"clock\", type: \"text\", context: { frame: \"awake\", style: null }, fields: [], unknown: [], aod_keys: [], overrides: {}, overridden: [], parts: null, device: null, shape: null, display: null, error: null };\n      const serve = respond;\n      respond = (request, reply) => {\n        if (request.op !== \"edit\") return serve(request, reply);\n        requests.push([request.op, request.args]);\n        const renamed = JSON.parse(JSON.stringify(summary));\n        renamed.version = summary.version + 1;\n        const rename = (nodes) => nodes.forEach((n) => { if (n.id === \"clock\") n.id = \"timer\"; rename(n.children || []); });\n        renamed.tree.forEach((b) => rename(b.children || []));\n        reply({ status: 200, json: renamed });\n      };\n      const row = (id) => find((e) => cls(e).startsWith(\"item\") && e.textContent.startsWith(id))[0];\n      await click(row(\"clock\"));\n      await settle();\n      const renamable = find((e) => cls(e) === \"name renamable\");\n      await click(renamable[renamable.length - 1]);\n      await typeName(\"timer\");\n      out(requests.find(([op, args]) => op === \"edit\" && args.edit && args.edit.op === \"rename\"));\n      const again = row(\"timer\");\n      out(again ? cls(again).includes(\"selected\") : false);\n      out(row(\"clock\") === undefined);\n    ");
  assert.deepEqual(printed[0][1].edit, { op: "rename", path: ["elements", "clock"], to: "timer" });
  assert.equal(printed[1], true);
  assert.equal(printed[2], true);
});

test("the preview draws one frame at a time, the one the watch has, and the sample moment resets only the time", async () => {
  const face = faceFixture();
  face.summary.targets = ["fenix847mm", "fr955"];
  const devices = [
    { id: "fenix847mm", name: "fenix847mm", display: "amoled", skin: true, ppi: null },
    { id: "fr955", name: "fr955", display: "mip", skin: true, ppi: null },
  ];
  const printed = await page({ ...face, devices }, `#/face/${face.summary.id}`, `
      const radios = () => find((e) => e.localName === "input" && e.attributes.type === "radio")
        .map((e) => [e.parentNode.textContent.trim(), "checked" in e.attributes, "disabled" in e.attributes]);
      const change = async (e) => { e.dispatch("change", { target: e }); await settle(); };
      const input = (pred) => find((e) => e.localName === "input" && pred(e))[0];
      await click(button("Preview"));
      out(radios());
      // AOD on the AMOLED watch, then skin and a time
      await change(input((e) => e.attributes.type === "radio" && e.parentNode.textContent.trim() === "AOD"));
      const skin = input((e) => e.attributes.type === "checkbox" && e.parentNode.textContent.trim() === "skin");
      skin.type = "checkbox"; skin.checked = true; await change(skin);
      const time = input((e) => e.attributes.type === "time");
      time.value = "08:30:00"; time.dispatch("change", { target: time }); await settle();
      out([radios(), localStorage.getItem("wfb-skin")]);
      await click(button("Back to the sample moment"));
      out([radios().filter(([, on]) => on).map(([label]) => label), skin.checked, time.value, !!button("Back to the sample moment")]);
      // the MIP watch: its asleep frame stands for AOD
      await click(find((e) => e.localName === "button" && e.attributes.title === "fr955")[0]);
      out(radios());
    `);
  assert.deepEqual(printed[0], [["awake", true, false], ["asleep", false, true], ["AOD", false, false]]);
  assert.deepEqual(printed[1], [[["awake", false, false], ["asleep", false, true], ["AOD", true, false]], "1"]);
  assert.deepEqual(printed[2], [["AOD"], true, "", false]);
  assert.deepEqual(printed[3], [["awake", false, false], ["asleep", true, false], ["AOD", false, true]]);
});

test("1:1 is a toggle that stays on from watch to watch until turned off or zoomed away", async () => {
  const face = faceFixture();
  face.summary.targets = ["fenix8solar47mm", "fr955"];
  const devices = [
    { id: "fenix8solar47mm", name: "fenix8solar47mm", display: "mip", skin: false, ppi: 192, width: 260 },
    { id: "fr955", name: "fr955", display: "mip", skin: false, ppi: 96, width: 260 },
  ];
  const printed = await page({ ...face, devices }, `#/face/${face.summary.id}`, `
      const real = () => button("1:1");
      const state = () => [find((e) => e.localName === "span" && cls(e) === "mono" && e.textContent.endsWith("×"))[0].textContent,
                           cls(real())];
      const watch = (id) => click(find((e) => e.localName === "button" && e.attributes.title === id)[0]);
      out(state());
      await click(real()); out(state());
      await watch("fr955"); out(state());
      await click(real()); out(state());
      await click(real()); await watch("fenix8solar47mm"); out(state());
      press("=", { ctrlKey: true }); await settle(); out(state());
    `);
  assert.deepEqual(printed, [["2.00×", ""], ["0.500×", "on"], ["1.00×", "on"], ["2.00×", ""], ["0.500×", "on"], ["0.630×", ""]]);
});

test("a jump switches the section of a Face tab already open", async () => {
  // The Face tab open at Fonts, Ctrl+K picking a style shows Styles: the
  // section is the page's state, not something the tab reads once when it
  // opens.
  const text = instantiate("minimal", "T") + "\ntheme:\n  schemes:\n    dark:\n      colors: { ink: color.text }\n\nconfig:\n  style:\n    default: nightly\n    choices: { nightly: { scheme: dark } }\n";
  const face = { summary: summary(text), vocabulary: {}, home: { templates: [], store: "this browser", shared: true, documents: [] } };
  const printed = await page(face, `#/face/${face.summary.id}`, `
      const nav = () => find((e) => e.localName === "button" && e.parentNode && cls(e.parentNode) === "tabs face-nav");
      const open = () => nav().filter((b) => cls(b) === "on").map((b) => b.textContent.replace(/\\d+$/, ""));
      await click(find((e) => e.localName === "button" && e.textContent === "Face")[0]);
      await click(nav().find((b) => b.textContent.startsWith("Fonts")));
      out(open());
      press("k", { ctrlKey: true }); await settle();
      const input = find((e) => e.localName === "input" && e.attributes.placeholder && e.attributes.placeholder.includes("element"))[0];
      input.value = "nightly"; input.dispatch("input", { target: input }); await settle();
      input.dispatch("keydown", { key: "Enter", target: input }); await settle();
      out([open(), storage.get("wfb-face-section")]);
    `);
  assert.deepEqual(printed[0], ["Fonts"]);
  assert.deepEqual(printed[1], [["Styles"], "styles"]);
});

test("the browser asks before leaving while a change is on its way, and not once it is answered", async () => {
  const face = faceFixture();
  const doc = face["summary"];
  const printed = await page(face, `#/face/${doc["id"]}`, DEFERRED_FETCH + `
      const leave = () => {
        const event = { prevented: false, preventDefault() { this.prevented = true; } };
        for (const f of listeners.beforeunload || []) f(event);
        return event.prevented;
      };
      out(leave());
      press("z", { ctrlKey: true }); await settle();
      out(leave());
      await release(0);
      out(leave());
    `);
  assert.deepEqual(printed, [false, true, false]);
});

test("Escape deselects a row selected in Layers, once any open dialog has closed", async () => {
  // The popovers' bodies are always in the DOM, so a guard that looked for
  // `.popover-body` found one every time and Escape never deselected; only
  // an open one holds Escape back.
  const face = faceFixture();
  const printed = await page(face, `#/face/${face.summary.id}`, `
      const row = (id) => find((e) => cls(e).startsWith("item") && e.textContent.startsWith(id))[0];
      const selected = () => cls(row("clock")).includes("selected");
      await click(row("clock"));
      out(selected());
      press("?", { shiftKey: true }); await settle();
      out([app.textContent.includes("Keyboard shortcuts"), press("Escape")]);
      await settle();
      out([app.textContent.includes("Keyboard shortcuts"), selected()]);
      out(press("Escape"));
      await settle();
      out(selected());
      out(press("Escape"));
    `);
  assert.equal(printed[0], true);
  assert.deepEqual(printed[1], [true, true]);
  assert.deepEqual(printed[2], [false, true], "the first Escape closes the dialog and keeps the selection");
  assert.equal(printed[3], true);
  assert.equal(printed[4], false, "the second deselects");
  assert.equal(printed[5], false, "with nothing selected the key is the browser's");
});

test("Edit for, beside the watch picker, says where a geometry edit lands", async () => {
  const face = faceFixture();
  face.summary.targets = ["fenix847mm", "fr955"];
  const devices = [
    { id: "fenix847mm", name: "fenix847mm", display: "amoled", shape: "round", skin: true, ppi: null },
    { id: "fr955", name: "fr955", display: "mip", shape: "round", skin: true, ppi: null },
  ];
  const printed = await page({ ...face, devices }, `#/face/${face.summary.id}`, `
      const seg = () => find((e) => cls(e).includes("edit-for"))[0];
      const buttons = () => seg().all((e) => e.localName === "button").map((b) => [b.textContent, cls(b), b.attributes.title]);
      out([seg().textContent.startsWith("Edit for"), buttons()]);
      await click(seg().all((e) => e.localName === "button")[3]);
      out(buttons().map(([, on]) => on));
      await click(find((e) => e.localName === "button" && e.attributes.title === "fr955")[0]);
      out(buttons().map(([, , title]) => title));
    `);
  assert.deepEqual(printed[0], [true, [
    ["all watches", "on", "the element's own key, for every watch"],
    ["this watch", "", "an override for fenix847mm only"],
    ["this shape", "", "an override for every round watch"],
    ["this display", "", "an override for every AMOLED watch"],
  ]]);
  assert.deepEqual(printed[1], ["", "", "", "on"]);
  assert.deepEqual(printed[2], ["the element's own key, for every watch", "an override for fr955 only", "an override for every round watch", "an override for every MIP watch"]);
});

test("accept here… on a lint warning asks the reason inline and writes the element's lint: block in one batch, keeping a block it has", async () => {
  const face = faceFixture();
  face.summary = summary(instantiate("minimal", "T").replace("at: { anchor: center, dy: 30%r }", "at: { anchor: center, dx: 300%r }"));
  const printed = await page(face, `#/face/${face.summary.id}`, `
      // the element's lint: as the worker's field tree reads it
      let lint = null;
      const serve = respond;
      respond = (request, reply) => {
        // a batch is taken: the face one version on
        if (request.op === "batch") { requests.push([request.op, request.args]); reply({ status: 200, json: { ...summary, version: request.args.version + 1, select: null } }); return; }
        if (request.op !== "inspect") return serve(request, reply);
        requests.push([request.op, request.args]);
        reply({ status: 200, json: { element: request.args.element, fields: [{ key: "lint", present: lint !== null, value: lint }] } });
      };
      const accepts = () => find((e) => e.localName === "button" && cls(e) === "accept");
      const rows = find((e) => e.localName === "li" && e.parentNode && cls(e.parentNode) === "diags");
      // every warning on the seconds offers it; the graphics-pool note does not
      out(rows.map((li) => [li.childNodes[0].textContent, li.all((e) => cls(e) === "accept").length]));
      await click(accepts()[0]);
      const reason = () => find((e) => e.localName === "input" && cls(e) === "reason")[0];
      const acceptButton = () => find((e) => e.localName === "button" && e.textContent === "Accept")[0];
      // asked for: the reason, empty while the element has none, and nothing sent without one; clicking it selected nothing
      out([reason().attributes.value ?? reason().value, "disabled" in acceptButton().attributes || acceptButton().disabled === true,
           requests.filter(([op]) => op === "inspect").map(([, a]) => a.element), find((e) => cls(e) === "accept-form").length]);
      const input = reason();
      input.value = "a seconds readout left off the dial on purpose"; input.dispatch("input", { target: input }); await settle();
      input.dispatch("keydown", { key: "Enter", target: input }); await settle();
      out(sent());
      // an element with a lint: block already: the code joins its list, and the reason it has is offered and kept
      lint = { allow: ["text-overflow"], reason: "the readout is two digits" };
      await click(accepts()[0]);
      out(reason().value ?? reason().attributes.value);
      await click(acceptButton());
      out(sent().slice(1));
      // Escape or x keeps the warning: nothing sent
      await click(accepts()[0]);
      reason().dispatch("keydown", { key: "Escape", target: reason(), stopPropagation() {} }); await settle();
      out([find((e) => cls(e) === "accept-form").length, sent().length]);
    `);
  const element = ["elements", "seconds"];
  assert.ok(printed[0].length > 1);
  for (const [severity, n] of printed[0]) assert.equal(n, severity === "warning" ? 1 : 0, severity);
  // one row asks, even where two rows say the same thing (one per target)
  assert.deepEqual(printed[1], ["", true, [element], 1]);
  assert.deepEqual(printed[2], [["batch", { label: "accept off-screen on seconds", id: face.summary.id, version: face.summary.version,
    edits: [{ op: "set", path: [...element, "lint"], value: { allow: ["off-screen"], reason: "a seconds readout left off the dial on purpose" } }] }]]);
  assert.equal(printed[3], "the readout is two digits");
  assert.deepEqual(printed[4], [["batch", { label: "accept off-screen on seconds", id: face.summary.id, version: face.summary.version + 1,
    edits: [{ op: "insert_item", path: [...element, "lint", "allow"], at: 1, value: "off-screen" }] }]]);
  assert.deepEqual(printed[5], [0, 2]);
});
