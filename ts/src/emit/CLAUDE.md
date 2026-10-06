# ts/src/emit/ — Monkey C, resources, manifest and jungle generation

Loaded automatically when working under `ts/src/emit/`. The codegen and
jungle lore in `ts/src/CLAUDE.md` (`docs/lore/codegen.md`) applies here too.
Read it if it is not already in context.

- Generated output is reviewed by the user. Golden copies are in
  `ts/test/goldens/monkeyc/`, and a real build must be **warning-free** under
  `-l 3` on all three targets.
- Every behavioural claim about generated code on a watch is unverified until
  the user runs it; there is no simulator in the container.

@../../../docs/lore/monkeyc.md
