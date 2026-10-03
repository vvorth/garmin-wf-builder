"""`wfb/studio/static/raster.js` against Pillow itself: every primitive the
draw program's JSON form uses, swept over sizes, widths, angles, odd and
even extents, fractional and off-canvas coordinates, drawn by both and
compared byte for byte.

This is the only guard on the browser's rasteriser, so it fails rather
than skips without Node (a skip once turned the goldens off silently)."""

from __future__ import annotations

import hashlib
import json
import random
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

RASTER = Path(__file__).resolve().parent.parent / "wfb/studio/static/raster.js"
GROUND = (10, 20, 30)
INK = (250, 128, 3)

RUNNER = """
import * as raster from %s;
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
const cases = JSON.parse(readFileSync(0, "utf8"));
const out = [];
for (const c of cases) {
  const im = raster.image(c.size[0], c.size[1], %s);
  try {
    const a = c.args;
    if (c.op === "rectangle") raster.rectangle(im, a.xy, a.style);
    else if (c.op === "ellipse") raster.ellipse(im, a.xy, a.style);
    else if (c.op === "arc") raster.arc(im, a.xy, a.start, a.end, a.color, a.width);
    else if (c.op === "line") raster.line(im, a.xy, a.color, a.width);
    else if (c.op === "polygon") raster.polygon(im, a.points, a.color);
    else if (c.op === "rounded_rectangle") raster.roundedRectangle(im, a.xy, a.radius, a.style);
    const rgb = Buffer.alloc(im.width * im.height * 3);
    for (let i = 0, j = 0; i < im.data.length; i += 4, j += 3) {
      rgb[j] = im.data[i]; rgb[j + 1] = im.data[i + 1]; rgb[j + 2] = im.data[i + 2];
    }
    out.push(createHash("md5").update(rgb).digest("hex"));
  } catch (e) {
    out.push("error: " + e.message);
  }
}
console.log(JSON.stringify(out));
"""


def node() -> str:
    found = shutil.which("node")
    if found is None:
        pytest.fail("Node is needed for the browser rasteriser's tests: install Node "
                    "(./tools/setup-env.sh says how) -- this test fails rather than skips")
    return found


def run_js(cases: list[dict[str, Any]]) -> list[str]:
    source = RUNNER % (json.dumps(RASTER.as_uri()), json.dumps(list(GROUND)))
    out = subprocess.run([node(), "--input-type=module", "-e", source],
                         input=json.dumps(cases), capture_output=True, text=True, check=True)
    result: list[str] = json.loads(out.stdout)
    return result


def run_pillow(case: dict[str, Any]) -> str:
    im = Image.new("RGB", tuple(case["size"]), GROUND)
    draw = ImageDraw.Draw(im)
    a = case["args"]
    try:
        if case["op"] == "rectangle":
            draw.rectangle(a["xy"], **_style(a["style"]))
        elif case["op"] == "ellipse":
            draw.ellipse(a["xy"], **_style(a["style"]))
        elif case["op"] == "arc":
            draw.arc(a["xy"], a["start"], a["end"], fill=tuple(a["color"]), width=a["width"])
        elif case["op"] == "line":
            draw.line(a["xy"], fill=tuple(a["color"]), width=a["width"])
        elif case["op"] == "polygon":
            draw.polygon([tuple(p) for p in a["points"]], fill=tuple(a["color"]))
        elif case["op"] == "rounded_rectangle":
            draw.rounded_rectangle(a["xy"], radius=a["radius"], **_style(a["style"]))
    except (ValueError, TypeError) as exc:
        return f"error: {exc}"
    return hashlib.md5(im.tobytes()).hexdigest()


def _style(style: dict[str, Any]) -> dict[str, Any]:
    return {k: tuple(v) if isinstance(v, list) else v for k, v in style.items()}


# -- the sweep ------------------------------------------------------------------------

def _coord(rng: random.Random, span: int) -> float:
    """A coordinate: mostly whole, sometimes a half or an odd fraction, now
    and then off the canvas."""
    v = rng.uniform(-span * 0.2, span * 1.2)
    kind = rng.random()
    if kind < 0.5:
        return float(round(v))
    if kind < 0.75:
        return round(v) + 0.5
    return round(v, 3)


def _box(rng: random.Random, span: int) -> list[float]:
    x0, y0 = _coord(rng, span), _coord(rng, span)
    w, h = abs(_coord(rng, span // 2)), abs(_coord(rng, span // 2))
    if rng.random() < 0.3:
        h = w                     # a circle
    return [x0, y0, x0 + w, y0 + h]


def _style_for(rng: random.Random) -> dict[str, Any]:
    if rng.random() < 0.5:
        return {"fill": list(INK)}
    return {"outline": list(INK), "width": rng.choice([1, 1, 2, 3, 4, 6])}


def cases(seed: int = 28, per_op: int = 400) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    out: list[dict[str, Any]] = []
    for _ in range(per_op):
        span = rng.choice([24, 64, 64, 160])
        size = [span, span]
        out.append({"op": "rectangle", "size": size,
                    "args": {"xy": _box(rng, span), "style": _style_for(rng)}})
        out.append({"op": "ellipse", "size": size,
                    "args": {"xy": _box(rng, span), "style": _style_for(rng)}})
        start = rng.choice([0, 90, 180, 270, -90, rng.uniform(-400, 400),
                            round(rng.uniform(-360, 360)) + 0.5])
        end = rng.choice([start + rng.uniform(0, 360), start + 360, start,
                          round(rng.uniform(-360, 720)), start - rng.uniform(0, 90)])
        out.append({"op": "arc", "size": size,
                    "args": {"xy": _box(rng, span), "start": start, "end": end,
                             "color": list(INK), "width": rng.choice([1, 2, 3, 5, 8])}})
        out.append({"op": "line", "size": size,
                    "args": {"xy": [_coord(rng, span) for _ in range(4)], "color": list(INK),
                             "width": rng.choice([1, 1, 2, 3, 4, 7])}})
        n = rng.choice([3, 3, 4, 4, 5, 6, 8])
        points = [[_coord(rng, span), _coord(rng, span)] for _ in range(n)]
        if rng.random() < 0.3:    # an axis-aligned run, as a hand's or tick's
            points[1][1] = points[0][1]
            points[2][1] = points[1][1]
        out.append({"op": "polygon", "size": size,
                    "args": {"points": points, "color": list(INK)}})
        xy = _box(rng, span)
        out.append({"op": "rounded_rectangle", "size": size,
                    "args": {"xy": xy, "radius": rng.choice([0, 1, 2, 3.5, 6, 12, 40]),
                             "style": _style_for(rng)}})
    return out


def _compare(all_cases: list[dict[str, Any]]) -> tuple[Counter[str], Counter[str], list[Any]]:
    js = run_js(all_cases)
    total: Counter[str] = Counter()
    bad: Counter[str] = Counter()
    misses: list[Any] = []
    for case, got in zip(all_cases, js):
        total[case["op"]] += 1
        want = run_pillow(case)
        if want.startswith("error") and got.startswith("error"):
            continue              # both refuse it, as the binding does
        if got != want:
            bad[case["op"]] += 1
            misses.append((case, want[:40], got[:40]))
    return total, bad, misses


def test_every_primitive_draws_what_pillow_draws():
    total, bad, misses = _compare(cases())
    assert not bad, (f"{dict(bad)} of {dict(total)} differ from Pillow; first: "
                     + json.dumps(misses[:3], default=str))


def small_ellipses_and_arcs() -> list[dict[str, Any]]:
    """Every ellipse up to 31 x 31 filled and ringed, and arcs at fractional
    angles: the integer ellipse's every tie, and the angles' float32."""
    rng = random.Random(30)
    out: list[dict[str, Any]] = []
    for a in range(32):
        for b in range(0, 32, 3):
            xy = [3, 5, 3 + a, 5 + b]
            out.append({"op": "ellipse", "size": [40, 40],
                        "args": {"xy": xy, "style": {"fill": list(INK)}}})
            out.append({"op": "ellipse", "size": [40, 40],
                        "args": {"xy": xy, "style": {"outline": list(INK),
                                                     "width": 1 + (a + b) % 3}}})
    for _ in range(600):
        r = rng.randint(4, 30)
        start = rng.uniform(-720, 720)
        out.append({"op": "arc", "size": [64, 64],
                    "args": {"xy": [32 - r, 32 - r, 32 + r, 32 + rng.choice([r, r - 3, r + 2])],
                             "start": start, "end": start + rng.uniform(-30, 400),
                             "color": list(INK), "width": rng.choice([1, 2, 4])}})
    return out


def test_small_ellipses_and_fractional_arcs():
    total, bad, misses = _compare(small_ellipses_and_arcs())
    assert not bad, f"{dict(bad)} of {dict(total)} differ; first: {misses[:2]}"


def test_large_shapes_at_the_editors_scale():
    """A 454 px screen at 3x: radii and polygons far past the small sweep."""
    rng = random.Random(29)
    big: list[dict[str, Any]] = []
    for _ in range(30):
        span = 1362
        big.append({"op": "ellipse", "size": [span, span],
                    "args": {"xy": _box(rng, span), "style": _style_for(rng)}})
        big.append({"op": "arc", "size": [span, span],
                    "args": {"xy": _box(rng, span), "start": rng.uniform(-180, 180),
                             "end": rng.uniform(-180, 540), "color": list(INK),
                             "width": rng.choice([2, 6, 12])}})
        big.append({"op": "polygon", "size": [span, span],
                    "args": {"points": [[_coord(rng, span), _coord(rng, span)] for _ in range(5)],
                             "color": list(INK)}})
    total, bad, misses = _compare(big)
    assert not bad, f"{dict(bad)} of {dict(total)} differ; first: {misses[:2]}"


def test_a_broken_primitive_is_caught():
    """The comparison can fail: Pillow's ellipse drawn one pixel wider does
    not hash the same."""
    case = {"op": "ellipse", "size": [64, 64],
            "args": {"xy": [10, 10, 40, 30], "style": {"fill": list(INK)}}}
    wider = {**case, "args": {**case["args"], "xy": [10, 10, 41, 30]}}
    assert run_js([case])[0] == run_pillow(case)
    assert run_js([case])[0] != run_pillow(wider)
