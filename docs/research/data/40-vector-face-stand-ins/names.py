# names.py FILE...: each font's name table (family, style, full name, version,
# copyright, licence), glyph count, units per em, weight class, OS/2 vendor
# and the first 16 hex digits of its SHA-256. Needs fontTools.
import sys, hashlib
from fontTools.ttLib import TTFont
for p in sys.argv[1:]:
    f = TTFont(p, lazy=True)
    n = f["name"]
    g = lambda i: (n.getDebugName(i) or "").replace("\n"," ")[:90]
    sha = hashlib.sha256(open(p,"rb").read()).hexdigest()[:16]
    print(f"{p.split('/')[-1]} | {g(1)} / {g(2)} | full={g(4)} | {g(5)} | glyphs={f['maxp'].numGlyphs} upm={f['head'].unitsPerEm} wght={f['OS/2'].usWeightClass} fvar={'fvar' in f} | sha={sha}")
    print(f"    (c) {g(0)} | lic={g(13)[:80]} | vendor={f['OS/2'].achVendID}")
