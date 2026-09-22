import os,sys,pickle,bisect
exec(open('graph.py').read().split("for n in sys.argv")[0])
def up2(t,depth,seen,maxd):
    for c in sorted(callers.get(t,())):
        f=func(c)
        if f in seen or f is None: continue
        seen.add(f)
        print('  '*depth+f'<- {lab(f)} (call@{hex(c)}) strs={strings_in(f)[:6]}')
        if depth<maxd: up2(f,depth+1,seen,maxd)
for a in sys.argv[1].split(','):
    print('###',a); up2(int(a,16),1,set(),int(sys.argv[2]))
