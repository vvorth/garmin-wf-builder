import colorsys
V=[0,0x55,0xAA,0xFF]
cols=[(r,g,b) for r in range(4) for g in range(4) for b in range(4)]
grays=sorted([c for c in cols if len(set(c))==1],reverse=True)
chroma=[c for c in cols if len(set(c))>1]
H=lambda c: colorsys.rgb_to_hsv(*(v/3 for v in c))[0]*360
names=["Red","Yellow","Green","Cyan","Blue","Magenta"]
fam={n:[] for n in names}
for c in chroma: fam[names[int(((H(c)+30)%360)//60)]].append(c)
hexs=lambda c:"".join("%02X"%V[i] for i in c)
def rel(c,i): return ((H(c)-i*60+180)%360)-180
blocks={}
for i,n in enumerate(names):
    tier=lambda c:(max(c),min(c))
    by=lambda *t: sorted([c for c in fam[n] if tier(c) in t], key=lambda c:(rel(c,i), -min(c)))
    light=by((3,2),(3,1)); vivid=by((3,0)); mid=by((2,1),(2,0)); dark=by((1,0))
    # light row: pastel in the middle
    pastel=[c for c in light if tier(c)==(3,2)][0]; others=[c for c in light if c!=pastel]
    light=[others[0],pastel,others[1]]
    muted=[c for c in mid if tier(c)==(2,1)][0]; others=[c for c in mid if c!=muted]
    mid=[others[0],muted,others[1]]
    blocks[n]=[light,vivid,mid,[None]+dark+[None]]
    assert sum(len([x for x in r if x]) for r in blocks[n])==10
for n in names:
    print(n.ljust(8)," / ".join(" ".join(hexs(c) if c else "------" for c in r) for r in blocks[n]))
print("Gray    ", " / ".join(hexs(c) for c in grays))
from PIL import Image, ImageDraw
S=40;G=4;SEC=14
W=6*(3*S+2*G)+6*SEC+S+2*G; Hh=4*(S+G)+G
im=Image.new("RGB",(W,Hh),(32,32,32)); d=ImageDraw.Draw(im)
x0=G
for n in names:
    for y,r in enumerate(blocks[n]):
        for x,c in enumerate(r):
            if c is None: continue
            X=x0+x*(S+G); Y=G+y*(S+G); d.rectangle([X,Y,X+S-1,Y+S-1],fill=tuple(V[i] for i in c))
    x0+=3*S+2*G+SEC
for y,c in enumerate(grays):
    Y=G+y*(S+G); d.rectangle([x0,Y,x0+S-1,Y+S-1],fill=tuple(V[i] for i in c))
im.save("palette-families.png")
