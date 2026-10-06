// The page's pure modules (`app/hit.js`, `outbox.js`, `textsync.js`,
// `session.js` and the rest without a DOM), run in Node.
import assert from "node:assert/strict";
import { test } from "node:test";
import { appText, appUri, count, DEFERRED_FETCH, eq, faceFixture, has, instantiate, len, node, page, render, repoText, run, summary, testUri } from "./page-harness.ts";
import { automaticName } from "../src/edit/colors.ts";
import { Color, MIP64_NAMED } from "../src/palette.ts";

test("select all and a shift range let a group stand for its children", async () => {
  const result = await run("\n      const el = (id, children = []) => ({kind: \"element\", id, children});\n      const tree = [{kind: \"block\", children: [el(\"a\"), el(\"g\", [el(\"g1\"), el(\"g2\")]), el(\"b\")]},\n                    {kind: \"block\", children: [el(\"c\"), el(\"hidden\")]}];\n      console.log(JSON.stringify({\n        all: hit.selectAll(tree, new Set([\"a\", \"g\", \"g1\", \"g2\", \"b\", \"c\"])),\n        ungrouped: hit.selectAll(tree, new Set([\"a\", \"g1\", \"b\"])),\n        down: hit.rangeIds(tree, \"a\", \"b\"),\n        up: hit.rangeIds(tree, \"b\", \"g1\"),\n        inside: hit.rangeIds(tree, \"g1\", \"g2\"),\n        noAnchor: hit.rangeIds(tree, \"zz\", \"c\"),\n        outer: hit.outermost(tree, [\"g2\", \"g\", \"c\"]),\n      }));\n    ");
  assert.deepEqual(result["all"], ["a", "g", "b", "c"]);
  assert.deepEqual(result["ungrouped"], ["a", "g1", "b"]);
  assert.deepEqual(result["down"], ["a", "g", "b"]);
  assert.deepEqual(result["up"], ["g1", "g2", "b"]);
  assert.deepEqual(result["inside"], ["g1", "g2"]);
  assert.deepEqual(result["noAnchor"], ["c"]);
  assert.deepEqual(result["outer"], ["g", "c"]);
});

test("each shortcut names its action and typing is left alone", async () => {
  const result = await run("\n      const k = (key, mods = {}) => keys.shortcutFor({key, ...mods});\n      console.log(JSON.stringify({\n        undo: k(\"z\", {ctrlKey: true}), redoShift: k(\"Z\", {metaKey: true, shiftKey: true}),\n        redoY: k(\"y\", {ctrlKey: true}), dup: k(\"d\", {metaKey: true}), all: k(\"a\", {ctrlKey: true}),\n        other: k(\"s\", {ctrlKey: true}), plainZ: k(\"z\"),\n        left: k(\"ArrowLeft\"), downTen: k(\"ArrowDown\", {shiftKey: true}), alt: k(\"ArrowUp\", {altKey: true}),\n        del: k(\"Delete\"), back: k(\"Backspace\"),\n        group: k(\"g\", {ctrlKey: true}), ungroup: k(\"G\", {metaKey: true, shiftKey: true}),\n        forward: k(\"]\", {ctrlKey: true}), backward: k(\"[\", {metaKey: true}),\n        zoomIn: k(\"=\", {ctrlKey: true}), zoomOut: k(\"-\", {ctrlKey: true}), fit: k(\"0\", {ctrlKey: true}),\n        real: k(\"1\"), help: k(\"?\", {shiftKey: true}), escape: k(\"Escape\"), altLetter: k(\"1\", {altKey: true}),\n        typing: keys.typingIn({closest: (sel) => sel.includes(\"input\") ? {} : null}),\n        notTyping: keys.typingIn({closest: () => null}), nothing: keys.typingIn(null),\n      }));\n    ");
  assert.deepEqual(result, {"undo": ["undo"], "redoShift": ["redo"], "redoY": ["redo"], "dup": ["duplicate"], "all": ["selectAll"], "other": null, "plainZ": null, "left": ["nudge", -1, 0], "downTen": ["nudge", 0, 10], "alt": null, "del": ["remove"], "back": ["remove"], "group": ["group"], "ungroup": ["ungroup"], "forward": ["forward"], "backward": ["backward"], "zoomIn": ["zoom", 1], "zoomOut": ["zoom", -1], "fit": ["zoomFit"], "real": ["zoomReal"], "help": ["help"], "escape": ["deselect"], "altLetter": null, "typing": true, "notTyping": false, "nothing": false});
});

test("topmost picks the last drawn layer with ink", async () => {
  const result = await run("\n      const layers = [\n        {id: \"bg\", box: [0, 0, 100, 100]},\n        {id: \"ring:g\", box: [10, 10, 20, 20]},\n        {id: \"dot\", box: [10, 10, 20, 20]},\n        {id: \"boxless\", box: null},\n      ];\n      // ink: bg everywhere, ring:g everywhere in its box, dot only at (15, 15),\n      // boxless nowhere\n      const ink = (l, x, y) => l.id === \"dot\" ? (x === 15 && y === 15 ? 255 : 0)\n                             : l.id === \"boxless\" ? 0 : 255;\n      const reads = [];\n      const counted = (l, x, y) => { reads.push(l.id); return ink(l, x, y); };\n      console.log(JSON.stringify({\n        onDot: hit.topmost(layers, 15, 15, ink).id,\n        besideDot: hit.topmost(layers, 16, 15, ink).id,\n        outside: hit.topmost(layers, 50, 50, ink).id,\n        offScreen: hit.topmost(layers, 500, 500, ink),\n        ring: hit.elementOf(\"ring:g\"), plain: hit.elementOf(\"dot\"),\n        reads: (hit.topmost(layers, 50, 50, counted), reads),\n      }));\n    ");
  assert.deepEqual(result, {"onDot": "dot", "besideDot": "ring:g", "outside": "bg", "offScreen": null, "ring": "g", "plain": "dot", "reads": ["boxless", "bg"]});
});

test("element at line is the deepest holding it", async () => {
  const result = await run("\n      const tree = [\n        {kind: \"block\", line: 10, children: [\n          {kind: \"element\", id: \"a\", line: 11, children: []},\n          {kind: \"element\", id: \"g\", line: 15, children: [\n            {kind: \"element\", id: \"g1\", line: 17, children: []},\n            {kind: \"element\", id: \"g2\", line: 20, children: []},\n          ]},\n        ]},\n        {kind: \"block\", line: null, children: []},\n        {kind: \"block\", line: 30, children: [\n          {kind: \"element\", id: \"z\", line: 31, children: []},\n        ]},\n        {kind: \"block\", line: null, children: []},\n      ];\n      const at = (n) => (hit.elementAtLine(tree, n) || {id: null}).id;\n      console.log(JSON.stringify({\n        lines: [10, 11, 14, 15, 16, 17, 19, 20, 29, 30, 31, 99].map(at),\n        flat: hit.flatten(tree).map((n) => n.id),\n      }));\n    ");
  assert.deepEqual(result, {"lines": [null, "a", "a", "g", "g", "g1", "g1", "g2", "g2", null, "z", "z"], "flat": ["a", "g", "g1", "g2", "z"]});
});

test("a quantity keeps the authors spelling", async () => {
  const result = await run("\n      const p = values.parseQuantity;\n      const f = values.formatQuantity;\n      console.log(JSON.stringify({\n        parsed: [p(\"12%r\", \"px\"), p(12, \"px\"), p(\" -3.5 deg \", \"deg\"), p(\"1 + x\", \"px\"), p(null, \"px\")],\n        bareStays: f(14, \"px\", \"px\", true),\n        bareGetsUnit: f(14, \"%\", \"px\", true),\n        unitKept: f(14, \"%r\", \"px\", false),\n        rounding: f(0.1 + 0.2, \"%r\", \"px\", false),\n        nan: f(NaN, \"px\", \"px\", false),\n      }));\n    ");
  assert.deepEqual(result, {"parsed": [{"number": 12, "unit": "%r", "bare": false}, {"number": 12, "unit": "px", "bare": true}, {"number": -3.5, "unit": "deg", "bare": false}, null, null], "bareStays": 14, "bareGetsUnit": "14%", "unitKept": "14%r", "rounding": "0.3%r", "nan": null});
});

test("colours against the mip palette", async () => {
  const result = await run("\n      console.log(JSON.stringify({\n        hex: [values.parseHex(\"#5af\"), values.parseHex(\"55AAFF\"), values.parseHex(\"color.x\")],\n        legal: [values.mipLegal([0x55, 0xaa, 0xff]), values.mipLegal([0x12, 0x34, 0x56])],\n        nearest: values.toHex(values.mipNearest([0x12, 0x34, 0x56])),\n        name: [values.colorName(\"color.bg\"), values.colorName(\"#FFF\"), values.colorName(\"color.a + 1\")],\n        ids: [values.isIdentifier(\"ok_1\"), values.isIdentifier(\"1x\"), values.isIdentifier(\"a-b\")],\n      }));\n    ");
  assert.deepEqual(result, {"hex": [[85, 170, 255], [85, 170, 255], null], "legal": [true, false], "nearest": "#005555", "name": ["bg", null, null], "ids": [true, false, false]});
});

test("a new style is shaped like the others", async () => {
  const result = await run("\n      const n = values.newStyleEntry;\n      console.log(JSON.stringify([\n        n([{name: \"a\", layout: \"big\", scheme: \"dark\"}], [\"big\", \"small\"], [\"dark\", \"light\"]),\n        n([{name: \"a\", scheme: \"light\"}], [\"big\"], [\"dark\", \"light\"]),\n        n([{name: \"a\", layout: \"small\"}], [\"big\", \"small\"], []),\n        n([], [\"big\"], [\"dark\"]),\n        n([], [], [\"dark\"]),\n      ]));\n    ");
  assert.deepEqual(result, [{"layout": "big", "scheme": "dark"}, {"scheme": "light"}, {"layout": "small"}, {"layout": "big"}, {"scheme": "dark"}]);
});

test("a move snaps to centres edges and the grid", async () => {
  const result = await run("\n      const items = [\n        {id: \"me\", box: [100, 100, 20, 10], center: [110, 105]},\n        {id: \"other\", box: [150, 40, 30, 30], center: [165, 55]},\n      ];\n      const t = snap.moveTargets(items, \"me\", 260, 260, 130, 5);\n      const me = items[0];\n      console.log(JSON.stringify({\n        // centre x 110+18=128 is 2 from the screen centre 130\n        toCentre: snap.snapMove(me, 18, 0, t, 4),\n        // left edge 100+48=148 is 2 from the other's left edge 150\n        toEdge: snap.snapMove(me, 48, 0, t, 4),\n        // nothing within 4: whole pixels, no guide\n        free: snap.snapMove({...me, box: [0, 0, 1, 1], center: [0, 0]}, 0.6, 0, {xs: [], ys: [], grid: 0, cx: 130, cy: 130}, 4),\n        // no guide near: the centre to the grid of 5%r (6.5 px) about the\n        // screen centre, 130 + 6.5k\n        grid: snap.snapMove({id: \"p\", box: [140, 0, 0, 0], center: [140, 0]}, 3, 0, {xs: [], ys: [], grid: 6.5, cx: 130, cy: 130}, 4),\n        // a guide beats the grid even when the grid is nearer\n        guideFirst: snap.snapMove({id: \"p\", box: [140, 0, 0, 0], center: [140, 0]}, 3, 0, {xs: [146], ys: [], grid: 6.5, cx: 130, cy: 130}, 4),\n        // an axis the drag did not move along stays put\n        still: snap.snapMove(me, 18, 0.4, t, 4).dy,\n        targets: [t.xs.length, t.grid],\n      }));\n    ");
  assert.deepEqual(result["toCentre"], {"dx": 20, "dy": 0, "guides": {"x": [130], "y": []}});
  assert.deepEqual(result["toEdge"], {"dx": 50, "dy": 0, "guides": {"x": [150], "y": []}});
  assert.deepEqual(result["free"], {"dx": 1, "dy": 0, "guides": {"x": [], "y": []}});
  assert.deepEqual(result["grid"], {"dx": 3, "dy": 0, "guides": {"x": [143], "y": []}});
  assert.deepEqual(result["guideFirst"], {"dx": 6, "dy": 0, "guides": {"x": [146], "y": []}});
  assert.deepEqual(result["still"], 0);
  assert.deepEqual(result["targets"], [4, 6.5]);
});

test("a selection moves together", async () => {
  const result = await run("\n      const tree = [{kind: \"block\", children: [\n        {kind: \"element\", id: \"g\", children: [\n          {kind: \"element\", id: \"a\", children: []},\n          {kind: \"element\", id: \"inner\", children: [{kind: \"element\", id: \"b\", children: []}]},\n        ]},\n        {kind: \"element\", id: \"c\", children: []},\n        {kind: \"element\", id: \"d\", children: []},\n      ]}];\n      const items = [\n        {id: \"g\", kind: \"group\", box: [10, 10, 40, 40], center: [30, 30]},\n        {id: \"a\", box: [10, 10, 10, 10], center: [15, 15]},\n        {id: \"c\", box: [100, 100, 20, 20], center: [110, 110]},\n        {id: \"d\", box: [200, 0, 10, 10], center: [205, 5]},\n      ];\n      const moving = hit.movedBy(tree, [\"g\", \"c\"]);\n      const t = snap.moveTargets(items, moving, 260, 260, 130, 0);\n      console.log(JSON.stringify({\n        // a group carries every element inside it, however deep\n        moving: [...moving].sort(),\n        alone: [...hit.movedBy(tree, [\"a\"])],\n        // the move handle: on the top edge of a group or of several, never\n        // on one plain element, which is pressed on itself; kept on the\n        // screen for a selection reaching its top\n        gripSeveral: hit.moveHandle(items, [\"g\", \"c\"]),\n        gripGroup: hit.moveHandle(items, [\"g\"]),\n        gripTop: hit.moveHandle(items, [\"g\", \"d\"], 6),\n        gripOne: hit.moveHandle(items, [\"c\"]),\n        gripNone: hit.moveHandle(items, []),\n        // the selection snaps as one box\n        together: hit.together(items, [\"g\", \"c\"]),\n        // nothing that moves is a snapping target; d is\n        xs: t.xs,\n      }));\n    ");
  assert.deepEqual(result["moving"], ["a", "b", "c", "g", "inner"]);
  assert.deepEqual(result["alone"], ["a"]);
  assert.deepEqual(result["gripSeveral"], {"x": 65, "y": 10});
  assert.deepEqual(result["gripGroup"], {"x": 30, "y": 10});
  assert.deepEqual(result["gripTop"], {"x": 110, "y": 6});
  assert.ok((result["gripOne"] === null && result["gripNone"] === null));
  assert.deepEqual(result["together"], {"id": "g", "box": [10, 10, 110, 110], "center": [65, 65], "handles": []});
  assert.deepEqual(result["xs"], [130, 200, 210, 205]);
});

test("angles lengths and resizes snap", async () => {
  const result = await run("\n      console.log(JSON.stringify({\n        angles: [28, 33.5, 44, 47, 359].map(snap.snapAngle),\n        at: [snap.angleAt(0, 0, 0, -10), snap.angleAt(0, 0, 10, 0), snap.angleAt(0, 0, 0, 10),\n             snap.angleAt(0, 0, -10, 0)],\n        turns: [snap.nearestTurn(10, 350), snap.nearestTurn(-80, 300), snap.nearestTurn(200, 190)],\n        lengths: [snap.snapLength(25, 130, 5), snap.snapLength(29.5, 130, 5), snap.snapLength(29.5, 130, 0)],\n        resize: [snap.resizeDelta({axis: \"x\", gain: 2}, 5, 9), snap.resizeDelta({axis: \"y\", gain: -1}, 5, 9)],\n      }));\n    ");
  assert.deepEqual(result["angles"], [30, 36, 42, 48, 360]);
  assert.deepEqual(result["at"].map((a: any) => Math.round(a)), [0, 90, 180, 270]);
  assert.deepEqual(result["turns"], [370, 280, 200]);
  assert.deepEqual(result["lengths"], [26, 33, 30]);
  assert.deepEqual(result["resize"], [10, -9]);
});

test("the tree offers its blocks siblings and drop zones", async () => {
  const result = await run("\n      const t = [\n        {kind: \"block\", label: \"static\", path: [\"static\"], children: []},\n        {kind: \"block\", label: \"elements\", path: [\"elements\"], children: [\n          {kind: \"element\", id: \"a\", type: \"text\", path: [\"elements\", \"a\"], children: []},\n          {kind: \"element\", id: \"g\", type: \"group\", path: [\"elements\", \"g\"], children: [\n            {kind: \"element\", id: \"c\", type: \"circle\", path: [\"elements\", \"g\", \"children\", \"c\"], children: []},\n          ]},\n        ]},\n      ];\n      const b = treeMod.blocksOf(t);\n      const g = b.nodes.find((n) => n.id === \"g\");\n      const a = b.nodes.find((n) => n.id === \"a\");\n      console.log(JSON.stringify({\n        nodes: b.nodes.map((n) => n.id),\n        destinations: b.destinations.map((d) => d.path.join(\".\")),\n        siblings: [treeMod.siblingsOf(t, [\"elements\", \"g\"]), treeMod.siblingsOf(t, [\"elements\", \"g\", \"children\", \"c\"])],\n        drops: [treeMod.dropTarget(a, 0.2, \"g\"), treeMod.dropTarget(a, 0.8, \"g\"), treeMod.dropTarget(g, 0.5, null),\n                treeMod.dropTarget(g, 0.9, null)],\n      }));\n    ");
  assert.deepEqual(result["nodes"], ["a", "g", "c"]);
  assert.deepEqual(result["destinations"], ["static", "elements", "elements.g.children"]);
  assert.deepEqual(result["siblings"], [["a", "g"], ["c"]]);
  assert.deepEqual(result["drops"], [{"where": "before", "target": {"block": ["elements"], "before": "a"}}, {"where": "after", "target": {"block": ["elements"], "before": "g"}}, {"where": "into", "target": {"block": ["elements", "g", "children"], "before": null}}, {"where": "after", "target": {"block": ["elements"], "before": null}}]);
});

test("layers shown front to back drop and step by draw order", async () => {
  const result = await run("\n      const el = (id, path, children = []) => ({kind: \"element\", id, type: children.length ? \"group\" : \"circle\", path, children});\n      const t = [{kind: \"block\", label: \"elements\", path: [\"elements\"], children: [\n        el(\"a\", [\"elements\", \"a\"]), el(\"b\", [\"elements\", \"b\"]), el(\"c\", [\"elements\", \"c\"])]}];\n      const b = t[0].children[1];\n      console.log(JSON.stringify({\n        // b is shown under c: its top half is in front of it, before c in draw order\n        top: treeMod.shownDrop(b, 0.2, \"c\"), bottom: treeMod.shownDrop(b, 0.8, \"c\"),\n        forward: treeMod.stepOp(t, b.path, 1), backward: treeMod.stepOp(t, b.path, -1),\n        frontmost: treeMod.stepOp(t, [\"elements\", \"c\"], 1),\n      }));\n    ");
  assert.deepEqual(result["top"], {"where": "before", "target": {"block": ["elements"], "before": "c"}});
  assert.deepEqual(result["bottom"], {"where": "after", "target": {"block": ["elements"], "before": "b"}});
  assert.deepEqual(result["forward"], {"op": "move", "path": ["elements", "b"], "block": ["elements"], "before": null});
  assert.deepEqual(result["backward"], {"op": "move", "path": ["elements", "b"], "block": ["elements"], "before": "a"});
  assert.equal(result["frontmost"], null);
});

test("copied elements are their own lines at the first column", async () => {
  const result = await run("\n      const text = \"elements:\\n  a:\\n    type: circle\\n    radius: 5\\n  g:\\n    type: group\\n\" +\n                   \"    children:\\n      c:\\n        type: text\\n  b: {type: circle}\\n\";\n      const el = (id, line, end, children = []) => ({kind: \"element\", id, line, end, children});\n      const t = [{kind: \"block\", children: [el(\"a\", 2, 4), el(\"g\", 5, 9, [el(\"c\", 8, 9)]), el(\"b\", 10, 10)]}];\n      console.log(JSON.stringify([treeMod.elementsYaml(text, t, [\"b\", \"a\"]), treeMod.elementsYaml(text, t, [\"c\", \"g\"])]));\n    ");
  assert.deepEqual(result[0], "a:\n  type: circle\n  radius: 5\nb: {type: circle}\n");
  assert.deepEqual(result[1], "g:\n  type: group\n  children:\n    c:\n      type: text\n");
});

test("a drag says how far it went and how to stop snapping", async () => {
  const result = await run("\n      console.log(JSON.stringify([\n        snap.dragHint({kind: \"move\", dx: 12, dy: -3}, false),\n        snap.dragHint({kind: \"resize\", delta: -4}, true),\n        snap.dragHint({kind: \"turn\", degrees: 89.6}, false),\n      ]));\n    ");
  assert.deepEqual(result, ["+12, −3 px · snapping · hold Alt to place freely", "−4 px · placed freely (Alt)", "90° · snapping · hold Alt to place freely"]);
});

test("the vendored editor bundle exports what the yaml tab imports", async () => {
  const source = appText("yaml.js");
  const start = source.indexOf("import {", source.indexOf("preact-htm"));
  const imported = source.slice((start + len("import {")), source.indexOf("}", start));
  const names = [...imported.split(",").filter((n: any) => n.trim()).map((n: any) => n.trim())].sort();
  const result = await run(`
      const m = await import(${JSON.stringify(appUri("vendor/codemirror.module.js"))});
      console.log(JSON.stringify(${JSON.stringify(names)}.filter((n) => !(n in m))));
    `);
  assert.ok((names && eq(result, [])));
});

test("zoom scale and real size", async () => {
  const result = await run("\n      console.log(JSON.stringify({\n        scales: [[0.3, 1], [1, 1], [1.01, 1], [2, 1], [0.5, 2], [1.5, 2], [3.9, 1], [5, 1]]\n          .map(([z, dpr]) => zoom.serverScale(z, dpr)),\n        clamp: [zoom.clampZoom(0.01), zoom.clampZoom(9), zoom.clampZoom(1.5)],\n        real: [zoom.realZoom(200), zoom.realZoom(326), zoom.realZoom(null), zoom.realZoom(200, 120)],\n        card: zoom.calibrate(323.53),\n        mm: [zoom.screenMm(260, 200), zoom.screenMm(260, null)],\n      }));\n    ");
  assert.deepEqual(result["scales"], [1, 1, 2, 2, 1, 3, 4, 4]);
  assert.deepEqual(result["clamp"], [0.2, 4, 1.5]);
  const real = result["real"];
  assert.ok((eq(real[0], 0.48) && Math.abs((real[1] - (96 / 326))) < 1e-09 && real[2] === null && eq(real[3], 0.6)));
  assert.ok(Math.abs((result["card"] - 96)) < 0.01);
  assert.ok((Math.abs((result["mm"][0] - 33.02)) < 0.01 && result["mm"][1] === null));
});

test("a picked colour is named and snapped as the compiler does", async () => {
  const mip = MIP64_NAMED.map(([n, v, label]: any) => ({"name": n, "value": v, "label": label}));
  const samples = ["#FF8000", "#FF5500", "#000000", "#123456", "#2E3A2E", "#2F4F4F", "#7A7A7A", "#767676", "#AAAAAA", "#FFFFFF", "#0F0F80", "#808000"];
  const palette = [{"name": "bg", "value": "#000"}, {"name": "odd", "value": "nope"}];
  const result = await run(`
      const mip = ${JSON.stringify(mip)};
      const samples = ${JSON.stringify(samples)};
      console.log(JSON.stringify({
        names: samples.map((s) => values.automaticName(values.parseHex(s), mip)),
        mono: samples.map((s) => values.toHex(values.safeOn(values.parseHex(s), [2]).nearest)),
        mip64: samples.map((s) => values.toHex(values.safeOn(values.parseHex(s), [64]).nearest)),
        ok: [values.safeOn([0x55, 0xaa, 0xff], [64, 65536]).ok, values.safeOn([1, 2, 3], [65536]).ok,
             values.safeOn([0x55, 0x55, 0x55], [2]).ok],
        held: values.swatchFor([0, 0, 0], ${JSON.stringify(palette)}, mip),
        adds: values.swatchFor([255, 0, 0], ${JSON.stringify(palette)}, mip),
      }));
    `);
  assert.deepEqual(result["names"], samples.map((s: any) => automaticName(s)));
  assert.deepEqual(result["mono"], samples.map((s: any) => String(Color.parse(s).nearestLegal(2))));
  assert.deepEqual(result["mip64"], samples.map((s: any) => String(Color.parse(s).nearestLegal(64))));
  assert.deepEqual(result["ok"], [true, true, false]);
  assert.deepEqual(result["held"], {"name": "bg", "adds": false});
  assert.deepEqual(result["adds"], {"name": "red", "adds": true});
});

test("the showing control sends only what differs from each default", async () => {
  const result = await run("\n      const slots = [{name: \"top\", default: \"steps\"}, {name: \"left\", default: \"vo2max_run\"},\n                     {name: \"right\", default: \"date\"}];\n      console.log(JSON.stringify({\n        none: values.picksParam({}, slots),\n        some: values.picksParam({top: \"steps\", right: \"battery\", left: \"heart_rate\", gone: \"x\"}, slots),\n        label: [values.typeLabel({complication_types: [{name: \"steps\", label: \"Steps\"}]}, \"steps\"),\n                values.typeLabel({}, \"steps\")],\n      }));\n    ");
  assert.deepEqual(result, {"none": "", "some": "left:heart_rate,right:battery", "label": ["Steps", "steps"]});
});

test("the outbox sends one at a time and folds repeated moves", async () => {
  // A held arrow key queues one move per repeat; while the first is on
  // its way, the rest fold into one request. A move of other elements, or
  // a resize, stays its own entry.
  const result = await run("\n      const move = (ids, dx, dy) => ({ids, gesture: {kind: \"move\", part: \"both\", dx, dy},\n                                      preview: {kind: \"move\", part: \"both\", dx, dy, guides: {x: [1], y: []}},\n                                      moving: new Set(ids)});\n      let q = outbox.enqueue([], move([\"a\"], 1, 0));\n      const first = outbox.next(q);\n      q = outbox.mark(q, first, \"sent\");\n      const whileSent = outbox.next(q);\n      q = outbox.enqueue(q, move([\"a\"], 1, 0));\n      q = outbox.enqueue(q, move([\"a\"], 0, 10));\n      q = outbox.enqueue(q, move([\"b\"], 1, 0));\n      q = outbox.enqueue(q, {ids: [\"b\"], gesture: {kind: \"resize\", key: [\"radius\"], delta: 2},\n                             preview: {kind: \"resize\"}, moving: new Set([\"b\"])});\n      q = outbox.enqueue(q, move([\"b\"], 1, 0));\n      q = outbox.enqueue(q, {...move([\"b\"], 1, 0), where: {device: \"fr955\"}});\n      const shape = q.map((e) => [e.ids.join(), e.state, e.gesture.kind, e.gesture.dx ?? null,\n                                  e.gesture.dy ?? null]);\n      q = outbox.mark(q, q[0], \"done\", 7);\n      console.log(JSON.stringify({\n        first: first.gesture, whileSent, shape,\n        folded: q[1].preview,\n        nextAfterDone: outbox.next(q).gesture,\n      }));\n    ");
  assert.deepEqual(result["first"], {"kind": "move", "part": "both", "dx": 1, "dy": 0});
  assert.equal(result["whileSent"], null);
  assert.deepEqual(result["shape"], [["a", "sent", "move", 1, 0], ["a", "queued", "move", 1, 10], ["b", "queued", "move", 1, 0], ["b", "queued", "resize", null, null], ["b", "queued", "move", 1, 0], ["b", "queued", "move", 1, 0]]);
  assert.deepEqual(result["folded"], {"kind": "move", "part": "both", "dx": 1, "dy": 10});
  assert.deepEqual(result["nextAfterDone"], {"kind": "move", "part": "both", "dx": 1, "dy": 10});
});

test("an edit made while a drag is on its way waits its turn", async () => {
  // An inspector edit, an undo or a layer edit made while a gesture is
  // being written is queued behind it, never folded into a move, and sent
  // only once the gesture's answer gives the version it builds on; done,
  // it leaves the queue, since the canvas has nothing to draw for it.
  const result = await run("\n      const move = (ids, dx) => ({ids, gesture: {kind: \"move\", part: \"both\", dx, dy: 0},\n                                  preview: {kind: \"move\", part: \"both\", dx, dy: 0}, moving: new Set(ids)});\n      let q = outbox.enqueue([], move([\"a\"], 1));\n      q = outbox.mark(q, outbox.next(q), \"sent\");\n      q = outbox.enqueue(q, {request: {path: \"undo\"}});\n      q = outbox.enqueue(q, move([\"a\"], 1));\n      const whileSent = outbox.next(q);\n      q = outbox.mark(q, q[0], \"done\", 5);\n      const second = outbox.next(q);\n      q = outbox.mark(q, second, \"sent\");\n      const sentShape = q.map((e) => [e.request ? e.request.path : \"move\", e.state]);\n      q = outbox.mark(q, q.find((e) => e.state === \"sent\"), \"done\", 6);\n      console.log(JSON.stringify({\n        whileSent, second: second.request, sentShape,\n        after: q.map((e) => [e.request ? e.request.path : \"move\", e.state, e.done]),\n        drawn: outbox.unshown(q, 4).length, moves: [...outbox.offsets(outbox.unshown(q, 4))],\n        saving: outbox.saveState({queue: q}),\n      }));\n    ");
  assert.equal(result["whileSent"], null);
  assert.deepEqual(result["second"], {"path": "undo"});
  assert.deepEqual(result["sentShape"], [["move", "done"], ["undo", "sent"], ["move", "queued"]]);
  assert.deepEqual(result["after"], [["move", "done", 5], ["move", "queued", null]]);
  assert.ok((eq(result["drawn"], 2) && eq(result["moves"], [["a", [2, 0]]])));
  assert.deepEqual(result["saving"], "saving");
});

test("an older face never replaces a newer one", async () => {
  const result = await run("\n      const n = outbox.newer;\n      console.log(JSON.stringify([\n        n(null, {id: \"a\", version: 1}),\n        n({id: \"a\", version: 5}, {id: \"a\", version: 6}),\n        n({id: \"a\", version: 5}, {id: \"a\", version: 5}),\n        n({id: \"a\", version: 5}, {id: \"a\", version: 4}),\n        n({id: \"a\", version: 5}, {id: \"b\", version: 1}),\n      ]));\n    ");
  assert.deepEqual(result, [true, true, true, false, true]);
});

test("a refusal says how many changes behind it were dropped", async () => {
  const result = await run("\n      const e = Object.assign(new Error(\"no such element\"), {status: 400});\n      const one = outbox.droppedError(e, 1), three = outbox.droppedError(e, 3);\n      console.log(JSON.stringify([outbox.droppedError(e, 0) === e, one.message, three.message, three.status]));\n    ");
  assert.deepEqual(result, [true, "no such element (1 later change was not sent)", "no such element (3 later changes were not sent)", 400]);
});

test("each tab has its own name", async () => {
  const result = await run("console.log(JSON.stringify(typeof session.TAB === 'string' && session.TAB.length > 8));");
  assert.equal(result, true);
});

test("the canvas draws what a frame does not show yet", async () => {
  // An entry stays drawn until a frame of the version it produced
  // arrives; its moves add up per element, a group's children included, and
  // the items they move are hit-tested where they will be.
  const result = await run("\n      const e = (ids, moving, gesture, state, done) => ({ids, moving: new Set(moving), gesture, state, done});\n      const mv = (dx, dy) => ({kind: \"move\", part: \"both\", dx, dy});\n      const q = [e([\"a\"], [\"a\"], mv(2, 0), \"done\", 5), e([\"g\"], [\"g\", \"a\"], mv(0, 3), \"sent\", null),\n                 e([\"b\"], [\"b\"], mv(-1, 0), \"queued\", null)];\n      const at5 = outbox.unshown(q, 5), at4 = outbox.unshown(q, 4);\n      const by = outbox.offsets(at4);\n      const items = [{id: \"a\", box: [10, 10, 4, 4], center: [12, 12],\n                      handles: [{kind: \"size\", x: 14, y: 12}, {kind: \"angle\", x: 1, y: 1, cx: 12, cy: 12}]},\n                     {id: \"c\", box: [0, 0, 1, 1], center: [0, 0], handles: []}];\n      const shifted = outbox.shiftItems(items, by);\n      console.log(JSON.stringify({\n        at5: at5.length, at4: at4.length,\n        by: [...by.entries()].sort(),\n        notAllMoves: outbox.offsets([e([\"a\"], [\"a\"], {kind: \"resize\", delta: 1}, \"sent\", null)]),\n        shifted, untouched: shifted[1] === items[1],\n      }));\n    ");
  assert.ok((eq(result["at5"], 2) && eq(result["at4"], 3)));
  assert.deepEqual(result["by"], [["a", [2, 3]], ["b", [-1, 0]], ["g", [0, 3]]]);
  assert.equal(result["notAllMoves"], null);
  assert.deepEqual(result["shifted"][0], {"id": "a", "box": [12, 13, 4, 4], "center": [14, 15], "handles": [{"kind": "size", "x": 16, "y": 15}, {"kind": "angle", "x": 3, "y": 4, "cx": 14, "cy": 15}]});
  assert.equal(result["untouched"], true);
});

test("the yaml tab sends against the version its text was typed over", async () => {
  // Text typed over version 1 is sent against version 1 even after a
  // change elsewhere (the inspector) made the face version 2, so the
  // server refuses it rather than overwrite that change; the author then
  // chooses. A pane with nothing unsent follows the change, and a late,
  // older face is ignored.
  const result = await run("\n      const v1 = {version: 1, text: \"a: 1\\n\"};\n      const v2 = {version: 2, text: \"a: 2\\n\"};\n      let s = textsync.initial(v1);\n      const typed = \"a: 1\\nb: 3\\n\";\n      const kept = textsync.follow(s, v2, typed);          // the inspector's change arrives\n      s = kept.state;\n      const send = textsync.plan(s, typed);\n      s = textsync.answered(s, typed, 409);\n      const waiting = textsync.plan(s, typed);\n      const whileConflict = textsync.follow(s, v2, typed).replace;\n      const mine = textsync.resolve(s, v2, \"mine\");\n      const theirs = textsync.resolve(s, v2, \"theirs\");\n      const resend = textsync.plan(mine.state, typed);\n      const saved = textsync.answered(mine.state, typed, 200, 3);\n      let clean = textsync.initial(v1);\n      const followed = textsync.follow(clean, v2, v1.text);\n      const late = textsync.follow(followed.state, v1, v2.text);\n      console.log(JSON.stringify({\n        keptReplace: kept.replace, send, waiting, whileConflict,\n        mineReplace: mine.replace, theirsReplace: theirs.replace, resend,\n        saved: [saved.acked === typed, saved.base, textsync.plan(saved, typed).kind],\n        followed: [followed.replace, followed.state.base],\n        late: [late.replace, late.state.base],\n      }));\n    ");
  assert.equal(result["keptReplace"], null);
  assert.deepEqual(result["send"], {"kind": "send", "text": "a: 1\nb: 3\n", "version": 1});
  assert.deepEqual(result["waiting"], {"kind": "wait"});
  assert.equal(result["whileConflict"], null);
  assert.ok((result["mineReplace"] === null && eq(result["theirsReplace"], "a: 2\n")));
  assert.deepEqual(result["resend"], {"kind": "send", "text": "a: 1\nb: 3\n", "version": 2});
  assert.deepEqual(result["saved"], [true, 3, "idle"]);
  assert.deepEqual(result["followed"], ["a: 2\n", 2]);
  assert.deepEqual(result["late"], [null, 2]);
});

test("the yaml tab holds text the server did not take", async () => {
  // Text that is not YAML, or whose send failed, is not sent again until
  // the author changes it: the pane does not poll the server with it.
  const result = await run("\n      let s = textsync.initial({version: 1, text: \"a: 1\\n\"});\n      const broken = \"a: [\";\n      const first = textsync.plan(s, broken).kind;\n      s = textsync.answered(s, broken, 400);\n      const again = textsync.plan(s, broken).kind;\n      const typedOn = textsync.plan(s, \"a: [1\").kind;\n      s = textsync.failed(s, \"a: [1]\");\n      const afterFailure = textsync.plan(s, \"a: [1]\").kind;\n      const retried = textsync.plan(textsync.retry(s), \"a: [1]\").kind;\n      s = textsync.answered(s, \"a: [1]\\n\", 200, 2);\n      console.log(JSON.stringify({first, again, typedOn, afterFailure, retried, held: s.held}));\n    ");
  assert.deepEqual(result, {"first": "send", "again": "held", "typedOn": "send", "afterFailure": "held", "retried": "send", "held": null});
});

test("leaving the yaml tab keeps text the server does not have", async () => {
  // Text that is not YAML, or waits on a conflict, is what the tab shows
  // again when it reopens, still unsaved; saved text is not kept, and the
  // face as it then is opens instead, however it changed meanwhile. A send
  // answered after the tab closed leaves nothing unsaved.
  const result = await run("\n      const v1 = {version: 1, text: \"a: 1\\n\"};\n      const v2 = {version: 2, text: \"a: 2\\n\"};\n      let s = textsync.initial(v1);\n      const broken = \"a: [\";\n      s = textsync.answered(s, broken, 400);\n      const held = textsync.closed(s, broken);\n      const heldBack = textsync.reopened(s, held.left, v2);\n\n      let c = textsync.answered(textsync.initial(v1), \"a: 1\\nb: 3\\n\", 409);\n      const waiting = textsync.closed(c, \"a: 1\\nb: 3\\n\");\n      const waitingBack = textsync.reopened(c, waiting.left, v2);\n\n      const clean = textsync.closed(textsync.initial(v1), v1.text);\n      const cleanBack = textsync.reopened(textsync.initial(v1), clean.left, v2);\n\n      const sending = textsync.closed(textsync.initial(v1), \"a: 5\\n\");\n      const answeredLate = textsync.answered(textsync.initial(v1), \"a: 5\\n\", 200, 2);\n      const lateBack = textsync.reopened(answeredLate, sending.left, {version: 2, text: \"a: 5\\n\"});\n      console.log(JSON.stringify({\n        held: [held.kind, held.left, heldBack.text, textsync.plan(heldBack.state, heldBack.text).kind],\n        waiting: [waiting.kind, waitingBack.text, textsync.plan(waitingBack.state, waitingBack.text).kind],\n        clean: [clean.kind, clean.left, cleanBack.text, textsync.plan(cleanBack.state, cleanBack.text).kind],\n        late: [sending.kind, sending.left, lateBack.text, textsync.plan(lateBack.state, lateBack.text).kind],\n      }));\n    ");
  assert.deepEqual(result["held"], ["held", "a: [", "a: [", "held"]);
  assert.deepEqual(result["waiting"], ["wait", "a: 1\nb: 3\n", "wait"]);
  assert.deepEqual(result["clean"], ["idle", null, "a: 2\n", "idle"]);
  assert.deepEqual(result["late"], ["send", "a: 5\n", "a: 5\n", "idle"]);
});

test("a conflict shows what the other change did", async () => {
  // The conflict banner's diff: the other change's lines, added and
  // removed, with two lines of context and a gap where more is left out.
  // A changed line reads as one removed and one added.
  const result = await run("\n      const base = [\"a: 1\", \"b: 2\", \"c: 3\", \"d: 4\", \"e: 5\", \"f: 6\", \"g: 7\", \"h: 8\"].join(\"\\n\");\n      const theirs = [\"a: 1\", \"b: 20\", \"c: 3\", \"d: 4\", \"e: 5\", \"f: 6\", \"g: 7\", \"h: 8\", \"i: 9\"].join(\"\\n\");\n      const ops = linediff.lineDiff(base, theirs);\n      const shown = linediff.hunks(ops).map((o) => o.op === \"gap\" ? \"~\" : o.op[0] + o.text);\n      console.log(JSON.stringify({\n        counts: linediff.diffCounts(ops), shown,\n        same: linediff.diffCounts(linediff.lineDiff(base, base)),\n        summaries: [linediff.changeSummary(linediff.diffCounts(ops)),\n                    linediff.changeSummary({added: 1, removed: 0}),\n                    linediff.changeSummary({added: 0, removed: 3}),\n                    linediff.changeSummary({added: 0, removed: 0})],\n      }));\n    ");
  assert.deepEqual(result["counts"], {"added": 2, "removed": 1});
  assert.deepEqual(result["shown"], ["sa: 1", "db: 2", "ab: 20", "sc: 3", "sd: 4", "~", "sg: 7", "sh: 8", "ai: 9"]);
  assert.deepEqual(result["same"], {"added": 0, "removed": 0});
  assert.deepEqual(result["summaries"], ["added 2 lines and removed 1 line", "added 1 line", "removed 3 lines", "left the text as it was"]);
});

test("a deleted face copies the text the author last had", async () => {
  // The deleted-face banner copies the YAML tab's text while it is open,
  // else the text it closed on unsaved, else the face as last heard of.
  const result = await run("\n      const doc = {text: \"face\\n\"};\n      console.log(JSON.stringify([\n        textsync.latestText(\"typing\\n\", \"left\\n\", doc),\n        textsync.latestText(null, \"left\\n\", doc),\n        textsync.latestText(null, null, doc),\n      ]));\n    ");
  assert.deepEqual(result, ["typing\n", "left\n", "face\n"]);
});

test("only a layer rows own drag reads as a path", async () => {
  const result = await run("\n      console.log(JSON.stringify({\n        path: treeMod.droppedPath('[\"elements\", \"clock\"]'),\n        notJson: treeMod.droppedPath(\"hello\"), empty: treeMod.droppedPath(\"\"),\n        object: treeMod.droppedPath('{\"a\": 1}'), none: treeMod.droppedPath(\"[]\"),\n        mixed: treeMod.droppedPath('[\"a\", 1.5]'),\n        ours: treeMod.carriesPath([treeMod.PATH_TYPE]),\n        file: treeMod.carriesPath([\"Files\", \"text/plain\"]),\n      }));\n    ");
  assert.deepEqual(result, {"path": ["elements", "clock"], "notJson": null, "empty": null, "object": null, "none": null, "mixed": null, "ours": true, "file": false});
});

test("delete acts on the whole selection", async () => {
  const result = await run("\n      const tree = [{kind: \"block\", path: [\"elements\"], children: [\n        {id: \"a\", type: \"text\", path: [\"elements\", \"a\"], children: []},\n        {id: \"g\", type: \"group\", path: [\"elements\", \"g\"], children: [\n          {id: \"b\", type: \"text\", path: [\"elements\", \"g\", \"children\", \"b\"], children: []}]}]}];\n      console.log(JSON.stringify({\n        one: treeMod.deleteOp(tree, [\"a\"]),\n        several: treeMod.deleteOp(tree, [\"b\", \"a\"]),\n        none: treeMod.deleteOp(tree, [\"zz\"]),\n      }));\n    ");
  assert.deepEqual(result, {"one": {"op": "delete", "path": ["elements", "a"]}, "several": {"op": "delete", "paths": [["elements", "a"], ["elements", "g", "children", "b"]]}, "none": null});
});

test("the top bar says whether the face is saved", async () => {
  const result = await run("\n      const s = outbox.saveState;\n      console.log(JSON.stringify([\n        s({}),\n        s({inflight: 1}),\n        s({queue: [{state: \"done\"}, {state: \"queued\"}]}),\n        s({queue: [{state: \"done\"}]}),\n        s({yaml: \"send\"}),\n        s({yaml: \"held\", inflight: 2}),\n        s({yaml: \"wait\"}),\n      ]));\n    ");
  assert.deepEqual(result, ["saved", "saving", "saving", "saved", "saving", "unsaved", "unsaved"]);
});

test("diagnostics are counted and filtered most severe first", async () => {
  const result = await run("\n      const items = [{severity: \"note\", m: 1}, {severity: \"error\", m: 2},\n                     {severity: \"warning\", m: 3}, {severity: \"error\", m: 4}];\n      console.log(JSON.stringify({\n        counts: values.severityCounts(items),\n        all: values.shownDiagnostics(items).map((d) => d.m),\n        errors: values.shownDiagnostics(items, \"error\").map((d) => d.m),\n      }));\n    ");
  assert.deepEqual(result, {"counts": {"error": 2, "warning": 1, "note": 1}, "all": [2, 4, 3, 1], "errors": [2, 4]});
});
