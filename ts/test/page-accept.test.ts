// "accept here…" in the page, over a face whose seconds readout overflows
// on its targets: a test of its own because the lint warning it accepts is
// measured on the real watches the face targets, so it needs the owner's
// Garmin device files, and CI (on the fixture device alone) leaves it out.
import assert from "node:assert/strict";
import { test } from "node:test";
import { faceFixture, instantiate, page, summary } from "./page-harness.ts";

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
