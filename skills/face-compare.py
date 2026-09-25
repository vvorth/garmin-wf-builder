#!/usr/bin/env python3
"""Compare a target picture of a watch face with a design's `wfb preview`.

    skills/face-compare.py TARGET.png design.yaml [-d DEVICE] [--time HH:MM[:SS]]
                           [--crop L,T,R,B] [--zoom REGION] [--style NAME] [--asleep] [--aod]
                           [-o OUT.png]

Renders the design with `wfb preview` (same geometry, fonts and 64-colour
quantisation the watch uses), crops the target to a square around the dial,
scales it to the preview's size, masks both to the round screen, and writes
one sheet of four panels:

    target | preview | 50/50 overlay | difference heat map (bright = differs)

`--zoom centre` (or any of the nine region names it prints, or `worst`)
adds a second row: that region of the target and of the preview blown up
3x, for the small things a whole-dial view hides -- a hub, a hand's tail, a
tick's width, a glyph's weight.

It also prints a difference score for the whole dial and for a 3x3 grid of
regions, so an agent looping on a design can see *where* it is furthest from
the target without guessing. The score is a guide, not a goal: a perfect
layout in a slightly different typeface still scores above zero, and a
target photographed at an angle never reaches it. Judge with your eyes; use
the numbers to pick what to fix next and to confirm a change helped.

Part of the watchface-builder skill (`skills/watchface-builder.md`).
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WFB = REPO / "wfb.py"

try:
    from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageStat
except ImportError:  # re-run under the project's own venv, like wfb.py does
    import os
    venv_python = REPO / ".venv" / "bin" / "python"
    if venv_python.exists() and not os.environ.get("FACE_COMPARE_REEXEC"):
        os.environ["FACE_COMPARE_REEXEC"] = "1"
        os.execv(str(venv_python), [str(venv_python), __file__, *sys.argv[1:]])
    raise

PANEL_GAP = 8
CAPTION = 22
GRID_NAMES = [["top-left", "top", "top-right"],
              ["left", "centre", "right"],
              ["bottom-left", "bottom", "bottom-right"]]


def render_preview(design: Path, args: argparse.Namespace) -> Image.Image:
    cmd = [sys.executable, str(WFB), "preview", str(design), "-o", "-",
           "--scale", str(args.scale)]
    if args.device:
        cmd += ["-d", args.device]
    if args.time:
        cmd += ["--time", args.time]
    if args.style:
        cmd += ["--style", args.style]
    if args.asleep:
        cmd.append("--asleep")
    if args.aod:
        cmd.append("--aod")
    proc = subprocess.run(cmd, capture_output=True)
    stderr = proc.stderr.decode(errors="replace")
    if proc.returncode != 0 or not proc.stdout:
        sys.stderr.write(stderr)
        sys.exit(f"face-compare: wfb preview failed (exit {proc.returncode})")
    # Lint notes are `wfb validate`'s job; keep only the one-line headline of
    # each warning (a stand-in font among them) so a round's output stays short.
    for line in stderr.splitlines():
        if "warning" in line.split(":", 3)[-1][:40] or "stand-in" in line:
            sys.stderr.write(line.strip() + "\n")
    return Image.open(io.BytesIO(proc.stdout)).convert("RGB")


def square_crop(image: Image.Image, crop: str | None) -> Image.Image:
    if crop:
        left, top, right, bottom = (int(v) for v in crop.split(","))
        return image.crop((left, top, right, bottom))
    side = min(image.size)
    left = (image.width - side) // 2
    top = (image.height - side) // 2
    return image.crop((left, top, left + side, top + side))


def round_mask(size: tuple[int, int]) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size[0] - 1, size[1] - 1], fill=255)
    return mask


def masked(image: Image.Image, mask: Image.Image) -> Image.Image:
    out = Image.new("RGB", image.size, (24, 24, 24))
    out.paste(image, (0, 0), mask)
    return out


def score(diff: Image.Image, mask: Image.Image, box=None) -> float:
    """Mean per-pixel difference inside the round mask, 0 (same) to 100."""
    grey = diff.convert("L")
    if box:
        grey, mask = grey.crop(box), mask.crop(box)
    if not mask.getbbox():
        return 0.0
    return 100.0 * ImageStat.Stat(grey, mask).mean[0] / 255.0


def sheet(panels: list[tuple[str, Image.Image]]) -> Image.Image:
    w, h = panels[0][1].size
    out = Image.new("RGB", (len(panels) * w + (len(panels) - 1) * PANEL_GAP, h + CAPTION),
                    (40, 40, 40))
    draw = ImageDraw.Draw(out)
    for i, (label, panel) in enumerate(panels):
        x = i * (w + PANEL_GAP)
        out.paste(panel, (x, CAPTION))
        draw.text((x + 6, 5), label, fill=(230, 230, 230))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("target", type=Path, help="the picture to match")
    parser.add_argument("design", type=Path, help="the face YAML")
    parser.add_argument("-d", "--device", help="device to preview (default: first target)")
    parser.add_argument("--time", help="HH:MM[:SS] -- set it to the time the target shows")
    parser.add_argument("--style", help="a config: style: entry to render")
    parser.add_argument("--asleep", action="store_true", help="render the sleeping frame")
    parser.add_argument("--aod", action="store_true",
                        help="render the AMOLED always-on frame (for an always-on screenshot)")
    parser.add_argument("--crop", help="L,T,R,B pixel box of the dial in the target "
                                       "(default: centred square)")
    parser.add_argument("--zoom", help="also blow up one region 3x: a region name "
                                       "(top-left ... bottom-right, centre) or 'worst'")
    parser.add_argument("--scale", type=int, default=2, help="preview scale (default 2)")
    parser.add_argument("-o", "--output", type=Path,
                        help="where to write the sheet (default: build/compare/<design>.png)")
    args = parser.parse_args()

    preview = render_preview(args.design, args)
    target = square_crop(Image.open(args.target).convert("RGB"), args.crop)
    target = target.resize(preview.size, Image.LANCZOS)
    mask = round_mask(preview.size)
    target, preview = masked(target, mask), masked(preview, mask)

    diff = ImageChops.difference(target, preview)
    heat = ImageOps.autocontrast(diff.convert("L"), cutoff=0).convert("RGB")
    heat = masked(ImageChops.multiply(heat, Image.new("RGB", heat.size, (255, 90, 60))), mask)
    blend = Image.blend(target, preview, 0.5)

    w, h = preview.size
    boxes = {GRID_NAMES[row][col]: (col * w // 3, row * h // 3, (col + 1) * w // 3, (row + 1) * h // 3)
             for row in range(3) for col in range(3)}
    scores = {name: score(diff, mask, box) for name, box in boxes.items()}

    out = args.output or REPO / "build" / "compare" / f"{args.design.parent.name}-{args.design.stem}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    image = sheet([("target", target), ("preview", preview),
                   ("overlay 50/50", blend), ("difference", heat)])
    if args.zoom:
        name = max(scores, key=scores.get) if args.zoom == "worst" else args.zoom
        if name not in boxes:
            sys.exit(f"face-compare: --zoom takes 'worst' or one of: {', '.join(boxes)}")
        box = boxes[name]
        size = ((box[2] - box[0]) * 3, (box[3] - box[1]) * 3)
        zoom = sheet([(f"target: {name} x3", target.crop(box).resize(size, Image.NEAREST)),
                      (f"preview: {name} x3", preview.crop(box).resize(size, Image.NEAREST))])
        tall = Image.new("RGB", (max(image.width, zoom.width), image.height + zoom.height + PANEL_GAP),
                         (40, 40, 40))
        tall.paste(image, (0, 0))
        tall.paste(zoom, (0, image.height + PANEL_GAP))
        image = tall
    image.save(out)

    print(f"sheet:   {out}")
    print(f"overall: {score(diff, mask):5.1f}   (0 = identical; lower is closer)")
    for row in GRID_NAMES:
        print("  ".join(f"{name:>12} {scores[name]:5.1f}" for name in row))


if __name__ == "__main__":
    main()
