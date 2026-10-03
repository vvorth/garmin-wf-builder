"""Plan 28 slice 2's measurement: what a frame costs now that it carries its
layers as JSON, against the frame plus the separate layers request before.

On each face's first target at 2x, in-process, warm, best of three:
- the server: building the frame's response as it is now (the render,
  the items, every layer's JSON, the packed tiles, a PNG only for a layer
  the browser does not draw), against the old pair (the render and items,
  then `wfb.draw.layers` painting every element twice, as PNGs);
- the bytes each sends;
- the browser, in Node: inflating the tiles, drawing the whole frame from
  its layers (what a move draws on every pointer move) and one layer's ink
  (what a press works out once per layer).

Run from the repo root:  PYTHONPATH=. .venv/bin/python \
    docs/research/probes/browser-renderer/frame_cost.py
"""

from __future__ import annotations

import base64
import io
import json
import subprocess
import tempfile
import time
from pathlib import Path

from wfb.devices import DeviceDatabase
from wfb.draw.layers import layers
from wfb.studio.bundle import from_path
from wfb.studio.document import FrameKey, Studio
from wfb.studio.store import Store

ROOT = Path(__file__).resolve().parents[4]
RASTER = ROOT / "wfb/studio/static/raster.js"
FACES = ["features/progress", "features/shapes", "showcase", "features/vector-text",
         "generated_by_skill/trail-utility"]

RUNNER = """
import * as raster from %s;
import { readFileSync } from "node:fs";
const f = JSON.parse(readFileSync(0, "utf8"));
const best = (fn) => { let b = Infinity; for (let i = 0; i < 5; i++) { const t = performance.now(); fn(); b = Math.min(b, performance.now() - t); } return b; };
let t = performance.now();
const tiles = await raster.inflateTiles(f.tiles);
const inflate = performance.now() - t;
const W = f.width * f.scale, H = f.height * f.scale;
const json = f.layers.filter((l) => l.ops);
const frame = best(() => {
  const im = raster.image(W, H, [0, 0, 0]);
  for (const l of json) raster.drawOps(im, l.ops, tiles, f.scale);
});
const inks = json.map((l) => best(() => raster.inkOf(l.ops, tiles, W, H, f.scale)));
console.log(JSON.stringify({ inflate, frame, ink: Math.max(...inks), inkAll: inks.reduce((a, b) => a + b, 0) }));
"""


def _png_bytes(image) -> int:
    buf = io.BytesIO()
    image.save(buf, format="PNG", compress_level=1)
    return len(base64.b64encode(buf.getvalue()))


def main() -> None:
    db = DeviceDatabase.discover()
    tmp = Path(tempfile.mkdtemp())
    studio = Studio(Store(tmp / "state"), db, scratch=tmp / "scratch")
    print("| face | frame now ms | frame + layers before ms | KB now | KB before | "
          "browser: inflate ms | a move's frame ms | slowest ink ms | every ink ms |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    try:
        for name in FACES:
            bundle, moved = from_path(ROOT / "examples" / name / "face.yaml")
            doc = studio.create(bundle, "open", moved)
            device = doc.summary()["targets"][0]
            key = FrameKey(device, scale=2)
            doc.frame(key)                                 # warm: fonts, analysis
            now = []
            for _ in range(3):
                doc._frames.clear()
                t0 = time.perf_counter()
                shown = doc.frame(key)
                now.append((time.perf_counter() - t0) * 1000)
            # before: the frame without its layers, then every layer painted
            resolved, options = doc._placed(key)
            before = []
            for _ in range(3):
                t0 = time.perf_counter()
                stack = layers(resolved, options)
                pngs = sum(_png_bytes(l.image.crop(l.image.getchannel("A").getbbox()))
                           for l in stack if l.image is not None and l.image.getchannel("A").getbbox())
                before.append((time.perf_counter() - t0) * 1000)
            frame_only = {k: v for k, v in shown.items() if k not in ("layers", "tiles")}
            kb_now = len(json.dumps(shown)) / 1024
            kb_before = (len(json.dumps(frame_only)) + pngs) / 1024
            # the render alone, for the old frame's own share
            t0 = time.perf_counter()
            from wfb.preview import render
            render(resolved, options)
            render_ms = (time.perf_counter() - t0) * 1000
            out = json.loads(subprocess.run(
                ["node", "--input-type=module", "-e", RUNNER % json.dumps(RASTER.as_uri())],
                input=json.dumps(shown), capture_output=True, text=True, check=True).stdout)
            print(f"| {name} ({device}) | {min(now):.0f} | {render_ms + min(before):.0f} | "
                  f"{kb_now:.0f} | {kb_before:.0f} | {out['inflate']:.1f} | {out['frame']:.1f} | "
                  f"{out['ink']:.1f} | {out['inkAll']:.0f} |")
    finally:
        studio.close()


if __name__ == "__main__":
    main()
