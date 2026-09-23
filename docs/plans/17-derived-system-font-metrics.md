# 17 — System-font metrics for devices missing from the SDK reference

**Status: approved by the user 2026-09-23 ("do it"), being built.** Delete
this file once shipped (`docs/CLAUDE.md`).

## 1. Problem

`Device.system_fonts` (`wfb/devices.py`) builds each `FONT_*` metric's
line height, `size_px`, from the scraped SDK device reference
(`docs/research/data/devices/<id>.json`, from SDK 9.2.0's
`doc/docs/Device_Reference/*.html`). That reference has no pages for the
fenix 9 family. Of the 20 installed devices, three are unscraped:
`fenix947mm`, `fenix9prosolar47mm` and `fenix9prosolar51mm`. On them
`system_fonts` is **empty**, so:

- every `text` element gets `note[metrics]: no pixel metrics ... text extent
  is not checked`, and layout records a 0×0 box;
- `wfb preview` draws no system-font text at all;
- `aod-burn-in` undercounts, because the unmeasured clock contributes 0%
  (the AOD example reads 0.3% lit on fenix947mm against 1.0% on fenix847mm).

The watch code is unaffected: `examples/features/aod/face.yaml` already
builds warning-free for fenix947mm (`5a47af9` fixed the preview crash).

## 2. Evidence: the line height can be derived (VERIFIED)

Research 10 §3's model, `em = size_pt × ppi / 72` and
`size_px = round(em × (hhea.ascent − hhea.descent) / head.unitsPerEm)`,
was checked on 2026-09-23 with **Garmin's own TTFs** from
`~/.Garmin/ConnectIQ/Fonts` (copied from `vendor/fonts/` by
`tools/setup-env.sh`). It covered every installed device that is both
scraped and has `ww` `type: "ttf"` entries with a point `size` and a
device `ppi`: **45 of 45 scraped `size_px` values reproduced exactly, 0
off.** That includes fenix847mm's `Roboto-Regular` (37/47/53/61/71) and
`Bionic_Medium` (113/153/173/210).

The unscraped devices' `simulator.json` files carry exactly those inputs:

| device | ppi | fonts (`ww`, `type: "ttf"`) |
|---|---|---|
| fenix947mm | 326 | `Roboto-Regular`, `Bionic_Medium`, the same sizes as fenix847mm to ±0.003 pt |
| fenix9prosolar47mm | 202 | `RobotoCondensed-Bold`, `Bionic_semibold` |
| fenix9prosolar51mm | 202 | `RobotoCondensed-Bold`, `Bionic_semibold` |

All four TTFs are present locally. Expected fenix947mm values, identical to
fenix847mm's scraped ones:

| symbol | size_px |
|---|---|
| `FONT_XTINY` | 37 |
| `FONT_TINY` | 47 |
| `FONT_SMALL` | 53 |
| `FONT_MEDIUM` | 61 |
| `FONT_LARGE` | 71 |
| `FONT_NUMBER_MILD` | 113 |
| `FONT_NUMBER_MEDIUM` | 153 |
| `FONT_NUMBER_HOT` | 173 |
| `FONT_NUMBER_THAI_HOT` | 210 |

hhea values: Roboto family `upm 2048, ascent 1900, descent −500`; Bionic
Medium and Semibold `upm 1000, ascent 930, descent −346`; lineGap is 0 in
all of them.

## 3. The rule

In `Device.system_fonts`, after the existing two loops, add a third source.
A `ww` `simulator.json` entry qualifies when **all** of these hold:

1. `type == "ttf"`, it has a point `size`, and the device has a top-level
   `ppi`;
2. its `FONT_*` symbol (`_symbol_for_simulator_name`) is in the
   **documented vocabulary**, the union of every `fixed` key across
   `docs/research/data/devices/*.json` (22 symbols: `FONT_XTINY` …
   `FONT_NUMBER_THAI_HOT`, `FONT_SYSTEM_*`, `FONT_GLANCE*`, `FONT_AUX1/2`).
   Compute it once, lazily, at module level;
3. `metrics` doesn't already hold that symbol (nothing scraped, and no
   stated `height` picked up by the second loop);
4. its `filename` resolves to a local `.ttf`/`.otf` through
   `wfb.fonts.fetch_system.garmin_font_root()` +
   `garmin_any_file(filename, root)`. Check both exist and are stdlib-only;
   `fetch_system` must not import `wfb`. This is local files only, never
   the registry's `ensure()` (no download inside a device property). A
   `.cft` result doesn't qualify.

For a qualifying entry, read the font's `head.unitsPerEm`, `hhea.ascent`
and `hhea.descent` with a **stdlib `struct` reader**. `devices.py` stays
free of Pillow and fontTools: parse the sfnt table directory, then `head`
at offset 18 and `hhea` at offsets 4 and 6. Cache it per path. Then:

```
em_px   = size * ppi / 72
size_px = round(em_px * (ascent - descent) / upm)
metric  = FontMetric(symbol, "", filename, size_px, em_px, None, size_px)
```

(`face` is `""` and `ascent_px` is `None`, matching the existing second
loop. `wfb.fonts.fallback` already derives the ascent from the located TTF.)

**Blast radius: none on any scraped device.** Rules 2 and 3 were checked
against all 17 scraped installed devices, and none gains a symbol. Only the
three fenix 9 devices gain the nine standard symbols. Tests set
`WFB_NO_GARMIN_FONTS=1` (`tests/conftest.py`), so the existing suite sees no
Garmin root and nothing changes there either.

**Machine dependence (accepted, documented):** without the licensed Garmin
fonts, an unscraped device stays "not checked", exactly as today. The
preview's font lookup already depends on the same root.

Bitmap (`.cft`) symbols on an unscraped device are out of scope. Research
10 §10.6 records that `.cft` height and scraped `size_px` differ, so there
is no verified model. They stay "not checked". So does the palette-size
check (`display_colors` also comes from the scrape).

## 4. Tests (new `tests/test_derived_font_metrics.py`)

Every test must be able to fail. Drive each red once.

1. **Deterministic, no licensed fonts.** Build a `Device` from a tmp device
   dir (see how other tests hand-build a `Device` or `DeviceDatabase`) whose
   `simulator.json` has `ppi` plus a `ww` `ttf` entry
   `{"name": "numberMild", "filename": "OpenSans-Regular", "size": 20}`.
   Put `tests/fixtures/slice/`'s Open Sans TTF, copied under that
   filename, in a tmp fonts root, and point `WFB_FONTS` at it with
   `WFB_NO_GARMIN_FONTS` unset (monkeypatch). Assert
   `FONT_NUMBER_MILD.size_px == round(20 * ppi / 72 * (asc - desc) / upm)`,
   with asc/desc/upm read independently via **fontTools** in the test. That
   cross-checks the struct reader.
2. With `WFB_NO_GARMIN_FONTS=1` (the default test env), the same device
   yields **no** `FONT_NUMBER_MILD`.
3. An entry whose symbol is **outside** the vocabulary (e.g. `glanceFont` →
   `FONT_GLANCE_FONT`) is not added.
4. A **scraped** device keeps its scraped `size_px` even when a fonts root
   is available: fenix847mm's `FONT_NUMBER_MILD` stays 113 from the scrape,
   and the dict's key set is unchanged. Skip if fenix847mm isn't installed.
5. **Leave-one-out against real data** (skip unless a Garmin root with
   `Bionic_Medium.ttf` exists; opt back in by clearing
   `WFB_NO_GARMIN_FONTS`): for fenix847mm, force `_scraped` to `{}` and
   assert that each of the 9 derived `size_px` equals the scraped value.
   Then assert that fenix947mm's derived values equal the table in §2.
6. A `.cft`-only or unlocatable filename yields nothing (no exception).

## 5. Docs (same change)

- `docs/research/10-system-fonts.md`: a new short section (or an §3
  addendum) with the 45/45 check using Garmin's own TTFs, Bionic included,
  and the derived fallback for unscraped devices. Mark it VERIFIED
  (script-reproducible). Extend `tools/research/font_metric_check.py` only
  if cheap; otherwise cite the method.
- `wfb/devices.py` docstrings (`system_fonts`, `FontMetric`): the third
  source.
- `docs/guide/text.md` (~line 136, where it says where metrics come from).
- `docs/limitations.md`: unscraped devices get derived TTF metrics when
  Garmin's fonts are installed; `.cft` symbols and the palette-size check
  stay unavailable there.
- `docs/lore/toolchain.md` if it lists where metrics come from.

## 6. Acceptance (checked by the orchestrator, not the implementer's report)

- `./wfb.py build examples/features/aod/face.yaml -d fenix947mm`: no
  `note[metrics]`, warning-free, and the `aod-burn-in` lit figure within a
  hair of fenix847mm's 1.0%.
- `wfb preview ... --aod -d fenix947mm` draws the clock.
- Builds of the three verification devices are byte-identical to before.
- The fast suite shows only the known `showcase` failure.
