"""The editor front end's pure functions (`wfb/studio/static/hit.js`),
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
              f"import * as snap from {json.dumps((STATIC / 'snap.js').as_uri())};\n{script}")
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
        {kind: "block", line: 30, children: [
          {kind: "element", id: "z", line: 31, children: []},
        ]},
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
