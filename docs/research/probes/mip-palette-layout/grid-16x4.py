import math, random
V=[0,0x55,0xAA,0xFF]
def lab(c):
    def lin(u):
        u/=255; return u/12.92 if u<=0.04045 else ((u+0.055)/1.055)**2.4
    r,g,b=(lin(V[i]) for i in c)
    X=(0.4124*r+0.3576*g+0.1805*b)/0.95047; Y=0.2126*r+0.7152*g+0.0722*b; Z=(0.0193*r+0.1192*g+0.9505*b)/1.08883
    f=lambda t: t**(1/3) if t>0.008856 else 7.787*t+16/116
    return (116*f(Y)-16, 500*(f(X)-f(Y)), 200*(f(Y)-f(Z)))
cols=[(r,g,b) for r in range(4) for g in range(4) for b in range(4)]
grays=[c for c in cols if c[0]==c[1]==c[2]]
chroma=[c for c in cols if c not in grays]
L={c:lab(c) for c in cols}
def hue(c): a,b=L[c][1],L[c][2]; return math.degrees(math.atan2(b,a))%360
def dE(p,q): return math.dist(L[p],L[q])
# start the hue circle at red: rotate so red (lab hue ~40) is first
srt=sorted(chroma,key=lambda c:((hue(c)-20)%360, -L[c][0]))
best=None
for off in range(60):
    seq=srt[off:]+srt[:off]
    colsets=[sorted(seq[i*4:i*4+4],key=lambda c:-L[c][0]) for i in range(15)]
    spread=sum(max(abs(((hue(a)-hue(b)+180)%360)-180) for a in s for b in s) for s in colsets)
    if best is None or spread<best[0]: best=(spread,colsets,off)
spread,colsets,off=best
W,H=16,4
grid=[[None]*W for _ in range(H)]
for x,s in enumerate(colsets):
    for y,c in enumerate(s): grid[y][x]=c
for y,c in enumerate(sorted(grays,key=lambda c:-L[c][0])): grid[y][15]=c
def cost(g):
    t=0
    for y in range(H):
        for x in range(15):  # gray column excluded from smoothness
            if x<14: t+=dE(g[y][x],g[y][x+1])
            if y<H-1: t+=dE(g[y][x],g[y+1][x])
            if y<H-1 and L[g[y][x]][0]<L[g[y+1][x]][0]: t+=40  # lighter must sit above
    return t
c0=cost(grid); cur=c0; T=20
random.seed(1)
for it in range(300000):
    y1,x1,y2,x2=random.randrange(H),random.randrange(15),random.randrange(H),random.randrange(15)
    grid[y1][x1],grid[y2][x2]=grid[y2][x2],grid[y1][x1]
    n=cost(grid) if it%1==0 else 0
    if n<=cur or random.random()<math.exp((cur-n)/T): cur=n
    else: grid[y1][x1],grid[y2][x2]=grid[y2][x2],grid[y1][x1]
    T=max(0.05,T*0.99997)
print("cost",round(c0),"->",round(cur))
hexs=lambda c:"".join("%02X"%V[i] for i in c)
for row in grid: print(" ".join(hexs(c) for c in row))
from PIL import Image, ImageDraw
S=40;G=4
im=Image.new("RGB",(W*S+(W+1)*G,H*S+(H+1)*G),(32,32,32)); d=ImageDraw.Draw(im)
for y in range(H):
    for x in range(W):
        c=grid[y][x]; X=G+x*(S+G)+(6 if x==15 else 0); Y=G+y*(S+G)
        d.rectangle([X,Y,X+S-1,Y+S-1],fill=tuple(V[i] for i in c))
im.save("palette-16x4.png")

