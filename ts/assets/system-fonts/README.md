# System fonts

Free stand-ins for Garmin's system fonts and device-resident scalable faces,
used to measure and draw text set in a device's `FONT_*` and vector faces on
previews (`ts/src/fonts/fallback.ts`), and baked by `fallback: auto`.

**Nothing here is committed.** `ts/src/data/font-registry.json` maps every
system-font and scalable-face name this project knows about to a pinned,
hash-checked, freely-licensed font (`exact`/`family`/`substitute` -- see
`docs/lore/toolchain.md`). `ts/tools/fetch-system-fonts.ts --registry`
downloads every one of them into this directory (about 34 MB the first time);
`tools/setup-env.sh` and the Dockerfile both run it. Without `--registry` it
installs only what the installed devices' system fonts need (`--all`: every
device in the SDK device reference). Re-running it is cheap: a font already
here with its pinned bytes is left alone and nothing is downloaded for it.

Each file is named `<font-key>.ttf` after its registry key, not its upstream
filename (several keys -- the `*-substitute` ones among them -- share one
underlying file, and Noto Sans SC's is CFF OpenType under that name). A
`<source>.LICENSE.txt` sits alongside, naming the font's licence and where it
came from, followed by the licence's text.

**Garmin's own font files are not fetched here at all.** They cannot be
downloaded and are the user's own licensed copy, vendored separately at
`vendor/fonts/` (see the root `CLAUDE.md` §2 and `docs/container.md`).
`garminFontRoot` in `ts/src/fonts/node.ts` looks there first, and a font
installed in this directory is used only when that root has no file for the
name.

`WFB_FONTS_MIRROR` points every download at a mirror that reproduces the same
paths.
