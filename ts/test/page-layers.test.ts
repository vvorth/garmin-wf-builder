// The Layers panel's hands and parts, rendered with preact over the minimal
// DOM (`studio_dom.mjs`) from a real face's summary: the rows under a
// `hands` element, a part row's selection by its tree path, the Enter and
// Exit affordances of an element with parts, and a part row dragged onto
// another, which reorders the parts as one `move_key`.
import assert from "node:assert/strict";
import { test } from "node:test";
import { appUri, htmPreactUri, instantiate, node, preactUri, summary, testUri } from "./page-harness.ts";

/** `Layers` rendered over `doc` with `entered`, then `body` run with `root`, `rows`, `row`, `cls`, `calls` and `out`: what it printed, one JSON value a line. */
function layers(doc: unknown, entered: unknown, body: string): any[] {
  const done = node(`
      import { install } from ${JSON.stringify(testUri("studio_dom.mjs"))};
      const document = install();
      const { html } = await import(${JSON.stringify(htmPreactUri)});
      const { render } = await import(${JSON.stringify(preactUri)});
      const { Layers } = await import(${JSON.stringify(appUri("layers.ts"))});
      const calls = [];
      const root = document.createElement("div");
      render(html\`<\${Layers} doc=\${${JSON.stringify(doc)}} vocab=\${{}} selected=\${null} extra=\${[]} drawn=\${null}
        entered=\${${JSON.stringify(entered)}}
        onSelect=\${(id, mode, owner) => calls.push({ select: id, mode, owner: owner ?? null })}
        onStructure=\${(op) => calls.push({ structure: op })} onEdit=\${(op) => calls.push({ edit: op })}
        onEnter=\${(path) => calls.push({ enter: path })} onExit=\${() => calls.push({ exit: true })} />\`, root);
      const cls = (e) => e.attributes.class || "";
      const rows = () => root.all((e) => cls(e).startsWith("item"));
      // the row of the element \`id\`, or of the part or hand whose path joined with "/" is \`id\`
      const row = (id) => rows().find((e) => e.attributes["data-path"] === id || (!e.attributes["data-path"] && e.childNodes[0].textContent === id));
      const out = (v) => console.log(JSON.stringify(v));
      ${body}
    `);
  if (done.returncode !== 0) throw new Error(done.stderr.slice(-2500));
  return done.stdout.split("\n").filter(Boolean).map((l) => JSON.parse(l));
}

const HOUR = ["resources", "hand_sets", "classic", "hour"];
const SECOND = ["resources", "hand_sets", "classic", "second"];
const HANDS = ["elements", "hands"];

test("a hands element lists its hands and their parts as rows, indented, each typed and selected by its path under its element", () => {
  const doc = summary(instantiate("analog", "T"));
  const printed = layers(doc, null, `
      // every row under the hands element: its text and class, in order
      const under = (e) => e.parentNode.all((r) => cls(r).startsWith("item") && r !== e);
      out(under(row("hands")).map((e) => [e.childNodes[0].textContent, e.all((s) => cls(s) === "type")[0].textContent, cls(e).split(" ").filter((c) => c !== "item").join(" ")]));
      // a pattern's parts sit under it too
      out(under(row("hour_ticks")).map((e) => [e.childNodes[0].textContent, e.all((s) => cls(s) === "type")[0].textContent, cls(e)]));
      // a part row sits under its hand's row, which sits under the element's: three trees deep
      const depth = (e) => { let n = 0; for (let p = e.parentNode; p; p = p.parentNode) if (cls(p).startsWith("tree")) n++; return n; };
      out([depth(row("hands")), depth(row(${JSON.stringify(HOUR.join("/"))})), depth(row(${JSON.stringify([...HOUR, "parts", "blade"].join("/"))}))]);
      // clicking a part row selects it by its path, naming the element it was clicked under; a hand row the same
      row(${JSON.stringify([...HOUR, "parts", "blade"].join("/"))}).click();
      row(${JSON.stringify(HOUR.join("/"))}).click();
      row("pin").click();
      out(calls);
      // only an element with parts offers Enter; a double-click on its row enters too
      out([row("hands").all((e) => cls(e) === "enter").length, row("pin").all((e) => cls(e) === "enter").length, row(${JSON.stringify([...HOUR, "parts", "blade"].join("/"))}).all((e) => cls(e) === "enter").length]);
      calls.length = 0;
      row("hands").all((e) => cls(e) === "enter")[0].click();
      row("hands").dispatch("dblclick");
      out(calls);
      // nothing is entered: no Exit, no row marked
      out([root.all((e) => cls(e) === "exit").length, rows().filter((e) => cls(e).includes("entered")).length]);
    `);
  assert.deepEqual(printed[0], [
    ["hour", "hand", "hand"], ["blade", "polygon", "part"],
    ["minute", "hand", "hand"], ["blade", "rectangle", "part"],
    ["second", "hand", "hand"], ["needle", "line", "part"], ["counterweight", "circle", "part"],
  ]);
  assert.deepEqual(printed[1], [["tick", "rectangle", "item part"]]);
  assert.deepEqual(printed[2], [2, 3, 4], "the element's row in the block's tree, the hand's a tree down, the part's another");
  assert.deepEqual(printed[3], [
    { select: [...HOUR, "parts", "blade"].join("/"), mode: false, owner: HANDS },
    { select: HOUR.join("/"), mode: false, owner: HANDS },
    // an element's row passes the click's own modifiers, none here
    { select: "pin", owner: null },
  ]);
  assert.deepEqual(printed[4], [1, 0, 0]);
  assert.deepEqual(printed[5], [{ enter: HANDS }, { enter: HANDS }]);
  assert.deepEqual(printed[6], [0, 0]);
});

test("while entered, the element's row is marked, Exit heads the list, and a part row dropped on another reorders the parts with one move_key", () => {
  const doc = summary(instantiate("analog", "T"));
  const needle = [...SECOND, "parts", "needle"].join("/"), weight = [...SECOND, "parts", "counterweight"].join("/");
  const printed = layers(doc, HANDS, `
      const needle = ${JSON.stringify(needle)}, weight = ${JSON.stringify(weight)};
      out([cls(row("hands")).includes("entered"), root.all((e) => cls(e) === "exit").length, root.all((e) => cls(e) === "entered-bar")[0].textContent.includes("hands")]);
      root.all((e) => cls(e) === "exit")[0].click();
      out(calls.splice(0));
      const data = {};
      const transfer = { types: [], setData(t, v) { data[t] = v; this.types.push(t); }, getData: (t) => data[t] ?? "" };
      // a part row is draggable; dropped on the lower half of its sibling it goes after it
      const rect = (height) => ({ getBoundingClientRect: () => ({ top: 0, height }) });
      row(needle).dispatch("dragstart", { dataTransfer: transfer });
      out(JSON.parse(data["application/x-wfb-path"]));
      row(weight).dispatch("drop", { dataTransfer: transfer, clientY: 15, currentTarget: rect(20) });
      // dropped on the upper half of a sibling, it goes before it
      row(weight).dispatch("dragstart", { dataTransfer: transfer });
      row(needle).dispatch("drop", { dataTransfer: transfer, clientY: 2, currentTarget: rect(20) });
      // a part of another hand, an element, or a block ignores it: parts stay with their hand
      row(${JSON.stringify([...HOUR, "parts", "blade"].join("/"))}).dispatch("drop", { dataTransfer: transfer, clientY: 2, currentTarget: rect(20) });
      row("pin").dispatch("drop", { dataTransfer: transfer, clientY: 2, currentTarget: rect(20) });
      root.all((e) => cls(e).startsWith("block") && e.textContent.trim() === "elements")[0].dispatch("drop", { dataTransfer: transfer });
      // and an element dropped on a part row is ignored too
      row("pin").dispatch("dragstart", { dataTransfer: transfer });
      row(needle).dispatch("drop", { dataTransfer: transfer, clientY: 2, currentTarget: rect(20) });
      out(calls);
    `);
  assert.deepEqual(printed[0], [true, 1, true]);
  assert.deepEqual(printed[1], [{ exit: true }]);
  assert.deepEqual(printed[2], [...SECOND, "parts", "needle"]);
  assert.deepEqual(printed[3], [
    { edit: { op: "move_key", element: SECOND, path: ["parts", "needle"], to: 1 } },
    { edit: { op: "move_key", element: SECOND, path: ["parts", "counterweight"], to: 0 } },
  ]);
});

test("the search narrows the rows to the ids and types holding it, each match under its ancestors; Escape and × clear it, and the selection stays", () => {
  const doc = summary(instantiate("analog", "T"));
  const printed = layers(doc, null, `
      const search = root.all((e) => e.localName === "input" && cls(e) === "search")[0];
      const shownIds = () => rows().map((e) => e.attributes["data-path"] ?? e.childNodes[0].textContent);
      const blocks = () => root.all((e) => cls(e).startsWith("block")).map((e) => e.textContent.trim());
      const type = async (v) => { search.value = v; search.dispatch("input", { target: search }); await new Promise((r) => setTimeout(r, 0)); };
      const all = shownIds();
      // "BLADE" in any case: the two blade parts, under their hands and the hands element, and nothing else
      await type("BLADE");
      out(shownIds());
      out(blocks());
      // a type matches too: every rectangle
      await type("rectangle");
      out(shownIds());
      // nothing matches: no row, and a note says so
      await type("zzz");
      out([shownIds().length, root.textContent.includes("no element's id or type holds")]);
      // × clears it; so does Escape, which goes no further than the box
      await type("pin");
      out(shownIds());
      root.all((e) => e.localName === "button" && e.attributes["aria-label"] === "clear the search")[0].click();
      await new Promise((r) => setTimeout(r, 0));
      out(shownIds().length === all.length);
      await type("pin");
      let stopped = false;
      search.dispatch("keydown", { key: "Escape", target: search, stopPropagation() { stopped = true; } });
      await new Promise((r) => setTimeout(r, 0));
      out([shownIds().length === all.length, stopped]);
      // the search sends nothing and selects nothing
      out(calls);
    `);
  const blade = (hand: string): string => ["resources", "hand_sets", "classic", hand, "parts", "blade"].join("/");
  const hand = (h: string): string => ["resources", "hand_sets", "classic", h].join("/");
  assert.deepEqual(printed[0], ["hands", hand("hour"), blade("hour"), hand("minute"), blade("minute")]);
  assert.deepEqual(printed[1], ["elements"], "a block none of whose rows match is left out");
  assert.deepEqual(printed[2], ["background", "hour_ticks", "static/hour_ticks/parts/tick", "date_frame", "hands", hand("minute"), blade("minute")],
    "a type matches as an id does: the static background, the pattern's tick part, the minute blade and the date frame, each under its ancestors");
  assert.deepEqual(printed[3], [0, true]);
  assert.deepEqual(printed[4], ["pin"]);
  assert.equal(printed[5], true);
  assert.deepEqual(printed[6], [true, true]);
  assert.deepEqual(printed[7], []);
});

test("a row shows its element's z: as a badge when written, and none when not", () => {
  const text = instantiate("minimal", "T").replace("    font: FONT_SMALL\n", "    font: FONT_SMALL\n    z: 5\n");
  const doc = summary(text);
  const printed = layers(doc, null, `
      const badge = (id) => row(id).all((e) => cls(e) === "z-badge").map((e) => e.textContent);
      out([badge("seconds"), badge("clock"), badge("background")]);
    `);
  assert.deepEqual(printed[0], [["z 5"], [], []]);
});
