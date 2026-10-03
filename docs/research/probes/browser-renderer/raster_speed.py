"""Plan 28 slice 0's measurement: `wfb/studio/static/raster.js` on the
corpus's real layers.

For every lowered element whose ops are shapes only (no `text`/`glyph`,
which slice 1 adds), on every example face, on fr955 at the editor's 2x:
- the JavaScript draws it onto a black ground, through the same op ->
  Pillow-call mapping `wfb.draw.jsonform.rasterise` uses, and the RGB
  bytes are compared with `rasterise`'s;
- the time Node takes to draw it, per layer and per face.

Run from the repo root:  PYTHONPATH=. .venv/bin/python \
    docs/research/probes/browser-renderer/raster_speed.py
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from wfb import preview
from wfb.devices import DeviceDatabase
from wfb.draw import barrel
from wfb.draw.jsonform import rasterise, to_json
from wfb.edit.gate import load_text
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve

ROOT = Path(__file__).resolve().parents[4]
RASTER = ROOT / "wfb/studio/static/raster.js"
DEVICE, SCALE = "fr955", 2

# The op -> primitive mapping of `jsonform.rasterise`, for shapes.
RUNNER = """
import * as r from %s;
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
const v = (n) => typeof n === "object" ? n.value + n.add : n;
const layers = JSON.parse(readFileSync(0, "utf8"));
const out = [];
for (const L of layers) {
  const im = r.image(L.width, L.height, [0, 0, 0]);
  const s = L.scale;
  const t0 = performance.now();
  for (let rep = 0; rep < L.reps; rep++) {
    let color = [255, 255, 255], pen = 1;
    for (const op of L.ops) {
      const name = op.op;
      if (name === "color") color = op.rgb;
      else if (name === "pen") pen = Math.trunc(v(op.width));
      else if (name === "fillPolygon") {
        if (op.points.length >= 3) r.polygon(im, op.points.map(([x, y]) => [x * s, y * s]), color);
      } else if (name === "arc") {
        const radius = v(op.radius);
        if (op.call === null || radius <= 0) continue;
        const cx = v(op.cx) * s, cy = v(op.cy) * s, rr = radius * s;
        r.arc(im, [cx - rr, cy - rr, cx + rr, cy + rr], op.pillow[0], op.pillow[1], color,
              Math.max(1, Math.trunc(v(op.pen)) * s));
      } else {
        const a = op.args.map(v);
        const width = Math.max(1, pen * s);
        const fill = name.startsWith("fill");
        const shape = name.slice(4);
        if (shape === "Rectangle" || shape === "RoundedRectangle") {
          const [x, y, w, h] = a;
          if (w <= 0 || h <= 0) continue;
          const rect = [x * s, y * s, (x + w) * s - 1, (y + h) * s - 1];
          const style = fill ? { fill: color } : { outline: color, width };
          if (shape === "Rectangle") r.rectangle(im, rect, style);
          else r.roundedRectangle(im, rect, a[4] * s, style);
        } else if (shape === "Circle" || shape === "Ellipse") {
          const [cx, cy] = a;
          const [rx, ry] = shape === "Circle" ? [a[2], a[2]] : [a[2], a[3]];
          r.ellipse(im, [(cx - rx) * s, (cy - ry) * s, (cx + rx) * s, (cy + ry) * s],
                    fill ? { fill: color } : { outline: color, width });
        } else if (name === "drawLine") {
          r.line(im, [a[0] * s, a[1] * s, a[2] * s, a[3] * s], color, width);
        }
      }
    }
  }
  const ms = (performance.now() - t0) / L.reps;
  const rgb = Buffer.alloc(L.width * L.height * 3);
  for (let i = 0, j = 0; i < im.data.length; i += 4, j += 3) {
    rgb[j] = im.data[i]; rgb[j + 1] = im.data[i + 1]; rgb[j + 2] = im.data[i + 2];
  }
  out.push({ md5: createHash("md5").update(rgb).digest("hex"), ms });
}
console.log(JSON.stringify(out));
"""


def main() -> None:
    db = DeviceDatabase.discover()
    device = db.get(DEVICE)
    faces = sorted(p for p in (ROOT / "examples").rglob("face.yaml") if "dashboard" not in p.parts)
    print("| face | shape-only layers | equal to `rasterise` | ops | Node ms, all of them | slowest layer ms |")
    print("|---|---:|---:|---:|---:|---:|")
    totals = [0, 0]
    for path in faces:
        loaded = load_text(path, path.read_text())
        if loaded.face is None:
            continue
        resolved = resolve(loaded.face, device, bake_fonts(loaded.face, device))
        options = preview.PreviewOptions(scale=SCALE)
        entry = preview._resolve_style_entry(resolved.face, options.style)
        values = preview.sample_values(resolved, options, entry)
        jobs, want = [], []
        for placed in preview.frame_items(resolved, options, entry):
            renderer = preview.new_renderer(resolved, options, values, (0, 0, 0), None)
            if not renderer.shows(placed):
                continue
            ops, fonts = to_json(renderer, placed)
            if not ops or any(o["op"] in ("text", "glyph") for o in ops):
                continue
            rasterise(ops, fonts, renderer)
            want.append(hashlib.md5(renderer.image.tobytes()).hexdigest())
            for o in ops:
                if o["op"] == "arc" and o["call"] is not None:
                    o["pillow"] = list(barrel.pillow_arc(tuple(o["call"])))
            jobs.append({"ops": ops, "width": renderer.image.width,
                         "height": renderer.image.height, "scale": SCALE, "reps": 5})
        if not jobs:
            continue
        source = RUNNER % json.dumps(RASTER.as_uri())
        got = json.loads(subprocess.run(["node", "--input-type=module", "-e", source],
                                        input=json.dumps(jobs), capture_output=True,
                                        text=True, check=True).stdout)
        equal = sum(g["md5"] == w for g, w in zip(got, want))
        totals[0] += len(jobs)
        totals[1] += equal
        nops = sum(len(j["ops"]) for j in jobs)
        name = path.parent.relative_to(ROOT / "examples")
        print(f"| {name} | {len(jobs)} | {equal} | {nops} | "
              f"{sum(g['ms'] for g in got):.1f} | {max(g['ms'] for g in got):.2f} |")
    print(f"\nTotal: {totals[1]} of {totals[0]} shape-only layers equal to `rasterise`.")


if __name__ == "__main__":
    main()
