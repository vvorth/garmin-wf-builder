// The whole page (`app/app.js`) rendered with preact over the minimal DOM
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
