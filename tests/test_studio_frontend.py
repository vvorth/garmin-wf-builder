"""The editor front end's pure functions (`wfb/studio/static/hit.js`),
run in Node when it is installed. The UI itself is checked by hand: there
is no headless browser here."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HIT = Path(__file__).resolve().parent.parent / "wfb/studio/static/hit.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run(script: str) -> object:
    source = f"import * as hit from {json.dumps(HIT.as_uri())};\n{script}"
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
