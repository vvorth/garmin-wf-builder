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


# -- the JSON form: every element of the corpus -----------------------------------------

DRAW_RUNNER = """
import * as raster from %s;
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { inflateSync } from "node:zlib";
const job = JSON.parse(readFileSync(0, "utf8"));
const tiles = raster.unpackTiles(new Uint8Array(inflateSync(Buffer.from(job.tiles, "base64"))),
                                 job.index);
const out = [];
for (const el of job.elements) {
  const hashes = [];
  for (const ground of [[0, 0, 0], [255, 255, 255]]) {
    const im = raster.image(job.width, job.height, ground);
    raster.drawOps(im, el.ops, tiles, job.scale);
    const rgb = Buffer.alloc(im.width * im.height * 3);
    for (let i = 0, j = 0; i < im.data.length; i += 4, j += 3) {
      rgb[j] = im.data[i]; rgb[j + 1] = im.data[i + 1]; rgb[j + 2] = im.data[i + 2];
    }
    hashes.push(createHash("md5").update(rgb).digest("hex"));
  }
  out.push(hashes);
}
console.log(JSON.stringify({ hashes: out, ops: raster.OPS }));
"""

CORPUS_DEVICES = ("fenix8solar47mm", "fr955")
CORPUS = sorted(p for p in (Path(__file__).resolve().parent.parent / "examples").rglob("face.yaml")
                if "dashboard" not in p.parts)


def _frames(resolved):
    from wfb import preview

    out = [preview.PreviewOptions(scale=2, quantise=False, mask_shape=False)]
    if any(p.element.aod is not None for p in resolved.items):
        out.append(preview.PreviewOptions(scale=2, quantise=False, mask_shape=False,
                                          aod=True, aod_mask=False))
    return out


@pytest.mark.parametrize("path", CORPUS, ids=lambda p: str(p.parent.name))
def test_the_browser_paints_every_element_as_rasterise_does(db, path):
    """Every lowered element of the face on two devices, awake and always-on,
    over black and over white: `raster.drawOps` equals
    `jsonform.rasterise` byte for byte, text and icons included."""
    import base64

    from tests.helpers import resolved_example
    from wfb import preview
    from wfb.draw.jsonform import BROWSER_OPS, Tiles, rasterise, to_json

    checked = 0
    for device in CORPUS_DEVICES:
        resolved = resolved_example(path, db, device)
        for options in _frames(resolved):
            entry = preview._resolve_style_entry(resolved.face, options.style)
            values = preview.sample_values(resolved, options, entry)
            tiles = Tiles()
            elements, want = [], []
            for placed in preview.frame_items(resolved, options, entry):
                probe = preview.new_renderer(resolved, options, values, (0, 0, 0))
                if not probe.shows(placed):
                    continue
                ops, _ = to_json(probe, placed, tiles)
                assert {op["op"] for op in ops} <= BROWSER_OPS, (placed.id, ops)
                hashes = []
                for ground in ((0, 0, 0), (255, 255, 255)):
                    r = preview.new_renderer(resolved, options, values, ground)
                    rasterise(ops, tiles, r)
                    hashes.append(hashlib.md5(r.image.tobytes()).hexdigest())
                elements.append({"id": placed.id, "ops": ops})
                want.append(hashes)
            packed, index = tiles.pack()
            job = {"width": probe.image.width, "height": probe.image.height, "scale": 2,
                   "tiles": base64.b64encode(packed).decode(), "index": index,
                   "elements": [{"ops": e["ops"]} for e in elements]}
            source = DRAW_RUNNER % json.dumps(RASTER.as_uri())
            out = subprocess.run([node(), "--input-type=module", "-e", source],
                                 input=json.dumps(job), capture_output=True, text=True,
                                 check=True)
            result = json.loads(out.stdout)
            assert set(result["ops"]) == BROWSER_OPS
            for element, got, expected in zip(elements, result["hashes"], want):
                assert got == expected, (path.parent.name, device, options.aod, element["id"])
                checked += 1
    assert checked, path


def test_runs_paste_as_pillow_pastes(db):
    """What the corpus never shows: tiles hanging off every edge, a
    translucent RGBA tile, and a box (text with no glyphs to draw)."""
    import base64

    from tests.helpers import resolved_example
    from wfb import preview
    from wfb.draw.jsonform import Tiles, rasterise

    resolved = resolved_example(CORPUS[0], db, "fr955")
    options = preview.PreviewOptions(scale=2, quantise=False, mask_shape=False)
    values = preview.sample_values(resolved, options, None)
    rng = random.Random(31)
    tiles = Tiles()
    run = []
    for i in range(60):
        w, h = rng.randint(1, 30), rng.randint(1, 30)
        if i % 3:
            image = Image.frombytes("L", (w, h), bytes(rng.randrange(256) for _ in range(w * h)))
        else:
            image = Image.frombytes("RGBA", (w, h),
                                    bytes(rng.randrange(256) for _ in range(w * h * 4)))
        run.append({"tile": tiles.add(image), "x": rng.randint(-40, 560), "y": rng.randint(-40, 560)})
    # and one straddling each edge and each corner, half on, half off
    width, height = 520, 520                      # fr955 at 2x
    ax, ay = 7, 2                                 # floor(3.75 * 2), floor(1 * 2)
    edge = Image.frombytes("L", (10, 10), bytes(rng.randrange(1, 256) for _ in range(100)))
    for x in (-5, (width - 10) // 2, width - 5):
        for y in (-5, (height - 10) // 2, height - 5):
            run.append({"tile": tiles.add(edge), "x": x - ax, "y": y - ay})
    run.append({"box": [-5, 30, 600, 40], "rgb": [64, 64, 64]})
    ops = [{"op": "color", "rgb": [200, 100, 50]},
           {"op": "text", "x": {"const": "T_X", "value": 3.75, "add": 0}, "y": 1, "run": run}]
    hashes = []
    for ground in ((0, 0, 0), (255, 255, 255)):
        r = preview.new_renderer(resolved, options, values, ground)
        assert r.image.size == (width, height)
        rasterise(ops, tiles, r)
        hashes.append(hashlib.md5(r.image.tobytes()).hexdigest())
    packed, index = tiles.pack()
    job = {"width": r.image.width, "height": r.image.height, "scale": 2,
           "tiles": base64.b64encode(packed).decode(), "index": index,
           "elements": [{"ops": ops}]}
    out = subprocess.run([node(), "--input-type=module", "-e",
                          DRAW_RUNNER % json.dumps(RASTER.as_uri())],
                         input=json.dumps(job), capture_output=True, text=True, check=True)
    assert json.loads(out.stdout)["hashes"][0] == hashes


INK_RUNNER = """
import * as raster from %s;
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
const job = JSON.parse(readFileSync(0, "utf8"));
const tiles = await raster.inflateTiles(job.tiles);
const out = job.layers.map((ops) => {
  const ink = raster.inkOf(ops, tiles, job.width, job.height, job.scale);
  return { box: ink.box, md5: createHash("md5").update(ink.mask).digest("hex") };
});
console.log(JSON.stringify(out));
"""


@pytest.mark.parametrize("path", CORPUS, ids=lambda p: str(p.parent.name))
def test_the_browsers_ink_is_the_servers_layer_alpha(db, path):
    """Hit-testing reads where a layer has ink: `raster.inkOf`, from the
    layer's JSON drawn on two grounds, equals the server's own layer image
    (`wfb.draw.layers`, matted from two grounds) wherever its alpha is not
    zero, pixel for pixel."""
    import base64

    from tests.helpers import resolved_example
    from wfb import preview
    from wfb.draw.layers import layers

    resolved = resolved_example(path, db, "fr955")
    options = preview.PreviewOptions(scale=2)
    stack = [l for l in layers(resolved, options) if l.ops is not None]
    tiles = stack[0].tiles if stack else None
    want = []
    for layer in stack:
        assert layer.image is not None
        alpha = layer.image.getchannel("A").point(lambda v: 1 if v else 0)
        box = alpha.getbbox()
        want.append({"box": list(box) if box else None,
                     "md5": hashlib.md5(alpha.crop(box).tobytes() if box else b"").hexdigest()})
    packed, index = tiles.pack() if tiles is not None else (b"", {})
    job = {"width": 520, "height": 520, "scale": 2, "layers": [l.ops for l in stack],
           "tiles": {"data": base64.b64encode(packed).decode(), "index": index}}
    out = subprocess.run([node(), "--input-type=module", "-e",
                          INK_RUNNER % json.dumps(RASTER.as_uri())],
                         input=json.dumps(job), capture_output=True, text=True, check=True)
    got = json.loads(out.stdout)
    for layer, g, w in zip(stack, got, want):
        assert g == w, (path.parent.name, layer.id)


MOVE_RUNNER = """
import * as raster from %s;
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
const job = JSON.parse(readFileSync(0, "utf8"));
const numbers = (x, out = []) => {
  if (Array.isArray(x)) x.forEach((v) => numbers(v, out));
  else if (x && typeof x === "object") {
    if ("const" in x && "value" in x) out.push(x.value + x.add);
    // a text's or icon's layout box and origin are not drawn: its run is
    else for (const [k, v] of Object.entries(x)) {
      if (k !== "tile" && k !== "box" && k !== "origin") numbers(v, out);
    }
  } else if (typeof x === "number") out.push(x);
  return out;
};
const out = [];
for (const pair of job.pairs) {
  const tiles = await raster.inflateTiles(pair.tiles);
  const draw = (ops) => {
    const im = raster.image(job.width, job.height, [0, 0, 0]);
    raster.drawOps(im, ops, tiles, job.scale);
    return createHash("md5").update(im.data).digest("hex");
  };
  const moved = raster.translateOps(pair.before, job.dx, job.dy);
  const a = numbers(moved), b = numbers(pair.after);
  // a run's offsets are frame pixels, everything else device pixels
  const worst = a.length === b.length ? Math.max(0, ...a.map((v, i) => Math.abs(v - b[i]))) : Infinity;
  out.push({ same: draw(moved) === draw(pair.after), worst });
}
console.log(JSON.stringify(out));
"""

MOVED_FACES = [Path(__file__).resolve().parent.parent / f"examples/{name}/face.yaml" for name in (
    "features/shapes", "features/align", "features/rings", "features/progress",
    "features/slots", "features/patterns", "features/analog", "features/graph",
    "features/vector-text", "showcase")]


def test_a_move_drawn_in_the_browser_is_the_servers_move(db):
    """During a move the canvas draws each moved element's ops translated
    (`raster.translateOps`). Against the server's own JSON after the real
    edit (`wfb.edit.move`, landed): every number within one device pixel
    (a `%` box re-rounds its edges where it lands; a run's offsets, in frame
    pixels, at most 2), and most elements drawn identically."""
    import base64

    from wfb import preview
    from wfb.draw.jsonform import Tiles, to_json
    from wfb.edit import Refused, View, move
    from wfb.edit.gate import load_text

    device = db.get("fr955")

    def ops_of(resolved, element_id, tiles):
        options = preview.PreviewOptions(scale=2)
        values = preview.sample_values(resolved, options, None)
        for placed in preview.frame_items(resolved, options, None):
            if placed.id == element_id:
                r = preview.new_renderer(resolved, options, values, (0, 0, 0))
                return to_json(r, placed, tiles)[0] if r.shows(placed) else None
        return None

    pairs, labels = [], []
    for path in MOVED_FACES:
        view = View(path, path.read_text(), device)
        for placed in view.resolved.items:
            if placed.kind == "group":
                continue
            tiles = Tiles()
            before = ops_of(view.resolved, placed.id, tiles)
            if not before:
                continue
            try:
                converted = move(view, placed.id, 5, -3)
            except Refused:
                continue
            if not converted.landed:
                continue
            after = ops_of(view.place(load_text(path, converted.patch.text)), placed.id, tiles)
            packed, index = tiles.pack()
            pairs.append({"before": before, "after": after,
                          "tiles": {"data": base64.b64encode(packed).decode(), "index": index}})
            labels.append(f"{path.parent.name}/{placed.id}")
    job = {"width": 520, "height": 520, "scale": 2, "dx": 5, "dy": -3, "pairs": pairs}
    out = json.loads(subprocess.run(
        [node(), "--input-type=module", "-e", MOVE_RUNNER % json.dumps(RASTER.as_uri())],
        input=json.dumps(job), capture_output=True, text=True, check=True).stdout)
    far = [(label, r["worst"]) for label, r in zip(labels, out) if r["worst"] > 2]
    assert not far, far
    same = sum(r["same"] for r in out)
    assert same >= 0.85 * len(out), f"{same} of {len(out)} drawn identically"
