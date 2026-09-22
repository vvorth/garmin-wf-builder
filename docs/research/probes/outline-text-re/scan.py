import os,sys,re,pickle,bisect
from elftools.elf.elffile import ELFFile
from capstone import *
e=ELFFile(open(os.environ['CIQ_SDK']+'/bin/simulator','rb'))
text=e.get_section_by_name('.text'); ta=text['sh_addr']; td=text.data()
md=Cs(CS_ARCH_X86,CS_MODE_64); md.skipdata=True
pat=re.compile(sys.argv[1])
for (a,sz,mn,op) in md.disasm_lite(td,ta):
    s=f'{mn} {op}'
    if pat.search(s): print(hex(a),s)
