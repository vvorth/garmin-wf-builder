# 14 — The stamped ring: offset sets, cost, and a format for outlined text

`docs/research/13-outline-vector-text.md` §5 named the **stamped ring** as
the one workable substitute for platform outline text that also works with
`curve:` (rotated/radial) vector text: draw the string N times at small
`(dx, dy)` offsets in an outline colour, then once more at the centre in a
fill colour (often the background, for a hollow look). This document
measures that technique rather than asserting it: which offset set to use
at ring width r = 1, 2, 3 px; whether it works per font kind, including the
radial-text geometry question 13 left as a one-line claim; what it costs in
lit pixels, code size and (as far as anything in this project can say) CPU;
how it compares to a `BufferedBitmap` mask and a build-time baked outline
sheet; whether the interior pass can be a true transparency mask instead
of a flat paint (§6); how `wfb/preview.py` would reproduce it; and a
proposed, unbuilt `outline:` format -- since resolved into a concrete,
unbuilt design, `docs/plans/15-text-outline.md`, which answers every open
question §8.2 leaves below under its own "Decisions (orchestrator, on
user's go-ahead)" heading. Read that plan for the format as it will
actually ship; this document remains the measurement record behind it.

Every behavioural claim is marked **VERIFIED** or **UNVERIFIED**, per
`docs/CLAUDE.md`. "VERIFIED" here mostly means *measured in this probe*,
which is a host-side Pillow/numpy/scipy/freetype-py simulation, not a
Connect IQ build — where a `monkeyc --build-stats` figure was actually
produced, it says so explicitly and is a real build, warning-free, on
`fenix8solar47mm`. No claim in this document was observed on a real watch
or in the simulator (root `CLAUDE.md` §3: no simulator here).

**No compiler code changed to write this document.** The probe lives
entirely under `docs/research/probes/stamped-ring/` and one ephemeral
`wfb build` output directory that was not committed.

---

## 1. Offset sets at r = 1, 2, 3

**Method (VERIFIED, measured):** `docs/research/probes/stamped-ring/
stamp_experiment.py` renders `"12:34"` at 80px with
`examples/features/vector-text/assets/ChivoMono-Bold.ttf` (already vendored
for the `curve:` examples), thresholds it to a 1-bit mask — the same
non-anti-aliased default `wfb/fonts/bmfont.py` uses — and compares four
offset sets against a **true morphological dilation**: every background
pixel within Euclidean distance r of a foreground one
(`scipy.ndimage.distance_transform_edt`, not an approximation). Full numbers
and PNGs: `docs/research/probes/stamped-ring/README.md` §1.

| r | offset set | draws | missing px | extra px | ring IoU | ring/solid ratio |
|---|---|---|---|---|---|---|
| 1 | square8 (8 fixed compass/diagonal points at radius r) | 8 | 0 | 229 | 0.820 | 0.240 |
| 1 | cross4 (4 axis-aligned points at radius r) | 4 | 0 | 0 | **1.000** | 0.197 |
| 1 | disc-filled (every integer point with dx²+dy²≤r²) | 4 | 0 | 0 | **1.000** | 0.197 |
| 1 | disc-perimeter (the outer integer shell only) | 4 | 0 | 0 | **1.000** | 0.197 |
| 2 | square8 | 8 | 0 | 480 | 0.814 | 0.485 |
| 2 | cross4 | 4 | 36 | 0 | 0.983 | 0.388 |
| 2 | disc-filled | 12 | 0 | 0 | **1.000** | 0.395 |
| 2 | disc-perimeter | 8 | 0 | 0 | **1.000** | 0.395 |
| 3 | square8 | 8 | 0 | 626 | 0.839 | 0.732 |
| 3 | cross4 | 4 | 213 | 0 | 0.935 | 0.574 |
| 3 | disc-filled | 28 | 0 | 0 | **1.000** | 0.614 |
| 3 | disc-perimeter | 16 | 0 | 0 | **1.000** | 0.614 |

**Findings, all VERIFIED against this probe:**

- **`square8` always overshoots, never undershoots.** Its diagonal offsets
  sit at Euclidean distance `r·√2`, past the true disc radius r, so it
  rounds every corner outward — 0 missing pixels at every r, but 229–626
  extra ones, visible as blue bulges at the glyph's corners in
  `diag-square8-r{1,2,3}.png`. This is the "corners" artefact the task
  asked to look for, and it is measured, not eyeballed.
- **`cross4` always undershoots on diagonal strokes, never overshoots.** 0
  extra pixels at every r, but 0 → 36 → 213 missing pixels as r grows —
  visible as gaps where the glyph's diagonal strokes (the `4`'s arm, the
  `2`'s curve) meet the ring in `diag-cross4-r{2,3}.png`. This is the
  "gaps on diagonal strokes" artefact, and it gets worse, not better, as
  the ring widens, because a fixed 4-point set covers a shrinking fraction
  of a growing circle's circumference.
- **`disc-perimeter` reproduces the true dilation exactly, at every r
  tested, with fewer draws than `disc-filled`** (4/8/16 vs 4/12/28) — for
  these glyph strokes, the disc's interior offsets are redundant. This is
  not obvious a priori (dilation by a filled convex set is not in general
  equal to dilation by only its boundary, for a shape with holes or thin
  concavities) but it holds here and at the larger sizes checked in §3.
- **The lit-pixel ratio (ring pixels ÷ original solid pixels) is size-
  dependent, and drops as text gets bigger**, because ring width is fixed
  in pixels while solid area grows with the square of size and ring
  perimeter only linearly. Re-run at 80/160/240px with `disc-perimeter`,
  r=2 (ring pixel count matches the true dilation exactly at every size,
  confirming §1's finding holds beyond the one size tabulated):

  | glyph height | solid px | ring px | ring/solid ratio |
  |---|---|---|---|
  | 80px | 5,321 | 2,103 | 0.395 |
  | 160px | 20,975 | 4,206 | 0.201 |
  | 240px | 47,335 | 6,325 | 0.134 |

  This matters directly for AOD sizing (§3).

**Recommendation from this section alone: `disc-perimeter`.** It is exact
(0 missing, 0 extra against the true dilation, at every r and every size
tried) at the lowest draw count of the three exact options, and strictly
better than `square8` in both draw count and correctness. `cross4` is
cheapest in draws but is the only one of the four with a **quality gap
that widens as the ring grows**, so it should not be the default for
r ≥ 2.

## 2. FreeType's stroker as a second "ideal"

The task asked to compare against FreeType's own stroker, since research
13 §2.1 found Garmin's own TTF engine calling exactly this pair of
primitives (`FT_Stroker_New`/`FT_Stroker_Set` with a round join, then
`FT_Glyph_StrokeBorder`) at a fixed 2.0px radius. `freetype-py` is not a
project dependency; it was installed transiently for this probe only
(`pip install freetype-py`, network access was available in this sandbox).

**VERIFIED, measured (`docs/research/probes/stamped-ring/README.md` §2):**
`FT_Glyph_Stroke` (the high-level call `freetype-py` exposes; it strokes
both borders of the outline rather than `FT_Glyph_StrokeBorder`'s
outside-only border, so the *filled* stroked glyph minus the *filled*
plain glyph is taken as "the ring" here) with `FT_STROKER_LINECAP_ROUND`/
`FT_STROKER_LINEJOIN_ROUND`, compared against this probe's own raster
(Euclidean) dilation of the plain glyph:

| radius px | FT stroke ring px | raster-dilation ring px | ring IoU |
|---|---|---|---|
| 1.0 | 269 | 244 | 0.907 |
| 2.0 | 539 | 487 | 0.904 |
| 3.0 | 811 | 771 | 0.951 |

IoU 0.90–0.95 across all three radii, including the 2.0px row that matches
Garmin's own engine exactly. The residual is curve-fitting on round joins
versus this probe's raster quantisation, not a structurally different
ring. **This means the raster-dilation "ideal" used throughout §1 and §3
is a good stand-in for what FreeType's real stroker — and by inference
Garmin's own TTF engine, on the one path a Connect IQ app cannot reach
(research 13 §3) — would draw**, not a second, disagreeing definition of
"ring". This is new evidence beyond what research 13 established: 13 knew
*that* the engine strokes at 2px round-join from the disassembly; this
probe independently confirms *what that stroke looks like* is close to a
plain disc dilation, from the outside, on real font outlines.

## 3. Per font kind

### 3.1 Which kinds can be stamped

All three text-drawing paths this project uses are call-then-call-again:
nothing about repeated invocation is special-cased by the platform.

| Font kind | Draw call | Stampable? |
|---|---|---|
| Baked BMFont resource (`font: font.<name>`) | `Dc.drawText` | **Yes.** Measured directly in §5's `monkeyc` probe, which stamps a real baked `.fnt` resource. |
| System `FONT_*` | `Dc.drawText` | **Yes** — same call, same signature; nothing in `wfb/preview.py`'s `_approximate_text` or the SDK docs treats a system font differently for repeated calls. |
| Vector `face:` font, upright | `Dc.drawText` | **Yes**, same call. |
| Vector `face:` font, `curve: {style: angled}` | `Dc.drawAngledText` | **Yes** — see §3.2. |
| Vector `face:` font, `curve: {style: radial}` | `Dc.drawRadialText` | **Yes** — see §3.2, with a caveat on offset-set quality, not on validity. |

`Dc.drawText`'s signature is `(x, y, font, text, justification)`
(`$CIQ_SDK/doc/Toybox/Graphics/Dc.html`) — every kind above funnels through
one of three calls that all take a plain `(x, y, ...)` anchor, which is
exactly what a stamped offset needs to exist at all.

### 3.2 Angled and radial text: is a screen-space `(dx, dy)` offset still a valid dilation?

**The two native signatures, read from `$CIQ_SDK/doc/Toybox/Graphics/
Dc.html` (VERIFIED):**

```
drawAngledText(x, y, font, text, justification, angle) as Void
drawRadialText(x, y, font, text, justification, angle, radius, direction) as Void
```

Both take a **plain screen-space `(x, y)` anchor as a separate argument**
from the angle (and, for radial, the radius/direction). This is the fact
the geometry argument below rests on.

**Angled text (a whole run rotated as one rigid shape).** `drawAngledText`
rotates the entire string about `(x, y)` by a fixed `angle` and draws it as
one rigid raster. Re-invoking it N times with the same `angle` and only
`(x, y)` shifted by each stamp offset is, by construction, N rigid
translations of the identical rotated raster — exactly what a dilation's
offset-and-union step needs, for *any* rotation angle, because translation
commutes with rotation: rotating a shape by θ and then translating it by
`(dx, dy)` gives the same result as translating first and then rotating
about the shifted centre by the same θ. **A screen-space offset set is a
valid dilation contribution for angled text at any angle, with no
correction needed.** This matches research 13 §5's original claim and
adds the derivation, plus confirmation from the real API signature rather
than only from `wfb/preview.py`'s own implementation
(`_paste_rotated_run`, which performs exactly this translate-then-rotate
arithmetic in `wfb/preview.py:1433-1546`).

**Radial text (each glyph its own position and rotation around a
circle).** `drawRadialText` places each glyph at its own position on the
circle of `radius` centred on `(x, y)`, each rotated to face along the
arc — `wfb/preview.py:1293-1431`'s `_draw_radial_vector_text` implements
exactly this per-glyph model (verified against the SDK's own
`TrueTypeFontsRadialText` sample and the real simulator, research 12 and
`wfb/preview.py:1305-1329`'s own citations). Crucially, in that model a
glyph's own rotation angle (`theta_pos`/`glyph_angle_garmin`) is a function
of its arc position — `base_theta`, `direction_sign`, `pixel_offset`,
`radius` — and **never of the centre `(cx, cy)`**. Shifting the centre by
`(dx, dy)` shifts every glyph's `(px, py)` by exactly `(dx, dy)` while every
glyph's rotation is untouched (`wfb/preview.py:1425-1426`:
`px = cx + glyph_radius * cos(theta_pos)`, `py = cy - glyph_radius *
sin(theta_pos)` — additive in `cx`/`cy`, with `theta_pos` computed two
lines earlier from none of them). So **re-invoking `drawRadialText` with
the same `angle`/`radius`/`direction` and only `(x, y)` shifted is,
exactly as for angled text, a rigid translation of the whole composed
raster — a valid dilation contribution, for the same reason.** This
directly answers the task's geometry question: **yes, it is still true for
radial text**, contrary to what a looser reading of research 13 §5's one
line ("offsets on a curved run move along x/y, not along the curve") might
suggest.

**What *is* still true, and is what that line in 13 was actually
gesturing at:** the *quality* of a coarse, direction-limited offset set
(the question §1 answers for straight text) is not rotation-invariant, and
a radial run puts every glyph at a *different* rotation by construction.
**VERIFIED, measured** (`docs/research/probes/stamped-ring/README.md` §3):
rotating a single glyph mask (`"1"`, one dominant straight stroke) from
0–90° in 15° steps and re-measuring each offset set's ring IoU against the
true dilation of that same rotated mask:

| offset set | min ring IoU | max ring IoU | spread |
|---|---|---|---|
| square8 | 0.536 | 0.929 | **0.393** |
| cross4 | 0.982 | 1.000 | 0.018 |
| disc-filled | 1.000 | 1.000 | 0.000 |
| disc-perimeter | 1.000 | 1.000 | 0.000 |

`square8`'s quality swings by nearly 40 IoU points depending on the
glyph's own rotation (worst at 45°, where its diagonal offsets and the
rotated glyph's now-axis-aligned edges disagree most), while
`disc-filled`/`disc-perimeter` are exactly rotation-invariant, as a true
disc must be. **So the corrected statement is: a fixed screen-space offset
set's approximation quality can vary around a radial ring (worst for
`square8`, negligible here for `cross4`, absent for a disc-shaped set),
but the underlying technique — re-invoking the draw call with a shifted
anchor — is exactly as valid for radial text as for straight text.** This
is measured on one glyph and one font; it is not a proof that every glyph
shape has the same spread, but the mechanism (rotation-variant coverage of
a direction-limited offset set) is general, and `disc-perimeter`/
`disc-filled` are immune to it by construction, so **the fix for
uneven-looking radial rings is the same fix §1 already recommends: use a
disc-shaped offset set, not `square8`.** Research 13 §5 is updated in
place below to reflect this.

### 3.3 Anti-aliased fonts, and 64-colour MIP dithering

`antialias:` is **not a `text` element key at all** in this project — it
governs `group`/`shape`/`progress`/`graph`/`hands`/`pattern`/`icon`/
`complication_slot`, explicitly excluding `text`
(`docs/guide/elements.md`'s own "at a glance" table). A custom font's
anti-aliasing is a **resource attribute** baked at build time
(`<font antialias="true">`, `docs/guide/elements.md` §"antialias:" and
`docs/research/probes/antialias/README.md`), and a system or vector font's
anti-aliasing is decided by the device's own rendering, not by anything
this compiler controls.

**Stacking N stamps of an anti-aliased glyph (VERIFIED, measured, as a
model of opaque non-blended compositing — `docs/research/probes/
stamped-ring/README.md` §4):** with `alphaBlendingSupport: false` on every
MIP target (constraint 10), overlapping opaque draws cannot be additively
blended; the physically available model is that a later stamp's covered
pixels simply overwrite (weighted only by that stamp's own edge coverage
at that pixel), never sum. Modelling this as a per-pixel maximum across
all stamps, on `"12:34"` rendered anti-aliased and stamped at `square8`
r=2:

| | fractional-alpha edge pixels | mean alpha there |
|---|---|---|
| original | 663 | 0.492 |
| stamped (max-composited) | 654 | 0.515 |

Fewer pixels remain fractional (more of the original soft edge reaches
full opacity under an overlapping stamp) and the ones that remain
fractional average higher — **the anti-aliased edge measurably hardens and
thickens under stamping; it cannot soften**, which is the only outcome
possible for overlapping *opaque*, non-blended draws. The magnitude here
is a model, **UNVERIFIED** against a real device (no simulator in this
container); the *direction* (harder, never softer) follows deductively
from `alphaBlendingSupport: false` and needs no device to state.

**64-colour MIP quantisation compounds this, and is already measured
elsewhere, not re-derived here.** Each channel must land on `0x00`/`0x55`/
`0xAA`/`0xFF`, or the firmware dithers it (`docs/limitations.md` "64
colours, and everything else dithers"; `lint.check_antialias_palette`,
`antialias-dither`). `docs/research/probes/antialias/README.md` §2 already
measured that turning a baked font's `antialias:` on trades ~3.6 KB of
`.prg` for a continuous 256-level grey ramp, and that ramp is exactly what
then dithers on a 64-colour panel. A stamped anti-aliased ring compounds
both effects in the same direction — more, and grainier, intermediate grey
— never in opposing directions, so there is no cancellation to hope for.
**Recommendation, and it needs no new evidence: stamp a *non-anti-aliased*
1-bit font.** This project's baked-font default is already 1-bit
(`antialias: false`), so the stamped-ring technique's natural input is
already the cheap, dither-free case; anti-aliasing a font that will then
be stamped actively fights both the dithering rule and the "thin/light,
not soft" AOD guidance (research 11 §1.3).

## 4. Cost

### 4.1 Lit pixels vs. the AOD budget

Research 11 §1.2 gives two numeric AMOLED rules (Venu-original: >10% of
pixels lit or any pixel lit >3 min; Venu 2+: <10% of screen luminance).
Using the size-scaled ring/solid ratios from §1 and the two installed
AMOLED devices' own resolution (`fenix847mm`/`fenix947mm`, `454×454`,
research 11 §3.6–3.7):

| glyph height | solid, % of a 454×454 screen | `disc-perimeter` r=2 ring, % of screen |
|---|---|---|
| 80px | 2.58% | 1.02% |
| 160px | **10.18%** | 2.04% |
| 240px | 22.97% | 3.07% |

**VERIFIED, measured** (same probe, same font, scaled). At 160px — a
plausible size for a large AOD clock's digits, roughly a third of the
screen's own height — a **solid** rendering of `"12:34"` alone is already
at the 10% whole-screen ceiling, before any bezel, date, or complication
is drawn; the **ring** version of the same string is under a quarter of
that. This is the concrete form of research 11 §1.3's "use fonts with thin
line weights" guidance: a stamped ring is a way to make a *bold, legible*
glyph behave like a thin one for the lit-pixel budget, without actually
thinning the font (which the FAQ also recommends, and remains the
zero-cost alternative — §1's ring/solid ratios show the two are not
mutually exclusive: a thin face stamped into a ring lights fewer pixels
still). This table is for one string at one font; a full face's budget is
the *sum* over every AOD-visible element (research 11 §3.4 — no burn-in
lint exists yet to check this automatically), so these numbers bound one
element's contribution, not a whole design's.

### 4.2 Per-`drawText` CPU cost

**UNVERIFIED, and stated as such deliberately.** No figure for the cost of
one `Dc.drawText`/`drawAngledText`/`drawRadialText` call exists anywhere
in this repository or in the SDK's own documentation. The closest thing on
record is `docs/research/00-summary.md` open question 1: an undocumented
`watchdogCount: 240000` in `simulator.json`, units unspecified, which
`wfb/lint.py`'s own `check_partial_update_budget` (§heuristic, not a
figure) already declines to turn into a per-operation cost — it warns on
**clip area** and **element count** in `low_power` mode, never on a
modelled millisecond figure, precisely because no such figure exists to
model with (`wfb/lint.py:1365-1370`'s own docstring: "the numeric budget is
not published"). Nothing in this probe changes that; a stamped ring's CPU
cost cannot be estimated beyond "N+1 draw calls of the same kind the face
already makes," which is qualitative, not a number.

**Relating that qualitative cost to the two relevant constraints:**

- **`onPartialUpdate` (constraint 4) / MIP low-power.** A stamped ring used
  in `low_power` mode multiplies the element's own contribution to
  `check_partial_update_budget`'s "how many elements does this clip draw
  each second" count (`operations = len(low_power)`,
  `wfb/lint.py`) by N+1 if implemented as N+1 separate elements — but the
  format proposal in §6 is a *style modifier* on one `text` element, not
  N+1 authored elements, so if codegen keeps it as one generated method
  making N+1 draw calls (the loop form measured in §5), the element count
  the lint sees is unchanged; only the *clip*, which already has to cover
  the ring's extra r pixels on every side, needs to grow by r px, a fixed,
  computable amount already knowable at layout time.
- **AOD 1-minute cadence / AMOLED pixel budget.** §4.1 is the pixel-budget
  side of this. On the CPU side, once a minute is the same cadence every
  other AOD draw call already runs at (research 11 §1.1), so N+1 draw
  calls once a minute is a much smaller time budget concern than the same
  N+1 calls would be at the 1 Hz `active` cadence — this is a reason to
  prefer the ring specifically for AOD over reusing it in `active` mode,
  independent of the pixel-budget case already made.

### 4.3 Code size: loop vs. unrolled (measured, real `monkeyc --build-stats`)

**VERIFIED, measured.** `docs/research/probes/stamped-ring/README.md` §5:
a real `wfb build` output (`examples/features/vector-text/face.yaml`,
`fenix8solar47mm`) with `drawClock`'s body replaced by an 8-offset and a
16-offset stamped ring, in both unrolled and array-loop form, built with
`$CIQ_SDK/bin/monkeyc -f monkey.jungle -d fenix8solar47mm -w -l 3
--build-stats 0`. All four variants (plus the untouched baseline) are
**BUILD SUCCESSFUL, warning-free**.

| variant | N | foreground total | delta over baseline |
|---|---|---|---|
| baseline (1 `drawText`) | – | 2,736 B | – |
| unrolled | 8 | 2,965 B | **+229 B** |
| loop (flat offsets array) | 8 | 2,945 B | **+209 B** |
| unrolled | 16 | 3,181 B | **+445 B** |
| loop | 16 | 3,025 B | **+289 B** |

The loop's **code is flat (1,933 B) at both N=8 and N=16** — only its data
grows, ~5 B/`Number` (~10 B/offset pair), matching
`docs/research/probes/pattern-cost/README.md` finding 4 ("a runtime loop's
cost is in the array, not the loop body") for a different draw call
(`drawLine`/`fillPolygon` there, `drawText` here) at a near-identical
per-coordinate rate. The unrolled form costs ~27–29 B of code per *added*
call. **Unlike `pattern-cost`'s dramatic 7–30× win for a 60-copy tick
pattern, the loop is close to a wash at N=8** (229 vs 209 B, ~9% smaller)
and only pulls ahead by ~35% at N=16 — the draw counts a stamped ring
actually needs (§1's exact sets: 4/8/16). **Either form is affordable in
absolute terms** (worst case measured, unrolled N=16, is 445 B — 0.34% of
the 131,072 B MIP watch-face budget on this device) — this is a
memory-size verdict only; §4.2 already states plainly that no CPU number
exists to weigh against it. The loop is still the better default: it
scales the right way as N or r grows, and an author-tunable ring width
(§6) is then one array literal, not a rewrite of unrolled call sites.

## 5. Alternatives compared

### 5.1 A `BufferedBitmap` mask, blitted at N offsets

**The idea:** render the text once into an off-screen bitmap, then
`Dc.drawBitmap` it N times at the stamp offsets, trading N `drawText` calls
(each doing font lookup, per-glyph advance and rasterisation) for one
`drawText` plus N cheap blits.

**What the SDK and this repo's own codegen establish (VERIFIED):**

- `Graphics.createBufferedBitmap` (`$CIQ_SDK/doc/Toybox/Graphics.html`)
  takes an optional `:palette` (an indexed colour array) and an optional
  `:alphaBlending` (`Graphics.AlphaBlending`) — the second is meaningless
  where `alphaBlendingSupport` is `false`, i.e. every MIP target here
  (constraint 10, "no transparency").
- **A non-palette'd buffer can hold anti-aliased text, but cannot be
  blitted with a transparent "hole"** — `wfb/emit/monkeyc/view.py:334-350`
  (`_emit_static_allocation`) deliberately omits `:palette` specifically
  *so that* `Dc.setAntiAlias` stays legal on that buffer's own `Dc`
  (`setAntiAlias` is documented unsupported only for a palette'd
  `BufferedBitmap`) and so an anti-aliased font can be drawn into it — the
  tradeoff being that this project's own static buffer is always filled
  with the *whole* static content (background included) and blitted
  whole, never composited as a transparent overlay on top of something
  already drawn (`_emit_static_methods`'s docstring: it clears to black
  first, "because the static content is always the prefix of draw
  order"). Nothing in the generated code today relies on a non-palette'd
  buffer's transparency, because it has none to rely on.
- **A palette'd buffer supports index-based ("this exact colour is a
  hole") transparency even on MIP** — this is how a bitmap *resource*
  (`disableTransparency`, `$CIQ_SDK/doc/docs/Core_Topics/Resources.html`
  "Bitmaps") already gets non-rectangular icons onto a 64-colour panel
  with `alphaBlendingSupport: false`; the same index mechanism is what a
  runtime-filled `:palette`'d `BufferedBitmap` would need for a "mask"
  blit — but research 13 §3.1 found the *engine's own* "Anti-aliased font
  cannot be drawn to a paletted buffer" message on exactly the `drawText`
  code path, so a mask buffer that needs transparency (palette'd) and a
  font that needs anti-aliasing are mutually exclusive, the same
  constraint `_emit_static_allocation`'s own comment already states for a
  different reason.
- Put together: a **1-bit, non-anti-aliased** baked font — already this
  project's default, and already what §3.3 recommends for stamping in the
  first place — is exactly the case that is unaffected by that
  restriction, so a mask-bitmap approach is not ruled out by anti-aliasing
  for the font kind that matters here.

**What is not established (UNVERIFIED):** whether `Dc.drawBitmap` is
actually cheaper than `Dc.drawText` per call. No SDK doc states a cost for
either, and no simulator or device is reachable from this container to
measure one. The *prior* for a blit being cheaper than a font-lookup-plus-
rasterise draw is a reasonable one, and how every 2D UI toolkit's own
sprite/glyph-cache tricks are justified — but it is not evidenced here,
and this project does not currently allocate any runtime `BufferedBitmap`
for anything but the whole-face `static:` buffer (`wfb/emit/monkeyc/
view.py`'s `STATIC_FIELD`, one per face), so a second, glyph-sized buffer
allocation (and its own memory-pool cost, `graphics-pool` lint, constraint
11) would be new machinery, not a reuse of something already measured.

**Verdict:** plausible, unmeasured, and non-trivial new machinery (a
palette'd mask buffer, a second allocation path, a fallback for a device
without `createBufferedBitmap`). Not recommended as the first
implementation; a candidate for later if §4.2's missing CPU number ever
gets measured and shows the stamped-loop form is actually expensive.

### 5.2 A build-time baked outline sheet

Bake an outline-design TTF, or stroke the glyphs at build time with
FreeType's own stroker (§2 shows this project's `.venv` can already do
this: `freetype-py`'s `Stroker`/`Glyph.stroke`, the exact primitive pair
research 13 found Garmin's own engine calling) directly inside
`wfb/fonts/bmfont.py`'s rasteriser, producing a second, already-hollow
glyph sheet with **zero runtime draw calls beyond the one `drawText` a
baked font already needs.**

**For:** the cheapest possible *runtime* cost (one draw, not N+1) and, per
§2's IoU-0.9+ agreement with raster dilation, visually close to what a
disc-shaped stamped ring already achieves. No new lint or memory-budget
category — it is exactly the existing baked-font path (font resource size
in the `.prg`, not the watch-face `memoryLimit`, per constraint 11 and the
`antialias` probe's own measured finding that font pixels are a resource
cost, invisible to `--build-stats`).

**Against, restating research 11 §1.4's own conclusion:** bitmap only — no
`curve:`, because a baked sheet has no outline to rotate per glyph the way
a vector font's live rasteriser does; no runtime colour change (the
ring/fill split is baked into the pixels, so `config.colors.<role>`-driven
recolouring — already supported for `color:` on ordinary text — cannot
retint just the ring or just the fill independently without two baked
sheets, doubling the resource cost); one more sheet in the graphics pool
per font/size combination actually used.

### 5.3 Recommendation

**Default to the stamped ring, `disc-perimeter` offsets, as a runtime
loop over a small constant array — the only option that reaches every
font kind including `curve:` — and keep a baked outline sheet in reserve
as a bitmap-only optimisation for a face that only ever needs one fixed
ring width on one baked font and wants to shave the N extra draw calls.**
The `BufferedBitmap` mask route is not recommended for a first cut: it is
unmeasured against the very call it exists to avoid, and it is new
allocation machinery this project does not otherwise need for this
feature.

## 6. Is there a transparency mask, so the interior pass can reveal instead of paint?

A natural question once the interior pass exists at all: instead of
painting the glyph's interior in a colour that merely *matches* the
background (§8.2 item 1's open question), can it be drawn *transparent*,
so it genuinely reveals whatever is underneath — the real background art,
or another element the glyph happens to overlap? **Short answer: no
general-purpose mask exists on the direct-to-screen path this project
uses, and the one narrow, unverified possibility found is AMOLED-only and
would need a whole second rendering path to exploit.** Every claim below
is checked directly against `$CIQ_SDK/doc/Toybox/Graphics.html` and
`$CIQ_SDK/doc/Toybox/Graphics/Dc.html`, not against research 13's earlier,
less formal finding (though it agrees with and sharpens that finding).

### 6.1 The documented blend modes, checked directly

**VERIFIED.** `Graphics.BlendMode` (`$CIQ_SDK/doc/Toybox/Graphics.html`)
has exactly four values:

| Constant | Formula (SDK's own notation) | Devices |
|---|---|---|
| `BLEND_MODE_DEFAULT` / `BLEND_MODE_SOURCE_OVER` | `S + (1 - S.a) * D` | all with `setBlendMode` |
| `BLEND_MODE_NO_BLEND` / `BLEND_MODE_SOURCE` | `S`, i.e. no blending | all with `setBlendMode` |
| `BLEND_MODE_MULTIPLY` | `(S * (1-D.a)) + (D * (1-S.a)) + (S*D)` | **"Only supported on devices with GPU"** |
| `BLEND_MODE_ADDITIVE` | `S + D` | **"Only supported on devices with GPU"** |

None of the four is a "destination-out"/erase/clear formula (the standard
name for what a real mask needs is `D * (1 - S.a)`, i.e. punch a hole in
the destination sized by the source's alpha — absent from this list
entirely). `Dc.setBlendMode`'s own detail page adds, verbatim: **"Note:
BLEND_MODE_NO_BLEND is only supported while drawing bitmaps."** So even
the one non-default mode that exists cannot be engaged for a `drawText`
call at all — confirming the orchestrator's reading exactly, from the
primary source rather than by inference.

### 6.2 `drawText` itself, and `COLOR_TRANSPARENT`, checked directly

**VERIFIED, and stronger than research 13's own finding.** Research 13 §3.1
found the string "Anti-aliased font cannot be drawn to a paletted buffer"
*inside the simulator binary* by static disassembly. The **public SDK
documentation says the same thing outright**, as `Dc.drawText`'s own
discussion and `Throws` clause (`$CIQ_SDK/doc/Toybox/Graphics/Dc.html`,
`drawText-instance_function`, second/detail occurrence):

> "This method is not supported for anti-aliased fonts (including most
> built in fonts) for a `BufferedBitmap` that has a palette."
>
> Throws `Graphics.InvalidPaletteException` — "Thrown if an anti-aliased
> font is used on a paletted bitmap."

(`Graphics.InvalidPaletteException` is a real, documented exception class,
also thrown by `Dc.drawBitmap`'s own, differently-worded case — "the source
color palette is not a subset of the destination palette" — and by
`Dc.setAntiAlias` — "Thrown if antialiasing is enabled for a paletted
bitmap." Three distinct paletted-buffer failure modes, one exception
type.) Note the parenthetical: **"including most built in fonts"** — most
system `FONT_*` faces are themselves anti-aliased on real hardware, so
this restriction is not limited to a custom baked font with
`antialias: true`; it is the default case for system text too, and is
exactly why this project's own recommendation (§3.3, §5.1) is to stamp a
1-bit baked font specifically.

**`Graphics.COLOR_TRANSPARENT` (`= -1`, API 1.0.0) as the *foreground*
(ink) colour is not a documented "write a hole" primitive anywhere in the
SDK.** Checked three ways:

1. `Dc.setColor(foreground, background)`'s own parameter docs describe
   both arguments identically — "`Graphics.COLOR_*` constant or 24-bit
   integer of the form `0xRRGGBB`" — with no special-cased behaviour for
   `COLOR_TRANSPARENT` as `foreground` distinct from any other colour
   constant.
2. Every SDK sample that passes `COLOR_TRANSPARENT` to `setColor` at all
   (`grep -rn COLOR_TRANSPARENT $CIQ_SDK/samples`, 20+ hits) uses it **only
   as the `background` argument** — meaning "do not paint a background box
   behind this text/shape" — never as `foreground`. The one call that
   *does* pass it as `foreground`
   (`samples/MO2Display/source/CommandView.mc:36`,
   `dc.setColor(Graphics.COLOR_TRANSPARENT, Graphics.COLOR_BLACK)`) is
   immediately followed by `dc.clear()`, whose own doc is "erase the
   screen using the **background** color" — the foreground argument is
   simply unread by that call; not a counter-example.
3. Under the `BLEND_MODE_SOURCE_OVER` formula from §6.1, a source with
   `S.a = 0` (fully transparent) reduces the formula to `D` — the
   destination is returned unchanged. **A `COLOR_TRANSPARENT` glyph draws
   nothing and erases nothing** — it is a no-op, exactly as the
   orchestrator's reading concluded, and this is now derived from the
   platform's own documented compositing formula rather than assumed.

### 6.3 The one narrow possibility this check turned up, flagged prominently and left unverified

**`Graphics.AlphaBlending.ALPHA_BLENDING_PARTIAL`, passed to
`createBufferedBitmap`'s `:alphaBlending` option, is documented to support
real per-pixel transparency reliably** — this is new relative to the
orchestrator's reading, and is reported here exactly as requested.
`Graphics.createBufferedBitmap`'s own detail page carries this note
(`$CIQ_SDK/doc/Toybox/Graphics.html`, second/detail occurrence):

> "The result of a draw/fill operation to a `BufferedBitmap` created with
> `ALPHA_BLENDING_PARTIAL` may produce inconsistent results between
> devices and the ConnectIQ simulator **if the drawn pixels are not fully
> opaque or fully transparent**."

Read the other way round: **fully opaque or fully transparent pixels on
such a buffer are documented to be consistent** — this is the one place
in the whole SDK that talks about a drawn pixel being genuinely,
reliably transparent, not merely "not painted this frame." `ColorType`
itself (`Graphics.html`'s named-type table) is `Lang.Number or
Graphics.ColorValue`, and `Graphics.createColor(alpha, r, g, b)` returns
exactly such a `Lang.Number`, with `alpha` documented as "0-255 representing
alpha channel" — so passing `Graphics.createColor(0, 0, 0, 0)` to
`setColor`'s `foreground` argument is *type-legal* everywhere a colour is
accepted.

**What stops this from being a confirmed answer:**

- `ALPHA_BLENDING_PARTIAL` requires `Graphics.createBufferedBitmap`'s
  alpha path, which is only meaningful where `alphaBlendingSupport` is
  `true` — **AMOLED only** (constraint 10; every MIP target in this
  project, including all three verification devices, is excluded
  outright).
- **Whether `Dc.drawText` actually reads and applies the alpha channel of
  a `createColor`-produced `foreground` value is undocumented either
  way.** `setColor`'s own parameter text never mentions alpha at all
  (§6.2). The only place the SDK docs discuss an alpha-bearing draw
  *tool* is `setFill`/`setStroke` ("set fill/draw tool for **drawing
  primitives**," never stated to include text), which research 11 §1.4
  already flagged as AMOLED-relevant for shapes, not for text. No SDK
  page states that `drawText`'s glyph ink is alpha-aware on any buffer,
  partial-alpha or not.
- Even granting the best case (it works), the mechanism only reveals
  what is *behind that offscreen buffer's own content* once the buffer is
  later blitted onto the main `Dc` with `Dc.drawBitmap` — it cannot erase
  pixels already painted directly on the screen's own `Dc`. Using it would
  mean: allocate a second, glyph-sized `ALPHA_BLENDING_PARTIAL` buffer:
  draw the N ring stamps into it, draw the interior with
  `createColor(0, 0, 0, 0)` ink to (if it works) punch a transparent hole,
  then `drawBitmap` the whole buffer onto the screen — new allocation
  machinery on top of §5.1's already-unmeasured `BufferedBitmap` route,
  gated to a fraction of the device fleet, resting on an unconfirmed
  premise.

**Verdict: mark this UNVERIFIED and do not build on it without a real
AMOLED device test** (no simulator here, root `CLAUDE.md` §3). It does not
change §8's recommendation — the interior pass stays a flat, matched-colour
paint in v1, universally (MIP and AMOLED alike), and this narrow
possibility is recorded as a labelled follow-up, not a reason to delay.

### 6.4 What the author actually sees, and what the compiler should do about it

**Since the interior pass is a flat paint and not a reveal (§6.1–6.2,
confirmed), it is pixel-identical to a plain solid glyph wherever the
element sits over nothing but a flat, matching background** — which is
exactly why §1–§5's measurements (ring vs. solid pixel counts, IoU against
a true dilation) are unaffected by any of this: they already model the
interior pass as "paint," not "reveal."

**It differs, visibly, wherever the glyph's footprint overlaps something
drawn earlier in z-order** (document order, per ADR 0004) that is *not*
the same flat colour as the interior pass names: a tick mark, a bezel
ring, another glyph, a gradient or baked-image background. The interior
pass draws through `drawText` with the *glyph's own shape* as the mask (not
a rectangle), so what the author sees is a flat-coloured patch, shaped
exactly like the letterforms, sitting on top of whatever was there —
looking like a solid cutout stamped into the earlier content, never like
the earlier content showing through. This is a real, visible authoring
trap: an `outline:` block whose interior colour was chosen to match the
*face's* background will look wrong the instant the same text is placed
over a busy tick ring or another element, and nothing before this
document said so.

**Recommendation:**

- **Document it unconditionally, in `docs/guide/text.md` alongside
  `outline:`'s own description** (§8.2 already flags the colour-matching
  open question; this is the sharper, user-facing reason it matters): "the
  interior colour paints over whatever is beneath it; it does not reveal
  it. Choose a colour that matches what will actually be underneath at
  that position, not just the face's background."
- **A scoped, buildable advisory lint is plausible, not merely
  hand-waved.** The layout resolver already computes every element's
  resolved ink box and the face's draw order (the same facts
  `check_off_screen`/`check_partial_update_budget`/`check_text_fit`
  already use, `wfb/layout.py`/`wfb/lint.py`). A `text-outline-interior`
  lint could fire when an `outline:` element's own box overlaps an
  **earlier-drawn** element's box (ordinary z-order overlap detection,
  already available) — a real, useful check that needs no new platform
  fact, only existing IR data read differently. It cannot, in general,
  know whether the interior colour *actually* matches what is under the
  overlap (that would mean rendering and diffing pixels, which is what
  `wfb preview`, not `wfb lint`, is for) — so the lint's honest scope is
  "this element overlaps another one earlier in z-order; check the
  interior colour by eye," an existence check, not a correctness
  check, in the same spirit as this project's other "estimate"/"advisory"
  confidence lints (ADR 0008). **Not designed further here** — this is a
  plan-14-adjacent follow-up once `outline:` itself exists to lint about,
  flagged as a real, scoped option rather than left as pure prose.

## 7. Preview parity

`wfb/preview.py` draws every text kind through one of three shared
methods, each already used by both a standalone `text` element and a
pattern's `shape: text` part (never a second, drifting implementation per
caller — the module's own repeated framing, e.g. `_draw_text`'s docstring:
"the one place either kind of element actually puts ink down"):

- `_draw_text` → `_blit_bitmap_text` (baked sheet) or `_approximate_text`
  (system font), `wfb/preview.py:1067-1186`;
- `_draw_vector_text` → `_approximate_text` (upright), or
  `_paste_rotated_run`/`_draw_radial_vector_text` (`curve:`),
  `wfb/preview.py:1238-1431`.

A stamped ring's preview needs no new drawing primitive: it is **the same
call, made N+1 times with the resolved offsets, in the ring colour then
the fill colour** — exactly how the generated Monkey C would do it
(§4.3's loop form). Concretely, whichever of `_draw_text`/
`_draw_vector_text` an element already resolves to would be wrapped in a
loop over the same offset table the codegen emits (§6 below proposes this
table live in the IR, computed once, shared by both backends — the same
"one shared source of truth" shape `wfb.layout`/`wfb.preview` already keep
for every other rendering fact, e.g. `alignment_shift`, cited repeatedly
throughout `preview.py`'s own docstrings as the reason the preview and the
device cannot silently disagree). The one piece that is not "loop the
existing call": anti-aliased compositing (§3.3) — Pillow's own text
drawing *does* alpha-blend correctly (unlike the device under constraint
10), so a preview that wants to show the device's harder, MIP-dithered
edge rather than a smooth Pillow blend would need to draw into an `"L"`
(single-channel) buffer with `max()` compositing, the same model §3.3's
probe used, rather than Pillow's default `RGBA` paste — a small, scoped
change, not a new rendering path.

## 8. Recommendation for the format

**Not implemented. Proposal only, for the user to weigh in on (root
`CLAUDE.md` §7: a format-shape decision needs options, tradeoffs and a
recommendation, then a wait for sign-off — this section is that
proposal.) Superseded in shape, not in substance, by `docs/plans/
15-text-outline.md`: every recommendation below was carried into that
plan, and §8.2's five open questions were each resolved there (D1–D5 in
its own "Decisions" section), so that plan is the current, citable
design — this section is left as-is as the record of what was proposed
before those decisions were made.**

### 8.1 Shape

An `outline:` key, sibling to `color:`, on a `text` element and on a
pattern's own `shape: text` part — matching plan 14's own `aod:`
allowlist shape (`color`, `font`, `format` for `text`; §2.3), and directly
usable as an `aod:` override value, which is the concrete use case that
motivated this whole investigation (research 13 §5's closing line: "If
plan 14 (`aod:`) wants outlined digits, this is the one to model.").

```yaml
outline: none                      # default -- today's plain fill, no change
outline:
  color: palette.text_outline      # required -- the ring colour, same grammar as color:
  width: 2                         # px, 1-3 recommended by S1; default 2 (matches Garmin's own engine, S2)
  offsets: disc-perimeter          # optional escape hatch -- square8 | cross4 | disc-perimeter | disc-filled; default disc-perimeter
```

`outline:` deliberately adds no second colour for the centre: the element's
own existing `color:` already names the interior/fill pass (§6 below spells
out exactly what that pass does, and why it is a paint, not a reveal), drawn
last, on top of the N ring stamps — no new key duplicates what `color:`
already means. As an `aod:` override (plan 14 §2.1's own allowlist syntax),
the *hollow* look is `color:` set to match the background (so the interior
reads as empty) with `outline.color` carrying the visible ring:

```yaml
- id: clock
  type: text
  value: time.clock
  color: palette.text
  aod:
    color: palette.background        # interior pass -- reads as empty against a flat background
    outline: {color: "#555555", width: 1}   # ring -- what actually reads as the digit
```

### 8.2 Open questions for the user, not resolved here

1. **`color: background` — there is no `background` colour role in this
   format today.** `docs/guide/colors.md` and the schema have no
   "background" keyword; a face's background is an ordinary `shape:
   rectangle` element with whatever `color:` the author gave it
   (`docs/guide/shapes.md`, the `background` example id). So "hollow, the
   interior reads as the background" cannot be spelled `color: background`
   without either (a) introducing a real background-colour role the
   layout tracks (a bigger, separate format change — plausibly worth it
   independent of this feature, since "what colour is underneath this
   element" would also help a future transparency feature, and is
   directly the question §6 below answers "no" to at the platform level),
   or (b) asking the author to repeat their own background colour
   literally/by palette reference, which silently drifts if the
   background changes and the `outline:`/`color:` pair does not.
   **Recommend (b) for v1** (no new colour-role machinery; `color:`'s
   existing grammar already lets an author write `color: palette.background`
   if they already keep their background in the palette, which
   `examples/*/face.yaml` conventionally do) **with the open question
   flagged rather than silently decided.** §6 below adds a sharper reason
   this matters: the interior pass is a flat paint, not a see-through
   hole, so getting this colour wrong is visibly wrong, not just
   suboptimal.
2. **Default `width`.** §1 recommends r=2 as the one directly evidenced
   against Garmin's own engine (§2); 1 or 3 are both plausible defaults
   too (thinner reads as more "AOD guideline" thin-font-like; thicker
   reads as more legible from a distance). No usability testing exists
   either way — this is a product call, not a technical one.
3. **`offsets:` as an author-facing escape hatch, or an implementation
   detail the compiler always resolves to `disc-perimeter`?** §1
   recommends `disc-perimeter` unconditionally on the evidence gathered;
   exposing `square8`/`cross4` adds an author-facing failure mode (§1, §3
   show both have a real quality cost) for no benefit this research
   found. **Recommend: no `offsets:` key in v1**, `disc-perimeter` always,
   revisit only if a real design needs a cheaper draw count badly enough
   to trade the quality (unlikely given §4.3's own numbers: the
   difference between `cross4` and `disc-perimeter` at r=2 is 4 draws,
   ~100 B).
4. **Interaction with `antialias:`.** `text` does not have `antialias:`
   today (§3.3); `outline:` should not silently add one. **Recommend:
   `outline:` always stamps whatever the font already is** (baked font's
   own resource `antialias:`, unaffected), with §3.3's finding — stamping
   an anti-aliased font hardens and thickens it further, and dithers
   harder on MIP — stated as guidance in `docs/guide/text.md`, not
   enforced by a lint. A `text-outline-antialias` advisory lint (parallel
   to the existing `antialias-dither`, `wfb/lint.py`) is a plausible
   follow-up once `outline:` exists to lint about.
5. **Should `outline:` reach `hands`/`icon` text-shaped parts, or stay
   `text`-and-pattern-text-part only?** Plan 14 §5.1 already flags
   list-shaped styling (`hands`/`pattern` parts) as a hard case for
   uniform overrides; this proposal deliberately scopes `outline:` to
   exactly the two places research 13 and this document analysed
   (`text` element, pattern `shape: text` part) and leaves the
   hands/pattern-wide question to whoever builds plan 14, since it is
   plan 14's own scoping problem, not a new one this feature introduces.

### 8.3 What is *not* proposed

- **No new `dim:`-style luminance machinery.** Plan 14 §4.5 already owns
  that; `outline:`'s job is shape (hollow vs. solid), not colour scaling.
- **No change to `curve:`'s own schema.** §3.2 establishes that
  `outline:` composes with `curve: {style: angled|radial}` with no new
  per-style handling needed at the format level — the offset loop wraps
  whichever draw call `curve:` already selected, unchanged.
- **No claim that this closes research 13's platform question.** Research
  13 §4 ("is real firmware different from the simulator") is untouched by
  anything here; this document is entirely about the workaround, not
  about whether Garmin might one day ship the real switch.

---

## Sources

- `$CIQ_SDK/doc/Toybox/Graphics/Dc.html`: `drawText`, `drawAngledText`,
  `drawRadialText` signatures (§3.2), `createBufferedBitmap`'s `:palette`/
  `:alphaBlending` options (§5.1); `drawText`'s full discussion and
  `Throws Graphics.InvalidPaletteException` clause, `setBlendMode`'s
  "only supported while drawing bitmaps" note, `setColor`/`setFill`/
  `setStroke`/`createColor` parameter text (§6)
- `$CIQ_SDK/doc/Toybox/Graphics.html`: `Graphics.BlendMode` enum table
  (four values, two GPU-only) and `Graphics.AlphaBlending` enum
  (`ALPHA_BLENDING_PARTIAL`'s own "fully opaque or fully transparent"
  consistency note), `ColorType`/`ColorValue` named types, `COLOR_TRANSPARENT`
  (§6)
- `$CIQ_SDK/doc/docs/Core_Topics/Resources.html`: bitmap `disableTransparency`
  (§5.1)
- `$CIQ_SDK/samples/Analog/source/AnalogView.mc` (the official second-buffer
  workaround for an anti-aliased font on a paletted `BufferedBitmap`, and
  its `:palette` array — no `COLOR_TRANSPARENT` entry, §6.2),
  `$CIQ_SDK/samples/MO2Display/source/CommandView.mc` (the one sample that
  passes `COLOR_TRANSPARENT` as `foreground`, immediately followed by
  `clear()`, §6.2)
- `docs/research/13-outline-vector-text.md` §2.1 (FreeType's 2.0px
  round-join stroke, the engine's two-pass draw), §5 (the stamped-ring
  entry this document measures and, in one line, corrects)
- `docs/research/11-always-on-display.md` §1.1–1.3 (the two numeric AOD
  rules, the FAQ's own design guidance), §3.6–3.7 (the two installed
  AMOLED devices and their resolution)
- `docs/research/00-summary.md` open question 1 (`watchdogCount`, no
  per-operation cost published)
- `docs/research/probes/antialias/README.md` §2–3 (measured antialias
  resource cost; the `setAntiAlias`-naming trap, unrelated here but the
  same probe)
- `docs/research/probes/pattern-cost/README.md` findings 1–4 (loop vs.
  unrolled, measured for `drawLine`/`fillPolygon` — cross-checked here for
  `drawText`)
- `docs/limitations.md` "64 colours, and everything else dithers"
- `wfb/preview.py:1067-1546` (every text-drawing path stamping would wrap)
- `wfb/emit/monkeyc/view.py:318-394` (`_emit_static_allocation`'s own
  `:palette`-omission reasoning, §5.1)
- `docs/guide/elements.md` (`antialias:`'s own applicability table,
  excluding `text`)
- `docs/plans/14-aod.md` §2.1, §2.3, §5.1 (the `aod:` override shape this
  proposal's `outline:` is designed to slot into)
- This document's own probe: `docs/research/probes/stamped-ring/`
  (`stamp_experiment.py`, `README.md`, and every PNG cited above)
