"""Read the 64 swatches out of phone photos of face.yaml on a watch and test the model (research 38).

The photos are a fēnix 8 Solar showing face.yaml in office light: one at an angle
with the backlight off, two with it on, and one close and square-on with it off,
taken to look as much like the watch as possible; and that last one again with
its levels set by the user while looking at the watch. For each photo the four corners
of the swatch grid were found by hand; a homography maps the face's 173 px grid
onto the photo, and each swatch is the median of a ring of points inside it, clear
of its edge and of the black dot a dropped colour carries.

A phone camera is not a colorimeter: its tone curve is unknown and it boosts
contrast and colour. So the step test uses only the *order* of the swatches'
lightness, which any monotone tone curve keeps, and the colour comparisons are
relative, inside one photo.

Prints, per photo:
  - the step test: pairs of swatches whose lightness order the linear (area) steps
    and the monitor-like steps predict the opposite way, and which order the photo
    shows; and the step values (55, AA) whose predicted order best matches it;
  - the photo's chroma against the model's, and the gamut that would match it;
  - lightness and chroma of each of choose.py's groups, against the photo's white;
  - the closest pairs among the 27 kept colours;
  - choose.py's deduplication re-run on the photo's colours;
each colour figure twice: as photographed, and less the light the watch glass
reflects (deglare), which washes every swatch toward white by the same amount.
`--png` writes photos.png: each photo's 64 balanced to its white swatch, the close
photo again less the glare, then the datasheet, wider and monitor models.
"""
import sys

import numpy as np
from PIL import Image
from scipy.stats import kendalltau

from choose import PURE, THRESHOLD, rule, select
from model import CONTRAST, GARMIN, LEVELS, NAMED, PANELS, Panel, de2000, lab, lch, transfer, widened

CELL, GAP = 19, 3
STEP = CELL + GAP
SIDE = 8 * STEP - GAP
# Corners of the swatch grid (top left, top right, bottom right, bottom left) in each photo, by eye.
PHOTOS = {
    "photo-ambient.jpg": [(112, 125), (625, 103), (681, 589), (113, 637)],
    "photo-backlight-1.jpg": [(82, 243), (573, 132), (703, 600), (167, 720)],
    "photo-backlight-2.jpg": [(85, 130), (586, 40), (686, 537), (155, 615)],
    "photo-close.jpg": [(-4, -2), (813, -2), (813, 811), (-4, 811)],  # cropped to the grid; its outer edge is off the image
    "photo-eye.jpg": [(-4, -2), (813, -2), (813, 811), (-4, 811)],    # photo-close.jpg, levels matched to the watch by eye
}
HEX = [h for _, h in NAMED]
NAME = {h: n for n, h in NAMED}
LV = np.array([[LEVELS.index(int(h[i:i + 2], 16)) for i in (0, 2, 4)] for h in HEX])
SRGB_TO_XYZ = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
DATASHEET, WIDER = PANELS[0], PANELS[1]


def homography(src, dst):
    rows = []
    for (x, y), (u, v) in zip(src, dst):
        rows += [[x, y, 1, 0, 0, 0, -u * x, -u * y, -u], [0, 0, 0, x, y, 1, -v * x, -v * y, -v]]
    h = np.linalg.svd(np.array(rows, float))[2][-1]
    return h.reshape(3, 3) / h[-1]


def swatches(path):
    """The 64 swatches' camera sRGB, in NAMED's order."""
    H = homography([(0, 0), (SIDE, 0), (SIDE, SIDE), (0, SIDE)], PHOTOS[path])
    a = np.asarray(Image.open(path).convert("RGB"), float)
    out = []
    for i in range(64):
        cx, cy = (i % 8) * STEP + CELL / 2, (i // 8) * STEP + CELL / 2
        ring = []
        for dx in np.arange(-7.5, 7.6, 0.75):
            for dy in np.arange(-7.5, 7.6, 0.75):
                if max(abs(dx), abs(dy)) < 5:  # the dot is 6 px wide
                    continue
                p = H @ [cx + dx, cy + dy, 1]
                ring.append(a[int(round(p[1] / p[2])), int(round(p[0] / p[2]))])
        out.append(np.median(ring, axis=0))
    return np.array(out)


def decode(v):
    c = v / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def predicted_y(steps):
    """Each colour's luminance on the datasheet panel if a channel's levels reflect `steps` of the light."""
    return (np.array(steps)[LV] * np.array(DATASHEET.m[1])).sum(1)


def step_test(Y):
    linear = predicted_y([0, 1 / 3, 2 / 3, 1])
    gamma = predicted_y([transfer(level, "gamma") for level in range(4)])
    votes = {"linear": 0, "gamma": 0, "too close": 0}
    for i in range(64):
        for j in range(i + 1, 64):
            dl, dg = linear[i] - linear[j], gamma[i] - gamma[j]
            if dl * dg >= 0:
                continue
            dy = Y[i] - Y[j]
            votes["too close" if abs(dy) < 0.03 * max(Y[i], Y[j]) else "linear" if dy * dl > 0 else "gamma"] += 1
    grid = [(kendalltau(Y, predicted_y([0, a, b, 1]))[0], a, b)
            for a in np.arange(0.02, 0.99, 0.02) for b in np.arange(0.04, 1.0, 0.02) if b > a]
    best = max(grid)
    near = [(a, b) for t, a, b in grid if t >= best[0] - 0.01]
    taus = {name: kendalltau(Y, y)[0] for name, y in (("linear", linear), ("gamma", gamma))}
    return votes, best, near, taus


def deglare(lin):
    """Linear swatches less the light the glass reflects: a constant, taken off until black is 1/25 of white (the
    measured panel's contrast). It keeps the lightness order and gives back the chroma the reflection washes out."""
    black, white = lin[HEX.index("000000")], lin[HEX.index("FFFFFF")]
    return lin - np.clip((black - white / CONTRAST) / (1 - 1 / CONTRAST), 0, None)


def adapted_lab(rgb, glare=False):
    """CIELAB with the photo's own white swatch as the white the eye adapts to (von Kries in linear sRGB)."""
    lin = deglare(decode(rgb)) if glare else decode(rgb)
    lin = lin / lin[HEX.index("FFFFFF")]
    white = SRGB_TO_XYZ @ np.ones(3)
    return {h: lab(*(SRGB_TO_XYZ @ lin[i]), white) for i, h in enumerate(HEX)}


def gamut_match(Lab):
    """The gamut (% of NTSC, the datasheet's primaries pushed out from white) whose median chroma matches the photo's."""
    chromatic = [h for h in HEX if rule(h) != "gray"]
    C = np.array([lch(Lab[h])[1] for h in chromatic])

    def ratio(panel):
        return np.median(C / np.array([lch(panel.seen(h))[1] for h in chromatic]))
    best = min((abs(ratio(Panel("fit", widened(DATASHEET.prim, r), "area", CONTRAST)) - 1), r)
               for r in np.arange(0.04, 0.40, 0.005))
    return ratio(DATASHEET), ratio(WIDER), best[1]


def reselect(Lab, kept):
    """choose.py's deduplication on the photo's colours, its threshold scaled by the photo's ΔE against the model's."""
    left = [h for h in HEX if rule(h) is None]
    scale = np.median([de2000(Lab[a], Lab[b]) / de2000(WIDER.seen(a), WIDER.seen(b))
                       for i, a in enumerate(left) for b in left[i + 1:]])
    order = (PURE + [h for h in HEX if h in GARMIN and h in left and h not in PURE]
             + sorted((h for h in left if h not in GARMIN and h not in PURE), key=lambda h: -lch(Lab[h])[1]))
    out = []
    for h in order:
        if all(de2000(Lab[h], Lab[k]) >= THRESHOLD * scale for k in out):
            out.append(h)
    chromatic = [h for h in kept if rule(h) != "gray"]
    return scale, [h for h in chromatic if h not in out], [h for h in out if h not in chromatic]


def report(Lab, kept, title):
    print(title)
    print("    grays L*: " + ", ".join(f"{h} {Lab[h][0]:.0f}" for h in ("000000", "555555", "AAAAAA", "FFFFFF")))
    vs_datasheet, vs_wider, ntsc = gamut_match(Lab)
    print(f"    chroma: {vs_datasheet:.2f}x datasheet, {vs_wider:.2f}x wider; matches a gamut of {100 * ntsc:.1f}% NTSC")
    for group in ("pastel", "muted", "dark", "brown/olive", None):
        hs = [h for h in HEX if rule(h) == group]
        print(f"    {group or 'the rest':<12} L* {np.mean([Lab[h][0] for h in hs]):5.1f}"
              f"  C* {np.mean([lch(Lab[h])[1] for h in hs]):5.1f}")
    pairs = sorted((de2000(Lab[a], Lab[b]), a, b) for i, a in enumerate(kept) for b in kept[i + 1:])
    print("    closest kept pairs: " + "; ".join(f"{NAME[a]}/{NAME[b]} {d:.1f}" for d, a, b in pairs[:8]))
    scale, lost, gained = reselect(Lab, kept)
    print(f"    re-run on the photo (threshold {THRESHOLD * scale:.1f}): drops {', '.join(NAME[h] for h in lost)};"
          f" adds {', '.join(NAME[h] for h in gained)}")


if __name__ == "__main__":
    kept, _ = select()
    sampled = {}
    for path in PHOTOS:
        rgb = sampled[path] = swatches(path)
        Y = decode(rgb) @ [0.2126, 0.7152, 0.0722]
        votes, best, near, taus = step_test(Y)
        print(f"== {path}")
        print(f"  steps: pairs the two step models order oppositely, the photo sides with {votes}")
        print(f"  steps: Kendall tau linear {taus['linear']:.3f}, monitor-like {taus['gamma']:.3f};"
              f" best fit 55={best[1]:.2f} AA={best[2]:.2f} (tau {best[0]:.3f}; within 0.01 of it:"
              f" 55 {min(a for a, _ in near):.2f}-{max(a for a, _ in near):.2f},"
              f" AA {min(b for _, b in near):.2f}-{max(b for _, b in near):.2f})")
        for glare in (False, True):
            report(adapted_lab(rgb, glare), kept, "  less the glass glare:" if glare else "  as photographed:")
    if "--png" in sys.argv:
        from PIL import ImageDraw
        S, G, PAD = 20, 2, 12
        def balanced(rgb, glare=False):
            """The photo's swatches scaled in linear light so its white swatch draws white."""
            lin = deglare(decode(rgb)) if glare else decode(rgb)
            lin = np.clip(lin / lin[HEX.index("FFFFFF")], 0, 1)
            enc = np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * lin ** (1 / 2.4) - 0.055)
            return lambda h: tuple(int(round(255 * v)) for v in enc[HEX.index(h)])
        cols = [(p, balanced(sampled[p])) for p in PHOTOS]
        cols += [("close, less glare", balanced(sampled["photo-close.jpg"], True))]
        cols += [(p.name, p.display) for p in (DATASHEET, WIDER, PANELS[-1])]
        im = Image.new("RGB", (len(cols) * (8 * (S + G) + PAD) + G, 8 * (S + G) + G), (40, 40, 40))
        d = ImageDraw.Draw(im)
        for k, (_, colour) in enumerate(cols):
            for i, h in enumerate(HEX):
                x, y = G + k * (8 * (S + G) + PAD) + (i % 8) * (S + G), G + (i // 8) * (S + G)
                d.rectangle([x, y, x + S - 1, y + S - 1], fill=colour(h))
        im.save("photos.png")
