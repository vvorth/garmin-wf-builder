V=["00","55","AA","FF"]
def cell(x,y):
    bx,by=x//4,y//4
    r = x if bx==0 else 7-x
    g = y if by==0 else 7-y
    b = bx + 2*by
    return r,g,b
rows=[[cell(x,y) for x in range(8)] for y in range(8)]
for row in rows: print(" ".join("#"+"".join(V[c] for c in p) for p in row))
# verify
d=lambda p,q: sum(abs(a-b) for a,b in zip(p,q))
steps=[]
for y in range(8):
    for x in range(8):
        if x<7: steps.append(d(rows[y][x],rows[y][x+1]))
        if y<7: steps.append(d(rows[y][x],rows[y+1][x]))
from collections import Counter; print(Counter(steps), "distinct", len({p for r in rows for p in r}))
try:
    from PIL import Image, ImageDraw
    S=48; im=Image.new("RGB",(8*S,8*S)); dr=ImageDraw.Draw(im)
    for y in range(8):
        for x in range(8):
            r,g,b=rows[y][x]; dr.rectangle([x*S,y*S,x*S+S-1,y*S+S-1],fill=(r*85,g*85,b*85))
    im.save("palette-8x8.png"); print("png")
except ImportError: print("no PIL")
