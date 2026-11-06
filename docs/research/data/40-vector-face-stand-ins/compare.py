# Renders one sample in a real Garmin face and in each free candidate, one
# row each at the same em, and scores every candidate against the real face:
#   width  -- the sample's advance width at the same em, relative to the
#             real face's (what a fallback at the same size would occupy);
#   ink    -- mean per-glyph ink overlap (IoU) with the real face, each glyph
#             drawn alone on the same baseline, the candidate scaled so that
#             MATCH (a reference glyph) is as tall as in the real face: the
#             letterform alike, size aside (1.00 = the same shape);
#   scale  -- that scale (how much larger or smaller the candidate draws);
#   cover  -- how many of the sample's characters the candidate maps.
# Usage: python -I compare.py OUT.png TITLE SAMPLE MATCH REAL=path [LABEL=path ...]
# Needs Pillow built with raqm (Arabic and Hebrew shaping) and fontTools.
import sys
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen

out, title, sample, match, *specs = sys.argv[1:]
rows = [s.split("=", 1) for s in specs]
EM, PAD, LABEL_W, MASK = 64, 16, 360, 128

def advance(path, text):
    return ImageFont.truetype(path, 1000, layout_engine=ImageFont.Layout.RAQM).getlength(text)

def cmap(path):
    return TTFont(path, lazy=True).getBestCmap()

def height(path, ch):
    f = TTFont(path); g = f.getBestCmap()[ord(ch)]; pen = BoundsPen(f.getGlyphSet()); f.getGlyphSet()[g].draw(pen)
    return (pen.bounds[3] - pen.bounds[1]) / f["head"].unitsPerEm

def mask(path, ch, size):
    f = ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.BASIC)
    im = Image.new("L", (MASK * 3, MASK * 3), 0)
    ImageDraw.Draw(im).text((MASK, MASK * 2), ch, font=f, fill=255, anchor="ls")
    return im.point(lambda v: 255 if v >= 128 else 0).tobytes()

def ink(real, cand, text, scale):
    cr, cc = cmap(real), cmap(cand)
    scores = []
    for ch in dict.fromkeys(c for c in text if not c.isspace()):
        if ord(ch) not in cr or ord(ch) not in cc: continue
        a, b = mask(real, ch, MASK), mask(cand, ch, round(MASK * scale))
        inter = sum(1 for p, q in zip(a, b) if p and q)
        union = sum(1 for p, q in zip(a, b) if p or q)
        if union: scores.append(inter / union)
    return sum(scores) / len(scores) if scores else 0.0

real_path = rows[0][1]
real_w, real_h = advance(real_path, sample), height(real_path, match)
fonts = [ImageFont.truetype(p, EM, layout_engine=ImageFont.Layout.RAQM) for _, p in rows]
width = max(int(f.getlength(sample)) for f in fonts) + LABEL_W + 3 * PAD
row_h = int(EM * 1.6)
im = Image.new("RGB", (width, PAD * 2 + 34 + row_h * len(rows)), "white")
d = ImageDraw.Draw(im)
small = ImageFont.load_default(size=15)
d.text((PAD, PAD), title, fill="black", font=ImageFont.load_default(size=20))
print(f"{title}  (sample {sample!r}, ink matched on {match!r})")
print("| candidate | width at same em | ink overlap | scale | covers |\n|---|---|---|---|---|")
for i, ((label, path), f) in enumerate(zip(rows, fonts)):
    y = PAD + 34 + i * row_h
    if i == 0: d.rectangle([0, y, width, y + row_h - 1], fill="#eef3ff")
    w = advance(path, sample) / real_w
    scale = real_h / height(path, match) if ord(match) in cmap(path) else 1.0
    score = 1.0 if i == 0 else ink(real_path, path, sample, scale)
    chars = [c for c in sample if not c.isspace()]
    n = sum(ord(c) in cmap(path) for c in chars)
    d.text((PAD, y + 8), label, fill="black", font=small)
    d.text((PAD, y + 30), f"width {w:.3f}  ink {score:.2f}  scale {scale:.2f}  covers {n}/{len(chars)}", fill="#555", font=small)
    d.text((LABEL_W + PAD, y + int(EM * 1.15)), sample, font=f, fill="black", anchor="ls")
    print(f"| {label} | {w:.3f} | {score:.2f} | {scale:.2f} | {n}/{len(chars)} |")
im.save(out)
