"""Stamped-ring outline text: offset-set comparison against a true dilation,
FreeType's own stroker, and a rotation sweep for the radial-text question.

Backs docs/research/14-stamped-ring-text.md. Renders "12:34" with a real TTF
already vendored in this repo
(examples/features/vector-text/assets/ChivoMono-Bold.ttf -- the face used by
the curve: vector-text examples), builds a binary glyph mask the way the
1-bit default in wfb/fonts/bmfont.py would, and compares four candidate
"stamp at N offsets" sets against:

  1. a true morphological (Euclidean-disc) dilation -- the "ideal" ring a
     platform primitive would draw if one existed;
  2. FreeType's stroker, run the same way research 13 found Garmin's own
     TTF engine calling it (FT_Glyph_Stroke with a round join/cap);
  3. a rotation sweep of a single glyph, isolating whether a *fixed*
     screen-space offset set's approximation quality depends on the angle
     the glyph itself sits at -- the radial-text question.

Run:
    ./.venv/bin/python docs/research/probes/stamped-ring/stamp_experiment.py

Writes PNGs and results.txt into this directory.

Host-only deps beyond requirements.txt (pillow is already a dependency):
numpy, scipy (true dilation via a distance transform), freetype-py (direct
access to FT_Stroker, the same call research 13 found in the simulator
binary). Installed into .venv for this probe only -- nothing under wfb/
imports them, so they are deliberately not added to requirements.txt.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

try:
    import freetype
    HAVE_FREETYPE = True
except ImportError:
    HAVE_FREETYPE = False

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]
FONT_PATH = REPO_ROOT / "examples/features/vector-text/assets/ChivoMono-Bold.ttf"
TEXT = "12:34"
PAD = 24


# --------------------------------------------------------------------------
# Mask construction
# --------------------------------------------------------------------------

def render_mask(text: str, px_size: int, *, antialias: bool) -> np.ndarray:
    """Render `text` with `FONT_PATH` at `px_size`, returning a boolean (or,
    if antialias, uint8 0..255) numpy array padded by PAD on every side so a
    dilation never clips at the image edge."""
    font = ImageFont.truetype(str(FONT_PATH), px_size)
    bbox = font.getbbox(text)
    w = bbox[2] - bbox[0] + 2 * PAD
    h = bbox[3] - bbox[1] + 2 * PAD
    img = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(img)
    draw.text((PAD - bbox[0], PAD - bbox[1]), text, font=font, fill=255)
    arr = np.array(img)
    if antialias:
        return arr
    return arr >= 128


def true_dilation(mask: np.ndarray, r: float) -> np.ndarray:
    """The ideal ring: every background pixel within Euclidean distance r of
    a foreground pixel. distance_transform_edt on the *inverted* mask gives
    exactly the distance from each background pixel to the nearest
    foreground one."""
    dist = ndimage.distance_transform_edt(~mask)
    return (dist <= r) | mask


# --------------------------------------------------------------------------
# Offset sets
# --------------------------------------------------------------------------

def offsets_square8(r: int) -> list[tuple[int, int]]:
    """The common game/UI "8-direction" outline trick: the 8 offsets at
    exactly radius r along the compass points and diagonals -- NOT a filled
    or perimeter disc, just 8 fixed points scaled by r."""
    return [(dx, dy) for dx, dy in itertools.product((-r, 0, r), repeat=2) if (dx, dy) != (0, 0)]


def offsets_cross4(r: int) -> list[tuple[int, int]]:
    return [(r, 0), (-r, 0), (0, r), (0, -r)]


def offsets_disc_filled(r: int) -> list[tuple[int, int]]:
    out = []
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            if (dx, dy) != (0, 0) and dx * dx + dy * dy <= r * r:
                out.append((dx, dy))
    return out


def offsets_disc_perimeter(r: int) -> list[tuple[int, int]]:
    """Only the outer integer shell of the disc: dx^2+dy^2 in ((r-1)^2, r^2]."""
    lo = (r - 1) * (r - 1)
    hi = r * r
    out = []
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            d2 = dx * dx + dy * dy
            if lo < d2 <= hi:
                out.append((dx, dy))
    return out


OFFSET_SETS = {
    "square8": offsets_square8,
    "cross4": offsets_cross4,
    "disc-filled": offsets_disc_filled,
    "disc-perimeter": offsets_disc_perimeter,
}


def stamp(mask: np.ndarray, offsets: list[tuple[int, int]]) -> np.ndarray:
    """Union of `mask` shifted by every offset in `offsets` (numpy roll with
    zero-fill at the border, matching how a stamp drawn near a canvas edge
    would simply draw less, not wrap)."""
    out = np.zeros_like(mask, dtype=bool)
    h, w = mask.shape
    for dx, dy in offsets:
        shifted = np.zeros_like(mask, dtype=bool)
        src_x0, src_x1 = max(0, -dx), min(w, w - dx)
        src_y0, src_y1 = max(0, -dy), min(h, h - dy)
        dst_x0, dst_x1 = max(0, dx), min(w, w + dx)
        dst_y0, dst_y1 = max(0, dy), min(h, h + dy)
        shifted[dst_y0:dst_y1, dst_x0:dst_x1] = mask[src_y0:src_y1, src_x0:src_x1]
        out |= shifted
    return out


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def compare(stamped: np.ndarray, ideal: np.ndarray, original: np.ndarray) -> dict:
    missing = ideal & ~stamped
    extra = stamped & ~ideal
    stamped_ring = stamped & ~original
    ideal_ring = ideal & ~original
    return {
        "missing_px": int(missing.sum()),
        "extra_px": int(extra.sum()),
        "stamped_ring_px": int(stamped_ring.sum()),
        "ideal_ring_px": int(ideal_ring.sum()),
        "ring_iou": (
            int((stamped_ring & ideal_ring).sum())
            / max(1, int((stamped_ring | ideal_ring).sum()))
        ),
    }


def save_mask_png(mask: np.ndarray, path: Path) -> None:
    Image.fromarray((mask.astype(np.uint8) * 255)).save(path)


def save_diagnostic_png(stamped: np.ndarray, ideal: np.ndarray, original: np.ndarray, path: Path) -> None:
    """RGB composite: white = original glyph, green = correctly-stamped ring
    pixel, red = missing (ideal but not stamped), blue = extra (stamped but
    not ideal)."""
    h, w = original.shape
    out = np.zeros((h, w, 3), dtype=np.uint8)
    out[original] = (255, 255, 255)
    ring_ok = stamped & ideal & ~original
    missing = ideal & ~stamped & ~original
    extra = stamped & ~ideal & ~original
    out[ring_ok] = (0, 200, 0)
    out[missing] = (220, 0, 0)
    out[extra] = (0, 100, 255)
    Image.fromarray(out, "RGB").save(path)


# --------------------------------------------------------------------------
# Part 1: offset-set comparison at r = 1, 2, 3, large digits
# --------------------------------------------------------------------------

def part1(results: list[str]) -> None:
    results.append("## Part 1 -- offset-set comparison, \"12:34\" at 80px, r = 1, 2, 3\n")
    mask = render_mask(TEXT, 80, antialias=False)
    save_mask_png(mask, HERE / "glyph-original.png")
    results.append(f"glyph mask: {mask.shape[1]}x{mask.shape[0]} px, {int(mask.sum())} lit px (solid)\n")
    results.append("| r | offsets | draws | missing px | extra px | ring IoU | stamped ring px | ideal ring px | lit ratio (ring/solid) |")
    results.append("|---|---|---|---|---|---|---|---|---|")
    solid_px = int(mask.sum())
    for r in (1, 2, 3):
        ideal = true_dilation(mask, r)
        save_mask_png(ideal, HERE / f"ideal-dilation-r{r}.png")
        for name, fn in OFFSET_SETS.items():
            offs = fn(r)
            stamped = stamp(mask, offs)
            m = compare(stamped, ideal, mask)
            save_diagnostic_png(stamped, ideal, mask, HERE / f"diag-{name}-r{r}.png")
            ratio = m["stamped_ring_px"] / solid_px
            results.append(
                f"| {r} | {name} | {len(offs)} | {m['missing_px']} | {m['extra_px']} | "
                f"{m['ring_iou']:.3f} | {m['stamped_ring_px']} | {m['ideal_ring_px']} | {ratio:.3f} |"
            )
    results.append("")


# --------------------------------------------------------------------------
# Part 2: FreeType stroker comparison
# --------------------------------------------------------------------------

def freetype_stroke_mask(char: str, px_size: int, radius_px: float) -> tuple[np.ndarray, np.ndarray]:
    """Render `char` twice through FreeType directly: once plain, once
    stroked with FT_Glyph_Stroke (round cap/join, the same primitives
    research 13 found Garmin's engine calling with a fixed 2px radius).
    Returns (plain_mask, stroked_mask) on a common canvas, aligned the way
    FreeType's own bitmap_left/top say to."""
    face = freetype.Face(str(FONT_PATH))
    face.set_pixel_sizes(0, px_size)
    face.load_char(char, freetype.FT_LOAD_DEFAULT | freetype.FT_LOAD_NO_BITMAP)

    plain_glyph = face.glyph.get_glyph()
    plain_bmp_glyph = plain_glyph.to_bitmap(freetype.FT_RENDER_MODE_NORMAL, freetype.Vector(0, 0), True)
    plain_bmp = plain_bmp_glyph.bitmap
    plain_left, plain_top = plain_bmp_glyph.left, plain_bmp_glyph.top

    face.load_char(char, freetype.FT_LOAD_DEFAULT | freetype.FT_LOAD_NO_BITMAP)
    stroked_glyph = face.glyph.get_glyph()
    stroker = freetype.Stroker()
    stroker.set(
        int(round(radius_px * 64)),
        freetype.FT_STROKER_LINECAP_ROUND,
        freetype.FT_STROKER_LINEJOIN_ROUND,
        0,
    )
    stroked_glyph.stroke(stroker, destroy=True)
    stroked_bmp_glyph = stroked_glyph.to_bitmap(freetype.FT_RENDER_MODE_NORMAL, freetype.Vector(0, 0), True)
    stroked_bmp = stroked_bmp_glyph.bitmap
    stroked_left, stroked_top = stroked_bmp_glyph.left, stroked_bmp_glyph.top

    def to_array(bmp) -> np.ndarray:
        buf = np.array(bmp.buffer, dtype=np.uint8).reshape(bmp.rows, bmp.width)
        return buf

    plain_arr = to_array(plain_bmp)
    stroked_arr = to_array(stroked_bmp)

    # Common canvas, generous padding, both placed by their own FreeType
    # bitmap_left/top relative to the shared pen origin (0, 0).
    pad = int(px_size * 0.6) + 8
    w = pad * 2 + max(plain_left + plain_arr.shape[1], stroked_left + stroked_arr.shape[1]) + 8
    h = pad * 2 + max(-plain_top + plain_arr.shape[0] * 2, -stroked_top + stroked_arr.shape[0] * 2) + 8
    canvas_plain = np.zeros((h, w), dtype=np.uint8)
    canvas_stroked = np.zeros((h, w), dtype=np.uint8)

    def paste(canvas, arr, left, top):
        x0, y0 = pad + left, pad - top + pad
        y1, x1 = y0 + arr.shape[0], x0 + arr.shape[1]
        canvas[y0:y1, x0:x1] = np.maximum(canvas[y0:y1, x0:x1], arr)

    paste(canvas_plain, plain_arr, plain_left, plain_top)
    paste(canvas_stroked, stroked_arr, stroked_left, stroked_top)
    return canvas_plain >= 128, canvas_stroked >= 128


def part2(results: list[str]) -> None:
    results.append("## Part 2 -- FreeType's own stroker vs. raster dilation\n")
    if not HAVE_FREETYPE:
        results.append("freetype-py not importable in this environment; skipped.\n")
        return
    char = "2"
    px = 80
    results.append(f"single glyph \"{char}\" at {px}px, FT_Glyph_Stroke (round cap/join):\n")
    results.append("| radius px | FT stroke ring px | raster-dilation ring px | ring IoU (FT vs raster) |")
    results.append("|---|---|---|---|")
    for radius in (1.0, 2.0, 3.0):
        plain, stroked = freetype_stroke_mask(char, px, radius)
        ft_ring = stroked & ~plain
        ideal = true_dilation(plain, radius)
        raster_ring = ideal & ~plain
        # Align sizes defensively (both built from the same canvas math so
        # they should already match).
        if ft_ring.shape != raster_ring.shape:
            results.append(f"| {radius} | shape mismatch {ft_ring.shape} vs {raster_ring.shape} | -- | -- |")
            continue
        inter = int((ft_ring & raster_ring).sum())
        union = int((ft_ring | raster_ring).sum())
        iou = inter / max(1, union)
        results.append(f"| {radius} | {int(ft_ring.sum())} | {int(raster_ring.sum())} | {iou:.3f} |")
        if radius == 2.0:
            save_mask_png(plain, HERE / "ft-plain-r2.png")
            save_mask_png(stroked, HERE / "ft-stroked-r2.png")
            save_diagnostic_png(stroked, ideal, plain, HERE / "ft-vs-raster-r2.png")
    results.append("")
    results.append(
        "Garmin's own engine (research 13 S2.1) uses a fixed 2.0px round-join "
        "stroke. The r=2.0 row above is the directly comparable case."
    )
    results.append("")


# --------------------------------------------------------------------------
# Part 3: rotation sweep -- does a fixed screen-space offset set's quality
# depend on the glyph's own rotation? (the radial-text question)
# --------------------------------------------------------------------------

def part3(results: list[str]) -> None:
    results.append("## Part 3 -- rotation sweep: does offset-set quality depend on glyph angle?\n")
    results.append(
        "Renders a single glyph (\"1\", chosen for its one dominant straight "
        "stroke), rotates the *mask* by theta (standing in for a radial-text "
        "glyph's own per-glyph rotation, which a fixed screen-space offset "
        "set cannot track), stamps with each offset set at r=2, and compares "
        "against the true dilation of the *rotated* mask (rotation and true "
        "dilation commute for a continuous disc, so this isolates the "
        "discrete offset set's own directional bias).\n"
    )
    base = render_mask("1", 100, antialias=False)
    # Crop tightly first so rotation doesn't compound padding asymmetry.
    ys, xs = np.where(base)
    base = base[ys.min() - 4: ys.max() + 5, xs.min() - 4: xs.max() + 5]
    r = 2
    results.append("| angle deg | offset set | missing px | extra px | ring IoU |")
    results.append("|---|---|---|---|---|")
    angles = (0, 15, 30, 45, 60, 75, 90)
    iou_by_set: dict[str, list[float]] = {name: [] for name in OFFSET_SETS}
    for angle in angles:
        img = Image.fromarray((base.astype(np.uint8) * 255))
        rotated_img = img.rotate(-angle, resample=Image.BICUBIC, expand=True, fillcolor=0)
        rotated = np.array(rotated_img) >= 128
        ideal = true_dilation(rotated, r)
        for name, fn in OFFSET_SETS.items():
            offs = fn(r)
            stamped = stamp(rotated, offs)
            m = compare(stamped, ideal, rotated)
            iou_by_set[name].append(m["ring_iou"])
            results.append(f"| {angle} | {name} | {m['missing_px']} | {m['extra_px']} | {m['ring_iou']:.3f} |")
    results.append("")
    results.append("Spread (max - min ring IoU) across the sweep, per offset set:\n")
    results.append("| offset set | min IoU | max IoU | spread |")
    results.append("|---|---|---|---|")
    for name, vals in iou_by_set.items():
        results.append(f"| {name} | {min(vals):.3f} | {max(vals):.3f} | {max(vals) - min(vals):.3f} |")
    results.append("")
    # One illustrative pair of PNGs: 0 degrees and 45 degrees, square8.
    for angle in (0, 45):
        img = Image.fromarray((base.astype(np.uint8) * 255))
        rotated_img = img.rotate(-angle, resample=Image.BICUBIC, expand=True, fillcolor=0)
        rotated = np.array(rotated_img) >= 128
        ideal = true_dilation(rotated, r)
        stamped = stamp(rotated, offsets_square8(r))
        save_diagnostic_png(stamped, ideal, rotated, HERE / f"rotation-square8-{angle}deg.png")
    results.append("")


# --------------------------------------------------------------------------
# Part 4: anti-aliased stamping (darkening/thickening)
# --------------------------------------------------------------------------

def part4(results: list[str]) -> None:
    results.append("## Part 4 -- stamping an anti-aliased glyph: edge alpha after overlap\n")
    aa = render_mask(TEXT, 80, antialias=True).astype(np.float64) / 255.0
    r = 2
    offs = offsets_square8(r)
    # Simulate "N stamps in outline colour, painter's-algorithm composited,
    # each draw call fully opaque *per source pixel* (this is what a real
    # drawText call does -- it is not additive blending): the result at
    # each destination pixel is the coverage-weighted alpha of the
    # topmost (last-drawn) stamp whose glyph covers that pixel, not a sum.
    # Model it as the maximum alpha seen at that pixel across all stamps,
    # which is the correct result for opaque single-colour draws over a
    # background of some fixed colour with no blending (constraint 10:
    # alphaBlendingSupport is false on MIP, so drawText's AA edge coverage
    # is resolved against the background colour at draw time, per call --
    # painting stamp k+1 fully overwrites whatever stamp k left at a given
    # pixel, weighted by stamp k+1's own coverage there).
    stacked = np.zeros_like(aa)
    for dx, dy in offs:
        shifted = np.zeros_like(aa)
        h, w = aa.shape
        src_x0, src_x1 = max(0, -dx), min(w, w - dx)
        src_y0, src_y1 = max(0, -dy), min(h, h - dy)
        dst_x0, dst_x1 = max(0, dx), min(w, w + dx)
        dst_y0, dst_y1 = max(0, dy), min(h, h + dy)
        shifted[dst_y0:dst_y1, dst_x0:dst_x1] = aa[src_y0:src_y1, src_x0:src_x1]
        stacked = np.maximum(stacked, shifted)
    edge_only_orig = (aa > 0.0) & (aa < 1.0)
    edge_only_stamped = (stacked > 0.0) & (stacked < 1.0)
    results.append(
        f"original AA edge pixels (0<alpha<1): {int(edge_only_orig.sum())}, "
        f"mean alpha there: {aa[edge_only_orig].mean():.3f}"
    )
    results.append(
        f"stamped (max-composited) AA edge pixels: {int(edge_only_stamped.sum())}, "
        f"mean alpha there: {stacked[edge_only_stamped].mean():.3f}"
    )
    results.append(
        "Interpretation: max-compositing N opaque stamps thickens the "
        "effective edge (more pixels reach alpha 1) and raises the mean "
        "alpha of what remains a fractional edge, i.e. the anti-aliased "
        "edge gets measurably harder/thicker, never softer -- consistent "
        "with N overlapping opaque draws, never additive-blended (constraint "
        "10, no alphaBlendingSupport on MIP)."
    )
    results.append("")
    save_mask_png(edge_only_orig, HERE / "aa-edge-original.png")
    save_mask_png(edge_only_stamped, HERE / "aa-edge-stamped.png")


def main() -> None:
    results: list[str] = [
        "# Stamped-ring probe results",
        "",
        f"font: {FONT_PATH.relative_to(REPO_ROOT)}",
        f"freetype-py available: {HAVE_FREETYPE}",
        "",
    ]
    part1(results)
    part2(results)
    part3(results)
    part4(results)
    text = "\n".join(results) + "\n"
    (HERE / "results.md").write_text(text)
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
