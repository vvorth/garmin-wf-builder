import os,sys,pickle,bisect,collections
exec(open('graph.py').read().split("for n in sys.argv")[0])
callees=collections.defaultdict(set)
for a,t in calls:
    f=func(a)
    if f is not None and func(t)==t: callees[f].add(t)
def paths(src,dst,maxd):
    out=[]; stack=[(src,[src])]
    while stack:
        n,p=stack.pop()
        if n==dst: out.append(p); continue
        if len(p)>maxd: continue
        for c in callees[n]:
            if c not in p: stack.append((c,p+[c]))
    return out
src=[int(x,16) for x in sys.argv[1].split(',')]; dst=int(sys.argv[2],16); md=int(sys.argv[3])
for s in src:
    ps=paths(s,dst,md)
    print('##',hex(s),len(ps))
    for p in sorted(ps,key=len)[:15]: print('  ',' -> '.join(hex(x) for x in p))
