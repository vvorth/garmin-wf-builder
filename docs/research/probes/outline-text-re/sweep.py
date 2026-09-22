import sys,re,bisect,pickle,os
from elftools.elf.elffile import ELFFile
from capstone import *
path=sys.argv[1]
e=ELFFile(open(path,'rb'))
d=e.get_section_by_name('.dynsym')
addr2name={}
for s in d.iter_symbols():
    if s['st_shndx']!='SHN_UNDEF' and s['st_info']['type']=='STT_FUNC' and s['st_value']:
        addr2name[s['st_value']]=s.name
text=e.get_section_by_name('.text'); ta=text['sh_addr']; td=text.data()
ro=e.get_section_by_name('.rodata'); ra,rsz=ro['sh_addr'],ro['sh_size']; rd=ro.data()
cache='sweep.pkl'
if os.path.exists(cache): calls,leas=pickle.load(open(cache,'rb'))
else:
    md=Cs(CS_ARCH_X86,CS_MODE_64); md.skipdata=True
    calls=[]; leas=[]
    for (a,sz,mn,op) in md.disasm_lite(td,ta):
        if mn in('call','jmp') and op.startswith('0x'):
            calls.append((a,int(op,16)))
        elif mn=='lea' and 'rip +' in op:
            m=re.search(r'rip \+ (0x[0-9a-f]+)',op)
            leas.append((a,a+sz+int(m.group(1),16)))
    pickle.dump((calls,leas),open(cache,'wb'))
print(len(calls),len(leas))
