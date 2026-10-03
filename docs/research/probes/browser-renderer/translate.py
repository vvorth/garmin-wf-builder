"""Plan 28 slice 2's measurement: a move drawn in the browser against the
server's frame after the real move.

For every element of every example face that the editor can move, on
fr955 at 2x: the element's JSON before, translated by (+5, -3) device
pixels in the browser (`raster.translateOps`), is drawn by `raster.drawOps`
and compared byte for byte with the element's JSON after the real edit
(`wfb.edit.move`, landed on the dragged pixel), drawn the same way.

Run from the repo root:  PYTHONPATH=. .venv/bin/python \
    docs/research/probes/browser-renderer/translate.py
"""

from __future__ import annotations

import base64
import json
import subprocess
from collections import Counter
from pathlib import Path

from wfb import preview
from wfb.devices import DeviceDatabase
from wfb.draw.jsonform import Tiles, to_json
from wfb.edit import Refused, View, move
from wfb.edit.gate import load_text

ROOT = Path(__file__).resolve().parents[4]
RASTER = ROOT / "wfb/studio/static/raster.js"
DEVICE, SCALE, DX, DY = "fr955", 2, 5, -3

RUNNER = """
import * as raster from %s;
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
const job = JSON.parse(readFileSync(0, "utf8"));
const out = [];
for (const pair of job.pairs) {
  const tiles = await raster.inflateTiles(pair.tiles);
  const draw = (ops) => {
    const im = raster.image(job.width, job.height, [0, 0, 0]);
    raster.drawOps(im, ops, tiles, job.scale);
    return createHash("md5").update(im.data).digest("hex");
  };
  out.push(draw(raster.translateOps(pair.before, job.dx, job.dy)) === draw(pair.after));
}
console.log(JSON.stringify(out));
"""


def element_ops(resolved, element_id, tiles):
    options = preview.PreviewOptions(scale=SCALE)
    entry = preview._resolve_style_entry(resolved.face, options.style)
    values = preview.sample_values(resolved, options, entry)
    for placed in preview.frame_items(resolved, options, entry):
        if placed.id == element_id:
            renderer = preview.new_renderer(resolved, options, values, (0, 0, 0))
            if renderer.shows(placed):
                return to_json(renderer, placed, tiles)[0]
    return None


def main() -> None:
    db = DeviceDatabase.discover()
    device = db.get(DEVICE)
    faces = sorted(p for p in (ROOT / "examples").rglob("face.yaml") if "dashboard" not in p.parts)
    tally: Counter[str] = Counter()
    misses = []
    pairs, labels = [], []
    for path in faces:
        try:
            view = View(path, path.read_text(), device)
        except Refused:
            continue
        for placed in view.resolved.items:
            if placed.kind == "group":
                continue
            tiles = Tiles()
            before = element_ops(view.resolved, placed.id, tiles)
            if not before:
                continue
            try:
                converted = move(view, placed.id, DX, DY)
            except Refused as exc:
                tally["refused by the engine"] += 1
                continue
            if not converted.landed:
                tally["did not land"] += 1
                continue
            after_face = view.place(load_text(path, converted.patch.text))
            after = element_ops(after_face, placed.id, tiles)
            if after is None:
                tally["not drawn after"] += 1
                continue
            packed, index = tiles.pack()
            pairs.append({"before": before, "after": after,
                          "tiles": {"data": base64.b64encode(packed).decode(), "index": index}})
            labels.append((path.parent.relative_to(ROOT / "examples"), placed.id, placed.kind))
    job = {"width": device.width * SCALE, "height": device.height * SCALE, "scale": SCALE,
           "dx": DX, "dy": DY, "pairs": pairs}
    out = subprocess.run(["node", "--input-type=module", "-e", RUNNER % json.dumps(RASTER.as_uri())],
                         input=json.dumps(job), capture_output=True, text=True, check=True)
    for ok, label in zip(json.loads(out.stdout), labels):
        tally["equal" if ok else "differ"] += 1
        tally[f"{label[2]}: {'equal' if ok else 'differ'}"] += 1
        if not ok:
            misses.append(label)
    print(f"# A move by ({DX:+d}, {DY:+d}) px on {DEVICE} at {SCALE}x, drawn in the browser\n")
    for k, n in sorted(tally.items()):
        print(f"- {k}: {n}")
    print("\nDiffer:")
    for m in misses:
        print(f"- {m[0]} `{m[1]}` ({m[2]})")


if __name__ == "__main__":
    main()
