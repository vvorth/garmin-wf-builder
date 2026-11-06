# identity.py GARMIN FREE: how alike two fonts are over the codepoints both map --
# advances (to 0.002 em), bounding boxes (to 0.01 em) and outlines (point for
# point, same units per em). Needs fontTools. Run by identity.sh.
import sys
from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.boundsPen import BoundsPen
def load(p):
    f = TTFont(p); return f, f.getBestCmap(), f.getGlyphSet(), f["head"].unitsPerEm, f["hmtx"]
a, ca, ga, ua, ha = load(sys.argv[1]); b, cb, gb, ub, hb = load(sys.argv[2])
shared = sorted(set(ca) & set(cb))
adv = bbox = outl = 0; diff = []
for cp in shared:
    x, y = ca[cp], cb[cp]
    eqa = abs(ha[x][0]/ua - hb[y][0]/ub) < 0.002
    pa, pb = BoundsPen(ga), BoundsPen(gb); ga[x].draw(pa); gb[y].draw(pb)
    ba = [v/ua for v in pa.bounds] if pa.bounds else None; bb = [v/ub for v in pb.bounds] if pb.bounds else None
    eqb = (ba is None and bb is None) or (ba is not None and bb is not None and max(abs(p-q) for p,q in zip(ba,bb)) < 0.01)
    ra, rb = RecordingPen(), RecordingPen(); ga[x].draw(ra); gb[y].draw(rb)
    eqo = ua == ub and ra.value == rb.value
    adv += eqa; bbox += eqb; outl += eqo
    if not (eqa and eqb): diff.append(chr(cp))
n = len(shared)
print(f"{sys.argv[1].split('/')[-1]} vs {sys.argv[2].split('/')[-1]}: only-garmin={len(set(ca)-set(cb))} only-free={len(set(cb)-set(ca))} shared={n} same-advance={adv/n:.1%} same-bbox={bbox/n:.1%} identical-outline={outl/n:.1%}")
ds = "".join(d for d in diff if d.isprintable())
print("   differ (advance or bbox):", len(diff), repr(ds[:80]))
