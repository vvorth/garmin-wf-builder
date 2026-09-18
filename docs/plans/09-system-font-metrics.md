# Plan 09 — real device typefaces for system-font previews and measurement

**Status (2026-09-18):** accepted, being built in four steps (§6), one
subagent at a time. §7 (fine calibration) stays open until the user sends
simulator screenshots. Do not delete this plan before then.

**Revision 2 (same day), after the user's correction:** "don't bake in just
the roboto condensed ... take font name needed and download the one that is
required, cache it for later. some names are obscure, so make a research to
map device definition fonts to actual font names if needed." The first
revision pinned one Roboto archive for every system font. That is superseded
here by a per-font registry fetched on demand. Step A's partial work (a
stdlib fetch module, `tools/fetch-system-fonts.py`, a `doctor` line,
`WFB_OFFLINE` in `tests/conftest.py`, setup/Dockerfile/doc edits for a fixed
Roboto set) is in the working tree, uncommitted, and gets reshaped rather
than thrown away.

## 1. The request

> download roboto condensed font either during env setup or at wfb runtime
> maybe (cache it of course). then use it for system fonts on previews and
> height/width calculations. also make a simple watchface with short static
> text of all possible system sizes, i will run it in emulator and provide
> screenshots to compare ...

plus the revision-2 correction quoted above.

## 2. What is true today (research, 2026-09-18)

- `wfb/fonts/fallback.py` measures and draws **every** system font with
  Pillow's bundled default face. It scales that face so its
  `ascent + descent` equals the device's published `size_px`.
- **Two sources of device font names**:
  1. **Device definitions** (`~/.Garmin/ConnectIQ/Devices/<id>/simulator.json`
     → `fonts[]`, one entry per `fontSet`, where `ww` is the default). Each
     entry has `name` (`xtiny`, `numberHot`, `glanceFont`, `auxiliaryFont1`,
     `simExtNumber1`, …), `filename`, `type` (`ttf`, `system_ttf`, or absent
     for a pre-rasterised bitmap font) and, for `ttf`, `size` **in points**.
     Top-level `ppi` (202 on fēnix 8, 200 on fr955; absent on older devices).
     Some entries also carry `ascent`, `descent`, `height`, `digitHeight` and
     `intLeading`. Only 13 devices are installed locally.
  2. **The scraped SDK device reference** (`docs/research/data/devices/*.json`,
     164 devices) → `fonts.<lang>.fixed.<FONT_*>` = `{face, font, size_px}`.
     `face` is a human family name (`Roboto Condensed`, `Bionic`,
     `Bebas Neue Bold DJV Glyph ttf`, `Chronos`, `Vera Sans`, …) and `font` the
     file name. `wfb.devices.FontMetric` keeps `face`/`size_px` and drops
     `font`.
- The names are partly obscure. Bitmap fonts look like
  `FNT_FENIX6_CDPG_ROBOTO_20B`, `FNT_FR945_ROBOTO_BC_NUMBER_FONT_34`,
  `FNT_FENIX6X_BIONIC_COND_BOLD_NUMBER_39`, `006B388800_0000_GARMIN_30` and
  `FNT_006B399100_NUMBER_FONT_SMALL`. TTF names look like
  `Roboto-Condensed_0`, `Pridi-SemiBold_Garmin`, `Kosugi-Regular-2` and
  `NotoSansSC-Medium-Outdoor`. The scraped `face` usually names the real
  family even when the file name does not.
- **Metric model: VERIFIED against the device files, and it needs no
  screenshots.** For a `ttf` entry, the em size in pixels is
  `size_pt × ppi / 72`. The Roboto v2 TTFs have `hhea` 1900/−500 at 2048 upm,
  and `round(em × 2400/2048)` reproduces the published `height` / scraped
  `size_px`. Ascent and descent come out as `round(em × 1900/2048)` and
  `round(em × 500/2048)`. Across the 35 entries that carry
  ascent/descent/height, the model is exact on 20 and off by at most 1–2 px
  on the rest. Those 15 are almost all `apac_vie`'s `Roboto-Condensed_0`,
  whose `size` differs from `ww`'s. So `size_px` **is the line height**, and
  the em comes from points × ppi, not from `size_px`. Where the file gives
  `ascent`/`height`, those numbers win.
- `Graphics.getFontHeight/getFontAscent/getFontDescent` and
  `Dc.getTextWidthInPixels` exist in `$CIQ_SDK/bin/api.debug.xml`, and
  `getFontAscent` is in both `fenix8solar47mm` and `fr955`'s
  `api.debug.xml`.
- The SDK ships no device TTFs; its only TTFs are sample-app fonts. The SDK
  Manager on the user's host may keep device fonts in
  `…/Garmin/ConnectIQ/Fonts/`. That is UNVERIFIED and the orchestrator will
  ask the user. It is not a dependency of this plan.
- Where the fallback is used: `wfb/layout.py` (`_resolve_text`,
  `_resolve_complication_slot`, the pattern-text part, `_font_for_ref`) and
  `wfb/preview.py` (the text drawer, the complication-slot text, the
  style-sheet caption).

## 3. Scope of the mapping

Map every `(face, font)` pair in any device's **default/English** table in
`docs/research/data/devices/*.json`, plus every `filename` in any installed
device's `simulator.json` `ww` set. CJK/Thai/Arabic/Hebrew/Armenian-only
faces are listed and may stay unmapped (they fall back), because measurement
uses the default language only. Each mapping has a **match level**:

- `exact`: the same font file, or a free release of it (Roboto,
  Roboto Condensed, Pridi, Kosugi, Nanum Gothic, Noto, Bebas Neue, Oswald,
  Rajdhani, Yantramanav, DejaVu/Vera, Exo, Tomorrow, …).
- `family`: the same family at a different weight or width, or a different
  release of it.
- `substitute`: a different free typeface chosen for similar metrics. This
  is for proprietary faces (Bionic, Chronos, Garmin, Swiss 721, Sakkal
  Majalla, Steelfish, Digi, Phelant, DF*, Motoya). Say why it was chosen.
- `none`: nothing sensible, so use Pillow's default.

## 4. Requirements

### R0 — research (Step R)

1. `docs/research/10-system-fonts.md`: the metric model above with its
   evidence table, the two name sources, how bitmap `FNT_*` names decode
   (family token, `B` = bold, trailing number = pixel size, device/part-number
   prefix), the mapping rationale per family, the licence of each source, and
   what stays unmapped. Mark each claim VERIFIED or UNVERIFIED (house style,
   `docs/CLAUDE.md`).
2. **`wfb/fonts/registry.json`** is committed, machine-readable and
   stdlib-readable:
   - `sources`: `id → {url, sha256, size, license, member?}`. `member`
     names a file inside a zip/tar archive. URLs are pinned to a tag or commit,
     never `main`. Every URL was actually downloaded and hashed during the
     research. Prefer Google Fonts' GitHub (`github.com/google/fonts` at a
     commit), `googlefonts/roboto` v2.138 for Roboto/Roboto Condensed (v2
     matches the `hhea` the model was verified against), `notofonts`, and
     `dejavu-fonts`.
   - `fonts`: `font-key → {source, match, note}`, one TTF per key.
   - `names`: an exact device font name → font-key, plus an ordered list of
     `patterns` (regex → font-key) for the bitmap `FNT_*` / `…_GARMIN_NN`
     families, plus a `faces` table (scraped `face` → font-key) as the last
     resort.
   - A `tests/test_font_registry.py` (no network) proves that every name in
     §3's scope resolves to a key or is listed as deliberately unmapped, that
     every key's source exists, and that every sha256 is 64 hex characters.

### R1 — fetching (Step A, reshaping the partial work)

1. `wfb/fonts/fetch_system.py` stays stdlib-only and loads
   `registry.json`. It provides `resolve(name, face=None) -> font-key | None`,
   `path_for(key) -> Path | None` (installed or cached, no network) and
   `ensure(key) -> Path | None` (download on demand, hash-check, cache; at
   most one attempt per source per process; `WFB_OFFLINE=1` skips it; on
   failure, one `note:` to stderr and never raise). An archive source is
   downloaded once, and every member any key needs is extracted from it.
2. **Cache:** `${XDG_CACHE_HOME:-~/.cache}/wfb/fonts/<key>.ttf` plus the
   licence file per source. Also search `wfb/assets/system-fonts/`
   (gitignored) first, which is where a prefetch installs to.
3. `tools/fetch-system-fonts.py [--device ID ...] [--all] [DEST]`
   prefetches the fonts that the given devices need (default: the three
   targets). It needs only the stdlib and loads the module by file path.
   `setup-env.sh` and the Dockerfile run it for the three targets.
   `.gitignore` ignores the install directory's contents, not specific
   Roboto file names.
4. `wfb doctor`: one line per target font key: installed, cached or missing.
   It never downloads.
5. Tests stay offline (`WFB_OFFLINE=1` in conftest) and use a local fake
   registry and archives. They cover a good hash, a bad archive hash, a bad
   member hash, a second run that does not download, the offline mode,
   `XDG_CACHE_HOME`, and pattern resolution order (exact name before pattern
   before face).
6. Docs: README font licences (per source, generic), `docs/container.md`,
   `docs/development.md`, `docs/lore/toolchain.md`, and the root `CLAUDE.md`
   §2 sentence.

### R2 — using them (Step B)

1. **Per-device font facts:** `Device.system_fonts` returns, per `FONT_*`
   symbol, `FontMetric(symbol, face, font, size_px, em_px, ascent_px,
   height_px)`. Get them from `simulator.json`'s `ww` set when installed
   (symbol ↔ `name` mapping: `FONT_XTINY`↔`xtiny`, …,
   `FONT_NUMBER_THAI_HOT`↔`numberThaiHot`, `FONT_SYSTEM_*`↔`system*` if
   present). Use `em_px = size × ppi / 72`, and take `ascent`/`height`
   from the entry when present. Fall back to the scraped table
   (`size_px`, `font`, `face`) when there is no `ppi` or `size`, or the entry
   is a bitmap font. `em_px` then comes from `size_px` ÷ the TTF's own
   `(asc−desc)/upm`. `size_px` stays the published line height, so layout
   does not move where no better number exists.
2. `wfb/fonts/fallback.py` is the one place that turns a `FontMetric` into a
   Pillow face. It exposes `system_face(metric, scale=1) -> SystemFace | None`
   with `.font`, `.line_height`, `.baseline` (px from the line-box top) and
   `.match`. It also keeps `measure(text, metric)` and `line_height(metric)`.
   `font_for_height` stays for the style-sheet caption. Baseline =
   `ascent_px` if known, else `round(em × hhea_asc/upm)`. Pillow's default
   face is used when `ensure` returns `None`. Everything is `lru_cache`d, and
   the `FontMetric` stays hashable.
3. **Layout:** `_font_for_ref` returns the `FontMetric`. Every system-font
   width and line height goes through `fallback`. The placed/resolved objects
   carry the metric (or its key fields), so the preview draws with exactly the
   face layout measured with. This covers text, the complication-slot text and
   the pattern-text part.
4. **Preview:** draw a system-font line from its line box. `top = anchor_y −
   {top: 0, center: line_height/2, bottom: line_height}`, then Pillow anchor
   `ls`/`ms`/`rs` at `top + baseline`. Custom baked fonts are unchanged.
5. `monkeyc` input does not change for custom-font-only faces, and
   `tests/golden/` must not move. Explain any example output that moves.
6. Tests that can fail:
   - Roboto Condensed Bold at fenix8solar47mm `FONT_MEDIUM` gives em
     32.86 → a Pillow size of 33, a line height of 39 and a baseline of 30.
   - A measured width differs from Pillow-default's.
   - A monkeypatched `em_px` moves the layout width and the preview ink the
     same way.
   - `top`/`bottom` ink positions against the anchor.
   - A `substitute` match (Bionic) is reported as such.
   - A device without `ppi` (fenix6) falls back to the scraped path.
   - Skip only when the fonts are absent.

### R3 — comparison faces and a metrics probe (Step C)

1. `examples/system-fonts/face.yaml` holds the text sizes (XTINY…LARGE), and
   `examples/system-fonts-numbers/face.yaml` holds NUMBER_MILD…THAI_HOT. The
   test sweep globs `examples/*/face.yaml`. Use short static strings: the
   size name plus mixed glyphs for text (`SMALL Hxg 0123`), digits only for
   numbers. Give each row a 1 px dim `shape: line` guide at its anchor y, with
   `vertical_align: top`. At least one row repeats with `center` and one with
   `bottom`. Black background, white text, grey guides, 64-colour palette.
   Both faces build warning-free on all three targets.
2. `docs/research/probes/system-font-metrics/`: a hand-written Monkey C face.
   For every `FONT_*` the SDK defines (has-guarded where device-dependent), it
   `System.println`s `h`, `a`, `d` and `getTextWidthInPixels` of `"Hxg0123"`
   and `"0123456789"` once, and draws the same table in `FONT_XTINY`. It
   builds warning-free for all three targets.
3. Preview PNGs of both faces for all three targets.

### R1b — Garmin's own font files first (revision 3, user decision 2026-09-18)

The user confirmed that the SDK Manager's `…/Garmin/ConnectIQ/Fonts/` holds
"lots of ttf and cft files". The user decided: "track vendor/fonts and copy
them manually, or bind a directory if in a container. such directory has to be
available in all installations (linux/windows/macos)". So:

1. **Lookup order for a device font name:**
   1. the **Garmin font root**: the device's own file, match level
      **`garmin`**, which ranks above `exact`;
   2. the registry download/cache (R1);
   3. Pillow's default face.
2. **Garmin font root discovery** mirrors `wfb.devices.DEFAULT_DEVICE_ROOTS`.
   The first existing, non-empty directory wins:
   1. `--fonts DIR` on the CLI, where that fits the existing device override;
   2. `WFB_FONTS`;
   3. `<repo>/vendor/fonts/` (**gitignored**, as `vendor/devices/` is, because
      it is the user's licensed copy);
   4. `~/.Garmin/ConnectIQ/Fonts` (Linux);
   5. `~/Library/Application Support/Garmin/ConnectIQ/Fonts` (macOS);
   6. `%APPDATA%\Garmin\ConnectIQ\Fonts` (Windows).

   All of these live in one helper, and `wfb doctor` reports which root was
   found.
3. `tools/setup-env.sh` copies `vendor/fonts/` into `~/.Garmin/ConnectIQ/Fonts`
   incrementally, as it does devices, so the sandbox toolchain sees them too.
   The Docker image sets `WFB_FONTS=/fonts`, and `docs/container.md`
   documents `-v "<host Fonts dir>:/fonts:ro"` next to the `/devices` mount,
   with the per-OS host path table.
4. **Name → file:** research how `simulator.json` `filename` values map to
   files in that directory. Is `RobotoCondensed-Bold` stored as
   `RobotoCondensed-Bold.ttf`? Is an `FNT_*` name stored as `FNT_*.cft`? What
   about case, and sub-directories?
5. **`.cft`** is a Garmin format, UNVERIFIED. Research whether it can be read
   for bitmap `FNT_*` fonts: its header and glyph table, whether it is a
   wrapped TTF or a bitmap strike. If it can be decoded within reasonable
   effort, a `.cft` bitmap font gives exact per-glyph advances and pixels.
   Otherwise treat `.cft`-only names as "fall through to the registry" and
   record the finding in `docs/research/10-system-fonts.md`.
6. Tests use a fake font root in `tmp_path`, never the real one. Cover the
   discovery order, `garmin` winning over the registry, and a missing root
   falling through.

## 5. Out of scope

- Per-language font tables (default/English only).
- Changing what `monkeyc` generates.

## 6. Build order (sequential subagents)

R (research + registry) → A (fetch, plus R1b discovery; the `.cft` research
waits until `vendor/fonts/` is populated) → B (use) → C (faces + probe). The
orchestrator reviews and commits after each step.

## 7. Calibration (open — needs the user)

Widths and the vertical model are compared against the user's simulator
screenshots of the two faces and the probe's console lines. Any residual
(tracking, hinting, what `TEXT_JUSTIFY_VCENTER` centres on) is recorded in
`docs/research/10-system-fonts.md` and fixed in `fallback.py`.
