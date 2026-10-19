import itertools, sys
sys.setrecursionlimit(10000)
pts=[(r,g,b) for r in range(4) for g in range(4) for b in range(4)]
def nb(p):
    for i in range(3):
        for d in (-1,1):
            q=list(p); q[i]+=d
            if 0<=q[i]<4: yield tuple(q)
N={p:set(nb(p)) for p in pts}
grid=[[None]*8 for _ in range(8)]
used=set(); found=[0]; nodes=[0]
def rec(k):
    nodes[0]+=1
    if k==64:
        found[0]+=1
        for row in grid: print(' '.join(''.join(map(str,c)) for c in row))
        return True
    y,x=divmod(k,8)
    cands=None
    if x>0: cands=set(N[grid[y][x-1]])
    if y>0:
        s=N[grid[y-1][x]]; cands=s if cands is None else cands & s
    if cands is None: cands=[(0,0,0)]  # unused: the first cell is set below
    for c in sorted(cands):
        if c in used: continue
        grid[y][x]=c; used.add(c)
        if rec(k+1): return True
        used.discard(c)
    grid[y][x]=None
    return False
# first cell: any point up to symmetry (cube symmetries): representatives
reps=[(0,0,0),(0,0,1),(0,1,1),(1,1,1)]
for r in reps:
    grid[0][0]=r; used={r}
    if rec(1): break
print("found" if found[0] else "none", "nodes", nodes[0])
