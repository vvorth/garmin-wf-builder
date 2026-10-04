"""The editor front end's pure functions (`wfb/studio/static/hit.js`,
`outbox.js`, `textsync.js` and the rest without a DOM),
run in Node when it is installed. The UI itself is checked by hand: there
is no headless browser here."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "wfb/studio/static"
HIT = STATIC / "hit.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run(script: str) -> object:
    source = (f"import * as hit from {json.dumps(HIT.as_uri())};\n"
              f"import * as values from {json.dumps((STATIC / 'values.js').as_uri())};\n"
              f"import * as snap from {json.dumps((STATIC / 'snap.js').as_uri())};\n"
              f"import * as treeMod from {json.dumps((STATIC / 'tree.js').as_uri())};\n"
              f"import * as zoom from {json.dumps((STATIC / 'zoom.js').as_uri())};\n"
              f"import * as outbox from {json.dumps((STATIC / 'outbox.js').as_uri())};\n"
              f"import * as textsync from {json.dumps((STATIC / 'textsync.js').as_uri())};\n{script}")
    out = subprocess.run(["node", "--input-type=module", "-e", source],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_topmost_picks_the_last_drawn_layer_with_ink():
    result = run("""
      const layers = [
        {id: "bg", box: [0, 0, 100, 100]},
        {id: "ring:g", box: [10, 10, 20, 20]},
        {id: "dot", box: [10, 10, 20, 20]},
        {id: "boxless", box: null},
      ];
      // ink: bg everywhere, ring:g everywhere in its box, dot only at (15, 15),
      // boxless nowhere
      const ink = (l, x, y) => l.id === "dot" ? (x === 15 && y === 15 ? 255 : 0)
                             : l.id === "boxless" ? 0 : 255;
      const reads = [];
      const counted = (l, x, y) => { reads.push(l.id); return ink(l, x, y); };
      console.log(JSON.stringify({
        onDot: hit.topmost(layers, 15, 15, ink).id,
        besideDot: hit.topmost(layers, 16, 15, ink).id,
        outside: hit.topmost(layers, 50, 50, ink).id,
        offScreen: hit.topmost(layers, 500, 500, ink),
        ring: hit.elementOf("ring:g"), plain: hit.elementOf("dot"),
        reads: (hit.topmost(layers, 50, 50, counted), reads),
      }));
    """)
    assert result == {
        "onDot": "dot", "besideDot": "ring:g", "outside": "bg", "offScreen": None,
        "ring": "g", "plain": "dot",
        # a layer whose box misses the point is never read
        "reads": ["boxless", "bg"],
    }


def test_element_at_line_is_the_deepest_holding_it():
    result = run("""
      const tree = [
        {kind: "block", line: 10, children: [
          {kind: "element", id: "a", line: 11, children: []},
          {kind: "element", id: "g", line: 15, children: [
            {kind: "element", id: "g1", line: 17, children: []},
            {kind: "element", id: "g2", line: 20, children: []},
          ]},
        ]},
        {kind: "block", line: null, children: []},
        {kind: "block", line: 30, children: [
          {kind: "element", id: "z", line: 31, children: []},
        ]},
        {kind: "block", line: null, children: []},
      ];
      const at = (n) => (hit.elementAtLine(tree, n) || {id: null}).id;
      console.log(JSON.stringify({
        lines: [10, 11, 14, 15, 16, 17, 19, 20, 29, 30, 31, 99].map(at),
        flat: hit.flatten(tree).map((n) => n.id),
      }));
    """)
    assert result == {
        "lines": [None, "a", "a", "g", "g", "g1", "g1", "g2", "g2", None, "z", "z"],
        "flat": ["a", "g", "g1", "g2", "z"],
    }


def test_a_quantity_keeps_the_authors_spelling():
    result = run("""
      const p = values.parseQuantity;
      const f = values.formatQuantity;
      console.log(JSON.stringify({
        parsed: [p("12%r", "px"), p(12, "px"), p(" -3.5 deg ", "deg"), p("1 + x", "px"), p(null, "px")],
        bareStays: f(14, "px", "px", true),
        bareGetsUnit: f(14, "%", "px", true),
        unitKept: f(14, "%r", "px", false),
        rounding: f(0.1 + 0.2, "%r", "px", false),
        nan: f(NaN, "px", "px", false),
      }));
    """)
    assert result == {
        "parsed": [{"number": 12, "unit": "%r", "bare": False},
                   {"number": 12, "unit": "px", "bare": True},
                   {"number": -3.5, "unit": "deg", "bare": False}, None, None],
        "bareStays": 14, "bareGetsUnit": "14%", "unitKept": "14%r", "rounding": "0.3%r",
        "nan": None,
    }


def test_colours_against_the_mip_palette():
    result = run("""
      console.log(JSON.stringify({
        hex: [values.parseHex("#5af"), values.parseHex("55AAFF"), values.parseHex("color.x")],
        legal: [values.mipLegal([0x55, 0xaa, 0xff]), values.mipLegal([0x12, 0x34, 0x56])],
        nearest: values.toHex(values.mipNearest([0x12, 0x34, 0x56])),
        name: [values.colorName("color.bg"), values.colorName("#FFF"), values.colorName("color.a + 1")],
        ids: [values.isIdentifier("ok_1"), values.isIdentifier("1x"), values.isIdentifier("a-b")],
      }));
    """)
    assert result == {
        "hex": [[85, 170, 255], [85, 170, 255], None],
        "legal": [True, False], "nearest": "#005555",
        "name": ["bg", None, None], "ids": [True, False, False],
    }


def test_a_new_style_is_shaped_like_the_others():
    result = run("""
      const n = values.newStyleEntry;
      console.log(JSON.stringify([
        n([{name: "a", layout: "big", scheme: "dark"}], ["big", "small"], ["dark", "light"]),
        n([{name: "a", scheme: "light"}], ["big"], ["dark", "light"]),
        n([{name: "a", layout: "small"}], ["big", "small"], []),
        n([], ["big"], ["dark"]),
        n([], [], ["dark"]),
      ]));
    """)
    assert result == [{"layout": "big", "scheme": "dark"}, {"scheme": "light"},
                      {"layout": "small"}, {"layout": "big"}, {"scheme": "dark"}]


def test_a_move_snaps_to_centres_edges_and_the_grid():
    result = run("""
      const items = [
        {id: "me", box: [100, 100, 20, 10], center: [110, 105]},
        {id: "other", box: [150, 40, 30, 30], center: [165, 55]},
      ];
      const t = snap.moveTargets(items, "me", 260, 260, 130, 5);
      const me = items[0];
      console.log(JSON.stringify({
        // centre x 110+18=128 is 2 from the screen centre 130
        toCentre: snap.snapMove(me, 18, 0, t, 4),
        // left edge 100+48=148 is 2 from the other's left edge 150
        toEdge: snap.snapMove(me, 48, 0, t, 4),
        // nothing within 4: whole pixels, no guide
        free: snap.snapMove({...me, box: [0, 0, 1, 1], center: [0, 0]}, 0.6, 0, {xs: [], ys: [], grid: 0, cx: 130, cy: 130}, 4),
        // no guide near: the centre to the grid of 5%r (6.5 px) about the
        // screen centre, 130 + 6.5k
        grid: snap.snapMove({id: "p", box: [140, 0, 0, 0], center: [140, 0]}, 3, 0, {xs: [], ys: [], grid: 6.5, cx: 130, cy: 130}, 4),
        // a guide beats the grid even when the grid is nearer
        guideFirst: snap.snapMove({id: "p", box: [140, 0, 0, 0], center: [140, 0]}, 3, 0, {xs: [146], ys: [], grid: 6.5, cx: 130, cy: 130}, 4),
        // an axis the drag did not move along stays put
        still: snap.snapMove(me, 18, 0.4, t, 4).dy,
        targets: [t.xs.length, t.grid],
      }));
    """)
    assert result["toCentre"] == {"dx": 20, "dy": 0, "guides": {"x": [130], "y": []}}
    assert result["toEdge"] == {"dx": 50, "dy": 0, "guides": {"x": [150], "y": []}}
    assert result["free"] == {"dx": 1, "dy": 0, "guides": {"x": [], "y": []}}
    assert result["grid"] == {"dx": 3, "dy": 0, "guides": {"x": [143], "y": []}}
    assert result["guideFirst"] == {"dx": 6, "dy": 0, "guides": {"x": [146], "y": []}}
    assert result["still"] == 0
    assert result["targets"] == [4, 6.5]


def test_a_selection_moves_together():
    result = run("""
      const tree = [{kind: "block", children: [
        {kind: "element", id: "g", children: [
          {kind: "element", id: "a", children: []},
          {kind: "element", id: "inner", children: [{kind: "element", id: "b", children: []}]},
        ]},
        {kind: "element", id: "c", children: []},
        {kind: "element", id: "d", children: []},
      ]}];
      const items = [
        {id: "g", kind: "group", box: [10, 10, 40, 40], center: [30, 30]},
        {id: "a", box: [10, 10, 10, 10], center: [15, 15]},
        {id: "c", box: [100, 100, 20, 20], center: [110, 110]},
        {id: "d", box: [200, 0, 10, 10], center: [205, 5]},
      ];
      const moving = hit.movedBy(tree, ["g", "c"]);
      const t = snap.moveTargets(items, moving, 260, 260, 130, 0);
      console.log(JSON.stringify({
        // a group carries every element inside it, however deep
        moving: [...moving].sort(),
        alone: [...hit.movedBy(tree, ["a"])],
        // the move handle: on the top edge of a group or of several, never
        // on one plain element, which is pressed on itself; kept on the
        // screen for a selection reaching its top
        gripSeveral: hit.moveHandle(items, ["g", "c"]),
        gripGroup: hit.moveHandle(items, ["g"]),
        gripTop: hit.moveHandle(items, ["g", "d"], 6),
        gripOne: hit.moveHandle(items, ["c"]),
        gripNone: hit.moveHandle(items, []),
        // the selection snaps as one box
        together: hit.together(items, ["g", "c"]),
        // nothing that moves is a snapping target; d is
        xs: t.xs,
      }));
    """)
    assert result["moving"] == ["a", "b", "c", "g", "inner"]
    assert result["alone"] == ["a"]
    assert result["gripSeveral"] == {"x": 65, "y": 10}
    assert result["gripGroup"] == {"x": 30, "y": 10}
    assert result["gripTop"] == {"x": 110, "y": 6}
    assert result["gripOne"] is None and result["gripNone"] is None
    assert result["together"] == {"id": "g", "box": [10, 10, 110, 110], "center": [65, 65],
                                  "handles": []}
    assert result["xs"] == [130, 200, 210, 205]


def test_angles_lengths_and_resizes_snap():
    result = run("""
      console.log(JSON.stringify({
        angles: [28, 33.5, 44, 47, 359].map(snap.snapAngle),
        at: [snap.angleAt(0, 0, 0, -10), snap.angleAt(0, 0, 10, 0), snap.angleAt(0, 0, 0, 10),
             snap.angleAt(0, 0, -10, 0)],
        turns: [snap.nearestTurn(10, 350), snap.nearestTurn(-80, 300), snap.nearestTurn(200, 190)],
        lengths: [snap.snapLength(25, 130, 5), snap.snapLength(29.5, 130, 5), snap.snapLength(29.5, 130, 0)],
        resize: [snap.resizeDelta({axis: "x", gain: 2}, 5, 9), snap.resizeDelta({axis: "y", gain: -1}, 5, 9)],
      }));
    """)
    assert result["angles"] == [30, 36, 42, 48, 360]
    assert [round(a) for a in result["at"]] == [0, 90, 180, 270]
    assert result["turns"] == [370, 280, 200]
    # the 5%r grid of a 130 px radius is 6.5 px: 25 -> 26, 29.5 -> 32.5 -> 33
    assert result["lengths"] == [26, 33, 30]
    assert result["resize"] == [10, -9]


def test_the_tree_offers_its_blocks_siblings_and_drop_zones():
    result = run("""
      const t = [
        {kind: "block", label: "static", path: ["static"], children: []},
        {kind: "block", label: "elements", path: ["elements"], children: [
          {kind: "element", id: "a", type: "text", path: ["elements", "a"], children: []},
          {kind: "element", id: "g", type: "group", path: ["elements", "g"], children: [
            {kind: "element", id: "c", type: "circle", path: ["elements", "g", "children", "c"], children: []},
          ]},
        ]},
      ];
      const b = treeMod.blocksOf(t);
      const g = b.nodes.find((n) => n.id === "g");
      const a = b.nodes.find((n) => n.id === "a");
      console.log(JSON.stringify({
        nodes: b.nodes.map((n) => n.id),
        destinations: b.destinations.map((d) => d.path.join(".")),
        siblings: [treeMod.siblingsOf(t, ["elements", "g"]), treeMod.siblingsOf(t, ["elements", "g", "children", "c"])],
        drops: [treeMod.dropTarget(a, 0.2, "g"), treeMod.dropTarget(a, 0.8, "g"), treeMod.dropTarget(g, 0.5, null),
                treeMod.dropTarget(g, 0.9, null)],
      }));
    """)
    assert result["nodes"] == ["a", "g", "c"]
    assert result["destinations"] == ["static", "elements", "elements.g.children"]
    assert result["siblings"] == [["a", "g"], ["c"]]
    assert result["drops"] == [
        {"where": "before", "target": {"block": ["elements"], "before": "a"}},
        {"where": "after", "target": {"block": ["elements"], "before": "g"}},
        {"where": "into", "target": {"block": ["elements", "g", "children"], "before": None}},
        {"where": "after", "target": {"block": ["elements"], "before": None}},
    ]


def test_the_vendored_editor_bundle_exports_what_the_yaml_tab_imports():
    source = (STATIC / "yaml.js").read_text()
    start = source.index("import {", source.index("preact-htm"))
    imported = source[start + len("import {"):source.index("}", start)]
    names = sorted(n.strip() for n in imported.split(",") if n.strip())
    result = run(f"""
      const m = await import({json.dumps((STATIC / 'vendor/codemirror.module.js').as_uri())});
      console.log(JSON.stringify({json.dumps(names)}.filter((n) => !(n in m))));
    """)
    assert names and result == []


def test_zoom_scale_and_real_size():
    result = run("""
      console.log(JSON.stringify({
        scales: [[0.3, 1], [1, 1], [1.01, 1], [2, 1], [0.5, 2], [1.5, 2], [3.9, 1], [5, 1]]
          .map(([z, dpr]) => zoom.serverScale(z, dpr)),
        clamp: [zoom.clampZoom(0.01), zoom.clampZoom(9), zoom.clampZoom(1.5)],
        real: [zoom.realZoom(200), zoom.realZoom(326), zoom.realZoom(null), zoom.realZoom(200, 120)],
        card: zoom.calibrate(323.53),
        mm: [zoom.screenMm(260, 200), zoom.screenMm(260, null)],
      }));
    """)
    assert result["scales"] == [1, 1, 2, 2, 1, 3, 4, 4]
    assert result["clamp"] == [0.2, 4, 1.5]
    real = result["real"]
    assert real[0] == 0.48 and abs(real[1] - 96 / 326) < 1e-9 and real[2] is None and real[3] == 0.6
    assert abs(result["card"] - 96) < 0.01          # 85.6 mm at 96 px per inch is 323.53 px
    assert abs(result["mm"][0] - 33.02) < 0.01 and result["mm"][1] is None


def test_a_picked_colour_is_named_and_snapped_as_the_compiler_does():
    from wfb.edit.colors import automatic_name
    from wfb.palette import MIP64_NAMED, Color

    mip = [{"name": n, "value": v, "label": label} for n, v, label in MIP64_NAMED]
    samples = ["#FF8000", "#FF5500", "#000000", "#123456", "#2E3A2E", "#2F4F4F", "#7A7A7A",
               "#767676", "#AAAAAA", "#FFFFFF", "#0F0F80", "#808000"]
    palette = [{"name": "bg", "value": "#000"}, {"name": "odd", "value": "nope"}]
    result = run(f"""
      const mip = {json.dumps(mip)};
      const samples = {json.dumps(samples)};
      console.log(JSON.stringify({{
        names: samples.map((s) => values.automaticName(values.parseHex(s), mip)),
        mono: samples.map((s) => values.toHex(values.safeOn(values.parseHex(s), [2]).nearest)),
        mip64: samples.map((s) => values.toHex(values.safeOn(values.parseHex(s), [64]).nearest)),
        ok: [values.safeOn([0x55, 0xaa, 0xff], [64, 65536]).ok, values.safeOn([1, 2, 3], [65536]).ok,
             values.safeOn([0x55, 0x55, 0x55], [2]).ok],
        held: values.swatchFor([0, 0, 0], {json.dumps(palette)}, mip),
        adds: values.swatchFor([255, 0, 0], {json.dumps(palette)}, mip),
      }}));
    """)
    assert result["names"] == [automatic_name(s) for s in samples]
    assert result["mono"] == [str(Color.parse(s).nearest_legal(2)) for s in samples]
    assert result["mip64"] == [str(Color.parse(s).nearest_legal(64)) for s in samples]
    assert result["ok"] == [True, True, False]
    assert result["held"] == {"name": "bg", "adds": False}
    assert result["adds"] == {"name": "red", "adds": True}


def test_the_showing_control_sends_only_what_differs_from_each_default():
    result = run("""
      const slots = [{name: "top", default: "steps"}, {name: "left", default: "vo2max_run"},
                     {name: "right", default: "date"}];
      console.log(JSON.stringify({
        none: values.picksParam({}, slots),
        some: values.picksParam({top: "steps", right: "battery", left: "heart_rate", gone: "x"}, slots),
        label: [values.typeLabel({complication_types: [{name: "steps", label: "Steps"}]}, "steps"),
                values.typeLabel({}, "steps")],
      }));
    """)
    assert result == {"none": "", "some": "left:heart_rate,right:battery",
                      "label": ["Steps", "steps"]}


def test_the_outbox_sends_one_at_a_time_and_folds_repeated_moves():
    """A held arrow key queues one move per repeat; while the first is on
    its way, the rest fold into one request. A move of other elements, or
    a resize, stays its own entry."""
    result = run("""
      const move = (ids, dx, dy) => ({ids, gesture: {kind: "move", part: "both", dx, dy},
                                      preview: {kind: "move", part: "both", dx, dy, guides: {x: [1], y: []}},
                                      moving: new Set(ids)});
      let q = outbox.enqueue([], move(["a"], 1, 0));
      const first = outbox.next(q);
      q = outbox.mark(q, first, "sent");
      const whileSent = outbox.next(q);
      q = outbox.enqueue(q, move(["a"], 1, 0));
      q = outbox.enqueue(q, move(["a"], 0, 10));
      q = outbox.enqueue(q, move(["b"], 1, 0));
      q = outbox.enqueue(q, {ids: ["b"], gesture: {kind: "resize", key: ["radius"], delta: 2},
                             preview: {kind: "resize"}, moving: new Set(["b"])});
      q = outbox.enqueue(q, move(["b"], 1, 0));
      q = outbox.enqueue(q, {...move(["b"], 1, 0), where: {device: "fr955"}});
      const shape = q.map((e) => [e.ids.join(), e.state, e.gesture.kind, e.gesture.dx ?? null,
                                  e.gesture.dy ?? null]);
      q = outbox.mark(q, q[0], "done", 7);
      console.log(JSON.stringify({
        first: first.gesture, whileSent, shape,
        folded: q[1].preview,
        nextAfterDone: outbox.next(q).gesture,
      }));
    """)
    assert result["first"] == {"kind": "move", "part": "both", "dx": 1, "dy": 0}
    assert result["whileSent"] is None
    assert result["shape"] == [
        ["a", "sent", "move", 1, 0],
        ["a", "queued", "move", 1, 10],
        ["b", "queued", "move", 1, 0],
        ["b", "queued", "resize", None, None],
        ["b", "queued", "move", 1, 0],
        # the same move written for another device stays apart
        ["b", "queued", "move", 1, 0],
    ]
    # the folded preview carries the sum, and no stale snapping guides
    assert result["folded"] == {"kind": "move", "part": "both", "dx": 1, "dy": 10}
    assert result["nextAfterDone"] == {"kind": "move", "part": "both", "dx": 1, "dy": 10}


def test_the_canvas_draws_what_a_frame_does_not_show_yet():
    """An entry stays drawn until a frame of the version it produced
    arrives; its moves add up per element, a group's children included, and
    the items they move are hit-tested where they will be."""
    result = run("""
      const e = (ids, moving, gesture, state, done) => ({ids, moving: new Set(moving), gesture, state, done});
      const mv = (dx, dy) => ({kind: "move", part: "both", dx, dy});
      const q = [e(["a"], ["a"], mv(2, 0), "done", 5), e(["g"], ["g", "a"], mv(0, 3), "sent", null),
                 e(["b"], ["b"], mv(-1, 0), "queued", null)];
      const at5 = outbox.unshown(q, 5), at4 = outbox.unshown(q, 4);
      const by = outbox.offsets(at4);
      const items = [{id: "a", box: [10, 10, 4, 4], center: [12, 12],
                      handles: [{kind: "size", x: 14, y: 12}, {kind: "angle", x: 1, y: 1, cx: 12, cy: 12}]},
                     {id: "c", box: [0, 0, 1, 1], center: [0, 0], handles: []}];
      const shifted = outbox.shiftItems(items, by);
      console.log(JSON.stringify({
        at5: at5.length, at4: at4.length,
        by: [...by.entries()].sort(),
        notAllMoves: outbox.offsets([e(["a"], ["a"], {kind: "resize", delta: 1}, "sent", null)]),
        shifted, untouched: shifted[1] === items[1],
      }));
    """)
    assert result["at5"] == 2 and result["at4"] == 3
    assert result["by"] == [["a", [2, 3]], ["b", [-1, 0]], ["g", [0, 3]]]
    assert result["notAllMoves"] is None
    assert result["shifted"][0] == {
        "id": "a", "box": [12, 13, 4, 4], "center": [14, 15],
        "handles": [{"kind": "size", "x": 16, "y": 15},
                    {"kind": "angle", "x": 3, "y": 4, "cx": 14, "cy": 15}],
    }
    assert result["untouched"] is True


def test_the_yaml_tab_sends_against_the_version_its_text_was_typed_over():
    """Text typed over version 1 is sent against version 1 even after a
    change elsewhere (the inspector) made the face version 2, so the
    server refuses it rather than overwrite that change; the author then
    chooses. A pane with nothing unsent follows the change, and a late,
    older face is ignored."""
    result = run("""
      const v1 = {version: 1, text: "a: 1\\n"};
      const v2 = {version: 2, text: "a: 2\\n"};
      let s = textsync.initial(v1);
      const typed = "a: 1\\nb: 3\\n";
      const kept = textsync.follow(s, v2, typed);          // the inspector's change arrives
      s = kept.state;
      const send = textsync.plan(s, typed);
      s = textsync.answered(s, typed, 409);
      const waiting = textsync.plan(s, typed);
      const whileConflict = textsync.follow(s, v2, typed).replace;
      const mine = textsync.resolve(s, v2, "mine");
      const theirs = textsync.resolve(s, v2, "theirs");
      const resend = textsync.plan(mine.state, typed);
      const saved = textsync.answered(mine.state, typed, 200, 3);
      let clean = textsync.initial(v1);
      const followed = textsync.follow(clean, v2, v1.text);
      const late = textsync.follow(followed.state, v1, v2.text);
      console.log(JSON.stringify({
        keptReplace: kept.replace, send, waiting, whileConflict,
        mineReplace: mine.replace, theirsReplace: theirs.replace, resend,
        saved: [saved.acked === typed, saved.base, textsync.plan(saved, typed).kind],
        followed: [followed.replace, followed.state.base],
        late: [late.replace, late.state.base],
      }));
    """)
    assert result["keptReplace"] is None
    assert result["send"] == {"kind": "send", "text": "a: 1\nb: 3\n", "version": 1}
    assert result["waiting"] == {"kind": "wait"}
    assert result["whileConflict"] is None
    assert result["mineReplace"] is None and result["theirsReplace"] == "a: 2\n"
    assert result["resend"] == {"kind": "send", "text": "a: 1\nb: 3\n", "version": 2}
    assert result["saved"] == [True, 3, "idle"]
    assert result["followed"] == ["a: 2\n", 2]
    assert result["late"] == [None, 2]


def test_the_yaml_tab_holds_text_the_server_did_not_take():
    """Text that is not YAML, or whose send failed, is not sent again until
    the author changes it: the pane does not poll the server with it."""
    result = run("""
      let s = textsync.initial({version: 1, text: "a: 1\\n"});
      const broken = "a: [";
      const first = textsync.plan(s, broken).kind;
      s = textsync.answered(s, broken, 400);
      const again = textsync.plan(s, broken).kind;
      const typedOn = textsync.plan(s, "a: [1").kind;
      s = textsync.failed(s, "a: [1]");
      const afterFailure = textsync.plan(s, "a: [1]").kind;
      s = textsync.answered(s, "a: [1]\\n", 200, 2);
      console.log(JSON.stringify({first, again, typedOn, afterFailure, held: s.held}));
    """)
    assert result == {"first": "send", "again": "held", "typedOn": "send",
                      "afterFailure": "held", "held": None}


def test_only_a_layer_rows_own_drag_reads_as_a_path():
    result = run("""
      console.log(JSON.stringify({
        path: treeMod.droppedPath('["elements", "clock"]'),
        notJson: treeMod.droppedPath("hello"), empty: treeMod.droppedPath(""),
        object: treeMod.droppedPath('{"a": 1}'), none: treeMod.droppedPath("[]"),
        mixed: treeMod.droppedPath('["a", 1.5]'),
        ours: treeMod.carriesPath([treeMod.PATH_TYPE]),
        file: treeMod.carriesPath(["Files", "text/plain"]),
      }));
    """)
    assert result == {"path": ["elements", "clock"], "notJson": None, "empty": None,
                      "object": None, "none": None, "mixed": None, "ours": True, "file": False}
