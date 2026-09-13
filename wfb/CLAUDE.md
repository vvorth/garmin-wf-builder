# wfb/ — the compiler

Loaded automatically when working under `wfb/`. The pipeline stage table is
in the root `CLAUDE.md` §6.

- `wfb/desugar.py` rewrites every alternative spelling (the mapping form of
  `elements:`, the top-level `static:` block) into one form **before** anything
  else runs. New sugar belongs there, gated by a byte-identical-output test.
- Any change to `wfb/build.py` or to how `monkeyc` is invoked or measured:
  read `docs/lore/toolchain.md` first. (A `.prg`'s size depends on its build
  path; prefer `--build-stats`.)
- Changing `wfb/emit/` or `runtime-lib/` means writing Monkey C, so
  `docs/lore/monkeyc.md` applies (auto-loaded there).

@../docs/lore/codegen.md
