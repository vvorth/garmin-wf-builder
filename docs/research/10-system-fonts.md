# 10 — System fonts: name decoding, free-font mapping, and metric-model evidence

Written for plan `09-system-font-metrics.md` §4 R0. Covers the two device
font-name sources, how the cryptic bitmap names decode, the free-font
mapping recorded machine-readably in `wfb/fonts/registry.json`, its
licensing, what is deliberately left unmapped, and the evidence for the
em/ascent/descent/height metric model plan 09 §2 stated as a preliminary
result. Every behavioural claim is marked **VERIFIED** (checked against the
files in this repository, or against an actually-downloaded font) or
**UNVERIFIED** (plausible but not checked), per `docs/CLAUDE.md`.

---

## 1. Two name sources, and why they disagree

**VERIFIED.** There are two independent places a device's system-font names
come from, and they are not the same vocabulary:

1. **The scraped SDK device reference**, `docs/research/data/devices/*.json`
   (164 device files, produced by `tools/research/extract_device_db.py`).
   `fonts` is keyed by a comma-joined language list (e.g.
   `"ara,bul,ces,...,eng,..."`) plus a literal `"default"` key — confirmed by
   reading `fenix8solar47mm.json`'s `fonts` keys directly. `wfb.devices.
   Device.system_fonts` (`wfb/devices.py:344`) reads exactly
   `fonts["default"]["fixed"]`; this document's scope additionally covers
   `fonts["default"]["scalable"]`, which that property does not currently
   read (plan 09 §3 explicitly asks for both). Each entry is
   `{face, font, size_px}` (`size_px` only in `fixed`); `face` is a
   human-readable family name, `font` a device-internal file/token name.

2. **The installed device's own `simulator.json`**
   (`~/.Garmin/ConnectIQ/Devices/<id>/simulator.json`, 13 devices installed
   locally: `fenix6`, `fenix6xpro`, `fenix7pro`, `fenix7x`, `fenix7xpro`,
   `fenix7xpronowifi`, `fenix8solar47mm`, `fenix8solar51mm`,
   `fenix9prosolar47mm`, `fenix9prosolar51mm`, `fr245`, `fr255`, `fr955`).
   `fonts` is a list of `{fontSet, fonts: [...]}` blocks; `fontSet` values
   observed: `ww` (worldwide/default — 13 devices), `apac_chn` (9),
   `apac_twn` (7), `apac_jpn` (13), `apac_kor` (13), `apac_tha` (13),
   `apac_vie` (9), `apac_twcn` (4). Each font entry has `filename` and `name`
   (`xtiny`, `numberHot`, `glanceFont`, `simExtNumber1`, `auxiliaryFont1`,
   ...) and, only for `type: "ttf"` entries, `size` **in points**, plus
   sometimes `ascent`/`descent`/`height`/`digitHeight`/`intLeading`. A
   bitmap font has no `type` key at all. There is **no `face` field
   anywhere in `simulator.json`** — filenames must be decoded on their own.

The two sources' filenames for the *same* font frequently differ in
superficial ways (`RobotoCondensed-Bold` vs. the bitmap-style
`FNT_FENIX6_CDPG_ROBOTO_20B`) because the scraped table is Garmin's
published reference table and `simulator.json` is the simulator's own asset
manifest for the exact bitmap/TTF files it ships. The scraped `face` column
is the more reliable signal for a family name where both exist, per plan 09
§2's finding that "the scraped `face` usually names the real family even
when the file name does not" — this document treats it as such throughout.

---

## 2. Decoding the bitmap `FNT_*` / part-number names

**VERIFIED** (read directly off both sources; cross-checked with the joined
device+symbol+face table in §4).

A pre-rasterised bitmap font's device-internal name follows one of these
shapes:

- **`FNT_<PREFIX>_<FAMILY TOKEN>_<SIZE>`** — e.g.
  `FNT_FENIX6_CDPG_ROBOTO_20B`, `FNT_FR945_ROBOTO_BC_NUMBER_FONT_34`,
  `FNT_FENIX6X_BIONIC_COND_BOLD_NUMBER_39`.
  - `<PREFIX>` is a device or device-family codename (`FENIX6`, `FENIX6X`,
    `FR945`, `MARQ`, ...) **or** a 10-digit Garmin internal part number
    (`006B399100`, `006B416900`, ...) — both are seen for the same font
    family across different devices, e.g. `FNT_FENIX6_CDPG_ROBOTO_20B` vs.
    `006B399100_CDPG_ROBOTO_20B` are the same Roboto Condensed Bold family.
  - `<FAMILY TOKEN>` names the family, sometimes abbreviated: `CDPG_ROBOTO`
    = **C**on**d**ensed (**P**ro?) **G**armin Roboto → Roboto Condensed;
    `BIONIC_COND` = Bionic Condensed; `ROBOTO_BC_NUMBER_FONT` = Roboto
    **B**old **C**ondensed number font; `ROBOTO_BLACK_NUMBER_FONT` = Roboto
    Black. **UNVERIFIED**: the exact expansion of `CDPG` (no Garmin source
    was found spelling it out; "Condensed" is confirmed by every scraped
    `face` for a `CDPG_ROBOTO` token being literally `"Roboto Condensed"`
    — the `PG` part is a guess).
  - A trailing **`B`** = Bold, **`M`** = Medium, no letter = ambiguous
    (resolved from the sibling scraped `face`/size table; the registry
    defaults these to Bold, the dominant case — see §4).
  - The trailing number is the **pixel size** the bitmap was baked at (not a
    point size) — confirmed by the `006B399100_CDPG_ROBOTO_20B` /
    `..._24B` family matching `size_px` 20/24 in the corresponding scraped
    rows one-for-one.
  - `_1252_PRO_` vs. `_0000_PRO_` distinguishes a Latin-1 (Windows codepage
    1252) Roboto Condensed bitmap from a `"Garmin"`-labelled generic/symbol
    one (**UNVERIFIED** codepage-number reading, but the two prefixes'
    scraped faces are consistently `"Roboto Condensed"` vs. `"Garmin"`
    respectively, which is what the registry's patterns rely on).
  - `_0000_GARMIN_<N>` (no `PRO`) is a *different* family again — every
    instance scrapes to face `"Bebas Neue Bold DJV Glyph ttf"` (§4).
- **Clean TTF-style names**, no `FNT_` prefix: `RobotoCondensed-Bold`,
  `Bionic_semibold`, `Pridi-SemiBold_Garmin`, `Kosugi-Regular-2`,
  `sakkal_majalla_bold`. These need no decoding — the family is in the name
  (or, for `Bionic_semibold`/`Bionic_Medium`, corroborated by the scraped
  `face`).
- **Version/variant suffixes** on an otherwise-clean name — `-2`, `-3`,
  `-Outdoor`, `_Garmin` (e.g. `NotoSansSC-Medium-Outdoor`,
  `Pridi-Regular_Garmin`) — mark a device- or firmware-generation-specific
  re-release of the same family; the registry does not distinguish them
  (all such variants of a CJK/Thai family are unmapped anyway, §6).

---

## 3. The metric model — verified against the actual TTFs

**VERIFIED**, reproducing plan 09 §2's preliminary finding with a script
(`tools/research/font_metric_check.py`) rather than trusting the earlier
by-hand count.

For a `type: "ttf"` `simulator.json` entry, the em size in pixels is:

```
em = size_pt * ppi / 72
```

The downloaded Roboto v2.138 family (`googlefonts/roboto` release
`roboto-unhinted.zip`, §7) has, **identically across every static instance
checked** (`RobotoCondensed-Bold`, `RobotoCondensed-Regular`, `Roboto-Black`):

```
unitsPerEm = 2048,  hhea.ascent = 1900,  hhea.descent = -500,  hhea.lineGap = 0
```

so the model predicts:

```
predicted_ascent  = round(em * 1900 / 2048)
predicted_descent = round(em *  500 / 2048)
predicted_height  = round(em * 2400 / 2048)
```

**Check 1 — reproducing the "35 entries" result.** Across *every*
`fontSet` (not just `ww`) of all 13 installed devices, 35 font entries carry
`ascent`/`descent`/`height` **and** have a `filename` this project has an
actual downloaded TTF for (`RobotoCondensed-Bold`, `RobotoCondensed-Regular`,
`Roboto-Black`, and `apac_vie`'s `Roboto-Condensed_0` — checked against
`RobotoCondensed-Bold`'s hhea, since the three static instances share
identical hhea and `apac_vie` number faces are bold elsewhere in this
family). Running `tools/research/font_metric_check.py --fonts-dir <dir
with the extracted TTFs>`:

```
Check 1: reproduce plan 09 §2's ascent/descent/height model
N = 35 entries (expected 35)
exact: 20  off-by-1-2px: 15
off entries by fontSet: {'apac_vie': 14, 'ww': 1}
```

This **exactly reproduces** plan 09 §2's stated preliminary result
("35 entries, 20 exact, rest off by 1-2 px, mostly `apac_vie`'s
`Roboto-Condensed_0`"). The 15 off-by-a-few-pixels rows are 14 `apac_vie`
entries (diffs of -1, 0, +1, or +2 px on one or more of ascent/descent/
height) plus one `ww` row (`fr955`'s `Roboto-Black` `FONT_NUMBER_HOT`, off
by -1 px on descent only). The full row-by-row list is reproducible by
running the script; it is not duplicated here to avoid the doc drifting
from the script. As plan 09 §2 already concluded: `size_px`/`height` **is
the line height** and the em comes from `size_pt × ppi / 72`, not from
`size_px` directly — where the file gives its own `ascent`/`height`, those
numbers win over the predicted ones.

**Check 2 — scraped `size_px` vs. a from-scratch prediction.** Independent
of check 1 (which trusts the device file's own `ascent`/`descent`/`height`
when present), this check instead predicts `size_px` purely from `size`
(points) + device `ppi` + the downloaded TTF's own hhea, and compares
against the **scraped** `docs/research/data/devices/<id>.json`
`fonts.default.fixed.<FONT_*>.size_px` for the matching symbol — a
different data source entirely from the device's own `ascent/descent/
height` fields used in check 1. Restricted to `ww` entries (13 devices)
whose `filename` resolves, via `wfb/fonts/registry.json`, to a font-key this
project actually downloaded a real (not substitute) TTF for:

```
Check 2: scraped size_px vs round(em*(asc-desc)/upm), ww entries only
exact: 19  off: 0
skipped (no downloaded TTF for that face): 30
skipped (no scraped FONT_* symbol): 34
```

Every checkable entry matches **exactly**. The 30 "no downloaded TTF"
skips are faces this registry maps to a *substitute* (Bionic, Bebas Neue,
DejaVu, ...) rather than the device's real proprietary file, so comparing
metrics there would test the substitute's own shape, not this model — those
are intentionally excluded, not a gap in the model. The 34 "no scraped
`FONT_*` symbol" skips are `simulator.json` names with no `FONT_*`
counterpart at all (`glanceFont`, `glanceNumberFont`, `simExtNumber1..8`,
`auxiliaryFont1..2`) or a scalable-table-only name (`BionicSemiBold`,
`RobotoCondensedBold`, ...); the join in the script is a best-effort
camelCase splitter (`xtiny` → `FONT_XTINY`) documented in its own
docstring, not a claim that those symbols do not exist.

**Reproducing this.** The TTFs are not committed (§7 — licensing weight, and
project convention: fonts are fetched, not vendored, see `wfb/fonts/
fetch_system.py`'s docstring). Download `roboto-unhinted.zip` per the
`sources` in `registry.json`, extract `RobotoCondensed-Bold.ttf`,
`RobotoCondensed-Regular.ttf` and `Roboto-Black.ttf` into one directory, and
run:

```sh
./.venv/bin/python tools/research/font_metric_check.py --fonts-dir <dir>
```

### 3.1 Deriving `size_px` for a device with no scraped page at all (plan 17, VERIFIED)

The SDK's scraped device reference has no pages for the fenix 9
family: of the 20 installed devices, `fenix947mm`, `fenix9prosolar47mm`
and `fenix9prosolar51mm` have an **empty** `Device.system_fonts` before
this, so every `text` element degrades to "not checked" and `wfb preview`
draws no system-font text at all.

Checked 2026-09-23 against **Garmin's own TTFs** (`~/.Garmin/ConnectIQ/Fonts`,
copied from `vendor/fonts/` by `tools/setup-env.sh`): the same em/hhea model
above, run the other way around (`size_px = round(em_px * (hhea.ascent -
hhea.descent) / head.unitsPerEm)`), reproduces **45 of 45** scraped
`size_px` values exactly, 0 off, across every installed device that is
both scraped and has `ww` `type: "ttf"` entries with a point `size` (that
includes fenix847mm's `Roboto-Regular` -- 37/47/53/61/71 -- and
`Bionic_Medium` -- 113/153/173/210). The unscraped fenix 9 devices'
`simulator.json` files carry exactly the same two inputs the model needs
(a point `size` and a top-level `ppi`), for the same font families:

| device | ppi | `ww` `type: "ttf"` fonts |
|---|---|---|
| `fenix947mm` | 326 | `Roboto-Regular`, `Bionic_Medium` -- the same sizes as `fenix847mm` to ±0.003 pt |
| `fenix9prosolar47mm` | 202 | `RobotoCondensed-Bold`, `Bionic_semibold` |
| `fenix9prosolar51mm` | 202 | `RobotoCondensed-Bold`, `Bionic_semibold` |

`fenix947mm`'s derived values are therefore identical to `fenix847mm`'s
scraped ones -- `FONT_XTINY`…`FONT_NUMBER_THAI_HOT` = 37, 47, 53, 61, 71,
113, 153, 173, 210 -- confirmed by running the real installed device
database (`wfb.devices.Device.system_fonts`, not this script) with the
real Garmin font root. `fenix9prosolar47mm`/`51mm` derive their own
distinct values from `RobotoCondensed-Bold`/`Bionic_semibold` at their own
`ppi`/point sizes (21/29/32/38/40/58/65/99/121 and
22/30/34/38/42/62/69/107/129 respectively).

**What ships is narrower than this script's own reach.** `wfb.devices`
stays free of Pillow/fontTools (this module's own docstring), so
`Device.system_fonts`' third source (`docs/lore/codegen.md`'s
"system-font metrics" entry) reads `head.unitsPerEm`/`hhea.ascent`/
`hhea.descent` with a **stdlib `struct` reader** instead of fontTools --
parsing the sfnt table directory directly, `head` at offset 18 and `hhea`
at offsets 4/6 (`wfb.devices._sfnt_head_hhea`). It only fires for the 9
standard `FONT_*` symbols (`FONT_XTINY`…`FONT_NUMBER_THAI_HOT` -- the
documented vocabulary, minus the symbols with no direct `ww` counterpart
like `FONT_GLANCE`/`FONT_AUX1`), only when nothing scraped or stated
already covers the symbol, and only when the user's own licensed Garmin
fonts are installed and locatable as a real `.ttf`/`.otf` (never the
free-stand-in registry, and never a `.cft` -- §10.6 below already found no
verified model for bitmap height). **No scraped device gains a symbol
from this**: checked against every installed device with a scrape, the
first loop (the scraped table) already covers every symbol this source
would otherwise reach.

---

## 4. Mapping rationale, by family

**VERIFIED** counts: 442 unique `(face, font)` pairs, 33 unique `face`
values, across the 164 scraped device files' `default` language table
(`fixed` + `scalable`). 22 faces appear in some device's `fixed` table (the
table `wfb.devices.Device.system_fonts` reads, and the one that actually
drives on-device text measurement); the other 11 are **scalable-only**
— confirmed by set-difference over all 164 files — meaning no device ever
selects them for a `FONT_*` symbol; they exist purely as auxiliary faces for
other-script text. All 11 scalable-only faces are CJK/Thai/Arabic/
Hebrew/Armenian, or (Exo, Tomorrow) single-device aviation extras never
exposed via a `FONT_*` symbol at all — see §6.

| Face (scraped) | Font-key(s) | Match | Rationale |
|---|---|---|---|
| Roboto Condensed | `roboto-condensed-bold`, `-regular`, `-medium` | exact | Byte-identical file shipped in `fr955`'s own `simulator.json` (`RobotoCondensed-Bold`/`-Regular`); `M`-suffixed `CDPG_ROBOTO` bitmap tokens use the Condensed Medium static instance from the same release. |
| Roboto | `roboto-regular` | exact | Plain (non-condensed) family. |
| Roboto Black | `roboto-black` | exact | Byte-identical to `fr955`'s `Roboto-Black` (`FONT_NUMBER_HOT`/`THAI_HOT`). |
| Roboto Medium | `roboto-medium` | exact | |
| Roboto Light | `roboto-light` | exact | Also used for the `VENU_BOLD_NUMBER_FONT_6`/`_7` scrape anomaly — filename says `BOLD`, scraped `face` column says `Roboto Light`; the face column is trusted (§2 of `05-device-files.md`'s sibling reasoning: prefer the more structured field). |
| Roboto Wide | `roboto-italic` | exact | Scrape anomaly: every device with face `"Roboto Wide"` has font filename literally `Roboto-Italic`. Treated as a labelling quirk in Garmin's own reference table, not a distinct family — the file name is definitive. |
| Bionic | `bionic-substitute` (→ `roboto-black`) | substitute | Proprietary. `fr955` uses `Roboto-Black` for the identical `FONT_NUMBER_HOT`/`THAI_HOT` role Bionic fills elsewhere — same slot, same free family already in Garmin's own lineup. |
| (Bionic, `*_COND_*` tokens) | `bionic-cond-substitute` (→ `roboto-condensed-bold`) | substitute | Same reasoning, condensed variant: the same devices' own body text (`fenix8solar47mm`, `marq2`, ...) is `Roboto Condensed`. |
| Rajdhani | `rajdhani-medium` | family | The scrape's own `face` column reads `"Rajdhani"` for font token `Bionic_Medium` (`d2mach2`, `fenix8`/`8pro47mm`/`fenixe` sibling entries) — an unexpected but consistent reading (never `"Bionic"`), taken at face value; downloaded the genuine Google Fonts Rajdhani Medium (OFL), but byte identity to Garmin's internal file cannot be confirmed, hence `family` not `exact`. |
| Yantramanav | `yantramanav-bold`, `-regular` | exact | Explicit `YANTRAMANAV` tokens and the un-named `NNNNNNNNNN_(BOLD_)?NUMBER_(LARGE\|SMALL\|XLARGE\|XSMALL\|XTINY)` ladder (distinguished from Roboto Condensed's own same-named `_LARGE`/`_MEDIUM`/... tokens by the literal `NUMBER` substring). |
| Chronos | `chronos-substitute` (→ `roboto-condensed-bold`) | substitute | Proprietary, `fenix5`-era. `fenix5`'s own `FONT_XTINY..LARGE` is Roboto Condensed. |
| Steelfish Rg | `steelfish-substitute` (→ `roboto-condensed-bold`) | substitute | `d2bravo`/`fenix3`'s own body text is Roboto Condensed. |
| Phelant | `phelant-substitute` (→ `roboto-condensed-bold`) | substitute | `epix`/`vivoactive`'s own body text is Roboto Condensed. |
| Digi | `digi-substitute` (→ `roboto-condensed-bold`) | substitute | Weakest substitute here: `fr920xt` uses Digi for its *entire* font table (no free same-device sibling to borrow, unlike Bionic/Chronos/Steelfish/Phelant). A dedicated 7-segment OFL face (e.g. DSEG7) would fit the "digital clock" look better; skipped to keep download scope sane for one legacy device — flagged as a follow-up, not a settled choice. |
| Digi Narrow | `digi-narrow-substitute` (→ `roboto-condensed-bold`) | substitute | Same caveat; `fr920xt` `FONT_NUMBER_MILD` only. |
| Bebas Neue Bold / `... Bold DJV Glyph ttf` / `... ttf` | `bebas-neue-regular` | exact | Google Fonts ships Bebas Neue as a single `Regular` style that is itself the heavy display weight; the three scraped face labels are read as the same family (DJV = a device/vendor tag, not a distinct cut — **UNVERIFIED** expansion). |
| Oswald Light | `oswald-variable` | family | Google Fonts ships Oswald only as a `wght 200–700` variable font (no static Light instance in the repository); a non-variation-aware loader resolves some default instance, not pinned to Light. `hhea` ascent/descent do **not** vary across the `wght` axis in this build (checked directly with fontTools), so the metric model is unaffected — only the rendered stroke weight is approximate. |
| Noto Sans | `noto-sans-variable` | family | Same variable-font caveat (`wght 100–900`, `wdth 62.5–100`). This is the Latin-script `"Noto Sans"` face (aviation bold numerals), not the CJK `"Noto Sans SC"` face, which stays unmapped (§6). |
| DejaVu Sans Medium Condensed B | `dejavu-sans-condensed-bold` | family | DejaVu ships an official Condensed-Bold cut of the same family; `"Medium"` in Garmin's label is read as normal (non-light) weight, not DejaVu's separate `"Medium"` style (which does not exist in this family). |
| Garmin | `dejavu-sans-bold` | substitute | Garmin's own generic label for DejaVu-derived cycling/hiking numeral bitmaps (`DEJAVU_FITNESS_*`, `GPSMAP66_DEJAVU_REC_*`, `006B345900_FNT_0000_PRO_*`, `DejaVuGarmin_Rec_with_bionic_numbers`). The scraped filename literally contains `DEJAVU`, so the real file is some DejaVu derivative; DejaVu Sans Bold (non-condensed) is the closest still-free relative. |
| Garmin Robo Units | `roboto-bold` | family | No device ships a file literally named `Roboto-Bold`; this is the same Apache-2.0 family's Bold static instance, standing in for `Garmin_Roboto_Bold` and the `006B416900_ROBOTO_BOLD_*` bitmaps. |

---

## 5. Simulator-only `ww` filenames (13 installed devices)

**VERIFIED.** 93 unique `filename`s appear across the 13 installed devices'
`fontSet == "ww"` entries. All 93 resolve through `wfb/fonts/registry.json`
(exact `names`, then `patterns`, then — for the scraped source only, since
`simulator.json` carries no `face` — the `faces` table), or are explicitly
listed in `unmapped`; `tests/test_font_registry.py` checks this on every
run. No new families appear beyond §4's 22 fixed-table faces plus the
scalable-only CJK/Thai/Arabic/Hebrew/Armenian ones (§6) — the `ww` set is a
subset of names already accounted for above, just spelled differently
(`FNT_FENIX6_CDPG_ROBOTO_20B` instead of `006B399100_CDPG_ROBOTO_20B`, same
family).

---

## 6. What stays unmapped, and why

**VERIFIED**, one entry per deliberately-unmapped face or name in
`wfb/fonts/registry.json`'s `unmapped` list (37 entries: 11 faces + 26
individual `simulator.json` filenames covering those same faces, since
`simulator.json` names carry no `face` field to key off of).

| Group | Faces | Reason |
|---|---|---|
| Japanese | `MotoyaLCedar` (Kosugi) | Scalable-only; never selected for a `FONT_*` symbol on any of the 164 devices — confirmed by the fixed/scalable face set-difference in §4. |
| Korean | `NanumGothic` | Same. |
| Chinese | `Noto Sans SC` | Same. |
| Arabic | `Noto Naskh Arabic`, `Sakkal Majalla Unicode` | Same. |
| Hebrew | `Noto Sans Hebrew`, `Swis721Hebrew BT` | Same. |
| Armenian | `Noto Sans Armenian` | Same. |
| Thai | `Pridi` | Same. |
| Aviation extras | `Exo`, `Tomorrow` | Scalable-only, each on 1–3 aviation devices (`d2mach1`, `marq2`, `marq2aviator`); never exposed via a `FONT_*` symbol either. |

Plan 09 §3 explicitly allows this: "CJK/Thai/Arabic/Hebrew/Armenian-only
faces may be listed as unmapped ... because measurement uses the default
language only." Since none of these 9 faces (11 minus the 2 aviation
extras, which are not script-specific but are equally never measurement-
relevant) are in scope for default-language `FONT_*` measurement, extending
the same "not exercised by the measurement path" reasoning to `Exo`/
`Tomorrow` keeps the download scope sane per the plan's own instruction,
rather than fetching two more font families for a combined 4 scraped rows
across 164 devices.

---

## 7. Sources and licensing

**VERIFIED** — every source below was actually downloaded during this
research (into the session scratchpad, not the repository — see
`wfb/fonts/registry.json`'s `sources` for the exact pinned URL, sha256 and
size of each) and opened with `fontTools` to confirm it parses and to read
its `hhea`/`head` tables.

| Source | Pinned at | License |
|---|---|---|
| `googlefonts/roboto` (Roboto + Roboto Condensed, 9 static instances) | tag `v2.138`, `roboto-unhinted.zip`, sha256 `70f64c71...4a72a728` (already verified in `wfb/fonts/fetch_system.py`'s `ARCHIVE_SHA256` from Step A's partial work — reused, not re-derived) | Apache-2.0 (`LICENSE` member in the same zip) |
| `google/fonts` — Bebas Neue, Rajdhani, Yantramanav, Oswald, Noto Sans | commit `a54f7446f84a1125ef6bf08baa46f3639e8905e0` (this repo's `HEAD` at research time, via `git ls-remote https://github.com/google/fonts HEAD`) | OFL-1.1 (each family's own `OFL.txt`, same commit) |
| `dejavu-fonts/dejavu-fonts` — DejaVu Sans Bold, DejaVu Sans Condensed Bold | release tag `version_2_37`, `dejavu-fonts-ttf-2.37.zip` | Bitstream Vera Fonts License (`LICENSE` member in the same zip) |

None of these URLs point at `main`/`master`/a branch — every one is a release
tag or a specific commit SHA, per plan 09 R0.2's requirement. `wfb/fonts/
registry.json`'s `sources` records the exact sha256 and byte size of every
file (or archive member) actually used, not just the archive as a whole.

**Total new download footprint for this research:** 6 direct files (~2.8 MB,
dominated by the two variable fonts) plus one small DejaVu archive
(~5.5 MB, only 2 of its ~9 members used) — the Roboto archive was already
fetched by Step A's partial work and is reused as-is (member hashes
cross-checked and found consistent with `wfb/fonts/fetch_system.py`'s
existing `FILES` dict; no re-derivation needed).

---

## 8. Open questions / lower-confidence choices

- **`CDPG` in the bitmap family token is not spelled out anywhere found**
  (§2) — read as "Condensed" from the consistent scraped `face`, the rest is
  a guess. Does not affect any mapping decision (the face, not the guess, is
  what the registry keys off).
- **`Digi`/`Digi Narrow` substitute is the weakest in the registry**
  (§4) — a genuine 7-segment OFL face (DSEG7) would look far more like the
  original than Roboto Condensed Bold on the one affected device (`fr920xt`).
  Left as a follow-up rather than a fourth new font family, per "keep total
  scope sane."
- **Oswald/Noto Sans are variable fonts with no static instance in
  `google/fonts`** (§4) — confirmed their `hhea` does not move across the
  weight axis, so the *metric* model this document exists to support is
  unaffected; only the actually-rendered stroke weight in a preview would be
  approximate. Extracting a pinned static instance with `fontTools.varLib.
  instancer` is a reasonable Step A/B refinement, not attempted here (would
  produce a derived file with no upstream URL to cite against plan 09
  R0.2's "every URL was actually downloaded" requirement).
- **`Rajdhani`/`Bionic_Medium` and `Roboto Wide`/`Roboto-Italic`** (§4) are
  both scrape "anomalies" — the scraped `face` and the font filename name
  two different-sounding families for the same row. Both are resolved by
  trusting one signal consistently (the filename for Roboto Wide, since it
  is unambiguous; the face column for Rajdhani, since the filename `Bionic_
  Medium` gives no size/weight information a substitute choice could use).
  This is a judgement call, not a verified fact about Garmin's internal
  files.

---

## 9. Calibration against the simulator (2026-09-18)

The user ran the metrics probe (`docs/research/probes/system-font-metrics/`)
and the three comparison faces (`examples/system-fonts/*`) in the Connect IQ
simulator on macOS for all three targets. They also copied their SDK
Manager's `ConnectIQ/Fonts` into `vendor/fonts/`: 36 `.ttf`, 189 `.cft` and
225 `.md5` files. Every file is named after the device font name, e.g.
`RobotoCondensed-Bold.ttf`, `Bionic_semibold.ttf`,
`FNT_FENIX6_CDPG_ROBOTO_20B.cft`. The probe's console output is transcribed
in `docs/research/probes/system-font-metrics/results-2026-09-18.txt`.

**Vertical metrics — VERIFIED exact.** For every authorable `FONT_*` on all
three targets (27 symbol/device pairs), `getFontHeight`, `getFontAscent` and
`getFontDescent` equal what `wfb.fonts.fallback.system_face` computes:
line height = published `size_px`, baseline = `round(em × hhea_asc/upm)`
with `em = size_pt × ppi / 72` from §3. There is one exception.
`fenix8solar51mm`'s `FONT_GLANCE` baseline is 1 px off, but that symbol is
not authorable. §3's model therefore stands, with no calibration constant.
An overlay of the `fenix8solar47mm` text-face screenshot with `wfb preview`
lines up on every row, including the `center` and `bottom` rows. So the
line-box drawing model (plan 09 R2.4) is right too, and
`TEXT_JUSTIFY_VCENTER` centres on `getFontHeight`.

**Widths — the device lays text out per glyph.** VERIFIED against 54
readings (9 symbols × 3 devices × 2 strings):

| model | exact | total error |
|---|---|---|
| Pillow `getlength` at the fractional em (plan 09 step B) | 33/54 | 56 px |
| Pillow `getlength` at `round(em)` | 38/54 | 26 px |
| sum of linear advances, rounded once | 8/54 | 90 px |
| **each glyph's `hmtx` advance at `round(em)`, rounded on its own** | **44/54** | **20 px** |

The winning model is exact on all 36 Roboto readings. Under Pillow's fractional em, `FONT_TINY` digits
(em 24.64) came out 12 px wide where the device used 13. The 10 misses are
all Bionic (fēnix 8 `FONT_NUMBER_*`), 1–4 px over ten digits. Bionic's digits
are all 516/1000 em wide, yet the device's ten-digit strings are not
multiples of a single rounded width (264 px at em 51.32, for example), so
Garmin's rasteriser adjusts Bionic advances in a way FreeType does not
reproduce. No model tried fits Bionic. `fallback.SystemFace.advances`
implements the winning model, and the preview draws glyph by glyph on those
pen positions. Kerning is not applied. That is UNVERIFIED for pairs these
strings do not contain.

**Bionic stand-in — corrected.** §4 first mapped non-condensed Bionic to
Roboto Black, because fr955 uses Roboto Black in the same `FONT_NUMBER_*`
role. With the real files in hand, the advances say otherwise:

| font | `0` | `H` | `x` | `g` |
|---|---|---|---|---|
| Bionic_semibold | 0.516 | 0.574 | 0.443 | 0.514 |
| RobotoCondensed-Bold | 0.506 | 0.614 | 0.453 | 0.503 |
| Roboto-Black | 0.580 | 0.703 | 0.515 | 0.576 |

`bionic-substitute` now points at RobotoCondensed-Bold. Without the Garmin
files, the probe's widths come out 40/54 exact with 87 px total error; the
earlier stand-in, Roboto Black, gave 645 px. The Roboto Condensed file
shipped with the SDK Manager is v2.000980 (2014), older than the v2.138 the
registry pins. Both give identical advances on the probe strings.

**`.cft`** files are Garmin's bitmap fonts, decoded in §10.

---

## 10. The `.cft` format

Decoded by `wfb/fonts/cft.py`.

### 10.1 Provenance (VERIFIED)

The container format is not documented by Garmin anywhere found. It is
documented, and was reverse-engineered, by
**`markw65/monkeyc-optimizer`**, file `src/cftinfo.ts`, MIT licence, pinned
at commit `cea919a92da74de1f5d277064caa6f7920554af7`
(<https://raw.githubusercontent.com/markw65/monkeyc-optimizer/cea919a92da74de1f5d277064caa6f7920554af7/src/cftinfo.ts>),
shipped as the `cft-font-info` CLI. `wfb/fonts/cft.py` is a credited port
of its decode logic. Every claim below was checked against that file or by
decoding real `vendor/fonts/*.cft` files.

### 10.2 The field table (VERIFIED)

Everything is big-endian:

| Off | Size | Field |
|---|---|---|
| 0 | 2 | header size: 36, or 40 (maybe-zlib variant) |
| 3 | 1 | flags: bit 1 (`2`) = RLE glyph data, bit 2 (`4`) = 2 bpp (else 1 bpp) |
| 4 | 4 | file size |
| 8 | 4 | cmap offset |
| 12 | 4 | glyph-info offset |
| 16 | 4 | glyph-data offset |
| 22 | 2 | **height** (px, the line box) |
| 24 | 2 | **ascent** (baseline, px from the top) |
| 26 | 2 | internal leading (unused by this decoder) |
| 32 | 4 | `0x12345678` when RLE (36-byte header) -- documented by the reference tool but not actually consulted by its own decode path (the flags byte at offset 3 already carries this) |
| 36 | 1 | row alignment in bytes (40-byte header only; else 1) |

- **cmap:** at `cmap_offset + 12`, a u32 group count, then that many
  `(start, end, start_glyph)` u32 triples starting at `cmap_offset + 16`. A
  codepoint in `[start, end]` maps to glyph `start_glyph + (codepoint -
  start)`. A codepoint matched by no group maps to glyph 0, the "missing"
  box. **What the device itself draws for an unmapped character is
  UNVERIFIED** -- glyph 0 is the working assumption, matching how every
  other consumer of this format (including the reference tool) treats it.
- **Glyph info:** one u32 per glyph, at `glyph_info_offset + 4 * index`.
  `glyph_offset = ((word >> 16) & 0xffff) + ((word & 0xff00) << 8)`, masked
  `& 0x7fffff` when RLE. `advance = word & 0xff`. **Every glyph is a full
  `advance x height` cell** -- no bearings, no bbox offsets, and there is
  no kerning.
- **Pixel layout:** row-major. Each row is `ceil(ceil(advance / ppb) /
  align) * align` bytes (`ppb` = 4 at 2 bpp, 8 at 1 bpp; `align` is 1 for a
  36-byte header). Pixels are packed **LSB-first** within a byte. A level
  runs `0..3` (2 bpp) or `0..1` (1 bpp), 0 background, max full ink.

### 10.3 RLE (VERIFIED by decoding, and by round-tripping synthetic files)

The bitstream is read **LSB-first**. Its header is a unary `run_bits`
(count of 0 bits up to the first 1, plus 1), then 5 bits of `chunk_size -
1`, then `chunk_size` bits of `escape`. Each chunk that follows is a
literal `chunk_size`-bit value. When the value equals `escape`, a
`run_bits`-wide run length `r` follows: `r = 0` means the escape value is
itself a literal (not a run at all); otherwise the *previous* literal
repeats `r + 1` times. Output is packed as `chunk_size`-bit values,
LSB-first, until `row_bytes * height` bytes exist. Each glyph's RLE stream
is fully self-contained -- it starts a fresh bit alignment at its own byte
offset into the shared glyph-data blob, so glyphs never share bit state.

`chunk_size` is a property of the *compressed byte stream*, not of the
pixel bpp -- the codec compresses whatever bytes it is given (already
bpp-packed pixel rows) generically; `tests/test_cft.py`'s
`test_rle_chunk_straddles_a_byte_boundary` deliberately picks a `chunk_size`
unrelated to the font's own bpp to prove this.

`wfb/fonts/cft.py` ports this faithfully but with a byte-array output
writer and a small bounded bit accumulator (at most ~39 bits), rather than
the reference's own approach of shifting one arbitrary-precision integer
for the whole glyph -- the naive port is quadratic in the glyph's pixel
count on a Python-scale bignum; this implementation is linear.

### 10.4 The 40-byte zlib variant (VERIFIED by decoding)

A 40-byte header's glyph data may be zlib-compressed. At the glyph-data
offset, a first u32 of `0xCD00000D` (3439329293) means "skip 4, then a u32
length, then zlib". `0xD000000D` (3489660941) means "skip 4, raw, not
compressed". Any other value means "u32 length, then zlib" (the value
itself *is* that length). `tests/test_cft.py` round-trips all three.

### 10.5 Variant census across `vendor/fonts/` (VERIFIED, 2026-09-18)

Of the 189 `.cft` files copied into `vendor/fonts/` (§9): **178** have a
36-byte header with flags `0x06` (RLE, 2 bpp). **11** have a 40-byte header
with flags `0x00` (no RLE, zlib, 1 bpp, row alignment 8) -- all
`FNT_006B402400_*`, used by fr255's `large` font and fr955's `simExt*`
fonts. Two real files decoded by `tests/test_cft.py` (skipped when
`vendor/fonts/` is absent): `FNT_FENIX6_CDPG_ROBOTO_20B.cft` (36-byte, RLE,
2 bpp, height 32, ascent 25) and `FNT_006B402400_CDPG_ROBOTO_15B.cft`
(40-byte, zlib, 1 bpp, height 24, ascent 19).

### 10.6 Height vs. the scraped `size_px` (VERIFIED difference, UNVERIFIED which the simulator reports)

Across the scraped default tables, `.cft` `height - size_px` is 0 in 260
entries, +1 in 92 (including all of fenix6: 32 vs 31, 100 vs 99) and +2 in
8. Since the `.cft` is the very file the simulator loads, its own
`height`/`ascent` are treated as the line box and baseline in preference to
the scraped `size_px` wherever a `.cft` is found. Whether
`Graphics.getFontHeight` on a bitmap-font device returns `height` or
`height - 1` is **UNVERIFIED** (§10.9).

### 10.7 Antialias blending (UNVERIFIED)

A 2 bpp level `v` is meant to be drawn as a linear blend `bg + (fg - bg) x
v/3`. Whether the simulator quantises that to the 64-colour MIP palette
(root `CLAUDE.md` §4.13) is unknown. The preview blends linearly (§10.9).

### 10.8 How layout and preview use it

- **Name → file.** `Device.system_fonts` carries the installed device's
  `simulator.json` `filename` (e.g. `FNT_FENIX6_CDPG_ROBOTO_20B`) in
  `FontMetric.font`. `fetch_system.garmin_any_file` tries `.ttf`/`.otf`,
  then `.cft`, then `"FNT_" + name` for scraped-only names. A hit is match
  `"garmin"`.
- **Measurement.** For a `.cft`, `fallback.system_face` returns a
  `SystemFace` with `bitmap` set and `font = None`. Line height and
  baseline are the file's `height`/`ascent` (§10.6), and advances are the
  file's per-glyph advances. `fallback.line_height` applies the same
  override, so layout and preview agree.
- **Preview.** `wfb.preview` pastes each decoded glyph cell at `baseline −
  ascent`, upscaled with `NEAREST` through an ink mask (§10.7's linear
  blend).

### 10.9 Open calibration

§10.6 and §10.7 are settled by running the `system-font-metrics` probe
(`docs/research/probes/system-font-metrics/README.md`, which builds for
`fenix6` and `fr245`) and `examples/system-fonts` on a bitmap-font device
in the simulator. Compare the probe's `h=`/`a=` lines with
`wfb.fonts.cft.load(...).height`/`.ascent`, and a screenshot with `wfb
preview`'s PNG.
