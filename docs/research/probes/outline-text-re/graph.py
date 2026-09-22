import sys,pickle,bisect,os
from elftools.elf.elffile import ELFFile
path=os.environ['CIQ_SDK']+'/bin/simulator'
e=ELFFile(open(path,'rb'))
calls,leas=pickle.load(open('sweep.pkl','rb'))
if os.path.exists('fde.pkl'): fstarts,fends=pickle.load(open('fde.pkl','rb'))
else:
    fr=[]
    for ent in e.get_dwarf_info().EH_CFI_entries():
        if hasattr(ent,'header') and 'initial_location' in ent.header:
            fr.append((ent.header['initial_location'],ent.header['initial_location']+ent.header['address_range']))
    fr.sort(); fstarts=[a for a,b in fr]; fends=[b for a,b in fr]
    pickle.dump((fstarts,fends),open('fde.pkl','wb'))
d=e.get_section_by_name('.dynsym')
name={}; byname={}
for s in d.iter_symbols():
    if s['st_shndx']!='SHN_UNDEF' and s['st_info']['type']=='STT_FUNC' and s['st_value']:
        name[s['st_value']]=s.name; byname[s.name]=s['st_value']
def func(a):
    i=bisect.bisect_right(fstarts,a)-1
    return fstarts[i] if i>=0 and a<fends[i] else None
callers={}
for a,t in calls: callers.setdefault(t,set()).add(a)
ro=e.get_section_by_name('.rodata'); ra,rsz=ro['sh_addr'],ro['sh_size']; rd=ro.data()
def rstr(a):
    if ra<=a<ra+rsz:
        o=a-ra; end=rd.find(b'\0',o); s=rd[o:end]
        if 3<=len(s)<200 and all(32<=c<127 or c in(9,10) for c in s): return s.decode()
lsorted=sorted(leas); la=[a for a,_ in lsorted]
def strings_in(f):
    i=fstarts.index(f); s,eend=fstarts[i],fends[i]
    out=[]
    for k in range(bisect.bisect_left(la,s),bisect.bisect_left(la,eend)):
        x=rstr(lsorted[k][1])
        if x: out.append(x)
    return out
def lab(f): return name.get(f,hex(f) if f else '?')
def up(target,depth,seen,maxd):
    for c in sorted(callers.get(target,())):
        f=func(c)
        if f in seen: continue
        seen.add(f)
        ss=strings_in(f) if f else []
        print('  '*depth+f'<- {lab(f)} (call@{hex(c)}) strs={ss[:8]}')
        if depth<maxd and not (lab(f).startswith('0x') and ss and depth>=2): up(f,depth+1,seen,maxd)
for n in sys.argv[1].split(','):
    print('###',n); up(byname[n],1,set(),int(sys.argv[2]) if len(sys.argv)>2 else 4)
