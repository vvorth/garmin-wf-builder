"""Bakes the example faces' own fonts with wfb.fonts.bmfont.bake (Pillow and
FreeType, 16x supersampled) and dumps every glyph tile and metric, for
fonts.mjs to reproduce without Pillow.

    ./.venv/bin/python docs/research/probes/typescript-stack/dump_bakes.py > bakes.json
"""
import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
from fontTools.ttLib import TTFont  # noqa: E402

from wfb.fonts.bmfont import bake  # noqa: E402

ASCII = "".join(chr(c) for c in range(0x21, 0x7F))
icon = Path("wfb/assets/icons/SymbolsNerdFont-Regular.ttf")
with TTFont(str(icon), lazy=True) as f:
    icon_chars = "".join(chr(c) for c in sorted(f.getBestCmap())[100:4000:60])
# (source, sizes): the example faces' sizes on a 260 px screen (r = 130).
CASES = [
    ("examples/showcase/assets/ChivoMono-Bold.ttf", [10, 29, 61, 78], ASCII),
    ("examples/features/patterns/assets/Questrial-Regular.ttf", [13, 24], ASCII),
    ("examples/showcase/assets/Dynalight-Regular.ttf", [39], ASCII),
    (str(icon), [16, 24], icon_chars),
]
out = []
for source, sizes, chars in CASES:
    for size in sizes:
        for aa in (False, True):
            t = time.perf_counter()
            font, sheet = bake(Path(source), name="f", size=size, glyphs=chars, antialias=aa)
            ms = (time.perf_counter() - t) * 1000
            glyphs = {}
            for ch, g in font.glyphs.items():
                tile = sheet.crop((g.x, g.y, g.x + g.width, g.y + g.height)).tobytes() if g.width else b""
                glyphs[ch] = {"w": g.width, "h": g.height, "xo": g.xoffset, "yo": g.yoffset,
                              "adv": g.xadvance, "tile": base64.b64encode(tile).decode()}
            out.append({"source": source, "size": size, "antialias": aa, "ms": round(ms),
                        "line_height": font.line_height, "base": font.base, "glyphs": glyphs})
json.dump(out, sys.stdout)
