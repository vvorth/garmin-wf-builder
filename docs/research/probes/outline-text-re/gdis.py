import os,sys,pickle,bisect,re
from elftools.elf.elffile import ELFFile
from capstone import *
e=ELFFile(open(os.environ['CIQ_SDK']+'/bin/simulator','rb'))
fstarts,fends=pickle.load(open('fde.pkl','rb'))
d=e.get_section_by_name('.dynsym')
name={s['st_value']:s.name for s in d.iter_symbols() if s['st_value'] and s['st_info']['type']=='STT_FUNC'}
text=e.get_section_by_name('.text'); ta=text['sh_addr']; td=text.data()
ro=e.get_section_by_name('.rodata'); ra,rsz=ro['sh_addr'],ro['sh_size']; rd=ro.data()
def rstr(a):
    if ra<=a<ra+rsz:
        o=a-ra; end=rd.find(b'\0',o); s=rd[o:end]
        if 3<=len(s)<200 and all(32<=c<127 for c in s): return s.decode()
md=Cs(CS_ARCH_X86,CS_MODE_64)
for arg in sys.argv[1:]:
    f=int(arg,16); i=bisect.bisect_right(fstarts,f)-1; s,en=fstarts[i],fends[i]
    print(f'==== func {hex(s)}-{hex(en)} ({en-s} bytes)')
    for ins in md.disasm(td[s-ta:en-ta],s):
        c=''
        m=re.search(r'rip \+ (0x[0-9a-f]+)',ins.op_str)
        if m:
            t=ins.address+ins.size+int(m.group(1),16); c=rstr(t) or name.get(t,'') 
            c=repr(c) if c else ''
        if ins.mnemonic in ('call','jmp') and ins.op_str.startswith('0x'):
            c=name.get(int(ins.op_str,16),'')
        print(f'{ins.address:x}: {ins.mnemonic} {ins.op_str}  {c}')
