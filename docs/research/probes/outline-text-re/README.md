# Probe: outline text in the simulator's graphics engine (static RE)

Backs `docs/research/13-outline-vector-text.md`. There is no Monkey C here:
the question ("does the platform draw outlined glyphs, and can a watch face
ask for them?") is not answerable from the public API. So these scripts take
apart `$CIQ_SDK/bin/simulator` (SDK 9.2.0, x86-64 ELF, stripped). It statically
links Garmin's own firmware graphics library (`GFX_*`,
`submodules/technology/graphics/TTF/ttf_intf.cpp`), the Monkey C VM
(`…/monkeybrains/virtual-machine/vm/tvm_gfx_c.cpp`, `tvm_Gfx.cpp`) and
FreeType.

Needs `pyelftools` and `capstone` in a throwaway venv (not project
dependencies):

```sh
uv venv /tmp/re && uv pip install -p /tmp/re/bin/python pyelftools capstone
cp docs/research/probes/outline-text-re/*.py <scratch> && cd <scratch>   # scripts load each other and write *.pkl caches in cwd
export CIQ_SDK=~/ciq/sdks/9.2.0
/tmp/re/bin/python sweep.py $CIQ_SDK/bin/simulator    # linear-sweep: direct calls + RIP-relative LEAs (~10 s)
/tmp/re/bin/python graph.py FT_Glyph_StrokeBorder,FT_Stroker_New 4   # callers of exported symbols
/tmp/re/bin/python names.py                            # names GFX_* functions by their log strings; lists tvm_gfx natives
/tmp/re/bin/python up.py 0xc12ec0 7                     # callers of an address, recursively
/tmp/re/bin/python down.py 0xd70780 0xc1abb0 12         # direct-call paths from A to B
/tmp/re/bin/python gdis.py 0xc1abb0 > f.txt             # disassemble a whole function (FDE bounds), strings annotated
/tmp/re/bin/python scan.py 'cmp byte ptr \[r\w+ \+ 0x30\], 0x20'   # regex over every instruction
```

Addresses are for the SDK 9.2.0 Linux simulator only. A different SDK build
moves everything. Direct calls only: anything dispatched through a function
pointer (the vector-font natives, the VM's font hook in `.bss`) is invisible
to `down.py`. That limit is recorded in the research doc.
