# System fonts

Free stand-ins for Garmin's proprietary system fonts, used to measure and
draw text set in a device's `FONT_*` faces on previews (`wfb/fonts/fallback.py`,
Step B of `docs/plans/09-system-font-metrics.md`).

**Nothing here is committed.** `wfb/fonts/registry.json` maps every system-font
name this project knows about to a pinned, hash-checked, freely-licensed TTF
(`exact`/`family`/`substitute`, or deliberately unmapped -- see
`docs/research/10-system-fonts.md`). `tools/fetch-system-fonts.py` (loaded by
`wfb/fonts/fetch_system.py`, stdlib-only) downloads the ones the project's
three build targets need into this directory; `tools/setup-env.sh` and the
Dockerfile both run it. Re-running it is cheap: a font already here is left
alone and nothing is downloaded for it.

Each file is named `<font-key>.ttf` after its `registry.json` key, not its
upstream filename (several keys -- the `*-substitute` ones -- share one
underlying file). A `<font-key>.LICENSE.txt` sits alongside each, naming the
font's licence and where it came from.

**Garmin's own font files are not fetched here at all.** They cannot be
downloaded and are the user's own licensed copy, vendored separately at
`vendor/fonts/` (see the root `CLAUDE.md` §2 and `docs/container.md`) --
`wfb/fonts/fetch_system.py`'s `garmin_font_root`/`garmin_font_file` look
there first, and only fall back to a font installed in this directory.

`WFB_OFFLINE=1` stops any fetch from reaching the network (tests set it for
the whole session). `WFB_FONTS_MIRROR` points every download at a mirror
that reproduces the same paths.
