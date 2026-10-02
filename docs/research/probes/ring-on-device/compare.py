"""Compare a simulator screenshot of face.yaml with the two Pillow models.

    ./.venv/bin/python docs/research/probes/ring-on-device/compare.py SCREENSHOT.png

The screenshot is the simulator's own screen capture of the face on
fenix8solar47mm (260x260; an integer upscale of it is accepted too). For
each grown/stamp pair the script reports how many pixels differ between
the two cells *in the simulator*, and how many of each cell's pixels differ
from today's preview (which stamps) and from the draw program's evaluator
(which draws what the code draws: grown on the left, stamped on the right).
Writes compare_results.txt next to this file.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3]))
sys.path.insert(0, str(HERE.parent / "draw-program"))

from PIL import Image, ImageChops  # noqa: E402

from make_face import ROWS  # type: ignore  # noqa: E402
from probe import resolve  # noqa: E402
from wfb import preview  # noqa: E402
from wfb.devices import DeviceDatabase  # noqa: E402
from wfb.draw import evaluator  # noqa: E402
from wfb.draw.program import Disagreement  # noqa: E402

sys.path.insert(0, str(HERE))
FACE = HERE / "face.yaml"


def program_frame(resolved, options) -> Image.Image:
    """The frame the generated code draws: the preview with every
    `Disagreement` evaluated on the watch's side (the grown copy)."""
    run = evaluator.Evaluator._run

    def watch_side(self, op):
        if isinstance(op, Disagreement):
            self.run(op.watch)
        else:
            run(self, op)

    evaluator.Evaluator._run = watch_side
    try:
        return preview.render(resolved, options)
    finally:
        evaluator.Evaluator._run = run


def cell(image: Image.Image, center) -> Image.Image:
    """A fixed window round the element's centre: the primitive (at most
    30x28 px) plus room for a 2 px ring, and nothing of its neighbours."""
    cx, cy = center
    return image.crop((cx - 19, cy - 18, cx + 19, cy + 18))


def diff(a: Image.Image, b: Image.Image) -> int:
    return sum(1 for v in ImageChops.difference(a, b).convert("L").tobytes() if v)


def main() -> None:
    shot = Image.open(sys.argv[1]).convert("RGB")
    db = DeviceDatabase.discover()
    resolved = resolve(db, str(FACE))
    w, h = resolved.device.width, resolved.device.height
    if shot.size != (w, h):
        k = shot.width // w
        shot = shot.resize((w, h), Image.Resampling.NEAREST) if k > 1 else shot
    options = preview.PreviewOptions(scale=1, quantise=False, mask_shape=False)
    stamped = preview.render(resolved, options)
    program = program_frame(resolved, options)
    out = [f"## simulator vs Pillow models, {FACE.name}"]
    # Each window centres on the element's own box (`inner_box`, without its
    # ring): a gauge's `center` is its anchor, not its box's middle.
    boxes = {p.id: (p.inner_box.x + p.inner_box.width // 2, p.inner_box.y + p.inner_box.height // 2)
             for p in resolved.items}
    for kind in ROWS:
        for width in (1, 2):
            gb, sb = boxes[f"{kind}_grown{width}"], boxes[f"{kind}_stamp{width}"]
            g, s = cell(shot, gb), cell(shot, sb)
            out.append(
                f"{kind:<9} {width}px  simulator grown vs stamp: {diff(g, s):>4} px | "
                f"grown cell vs program {diff(g, cell(program, gb)):>4}, "
                f"vs preview {diff(g, cell(stamped, gb)):>4} | "
                f"stamp cell vs preview {diff(s, cell(stamped, sb)):>4}")
    print("\n".join(out))
    HERE.joinpath("compare_results.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
