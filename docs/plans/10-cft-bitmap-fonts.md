# Plan 10 — decode Garmin `.cft` bitmap fonts for previews and measurement

**Status (2026-09-18):** research done by the orchestrator (§2, feasibility
VERIFIED by a throwaway decoder that rendered real glyphs). Steps A → B → C
are to be built by sequential subagents, each reviewed and committed by the
orchestrator on branch `feat/cft-bitmap-fonts`. This plan closes plan 09's
last open item, **R1b.5**. Once C lands, both plan 09 and this plan are
deleted, per `docs/CLAUDE.md`.

## 1. The request

> research, plan and orchestrate … implementation of relevant .cft fonts
> (according to the device files) usage for previews to make previews as
> close to official simulator as possible.

## 2. Research findings (orchestrator, 2026-09-18)

### 2.1 Which devices need `.cft` (VERIFIED)

The three targets use only TTFs for every `FONT_*`. On fr955, only
`simExtNumber4/5` (simulator data-field fonts, not `FONT_*`) are `.cft`.
**8 of the 13 installed devices** resolve *every* `FONT_*` to a bitmap
`FNT_*` name whose file exists only as `vendor/fonts/<name>.cft`: `fenix6`,
`fenix6xpro`, `fenix7pro`, `fenix7x`, `fenix7xpro`, `fenix7xpronowifi`,
`fr245` and `fr255`. Today these fall to the registry's free stand-in
(Roboto/Bionic substitute), scaled to the scraped `size_px`.
`examples/dashboard` targets fenix6, and `wfb -d` takes any installed
device. Every `.cft` that an installed device's `simulator.json` `ww` set
names is present in `vendor/fonts/`.

For a bitmap entry, `simulator.json` gives only `{name, filename}` (e.g.
`small` → `FNT_FENIX6_CDPG_ROBOTO_20B`). There is no `type`, `size`, `height`
or `ascent`. The scraped table's `font` drops the `FNT_` prefix
(`FENIX6_CDPG_ROBOTO_20B`).

### 2.2 The format (VERIFIED by decoding; prior art cited)

The format is documented in **`markw65/monkeyc-optimizer` `src/cftinfo.ts`**,
MIT licence, pinned at commit `cea919a92da74de1f5d277064caa6f7920554af7`
(<https://raw.githubusercontent.com/markw65/monkeyc-optimizer/cea919a92da74de1f5d277064caa6f7920554af7/src/cftinfo.ts>).
It is used as `npx cft-font-info`. Everything is big-endian:

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
| 26 | 2 | internal leading (unused here) |
| 32 | 4 | `0x12345678` when RLE (36-byte header) |
| 36 | 1 | row alignment in bytes (40-byte header only; else 1) |

- **cmap:** at +12, `nGroups`, then groups of `(start, end, startGlyph)`,
  each u32. A codepoint that is absent maps to glyph 0, the "missing" box.
  What the device draws for an unmapped character is UNVERIFIED; using
  glyph 0 is the working assumption.
- **Glyph info:** a u32 per glyph. `offset = ((w >> 16) & 0xffff) +
  ((w & 0xff00) << 8)`, masked `& 0x7fffff` when RLE. `advance = w & 0xff`.
  **Every glyph is a full `advance × height` cell**, so there are no
  bearings or bbox offsets. The advance is the pen advance, and there is no
  kerning.
- **Pixel layout:** row-major. Each row is `ceil(ceil(advance / ppb) /
  align) * align` bytes, and pixels are packed **LSB-first** within a byte
  (ppb = 4 at 2 bpp, 8 at 1 bpp). A level runs 0..3 (2 bpp) or 0..1 (1 bpp),
  where 0 is background and max is full ink.
- **RLE** (`rleDecode`): the bitstream is read LSB-first. Its header is a
  unary `runBits` (count of 0 bits up to the first 1, plus 1), then 5 bits
  of `chunkSize − 1`, then `chunkSize` bits of `escape`. Each chunk that
  follows is a literal value. When the value equals `escape`, a `runBits`
  run length `r` follows. `r = 0` means the escape value is itself a literal;
  otherwise the *previous* value repeats `r + 1` times. The output is packed
  as `chunkSize`-bit values, LSB-first, until `rowBytes × height` bytes
  exist.
- **40-byte header:** the glyph data may be zlib-compressed. At the data
  offset, a first u32 of `0xCD00000D` (3439329293) means "skip 4, then u32
  length, then zlib". `0xD000000D` (3489660941) means "skip 4, raw". Any
  other value means "u32 length, then zlib".
- **Variants in `vendor/fonts/` (189 files):** 178 have a 36-byte header
  with flags `0x06` (RLE, 2 bpp). 11 have a 40-byte header with flags
  `0x00`, zlib, 1 bpp and align 8 (all `FNT_006B402400_*`, used by fr255's
  `large` and fr955's simExt fonts). The throwaway decoder rendered
  `SMALL Hxg 0123` (fenix6 Roboto 20B), `12:45` (fenix6 Bionic 50) and
  `Hxg 0123 Ab` (a 1 bpp zlib file) correctly, with the ascent line on the
  baseline.

### 2.3 Height vs the published `size_px` (VERIFIED difference, UNVERIFIED which the simulator reports)

Across the scraped default tables, `.cft` `height − size_px` is 0 in 260
entries, +1 in 92 (including all of fenix6: 32 vs 31, 100 vs 99) and +2 in 8.

**Decision (orchestrator):** when a `.cft` is found, its `height`/`ascent`
are the line box and baseline. It is the very file the simulator loads, and
plan 09's rule only keeps `size_px` "where no better number exists". This
can move a fenix6-family layout by 1–2 px. Whether `Graphics.getFontHeight`
on those devices returns `height` or `height − 1` is **UNVERIFIED**. The
existing probe (`docs/research/probes/system-font-metrics/`) answers it when
the user runs it on fenix6 in the simulator; that is the calibration
follow-up in §6.

### 2.4 Antialias blending (UNVERIFIED)

A 2 bpp level `v` is drawn as a linear blend `bg + (fg − bg) × v/3`. Whether
the simulator quantises that to the 64-colour palette is unknown. Blend
linearly, and record the open question.

## 3. Requirements

### Step A — decoder (`wfb/fonts/cft.py`)

1. It is stdlib-only (`struct`, `zlib`, `functools`), with no Pillow import,
   in the same spirit as `fetch_system.py`. It exposes:
   - `load(path) -> CftFont | None`, `lru_cache`d on the path string. It
     never raises, and a malformed file gives `None`.
   - `CftFont` (frozen): `height`, `ascent`, `internal_leading`, `bpp` (1|2),
     `advance(ch) -> int`, `advances(text) -> list[int]`, and
     `glyph(ch) -> Glyph(advance, height, levels: bytes)`. `levels` is
     row-major, one byte per pixel with the value 0..max. Decoded glyphs are
     cached, and `max_level` is exposed.
2. The module docstring cites the reference (repo, file, pinned commit, MIT)
   and carries the field table. A port credits the source, so add
   `monkeyc-optimizer` to README's licence/credits section if one exists, in
   the house style.
3. Tests (`tests/test_cft.py`) must not depend on Garmin's licensed files for
   their core coverage. Add a small **test-side encoder** that writes
   synthetic `.cft` files (36-byte RLE 2 bpp, 36-byte raw 1 bpp and 40-byte
   zlib 1 bpp with align 8) and round-trip against known pixel grids. Cover:
   - an escape literal (`r = 0`);
   - a run longer than one value;
   - a chunk that straddles a byte boundary;
   - a cmap miss → glyph 0;
   - a truncated file → `None`.

   One extra test decodes real `vendor/fonts/FNT_FENIX6_CDPG_ROBOTO_20B.cft`
   and asserts height 32, ascent 25 and a sane advance for `'0'`. It
   **skips when that file is absent**, which must also hold with
   `WFB_NO_GARMIN_FONTS=1`. It reads the file by explicit path.
4. Research: add `docs/research/10-system-fonts.md` **§10 "The `.cft`
   format"** with §2.2–2.4 of this plan, VERIFIED/UNVERIFIED marks, the
   variant census and the height table. Leave the existing §8/§9 `.cft`
   paragraphs in place with a dated "superseded by §10" note beside them
   (house style).

### Step B — use it (layout + preview)

1. **Name → file.** A bitmap `FontMetric` must reach the `.cft`. In
   `Device.system_fonts`, keep the scraped `font`, but carry the
   `simulator.json` `filename` whenever the installed device has one for that
   symbol. Either add a field such as `file` to the `FontMetric`, or make
   `locate` also try `"FNT_" + font`. Pick one, say why, and keep
   `FontMetric` hashable.
2. `fetch_system.locate` (or a sibling that `fallback` calls) returns the
   `.cft` path with match `"garmin"` when no `.ttf`/`.otf` exists for the
   name. A `.ttf` still wins over a `.cft` with the same stem. Update
   `garmin_font_file`/`garmin_cft_file` and their docstrings. The existing
   test `test_cft_is_reported_but_never_returned_as_a_usable_font` is
   deliberately replaced: invert it, don't just delete it. `wfb doctor`
   reports a `.cft` hit as usable.
3. `fallback.system_face`: when the located file is a `.cft`, return a
   `SystemFace` backed by the `CftFont` with these values:
   - `line_height = cft.height × scale`, `baseline = cft.ascent × scale`;
   - `advances()` = the cft advances × scale;
   - `match="garmin"`;
   - a new field, e.g. `bitmap: CftFont | None`, and a `kind`/property that
     the preview can branch on.

   `font` may be `None` for a bitmap face. Audit every `face.font` use
   (`preview.py` and anywhere else) so that no path calls Pillow with `None`.
   `measure()` and `line_height()` must agree with it. `line_height(metric)`
   currently answers without locating a file, so it must now consult the
   `.cft` when one exists (cached) so that layout and preview cannot
   disagree (§2.3).
4. **Preview drawing.** In `_draw_system_line`, and the complication-slot
   path that calls it, a bitmap face draws each glyph cell at `(pen,
   baseline_y − ascent×scale)`. Upscale each glyph by an integer factor with
   `NEAREST`, and paste the colour through an `L` mask whose value is
   `level × 255 / max_level` (§2.4). Pen advances come from `advances()`.
   Build one mask per glyph and scale, and cache it.
5. **Tests** (they must be able to fail; use a fake font root plus a
   synthetic `.cft` from Step A's encoder):
   - `system_face` on a metric whose name has only a `.cft` gives a bitmap
     face with height, ascent and advances equal to the file's;
   - `measure` equals the sum of the cft advances;
   - the preview ink of a known glyph lands on the exact pixels
     (`top`/`center`/`bottom` against the anchor);
   - a `.ttf` with the same stem wins;
   - with the root absent, the old registry path is unchanged.
6. **No golden moves** (`tests/golden/` holds targets only, which are TTF).
   Run `pytest -m "not slow"`. The known 3 failures are listed in
   `tests/CLAUDE.md`, and anything beyond them must be explained. Also check
   the slow fenix6 build test if it is quick enough, and report whether
   fenix6's generated output changed (it may, by the §2.3 pixel), and why.

### Step C — evidence and docs

1. For `fenix6`, `fr245`, `fr255` and `fenix7x`, render the preview PNGs of
   `examples/system-fonts`, `examples/system-fonts-numbers` and
   `examples/system-fonts-numbers-large`. Put them under
   `docs/research/probes/system-font-metrics/previews-cft/`, plus a
   before/after pair for fenix6 FONT_SMALL. Look at them: glyph shapes must
   be the real bitmap faces, with no clipped descenders and baselines on the
   guides as the anchors say.
2. Confirm that the metrics probe builds warning-free for `fenix6` (and
   `fr245`), so the user can run it in the simulator for §2.3's calibration.
   Put the exact command in the research doc.
3. Docs, in the same commit: `docs/lore/toolchain.md` (the Garmin font root
   now serves `.cft`), `docs/limitations.md` (preview fidelity on bitmap-font
   devices; the remaining UNVERIFIEDs), the `wfb/fonts` docstrings, the root
   `CLAUDE.md` plans row (it says "none open", which is stale while 09/10
   exist; set it back to "none open" once both are deleted), and an append to
   `docs/history.md`. Then **delete plans 09 and 10**, and add their
   read-back `git show` lines to `docs/CLAUDE.md` as for the earlier plans.

## 4. Out of scope

- Per-language font sets (non-`ww`).
- CJK `.cft` files beyond what decoding gives for free.
- Changing generated Monkey C.
- Emulating the simulator's palette quantisation (§2.4).

## 5. Build order

A → B → C, each by one Sonnet subagent that does its own work and spawns no
helpers. The orchestrator reviews the diff, runs the fast tests and commits
after each step.

## 6. Follow-up for the user (calibration)

Run the metrics probe and `examples/system-fonts` on **fenix6** in the host
simulator, and send the console lines and a screenshot. That settles §2.3
(`height` vs `height − 1`) and §2.4 (the blend).
