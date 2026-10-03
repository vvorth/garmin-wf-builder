"""Plan 28 slice 1's measurement: the tiles a frame's text and icons need,
and how many layers can travel as JSON.

Every example face but examples/dashboard, on fr955 at the editor's 2x,
through `wfb.draw.layers` (which builds every layer's JSON and one `Tiles`
store for the frame):
- layers, and those that can travel as JSON (ops all in `BROWSER_OPS`);
  the rest are an outlined group's ring, which has no ops;
- stamps pasted, distinct tiles kept, the store packed (zlib) and the time
  to pack it;
- the layer PNGs the editor fetches today, for comparison.

Run from the repo root:  PYTHONPATH=. .venv/bin/python \
    docs/research/probes/browser-renderer/tiles.py
"""

from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path

from wfb import preview
from wfb.devices import DeviceDatabase
from wfb.draw.jsonform import BROWSER_OPS
from wfb.draw.layers import layers
from wfb.edit.gate import load_text
from wfb.emit.resources import bake_fonts
from wfb.layout import resolve

ROOT = Path(__file__).resolve().parents[4]
DEVICE, SCALE = "fr955", 2


def main() -> None:
    db = DeviceDatabase.discover()
    device = db.get(DEVICE)
    faces = sorted(p for p in (ROOT / "examples").rglob("face.yaml") if "dashboard" not in p.parts)
    print("| face | layers | as JSON | stamps | tiles | tiles KB packed | pack ms | ops JSON KB | layer PNGs KB |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    total = {"layers": 0, "json": 0, "packed": 0, "ops": 0, "png": 0}
    for path in faces:
        loaded = load_text(path, path.read_text())
        if loaded.face is None:
            continue
        resolved = resolve(loaded.face, device, bake_fonts(loaded.face, device))
        stack = layers(resolved, preview.PreviewOptions(scale=SCALE))
        as_json = [l for l in stack if l.ops is not None and {o["op"] for o in l.ops} <= BROWSER_OPS]
        tiles = next((l.tiles for l in stack if l.tiles is not None), None)
        stamps = sum(len(o.get("run", [])) for l in as_json for o in (l.ops or []))
        t0 = time.perf_counter()
        packed, index = tiles.pack() if tiles is not None else (b"", {})
        pack_ms = (time.perf_counter() - t0) * 1000
        ops_bytes = len(json.dumps([l.ops for l in as_json], separators=(",", ":")))
        png = 0
        for l in stack:
            ink = l.image.getchannel("A").getbbox()
            if ink:
                buf = io.BytesIO()
                l.image.crop(ink).save(buf, format="PNG", compress_level=1)
                png += len(base64.b64encode(buf.getvalue()))
        packed_b64 = len(base64.b64encode(packed))
        total["layers"] += len(stack)
        total["json"] += len(as_json)
        total["packed"] += packed_b64
        total["ops"] += ops_bytes
        total["png"] += png
        name = path.parent.relative_to(ROOT / "examples")
        print(f"| {name} | {len(stack)} | {len(as_json)} | {stamps} | {len(index)} | "
              f"{packed_b64 / 1024:.1f} | {pack_ms:.1f} | {ops_bytes / 1024:.1f} | {png / 1024:.1f} |")
    print(f"\nTotal: {total['json']} of {total['layers']} layers as JSON; "
          f"ops {total['ops'] / 1024:.0f} KB + tiles {total['packed'] / 1024:.0f} KB (base64) "
          f"against layer PNGs {total['png'] / 1024:.0f} KB (base64).")


if __name__ == "__main__":
    main()
