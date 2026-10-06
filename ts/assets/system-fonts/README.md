# System fonts

Free stand-ins for Garmin's proprietary system fonts, used to measure and
draw text set in a device's `FONT_*` faces on previews (`ts/src/fonts/fallback.ts`).

**Nothing here is committed.** `ts/src/data/font-registry.json` maps every system-font
name this project knows about to a pinned, hash-checked, freely-licensed TTF
(`exact`/`family`/`substitute`, or deliberately unmapped -- see
`docs/lore/toolchain.md`). `ts/tools/fetch-system-fonts.ts` (loaded by
`ts/tools/fetch-system-fonts.ts`, stdlib-only) downloads the ones every installed
device needs into this directory (`--all`: every device in the SDK device
reference); `tools/setup-env.sh` and the Dockerfile (with `--all`) both run it. Re-running it is cheap: a font already here is left
alone and nothing is downloaded for it.

Each file is named `<font-key>.ttf` after its `registry.json` key, not its
upstream filename (several keys -- the `*-substitute` ones -- share one
underlying file). A `<font-key>.LICENSE.txt` sits alongside each, naming the
font's licence and where it came from.

**Garmin's own font files are not fetched here at all.** They cannot be
downloaded and are the user's own licensed copy, vendored separately at
`vendor/fonts/` (see the root `CLAUDE.md` §2 and `docs/container.md`) --
`ts/tools/fetch-system-fonts.ts`'s `garmin_font_root`/`garmin_font_file` look
there first, and only fall back to a font installed in this directory.

`WFB_OFFLINE=1` stops any fetch from reaching the network (tests set it for
the whole session). `WFB_FONTS_MIRROR` points every download at a mirror
that reproduces the same paths.
