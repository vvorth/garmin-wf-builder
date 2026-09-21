# 12 — Preview font fidelity

**Status:** proposed, 2026-09-21. User-requested. Decision recorded in §1.3.

`wfb preview` is meant to differ from the simulator only in glyph
rasterisation. The user reported that it differs in *typeface*. This plan
records what was actually measured, and what to build.

---

## 1. What was measured, before anything was written

### 1.1 The preview already uses Garmin's own font files

**VERIFIED**, 2026-09-21, by tracing `wfb.fonts.fallback.system_face` through
a real `wfb preview examples/features/vector-text/face.yaml -d
fenix8solar47mm`:

```
FontMetric(symbol='BionicSemiBold', face='BionicSemiBold', font='Bionic_semibold', size_px=18)
  -> match 'garmin', vendor/fonts/Bionic_semibold.ttf
FontMetric(symbol='FONT_TINY', face='Roboto Condensed', font='RobotoCondensed-Bold', size_px=29)
  -> match 'garmin', vendor/fonts/RobotoCondensed-Bold.ttf
```

`wfb.fonts.fetch_system.locate` ranks the Garmin font root
(`vendor/fonts/`, `WFB_FONTS`, the SDK Manager's own `Fonts` directory)
above every registry stand-in, and a vector `face:` reaches it through
`Resolver._vector_font_metric`, whose `FontMetric.font` is the
`simulator.json` `filename` (`Bionic_semibold`), not the `:face` string.
That lookup works, and is what a preview on this machine draws with.

### 1.2 The size model is correct too

**VERIFIED.** An earlier reading of
`docs/research/probes/vector-fonts/radial-facing-simulator-vs-preview.png`
suggested the preview drew vector text ~1.6x too large. It does not: that
image's simulator half was captured at `dial: size: 8%r` (commit
`769f3fc`), and the comparison was made against a fresh render of the
current `14%r` (commit `4771693`). Measured on the two halves of that one
image — which *are* the same design — `FIELD TRACK` is 76 px wide in the
simulator and 72 px in the preview, a 5% agreement. The
`em = size_px / ((hhea.ascent - hhea.descent) / upm)` conversion in
`wfb.fonts.fallback.system_face` is right for a vector face.

### 1.3 What *is* different, and the decision

Two things, neither of them the typeface:

1. **Silent substitution when the Garmin font root is absent.** The root is
   gitignored (it is the user's licensed copy). Without it,
   `locate("Bionic_semibold", "BionicSemiBold")` returns
   `wfb/assets/system-fonts/bionic-substitute.ttf` at match level
   `substitute` — **a different typeface, drawn with no warning at all**.
   A render made on such a machine looks exactly like the reported symptom.
   `wfb doctor` reports the root; `wfb preview` says nothing.
2. **Rotated-text rasterisation.** `_paste_rotated_run` draws the run
   upright at the preview's own scale and then `Image.rotate(...,
   BICUBIC)`s the bitmap. Garmin rasterises the rotated outline. The
   difference shows as softer, thinner stems on angled and radial text.

**User decision (2026-09-21):** build all three of — warn on substitute
fonts, improve the rotated-text rasterisation, and make the font root
harder to miss.

---

## 2. R1 — `wfb preview` reports the faces it actually drew with

**Why:** a wrong typeface must cost one line to diagnose, not a session.

R1.1 `wfb.preview` records, per render, every distinct
`(FontMetric, SystemFace.match, SystemFace.path)` it resolved. `SystemFace`
already carries `match` and `path`; nothing new has to be measured.

R1.2 A render that used **any** face at match level `substitute` or `none`
prints a warning to stderr, once per run, naming each affected font and the
face that was drawn instead:

```
warning: 2 fonts were drawn with a stand-in, not Garmin's own face --
         glyph shapes will not match the simulator:
           BionicSemiBold        -> bionic-substitute.ttf   (substitute)
           Swiss721Bold          -> Pillow default          (none)
         install the SDK Manager's Fonts directory at vendor/fonts/,
         or set WFB_FONTS / pass --fonts DIR -- see `wfb doctor`.
```

R1.3 `exact`/`family` match levels are **not** warned about: those are the
same typeface from a free release, which is what the registry exists for.
Only `substitute` and `none` change the letterforms.

R1.4 The warning goes to **stderr**, so `-o -` keeps working as a pipe, and
is suppressed by neither `-q` nor `-o -` — both of those silence *stdout*
progress, and this is a correctness warning, not progress.

R1.5 `wfb preview` gains `--fonts DIR`, matching `wfb doctor`'s own flag and
threaded through to `fetch_system.locate`'s `fonts_root`. Today the preview
has no way to point at a font root at all.

R1.6 **Drive it red.** A test renders a design with `WFB_NO_GARMIN_FONTS=1`
and asserts the warning names the substituted face; another renders with a
`--fonts` root that has the real file and asserts silence. A guard nobody
has watched fail is not a guard (root `CLAUDE.md` §7).

---

## 3. R2 — rotated text is rasterised, not resampled

**Why:** `angled`/`radial` text is the one thing vector fonts exist for, and
it is the one thing the preview renders worst.

R2.1 `_paste_rotated_run` renders its throwaway layer at an internal
supersample factor `SS` (4 is the proposal) — i.e. the face is loaded at
`em * scale * SS` and the line drawn at `SS`-scaled coordinates — rotates
that layer, then downsamples by `SS` with `Image.LANCZOS` before
compositing.

R2.2 **Geometry must not move.** The anchor maths in `_paste_rotated_run`
is in scaled preview pixels and stays there; only the layer is bigger. The
final paste position is computed exactly as today. A test asserts that the
centre of mass of a rotated run moves by less than a pixel against the
current implementation for a spread of angles — the fidelity change is ink
weight, not placement, and a regression here would silently move every
curved element.

R2.3 `SystemFace` gains no new field for this: `system_face(metric,
scale=...)` already takes the scale, so the supersampled face is
`system_face(metric, scale=self.scale * SS)` — one cached call, the same
advances model, `layout_em` consistent by construction.

R2.4 A bitmap (`.cft`) face has no outline to supersample. That branch keeps
today's behaviour: render at `scale`, rotate, composite — a `.cft` can never
be a vector `face:` anyway (gate 2 only ever publishes outline faces), so
this is defensive.

R2.5 The golden-image tests that cover curved text will move. Regenerate
them in the same commit and say so in the message.

---

## 4. R3 — the font root is harder to miss

R3.1 `tools/setup-env.sh` already copies `vendor/fonts/` incrementally. It
ends by stating, in one line, whether a Garmin font root was found and what
preview fidelity that means — `exact glyph shapes` vs `stand-in faces; see
wfb doctor`.

R3.2 `wfb doctor`'s existing `Garmin fonts` line gains the same one-line
consequence, so the report says what the absence *costs*, not only that it
is optional.

R3.3 `docs/development.md` and `docs/lore/toolchain.md` state the rule
plainly: **without the Garmin font root, previews draw stand-in typefaces
for any face the registry has no exact match for, and the substituted set
is listed by `wfb doctor`.**

---

## 5. Out of scope

- Matching Garmin's rasteriser exactly (hinting, stem darkening). R2 closes
  most of the visible gap; the simulator stays authoritative for glyph
  rendering, as `docs/limitations.md` already says.
- Any change to the size/em model (§1.2: it is correct).
- Any change to `locate`'s ranking (§1.1: it is correct).

---

## 6. Slices

| # | Content | Done when |
|---|---|---|
| 1 | R1 + R3 — diagnostics | the warning fires red in a test, `--fonts` works, docs updated |
| 2 | R2 — rasterisation | goldens regenerated, placement test green |
