# runtime-lib/ — the hand-written Monkey C support barrel

Loaded automatically when working under `runtime-lib/`. ADR 0003 permits a
*small* hand-written barrel. Everything here ships inside the 128 KB watch-face
budget, so measure a change with `--build-stats`, not `.prg` size
(`docs/lore/toolchain.md`).

@../docs/lore/monkeyc.md
