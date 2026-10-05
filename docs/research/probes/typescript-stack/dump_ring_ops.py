"""The ring-on-device face's draw ops (fenix8solar47mm, scale 1) as JSON,
each element's window centre, and two raw RGBA frames (the simulator capture
and Pillow's preview), for shapes.mjs to compare with Skia.

    ./.venv/bin/python docs/research/probes/typescript-stack/dump_ring_ops.py OUTDIR

writes OUTDIR/ring_ops.json, OUTDIR/capture.rgba and OUTDIR/pillow.rgba.
"""
import json
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "docs/research/probes/draw-program"))
from PIL import Image  # noqa: E402
from probe import resolve  # type: ignore  # noqa: E402

from wfb import preview  # noqa: E402
from wfb.devices import DeviceDatabase  # noqa: E402
from wfb.draw.layers import layers  # noqa: E402

out_dir = Path(sys.argv[1])
probe = ROOT / "docs/research/probes/ring-on-device"
resolved = resolve(DeviceDatabase.discover(), str(probe / "face.yaml"))
options = preview.PreviewOptions(scale=1, quantise=False, mask_shape=False)
out = {"width": resolved.device.width, "height": resolved.device.height, "layers": [],
       "centres": {p.id: [p.inner_box.x + p.inner_box.width // 2,
                          p.inner_box.y + p.inner_box.height // 2]
                   for p in resolved.items}}
for layer in layers(resolved, options, paint_all=False):
    out["layers"].append({"id": layer.id, "kind": layer.kind, "ops": layer.ops})
(out_dir / "ring_ops.json").write_text(json.dumps(out))
(out_dir / "capture.rgba").write_bytes(
    Image.open(probe / "capture.png").convert("RGBA").tobytes())
(out_dir / "pillow.rgba").write_bytes(preview.render(resolved, options).convert("RGBA").tobytes())
