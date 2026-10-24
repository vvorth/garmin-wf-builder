"""How the 64 MIP colours look on a reflective panel, modelled from a datasheet.

Each colour is mixed from the panel's own measured primaries (a 64-colour
MIP module's datasheet, research 37 §2), reflected under ambient light with
the panel's contrast, and judged in CIELAB against the panel's own white.
Run with no arguments for the table (`--csv` for CSV); `--png` also writes
`appearance.png`, the 64 as a monitor shows them beside the model's view.
"""
import math
import sys

LEVELS = [0x00, 0x55, 0xAA, 0xFF]

# The 64 with Garmin-community names (ts/src/palette.ts, MIP64_NAMED).
NAMED = [
    ("white", "FFFFFF"), ("shalimar", "FFFFAA"), ("laser_lemon", "FFFF55"), ("yellow", "FFFF00"),
    ("lavender_rose", "FFAAFF"), ("sundown", "FFAAAA"), ("texas_rose", "FFAA55"), ("web_orange", "FFAA00"),
    ("pink_flamingo", "FF55FF"), ("brilliant_rose", "FF55AA"), ("sunset_orange", "FF5555"), ("international_orange", "FF5500"),
    ("magenta_fuchsia", "FF00FF"), ("hollywood_cerise", "FF00AA"), ("razzmatazz", "FF0055"), ("red", "FF0000"),
    ("pale_turquoise", "AAFFFF"), ("mint_green", "AAFFAA"), ("conifer", "AAFF55"), ("spring_bud", "AAFF00"),
    ("perano", "AAAAFF"), ("silver_chalice", "AAAAAA"), ("olive_green", "AAAA55"), ("citrus", "AAAA00"),
    ("medium_purple", "AA55FF"), ("violet_blue", "AA55AA"), ("apple_blossom", "AA5555"), ("rust", "AA5500"),
    ("electric_violet", "AA00FF"), ("dark_magenta", "AA00AA"), ("jazzberry_jam", "AA0055"), ("bright_red", "AA0000"),
    ("baby_blue", "55FFFF"), ("medium_aquamarine", "55FFAA"), ("screamin_green", "55FF55"), ("bright_green", "55FF00"),
    ("cornflower_blue", "55AAFF"), ("cadet_blue", "55AAAA"), ("fruit_salad", "55AA55"), ("kelly_green", "55AA00"),
    ("neon_blue", "5555FF"), ("rich_blue", "5555AA"), ("emperor", "555555"), ("verdun_green", "555500"),
    ("electric_indigo", "5500FF"), ("indigo", "5500AA"), ("tyrian_purple", "550055"), ("maroon", "550000"),
    ("aqua", "00FFFF"), ("medium_green", "00FFAA"), ("malachite", "00FF55"), ("green", "00FF00"),
    ("azure_radiance", "00AAFF"), ("persian_green", "00AAAA"), ("pigment_green", "00AA55"), ("japanese_laurel", "00AA00"),
    ("navy_blue", "0055FF"), ("cobalt", "0055AA"), ("mosque", "005555"), ("dark_green", "005500"),
    ("blue", "0000FF"), ("midnight_blue", "0000AA"), ("navy", "000055"), ("black", "000000"),
]

# Graphics.COLOR_* (Toybox/Graphics.html): Garmin's own named colours, all 14 among the 64.
GARMIN = {"FFFFFF", "AAAAAA", "555555", "000000", "FF0000", "AA0000", "FF5500", "FFAA00",
          "00FF00", "00AA00", "00AAFF", "0000FF", "AA00FF", "FF00FF"}

# ASI-T-213DA1AN/A, 64-colour MIP, reflective, typical values (research 37 §2).
DATASHEET = {"R": (0.381, 0.289), "G": (0.322, 0.371), "B": (0.165, 0.176), "W": (0.291, 0.288)}
CONTRAST = 25.0
NTSC = [(0.67, 0.33), (0.21, 0.71), (0.14, 0.08)]


def area(tri):
    (x1, y1), (x2, y2), (x3, y3) = tri
    return abs(x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2)) / 2


def ntsc_ratio(prim):
    return area([prim["R"], prim["G"], prim["B"]]) / area(NTSC)


def widened(prim, ratio):
    """The primaries pushed straight out from the white point until the gamut is `ratio` of NTSC."""
    k = math.sqrt(ratio / ntsc_ratio(prim))
    wx, wy = prim["W"]
    out = {c: (wx + (x - wx) * k, wy + (y - wy) * k) for c, (x, y) in prim.items() if c != "W"}
    out["W"] = prim["W"]
    return out


def xyz(x, y, Y=1.0):
    return (x * Y / y, Y, (1 - x - y) * Y / y)


def solve3(m, v):
    """m (3x3, rows) times u = v, by Cramer's rule."""
    def det(a):
        return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
                + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    d = det(m)
    out = []
    for i in range(3):
        a = [row[:] for row in m]
        for r in range(3):
            a[r][i] = v[r]
        out.append(det(a) / d)
    return out


def matrix(prim):
    """Linear RGB (white = 1, 1, 1) to XYZ with white Y = 1: the usual primaries derivation."""
    cols = [xyz(*prim[c]) for c in "RGB"]
    m = [[cols[c][r] for c in range(3)] for r in range(3)]
    s = solve3(m, list(xyz(*prim["W"])))
    return [[m[r][c] * s[c] for c in range(3)] for r in range(3)]


SRGB = {"R": (0.64, 0.33), "G": (0.30, 0.60), "B": (0.15, 0.06), "W": (0.3127, 0.3290)}


def srgb_decode(v):
    c = v / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def transfer(level, mode):
    """A channel's level (0..3) as the fraction of light its subpixel reflects."""
    if mode == "area":           # two memory bits per subpixel, areas 2:1 (§3): linear steps
        return level / 3
    return srgb_decode(LEVELS[level])  # as a monitor would, for comparison


def lab(X, Y, Z, white):
    def f(t):
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29
    fx, fy, fz = f(X / white[0]), f(Y / white[1]), f(Z / white[2])
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def de2000(a, b):
    """CIEDE2000 (Sharma, Wu and Dalal 2005)."""
    L1, a1, b1 = a
    L2, a2, b2 = b
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if C1p else 0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if C2p else 0
    dL, dC = L2 - L1, C2p - C1p
    dh = 0 if C1p * C2p == 0 else (h2p - h1p if abs(h2p - h1p) <= 180 else h2p - h1p - 360 if h2p > h1p else h2p - h1p + 360)
    dH = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dh / 2))
    Lb, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    if C1p * C2p == 0:
        hb = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hb = (h1p + h2p) / 2
    else:
        hb = (h1p + h2p + 360) / 2 if h1p + h2p < 360 else (h1p + h2p - 360) / 2
    T = (1 - 0.17 * math.cos(math.radians(hb - 30)) + 0.24 * math.cos(math.radians(2 * hb))
         + 0.32 * math.cos(math.radians(3 * hb + 6)) - 0.20 * math.cos(math.radians(4 * hb - 63)))
    Sl = 1 + 0.015 * (Lb - 50) ** 2 / math.sqrt(20 + (Lb - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * T
    Rt = -2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7)) * math.sin(math.radians(60 * math.exp(-(((hb - 275) / 25) ** 2))))
    return math.sqrt((dL / Sl) ** 2 + (dC / Sc) ** 2 + (dH / Sh) ** 2 + Rt * (dC / Sc) * (dH / Sh))


class Panel:
    def __init__(self, name, prim, mode, contrast):
        self.name, self.prim, self.mode, self.contrast = name, prim, mode, contrast
        self.m = matrix(prim)
        self.white = [sum(row) for row in self.m]

    def seen(self, hexcode):
        """CIELAB against the panel's own white: the eye adapted to the panel."""
        levels = [LEVELS.index(int(hexcode[i:i + 2], 16)) for i in (0, 2, 4)]
        lin = [transfer(level, self.mode) for level in levels]
        black = 1 / self.contrast
        lin = [black + (1 - black) * v for v in lin]
        X, Y, Z = (sum(self.m[r][c] * lin[c] for c in range(3)) for r in range(3))
        return lab(X, Y, Z, self.white)

    def display(self, hexcode):
        """The model's colour as sRGB for a picture, its white mapped to sRGB white."""
        L, a, b = self.seen(hexcode)
        fy = (L + 16) / 116
        fx, fz = fy + a / 500, fy - b / 200
        inv = lambda t: t ** 3 if t > 6 / 29 else 3 * (6 / 29) ** 2 * (t - 4 / 29)
        X, Y, Z = 0.95047 * inv(fx), inv(fy), 1.08883 * inv(fz)
        r = 3.2406 * X - 1.5372 * Y - 0.4986 * Z
        g = -0.9689 * X + 1.8758 * Y + 0.0415 * Z
        bb = 0.0557 * X - 0.2040 * Y + 1.0570 * Z
        enc = lambda c: round(255 * max(0.0, min(1.0, 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055)))
        return (enc(r), enc(g), enc(bb))


PANELS = [
    Panel("datasheet", DATASHEET, "area", CONTRAST),            # the measured module, linear steps
    Panel("wider", widened(DATASHEET, 0.23), "area", CONTRAST),  # JDI's 8-colour MIP gamut, 23% NTSC
    Panel("gamma", DATASHEET, "gamma", CONTRAST),                # the measured module, monitor-like steps
    Panel("monitor", SRGB, "gamma", 1e9),                        # an sRGB monitor, the simulator's view
]


def lch(c):
    L, a, b = c
    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


if __name__ == "__main__":
    for p in PANELS:
        print(f"# {p.name}: NTSC {100 * ntsc_ratio(p.prim):.1f}%, steps {p.mode}, contrast {p.contrast:g}:1", file=sys.stderr)
    csv = "--csv" in sys.argv
    head = ["name", "hex"] + [f"{p.name}_{k}" for p in PANELS for k in ("L", "C", "h", "near", "dE")]
    print(",".join(head) if csv else "")
    for name, h in NAMED:
        row = [name, h]
        for p in PANELS:
            me = p.seen(h)
            near = min((de2000(me, p.seen(o)), o) for n, o in NAMED if o != h)
            L, C, hue = lch(me)
            row += [f"{L:.0f}", f"{C:.0f}", f"{hue:.0f}", near[1], f"{near[0]:.1f}"]
        print(",".join(row) if csv else " ".join(f"{v:>7}" if i > 1 else f"{v:<21}" for i, v in enumerate(row)))
    if "--png" in sys.argv:
        from PIL import Image, ImageDraw
        S, G = 28, 3
        im = Image.new("RGB", (len(PANELS) * (8 * (S + G) + 12) + G, 8 * (S + G) + G), (40, 40, 40))
        d = ImageDraw.Draw(im)
        for k, p in enumerate(PANELS):
            for i, (_, h) in enumerate(NAMED):
                x = G + k * (8 * (S + G) + 12) + (i % 8) * (S + G)
                y = G + (i // 8) * (S + G)
                d.rectangle([x, y, x + S - 1, y + S - 1], fill=p.display(h))
        im.save("appearance.png")
