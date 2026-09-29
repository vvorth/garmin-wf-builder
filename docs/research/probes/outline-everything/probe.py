"""Outlines on every drawable: analytic offset vs. true dilation, the stamp on
icons with openings, and group union by two passes.

Backs docs/research/19-outline-everything.md. Host-side only (Pillow, numpy,
scipy, all already in .venv for the stamped-ring probe); the rasteriser is
Pillow's, not Garmin's, so every number here is a model of the device, not a
measurement of it.

Run:
    ./.venv/bin/python docs/research/probes/outline-everything/probe.py

Prints results; writes results.txt and PNGs next to this file.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
ICON_FONT = REPO / "wfb/assets/icons/SymbolsNerdFont-Regular.ttf"
SIZE = 260
C = SIZE // 2
OUT: list[str] = []


def say(line: str = "") -> None:
    print(line)
    OUT.append(line)


def dilate(mask: np.ndarray, r: int) -> np.ndarray:
    """True Euclidean-disc dilation: every pixel within distance r."""
    return ndimage.distance_transform_edt(~mask) <= r


def raster_polygon(points: list[tuple[float, float]]) -> np.ndarray:
    img = Image.new("1", (SIZE, SIZE), 0)
    ImageDraw.Draw(img).polygon(points, fill=1)
    return np.array(img, dtype=bool)


def raster_line(p1, p2, width: int) -> np.ndarray:
    img = Image.new("1", (SIZE, SIZE), 0)
    ImageDraw.Draw(img).line([p1, p2], fill=1, width=width)
    return np.array(img, dtype=bool)


def rotate(points, angle, cx=C, cy=C):
    s, c = math.sin(angle), math.cos(angle)
    return [(cx + x * c - y * s, cy + x * s + y * c) for x, y in points]


def offset_polygon(points, w, miter_limit=2.0):
    """Mitred outward offset of a simple polygon by w px, bevelled where the
    mitre would reach further than miter_limit * w (a sharp hand tip).
    Pure build-time Python: this is what the compiler would bake into a
    second `_POINTS` constant."""
    n = len(points)
    area = sum(points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1]
               for i in range(n))
    sign = 1 if area > 0 else -1  # screen coords, y down
    out = []
    for i in range(n):
        p0, p1, p2 = points[i - 1], points[i], points[(i + 1) % n]
        def normal(a, b):
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy)
            return (-dy / length * -sign, dx / length * -sign)
        n1, n2 = normal(p0, p1), normal(p1, p2)
        bis = (n1[0] + n2[0], n1[1] + n2[1])
        blen = math.hypot(*bis)
        cos_half = blen / 2  # cos of half the turn between the normals
        if blen < 1e-9 or 1 / cos_half > miter_limit:
            out.append((p1[0] + n1[0] * w, p1[1] + n1[1] * w))
            out.append((p1[0] + n2[0] * w, p1[1] + n2[1] * w))
        else:
            k = w / cos_half
            out.append((p1[0] + bis[0] / blen * k, p1[1] + bis[1] / blen * k))
    return out


def ring_stats(shape: np.ndarray, analytic_outer: np.ndarray, r: int):
    """Compare an analytic outer silhouette with the true dilation of the
    *rasterised* shape. gaps = pixels 4-adjacent to the shape that the
    analytic ring leaves background (the outline visibly breaks there);
    extra = ring pixels further than r from the shape."""
    ideal = dilate(shape, r)
    ring = analytic_outer & ~shape
    adjacent = dilate(shape, 1) & ~shape
    gaps = int((adjacent & ~analytic_outer).sum())
    extra = int((ring & ~ideal).sum())
    ideal_ring = ideal & ~shape
    iou = (ring & ideal_ring).sum() / max(1, (ring | ideal_ring).sum())
    return gaps, extra, float(iou)


def hands() -> None:
    say("## 1. Hand polygon: build-time mitred offset, rotated at runtime")
    say("sword hand, 8 px wide, 100 px long, sharp tip; 60 rotations (every minute)")
    hand = [(-4, 20), (4, 20), (3, -88), (0, -100), (-3, -88)]
    for w, r in ((1, 1), (1.5, 1), (2, 2), (3, 3)):
        outer = offset_polygon(hand, w)
        total_gaps = worst_gaps = total_extra = 0
        ious = []
        for minute in range(60):
            a = math.radians(minute * 6)
            shape = raster_polygon(rotate(hand, a))
            analytic = raster_polygon(rotate(outer, a)) | shape
            g, e, iou = ring_stats(shape, analytic, r)
            total_gaps += g
            worst_gaps = max(worst_gaps, g)
            total_extra += e
            ious.append(iou)
        say(f"offset={w} (ring {r}px): {len(outer)} vertices (from {len(hand)}); gap px/frame mean "
            f"{total_gaps / 60:.2f} worst {worst_gaps}; extra px/frame {total_extra / 60:.1f}; "
            f"ring IoU vs dilation min {min(ious):.3f} mean {np.mean(ious):.3f}")
    say()


def lines() -> None:
    say("## 2. Line part: pen + 2w, ends extended by w (build time, local frame)")
    for pen in (2, 3, 5):
        for w in (1, 2):
            gaps = extra = 0
            for minute in range(60):
                a = math.radians(minute * 6)
                (p1, p2) = rotate([(0, 10), (0, -90)], a)
                (q1, q2) = rotate([(0, 10 + w), (0, -90 - w)], a)
                shape = raster_line(p1, p2, pen)
                analytic = raster_line(q1, q2, pen + 2 * w) | shape
                g, e, _ = ring_stats(shape, analytic, w)
                gaps += g
                extra += e
            say(f"pen={pen} w={w}: gap px/frame {gaps / 60:.2f}, extra px/frame {extra / 60:.1f}")
    say()


def holes(mask: np.ndarray) -> int:
    """Background components not connected to the image border."""
    labels, n = ndimage.label(~mask)
    border = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])))
    return len([i for i in range(1, n + 1) if i not in border])


def icons() -> None:
    say("## 3. Icons: the stamp is a true dilation, so openings get a ring too")
    say("per enclosed opening: background px still open after the ring / px before")
    font_names = {"heart": "\U000f02d1", "alarm": "\U000f0020", "battery": "\U000f0079",
                  "sunrise": "\U000f059c", "steps": ""}
    sheet = Image.new("RGB", (len(font_names) * 3 * 70, 3 * 70), (40, 40, 40))
    for px in (20, 28, 40):
        font = ImageFont.truetype(str(ICON_FONT), px)
        row = []
        for name, cp in font_names.items():
            img = Image.new("1", (96, 96), 0)
            ImageDraw.Draw(img).text((48, 48), cp, font=font, fill=1, anchor="mm")
            glyph = np.array(img, dtype=bool)
            labels, n = ndimage.label(~glyph)
            border = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])))
            inner = [i for i in range(1, n + 1) if i not in border]
            cells = [f"{name}@{px}px openings={len(inner)}"]
            for w in (1, 2):
                union = dilate(glyph, w)
                kept = [f"{(~union & (labels == i)).sum()}/{(labels == i).sum()}" for i in inner]
                cells.append(f"w{w} open px: {','.join(kept) or '-'}")
            row.append(" ".join(cells))
        say("  " + " | ".join(row))
    # one picture: glyph in white, w=1 ring in orange, at 40px
    font = ImageFont.truetype(str(ICON_FONT), 40)
    for col, (name, cp) in enumerate(font_names.items()):
        for r, w in enumerate((0, 1, 2)):
            img = Image.new("1", (70, 70), 0)
            ImageDraw.Draw(img).text((35, 35), cp, font=font, fill=1, anchor="mm")
            g = np.array(img, dtype=bool)
            rgb = np.full(g.shape + (3,), 40, np.uint8)
            if w:
                rgb[dilate(g, w)] = (255, 170, 0)
            rgb[g] = (255, 255, 255)
            sheet.paste(Image.fromarray(rgb), (col * 70 * 3 + r * 70, 0))
    sheet = sheet.crop((0, 0, sheet.width, 70)).resize((sheet.width * 2, 140), Image.NEAREST)
    sheet.save(HERE / "icons.png")
    say("  (icons.png: each icon at w=0, 1, 2)")
    say()


def group() -> None:
    say("## 4. Group union: per-member rings vs. two passes")
    img_a = Image.new("1", (SIZE, SIZE), 0)
    d = ImageDraw.Draw(img_a)
    d.ellipse((80, 80, 160, 160), fill=1)
    circle = np.array(img_a, dtype=bool)
    img_b = Image.new("1", (SIZE, SIZE), 0)
    ImageDraw.Draw(img_b).rectangle((130, 110, 200, 130), fill=1)
    bar = np.array(img_b, dtype=bool)
    w = 2
    # per member: ring A, A, ring B, B  -> B's ring cuts into A
    seq = np.zeros((SIZE, SIZE), np.uint8)
    for m in (circle, bar):
        seq[dilate(m, w) & ~m] = 1
        seq[m] = 2
    # two passes: every dilation, then every member
    two = np.zeros((SIZE, SIZE), np.uint8)
    for m in (circle, bar):
        two[dilate(m, w)] = 1
    for m in (circle, bar):
        two[m] = 2
    union = circle | bar
    seam_seq = int(((seq == 1) & union).sum())
    seam_two = int(((two == 1) & union).sum())
    ideal = dilate(union, w) & ~union
    say(f"w={w}: ring px inside the union silhouette -- per member {seam_seq}, two-pass {seam_two}; "
        f"two-pass ring == dilation of the union: {bool(((two == 1) == ideal).all())}")
    pal = np.array([(40, 40, 40), (255, 170, 0), (255, 255, 255)], np.uint8)
    pic = np.concatenate([pal[seq], np.full((SIZE, 8, 3), 0, np.uint8), pal[two]], axis=1)
    Image.fromarray(pic[60:230]).resize((pic.shape[1] * 2, 340), Image.NEAREST).save(HERE / "group.png")
    say("  (group.png: left per member, right two-pass)")
    say()


if __name__ == "__main__":
    hands()
    lines()
    icons()
    group()
    (HERE / "results.txt").write_text("\n".join(OUT) + "\n")
