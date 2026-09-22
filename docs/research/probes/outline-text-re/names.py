import os,sys,pickle,bisect,collections,re
exec(open('graph.py').read().split("for n in sys.argv")[0])
# name functions by GFX_* / Set* string referenced anywhere inside
fname={}
for a,t in lsorted:
    s=rstr(t)
    if s and re.match(r'^(GFX_|Set|Get|Bitblt|Fill|Process|fillPath)',s):
        f=func(a)
        if f and f not in fname: fname[f]=s
pickle.dump(fname,open('fname.pkl','wb'))
callees=collections.defaultdict(set)
for a,t in calls:
    f=func(a)
    if f is not None: callees[f].add(t)
tv=set()
for a,t in lsorted:
    s=rstr(t)
    if s and 'tvm_gfx' in s: tv.add(func(a))
for f in sorted(x for x in tv if x):
    ss=[x for x in strings_in(f) if 'tvm_gfx' not in x]
    cs=sorted(set(fname.get(c,'') for c in callees[f])-{''})
    print(hex(f), fends[fstarts.index(f)]-f, ss[:6], cs)
