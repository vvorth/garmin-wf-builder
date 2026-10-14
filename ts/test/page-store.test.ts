// The editor's store (`app/store.ts`) run in Node against the stand-in
// worker of `page-harness.ts`: the selection, the outbox's order and its
// refusals, the frame's "newest wins", the YAML tab's debounced save, the
// preferences this browser keeps, and a face's editor-only state.
import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFERRED_FETCH, faceFixture, store } from "./page-harness.ts";

/** A frame as the worker would answer it, with nothing drawn. */
const FRAME_OF = `
      const frameOf = (a) => ({ version: summary.version, device: a.device, scale: a.scale, width: 260, height: 260, shape: "round",
                                minor_radius: 130, frame: "", items: [], layers: [], tiles: { data: "", index: {} } });
      const frames = () => requests.filter(([op]) => op === "frame").map(([, a]) => a.scale);
`;

test("the store selects alone, toggles with Ctrl, ranges with Shift and deselects", async () => {
  const face = faceFixture();
  const printed = await store(face, `
      const s = new EditorStore(summary.id);
      await settle();
      const ids = summary.tree.flatMap((b) => b.children.map((n) => n.id));
      out(ids.length >= 3);
      s.select(ids[0]); out(s.state.selection);
      s.select(ids[1], true); out(s.state.selection);
      s.select(ids[1], true); out(s.state.selection);
      s.select(ids[2], "range"); out(s.state.selection);
      const before = s.state.selection;
      s.deselect(); out([s.state.selection, s.state.selection === before]);
      s.select(ids[1]); s.select(ids[1]); out(s.state.selection);
      s.dispose();
      console.log(JSON.stringify(ids));
    `);
  const ids = printed[printed.length - 1];
  assert.equal(printed[0], true);
  assert.deepEqual(printed[1], { primary: ids[0], extra: [] });
  assert.deepEqual(printed[2], { primary: ids[0], extra: [ids[1]] });
  assert.deepEqual(printed[3], { primary: ids[0], extra: [] });
  assert.deepEqual(printed[4], { primary: ids[0], extra: [ids[1], ids[2]] });
  assert.deepEqual(printed[5], [{ primary: null, extra: [] }, false]);
  assert.deepEqual(printed[6], { primary: ids[1], extra: [] });
});

test("an edit queued while a drag is on its way is sent after it, against the version the drag produced", async () => {
  const face = faceFixture();
  face.summary.targets = ["fenix8solar47mm"];
  const printed = await store(face, DEFERRED_FETCH + `
      const s = new EditorStore(summary.id);
      await settle();
      const gesture = { kind: "move", part: "both", dx: 1, dy: 0 };
      const shown = { item: { id: "clock", box: [0, 0, 10, 10], center: [5, 5], handles: [] }, moving: new Set(["clock"]), preview: gesture };
      s.drag(["clock"], gesture, shown);
      const edited = s.edit({ op: "set", path: ["face", "version"], value: "2.0.0" });
      await settle();
      out([sent().map(([op, a]) => [op, a.version, a.element, a.device]), s.state.pending.queue.map((e) => e.state)]);
      await release(0);
      out([sent().map(([op, a]) => [op, a.version]), s.state.pending.queue.map((e) => e.state)]);
      await release(1);
      const answer = await edited;
      out([answer.version, s.state.doc.version, s.state.pending.queue.map((e) => [e.state, e.done])]);
      // the frame asked before the drag is dropped (a newer ask waits); the frame of the drag's version retires it
      unanswered.shift()({ status: 200, json: frameOf({ device: summary.targets[0], scale: 2 }) });
      await settle();
      out([s.state.frame.current, s.state.pending.queue.length]);
      unanswered.shift()({ status: 200, json: { ...frameOf({ device: summary.targets[0], scale: 2 }), version: summary.version + 1 } });
      await settle();
      out([s.state.frame.current.version, s.state.pending.queue.length]);
      s.dispose();
    `.replace("const s = new EditorStore", FRAME_OF + "const s = new EditorStore"));
  const v = face.summary.version;
  assert.deepEqual(printed[0], [[["drag", v, "clock", face.summary.targets[0]]], ["sent", "queued"]]);
  assert.deepEqual(printed[1], [[["drag", v], ["edit", v + 1]], ["done", "sent"]]);
  assert.deepEqual(printed[2], [v + 1, v + 1, [["done", v + 1]]]);
  assert.deepEqual(printed[3], [null, 1]);
  assert.deepEqual(printed[4], [v + 1, 0]);
});

test("a refused change drops what was queued behind it and says how many", async () => {
  const face = faceFixture();
  const printed = await store(face, DEFERRED_FETCH + `
      const s = new EditorStore(summary.id);
      await settle();
      const answers3 = [s.undo(), s.undo(), s.undo()];
      await settle();
      out(sent().length);
      await release(0, 400);
      out([s.state.messages.log.map((m) => [m.kind, m.message]), s.state.messages.unseen, sent().length, s.state.pending.queue.length]);
      out(await Promise.all(answers3));
      // the next change is aimed at the version the face still has
      s.redo(); await settle();
      out(sent().map(([op, a]) => [op, a.version]));
      s.dispose();
    `);
  const v = face.summary.version;
  assert.equal(printed[0], 1);
  assert.deepEqual(printed[1], [[["error", "refused for the test (2 later changes were not sent)"]], 1, 1, 0]);
  assert.deepEqual(printed[2], [null, null, null]);
  assert.deepEqual(printed[3], [["undo", v], ["redo", v]]);
});

test("one frame is on its way at a time, a newer ask replaces the one waiting, and the context changes the ask", async () => {
  const face = faceFixture();
  face.summary.targets = ["fenix8solar47mm", "fr955"];
  const printed = await store(face, FRAME_OF + `
      const s = new EditorStore(summary.id);
      await settle();
      out([frames(), s.state.frame.busy]);
      // three zoom steps while the first frame is still being drawn
      s.setZoom(2.5); s.setZoom(3.125); s.setZoom(3.9);
      await settle();
      out(frames());
      // the first answer is not the newest ask's: dropped, and the newest goes out
      unanswered.shift()({ status: 200, json: frameOf({ device: summary.targets[0], scale: 2 }) });
      await settle();
      out([frames(), s.state.frame.current, s.state.frame.busy]);
      unanswered.shift()({ status: 200, json: frameOf({ device: summary.targets[0], scale: 4 }) });
      await settle();
      out([s.state.frame.current.scale, s.state.frame.busy]);
      // the same picture is not asked for twice
      s.setView({ zoom: 3.9 }); s.setContext({ style: "" });
      await settle();
      out(frames().length);
      // the context decides what is drawn
      s.setContext({ frame: "asleep", time: "08:30:00", device: "fr955" });
      await settle();
      const last = requests.filter(([op]) => op === "frame").at(-1)[1];
      out([last.device, last.asleep, last.aod, last.time, s.state.frame.busy]);
      unanswered.shift()({ status: 400, json: { error: "an old frame failed" } });
      await settle();
      out(s.state.messages.log.map((m) => m.message));
      s.dispose();
    `);
  assert.deepEqual(printed[0], [[2], true]);
  assert.deepEqual(printed[1], [2]);
  assert.deepEqual(printed[2], [[2, 4], null, true]);
  assert.deepEqual(printed[3], [4, false]);
  assert.equal(printed[4], 2);
  assert.deepEqual(printed[5], ["fr955", true, false, "08:30:00", true]);
  assert.deepEqual(printed[6], ["an old frame failed"]);
});

test("the YAML tab's text is sent once typing rests, against the version it was typed over, and a conflict waits for the author", async () => {
  const face = faceFixture();
  const printed = await store(face, `
      const s = new EditorStore(summary.id);
      await settle();
      const texts = () => requests.filter(([op]) => op === "text").map(([, a]) => [a.version, a.text.split("\\n").at(-2)]);
      s.yamlOpened();
      out([s.state.yaml.text === summary.text, storeMod.yamlSaving(s.state), storeMod.savedState(s.state)]);
      s.replaceText(summary.text + "# a\\n");
      s.replaceText(summary.text + "# ab\\n");
      await wait(storeMod.TEXT_DEBOUNCE_MS / 2);
      out([texts(), storeMod.yamlSaving(s.state), storeMod.savedState(s.state)]);
      await wait(storeMod.TEXT_DEBOUNCE_MS);
      out([texts(), storeMod.yamlSaving(s.state), s.inFlight()]);
      // typed on while the send is out: sent again once it is answered
      s.replaceText(summary.text + "# abc\\n");
      unanswered.shift()({ status: 200, json: { ...summary, version: summary.version + 1, text: summary.text + "# ab\\n" } });
      await settle();
      out([s.state.doc.version, storeMod.yamlSaving(s.state), texts().length]);
      await wait(storeMod.TEXT_DEBOUNCE_MS + 50);
      out(texts());
      // refused as stale: the text stays, the author chooses
      unanswered.shift()({ status: 409, json: { error: "the face moved on" } });
      await settle();
      out([s.state.yaml.conflict, storeMod.yamlSaving(s.state), storeMod.savedState(s.state), s.state.yaml.text.endsWith("# abc\\n")]);
      s.yamlChoose("theirs");
      out([s.state.yaml.conflict, s.state.yaml.text === s.state.doc.text, storeMod.yamlSaving(s.state)]);
      // not YAML: held, and not sent again until it changes
      s.replaceText("a: [");
      await wait(storeMod.TEXT_DEBOUNCE_MS + 50);
      unanswered.shift()({ status: 400, json: { error: "not YAML" } });
      await settle();
      out([s.state.yaml.status, storeMod.yamlSaving(s.state), storeMod.savedState(s.state)]);
      s.replaceText("a: [");
      await wait(storeMod.TEXT_DEBOUNCE_MS + 50);
      out(texts().length);
      s.dispose();
    `);
  const v = face.summary.version;
  assert.deepEqual(printed[0], [true, "idle", "saved"]);
  assert.deepEqual(printed[1], [[], "send", "saving"], "nothing is sent before typing rests");
  assert.deepEqual(printed[2], [[[v, "# ab"]], "send", true], "one send for the burst, against the version typed over");
  assert.deepEqual(printed[3], [v + 1, "send", 1]);
  assert.deepEqual(printed[4], [[v, "# ab"], [v + 1, "# abc"]]);
  assert.deepEqual(printed[5], [true, "wait", "unsaved", true]);
  assert.deepEqual(printed[6], [false, true, "idle"]);
  assert.deepEqual(printed[7], [{ kind: "invalid", message: "not YAML" }, "held", "unsaved"]);
  assert.equal(printed[8], 3, "the held text is not sent again");
});

test("the preferences persist to the browser's storage under the page's keys, and a new store reads them back", async () => {
  const face = faceFixture();
  const printed = await store(face, `
      const s = new EditorStore(null);
      out([s.state.view, s.state.ui.faceSection, s.state.ui.folds]);
      s.setZoom(3); s.setView({ skin: true, pxPerInch: 120, panels: { left: 300, right: 400 } });
      s.setUi({ faceSection: "fonts" }); s.setFolded("props", true);
      out(Object.fromEntries([...storage].sort()));
      const again = new EditorStore(null);
      out([again.state.view, again.state.ui.faceSection, again.state.ui.folds]);
      s.dispose(); again.dispose();
    `);
  assert.deepEqual(printed[0], [{ zoom: 2, real: false, skin: false, pxPerInch: 96, panels: { left: 280, right: 340 } }, "targets", { props: false, lower: false }]);
  assert.deepEqual(printed[1], {
    "wfb-css-px-per-inch": "120", "wfb-face-section": "fonts", "wfb-fold": JSON.stringify({ props: true, lower: false }),
    "wfb-panel-left": "300", "wfb-panel-right": "400", "wfb-skin": "1", "wfb-zoom": "3",
  });
  assert.deepEqual(printed[2], [{ zoom: 3, real: false, skin: true, pxPerInch: 120, panels: { left: 300, right: 400 } }, "fonts", { props: true, lower: false }]);
});

test("a face's editor-only state is read when it opens and written beside the face", async () => {
  const face = faceFixture();
  const printed = await store(face, `
      const s = new EditorStore(summary.id);
      await settle();
      out(s.state.faceState[summary.id]);
      s.setFaceState({ locked: ["clock"] });
      out(s.state.faceState[summary.id]);
      await settle();
      out(requests.filter(([op]) => op === "ui_state").map(([, a]) => [a.id === summary.id, a.action, a.state ?? null]));
      const again = new EditorStore(null);
      again.open(summary.id);
      await settle();
      out(again.state.faceState[summary.id]);
      s.dispose(); again.dispose();
    `);
  assert.deepEqual(printed[0], {});
  assert.deepEqual(printed[1], { locked: ["clock"] });
  assert.deepEqual(printed[2], [[true, "get", null], [true, "set", { locked: ["clock"] }]]);
  assert.deepEqual(printed[3], { locked: ["clock"] });
});

test("the editing context asks the inspector again when the frame changes, and Edit for decides a geometry edit's scope", async () => {
  const face = faceFixture();
  face.summary.targets = ["fenix8solar47mm"];
  const printed = await store(face, FRAME_OF + `
      const inspects = () => requests.filter(([op]) => op === "inspect").map(([, a]) => [a.element.at(-1), a.device, a.frame, a.style]);
      const s = new EditorStore(summary.id);
      await settle();
      out([inspects(), s.state.inspect, s.state.context.target]);
      s.select("clock");
      await settle();
      out([inspects(), s.state.inspect === null]);
      // the answer is the stand-in's: it did not come, so the tree stays empty; the frame asks again
      s.setContext({ frame: "aod" });
      await settle();
      out(inspects());
      s.setContext({ style: "night" });
      await settle();
      out(inspects().at(-1));
      // the same tree is not asked for twice
      s.setContext({ target: "shape" });
      await settle();
      out([inspects().length, s.state.context.target]);
      // a drag is written where Edit for says
      const gesture = { kind: "move", part: "both", dx: 1, dy: 0 };
      const shown = { item: { id: "clock", box: [0, 0, 10, 10], center: [5, 5], handles: [] }, moving: new Set(["clock"]), preview: gesture };
      s.drag(["clock"], gesture, shown);
      await settle();
      s.setContext({ target: "all" });
      s.drag(["clock"], gesture, shown);
      await settle();
      // the first is out (the stand-in never answers a drag), the second waits behind it: each carries the target it was made under
      out([requests.filter(([op]) => op === "drag").map(([, a]) => a.scope), s.state.pending.queue.map((e) => [e.state, e.where.scope])]);
      s.deselect();
      await settle();
      out([inspects().length, s.state.inspect]);
      s.dispose();
    `);
  assert.deepEqual(printed[0], [[], null, "all"], "nothing selected: nothing asked");
  assert.deepEqual(printed[1], [[["clock", "fenix8solar47mm", "awake", ""]], true]);
  assert.deepEqual(printed[2], [["clock", "fenix8solar47mm", "awake", ""], ["clock", "fenix8solar47mm", "aod", ""]]);
  assert.deepEqual(printed[3], ["clock", "fenix8solar47mm", "aod", "night"]);
  assert.deepEqual(printed[4], [3, "shape"]);
  assert.deepEqual(printed[5], [["shape"], [["sent", "shape"], ["queued", "auto"]]]);
  assert.deepEqual(printed[6], [3, null]);
});
