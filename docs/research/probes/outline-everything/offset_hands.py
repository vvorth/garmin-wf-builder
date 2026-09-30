"""What a build-time offset polygon looks like as a hand's 1px ring, next to
the exact ring (research 19 §4.1, §4.7).

The exact ring is the dilation of the drawn hand -- what the four-fill stamp
paints.  The offset ring is one extra polygon, the hand's outline pushed out
at build time (mitred, bevelled at the tip) and rotated with the hand: one
extra fill instead of four.  Both hand and offset polygon are rasterised on
their own, which is where the offset ring goes wrong: a 1px offset rounds
onto the hand's own edge pixels at some angles and disappears there.

The hour hand of examples/features/rings at 260px (fenix8solar47mm), at a
few angles.  Pillow's rasteriser, not Garmin's: a model of the device.

    ./.venv/bin/python docs/research/probes/outline-everything/offset_hands.py

Writes offset-hands.png beside this file.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from probe import offset_polygon  # noqa: E402

HAND = [(-5, 10), (-4, -52), (0, -62), (4, -52), (5, 10)]  # 4%r .. 48%r of 130px
SIZE, C, ZOOM, CROP = 150, 75, 3, 66
ANGLES = (0, 11, 27, 45, 63, 98)
BG, HANDC, RING, GAP, EXTRA = (0, 0, 0), (255, 255, 255), (255, 170, 0), (255, 0, 0), (0, 120, 255)


def raster(points) -> np.ndarray:
    img = Image.new("1", (SIZE, SIZE), 0)
    ImageDraw.Draw(img).polygon(points, fill=1)
    return np.array(img, dtype=bool)


def rotate(points, degrees):
    a = math.radians(degrees)
    s, c = math.sin(a), math.cos(a)
    return [(C + x * c - y * s, C + x * s + y * c) for x, y in points]


def panel(hand: np.ndarray, ring: np.ndarray, title: str) -> Image.Image:
    exact = ndimage.binary_dilation(hand, structure=ndimage.generate_binary_structure(2, 1))
    rgb = np.zeros(hand.shape + (3,), np.uint8)
    rgb[ring & ~hand] = RING
    rgb[ring & ~hand & ~exact] = EXTRA          # blue: ring pixels 2px out
    rgb[exact & ~hand & ~ring] = GAP            # red: where the 1px ring is missing
    rgb[hand] = HANDC
    rgb = rgb[C - CROP:C + CROP, C - CROP:C + CROP]
    side = 2 * CROP * ZOOM
    img = Image.fromarray(rgb).resize((side, side), Image.NEAREST)
    d = ImageDraw.Draw(img)
    d.text((6, 4), title, fill=(200, 200, 200))
    return img


def main() -> None:
    columns = [("exact (stamp)", None), ("offset 1px", 1.0), ("offset 1.5px", 1.5)]
    rows = []
    for angle in ANGLES:
        hand = raster(rotate(HAND, angle))
        cells = []
        for name, w in columns:
            if w is None:
                ring = ndimage.binary_dilation(hand, structure=ndimage.generate_binary_structure(2, 1))
            else:
                ring = raster(rotate(offset_polygon(HAND, w), angle)) | hand
            gaps = int((ndimage.binary_dilation(hand, structure=ndimage.generate_binary_structure(2, 1))
                        & ~hand & ~ring).sum())
            cells.append(panel(hand, ring, f"{angle}deg  {name}  gaps={gaps}"))
        row = Image.new("RGB", (sum(c.width for c in cells) + 8 * (len(cells) - 1), cells[0].height),
                        (60, 60, 60))
        x = 0
        for c in cells:
            row.paste(c, (x, 0))
            x += c.width + 8
        rows.append(row)
    out = Image.new("RGB", (rows[0].width, sum(r.height for r in rows) + 8 * (len(rows) - 1)),
                    (60, 60, 60))
    y = 0
    for r in rows:
        out.paste(r, (0, y))
        y += r.height + 8
    out.save(HERE / "offset-hands.png", optimize=True)
    print("wrote", HERE / "offset-hands.png", out.size)


if __name__ == "__main__":
    main()
