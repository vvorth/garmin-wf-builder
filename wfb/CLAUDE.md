# wfb/ — the compiler

Loaded automatically when working under `wfb/`. The pipeline stage table is
in the root `CLAUDE.md` §6.

- The builder reads format 2's keys and kind names as the author writes
  them. `wfb/lower.py` checks what the schema cannot (colour names,
  `text:` templates) and spells out compass aliases; it renames nothing.
  A diagnostic or a generated comment names what the author wrote
  (`Expression.shown` for an expression).
- `wfb/desugar.py` runs after `wfb/lower.py` and rewrites the element
  blocks (the id-keyed mappings, the `static:` blocks, a layout's content)
  into the one list-of-elements shape the IR builder walks. The pipeline is
  load → validate → lower → desugar → build. New sugar belongs in
  `desugar`, gated by a snapshot proving the output unchanged
  (`tools/snapshot.py`).
- Any change to `wfb/build.py` or to how `monkeyc` is invoked or measured:
  read `docs/lore/toolchain.md` first. (A `.prg`'s size depends on its build
  path; prefer `--build-stats`.)
- Changing `wfb/emit/` or `runtime-lib/` means writing Monkey C, so
  `docs/lore/monkeyc.md` applies (auto-loaded there).

@../docs/lore/codegen.md
