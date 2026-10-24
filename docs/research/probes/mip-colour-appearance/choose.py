"""Choose the colours a `choices: any` colour setting offers (research 37 §5); `python3 choose.py`.

Rules, in order, over the 64:
  1. the four grays stay;
  2. pastels (brightest channel FF, dimmest AA) go: off-white on the panel;
  3. muted colours (brightest AA, dimmest 55) go: gray with a tint;
  4. dark colours (no channel above 55) go: a dim copy of a brighter sibling;
  5. brown, olive and dark chartreuse (an orange-to-yellow-green hue whose
     brightest channel is AA) go;
  6. what is left is deduplicated: in priority order (the six full-strength
     hues, then Garmin's own Graphics.COLOR_* colours, then by chroma), a
     colour within CIEDE2000 9 of one already kept, on the `wider` panel, goes.
Prints the kept list in the picker's family order, the drops with reasons,
and the closest kept pair on every panel; `--png` writes `selection.png`.
"""
import colorsys
import sys

from model import GARMIN, LEVELS, NAMED, PANELS, de2000, lch

THRESHOLD = 9.0
MAIN = next(p for p in PANELS if p.name == "wider")
PURE = ["FF0000", "FFFF00", "00FF00", "00FFFF", "0000FF", "FF00FF"]
FAMILIES = ["Red", "Yellow", "Green", "Cyan", "Blue", "Magenta"]
NAME = {h: n for n, h in NAMED}


def levels(h):
    return [LEVELS.index(int(h[i:i + 2], 16)) for i in (0, 2, 4)]


def hue(h):
    return colorsys.rgb_to_hsv(*(v / 3 for v in levels(h)))[0] * 360


def rule(h):
    hi, lo = max(levels(h)), min(levels(h))
    if hi == lo:
        return "gray"
    if (hi, lo) == (3, 2):
        return "pastel"
    if (hi, lo) == (2, 1):
        return "muted"
    if hi == 1:
        return "dark"
    if 20 <= hue(h) <= 105 and hi < 3:
        return "brown/olive"
    return None


def select():
    reasons = {h: rule(h) for _, h in NAMED}
    left = [h for _, h in NAMED if reasons[h] is None]
    order = (PURE + [h for _, h in NAMED if h in GARMIN and h in left and h not in PURE]
             + sorted((h for h in left if h not in GARMIN and h not in PURE), key=lambda h: -lch(MAIN.seen(h))[1]))
    kept = []
    for h in order:
        clash = next((k for k in kept if de2000(MAIN.seen(h), MAIN.seen(k)) < THRESHOLD), None)
        if clash is None:
            kept.append(h)
        else:
            reasons[h] = f"like {NAME[clash]}"
    kept += [h for _, h in NAMED if reasons[h] == "gray"]
    return kept, reasons


def family_order(kept):
    """The editor picker's order (research 36): family by family, each light to dark, a row running on from the
    previous family's side; then the grays light to dark. The kept set has no pastel or muted colour, so a row is
    its tier, and a row's order is the signed hue angle from the family's centre."""
    def key(h):
        family = int(((hue(h) + 30) % 360) // 60)
        row = {(3, 1): 0, (3, 2): 0, (3, 0): 1, (2, 0): 2, (2, 1): 2, (1, 0): 3}[(max(levels(h)), min(levels(h)))]
        return family, row, ((hue(h) - family * 60 + 540) % 360) - 180
    chromatic = sorted((h for h in kept if rule(h) != "gray"), key=key)
    return chromatic + sorted((h for h in kept if rule(h) == "gray"), key=lambda h: -levels(h)[0])


if __name__ == "__main__":
    kept, reasons = select()
    ordered = family_order(kept)
    print(f"kept {len(ordered)}:")
    for h in ordered:
        L, C, H = lch(MAIN.seen(h))
        fam = "Gray" if rule(h) == "gray" else FAMILIES[int(((hue(h) + 30) % 360) // 60)]
        print(f"  {fam:<8} {NAME[h]:<20} #{h}  L*{L:3.0f} C*{C:3.0f} h{H:4.0f}{'  Garmin' if h in GARMIN else ''}")
    print("dropped:")
    for why in ("pastel", "muted", "dark", "brown/olive"):
        print(f"  {why:<12} " + ", ".join(NAME[h] for _, h in NAMED if reasons[h] == why))
    print("  " + "duplicate".ljust(12) + " " + ", ".join(f"{NAME[h]} ({r})" for _, h in NAMED if (r := reasons[h]) and r.startswith("like ")))
    for p in PANELS:
        d, a, b = min((de2000(p.seen(a), p.seen(b)), a, b) for i, a in enumerate(kept) for b in kept[i + 1:])
        print(f"closest kept pair, {p.name}: {NAME[a]} / {NAME[b]}, dE00 {d:.1f}")
    if "--png" in sys.argv:
        from PIL import Image, ImageDraw
        S, G = 28, 3
        panels = [MAIN, PANELS[-1]]
        im = Image.new("RGB", (len(panels) * (8 * (S + G) + 12) + G, 8 * (S + G) + G), (40, 40, 40))
        d = ImageDraw.Draw(im)
        for k, p in enumerate(panels):
            for i, (_, h) in enumerate(NAMED):
                x = G + k * (8 * (S + G) + 12) + (i % 8) * (S + G)
                y = G + (i // 8) * (S + G)
                d.rectangle([x, y, x + S - 1, y + S - 1], fill=p.display(h))
                if h not in kept:  # a dropped colour is crossed out
                    d.line([x + 4, y + 4, x + S - 5, y + S - 5], fill=(40, 40, 40), width=3)
                    d.line([x + 4, y + S - 5, x + S - 5, y + 4], fill=(40, 40, 40), width=3)
        im.save("selection.png")
