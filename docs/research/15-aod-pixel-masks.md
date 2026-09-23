# 15 — Pixel-pattern masks for the AOD frame, compared with jitter

**Question.** The idea under test is to leave the AOD image where it is and
light only a rotating subset of its pixels each minute. Could that replace
or complement `jitter:` (plan 14 slice 5), and does it pass Garmin's
3-minute rule by construction, whatever the face draws? It could stack
with `dim:`. The user's two examples:

- **Example 1:** the 2×2 tile `((1,0),(1,0))`, rotated 90° each minute, so
  it cycles through 4 phases.
- **Example 2:** the 2×4 tile `((1,0,0,0),(0,0,1,0))`, a sparser and less
  stripe-like variant with a stable average luminance.

**Status: this research fed plan 16, which is built** (`aod: {mask: ...}`,
slice 1 `3c2b40d`, slice 2 `965518a`). §7 records the decision and why it
departed from this document's own §7 recommendation (queen-5, opt-in). The
comparison and line-vanishing tables below (§3, §4, §6) were remeasured on
2026-09-23 alongside the shipped pattern, so figures differ slightly from
earlier drafts of this document; the methodology and every other pattern
are unchanged. Every behavioural claim is marked **VERIFIED** or
**UNVERIFIED**, per `docs/CLAUDE.md`. Here "VERIFIED" means one of:

- measured host-side, on frames from `wfb.preview.render` (the renderer
  that `wfb preview --aod` and the `aod-burn-in` lint use), at `fenix847mm`
  resolution;
- read from the SDK or the device files.

`jitter:` rows below are kept as data, labelled "(removed 2026-09-23)" --
plan 14 slice 5 shipped `aod: {jitter: ...}` and it was removed the same
day the mask shipped (`d20b633`), so it can no longer be remeasured; its
figures are the ones originally recorded.

Nothing was run on a watch or in the simulator (root `CLAUDE.md` §3). The
probe is `docs/research/probes/aod-pixel-masks/`.

---

## 1. Which rule a mask would be satisfying

From `$CIQ_SDK/doc/docs/Connect_IQ_FAQ/How_Do_I_Make_a_Watch_Face_for_AMOLED_Products.html`,
restated in research 11 §1.2 (**VERIFIED**, read):

| Generation | Enforced rule |
|---|---|
| Original Venu | ≤10% of pixels on, **and** no pixel on for longer than 3 minutes |
| Venu 2 and later | <10% of the screen's **luminance** |

Two consequences shape everything below:

1. **The 3-minute rule is enforced only on original-Venu-class devices.**
   The fēnix 8/9 AMOLED devices are later than the Venu 2, so the only
   enforced rule there is luminance. The device files do not say which
   generation a device belongs to (plan 14 slice 4's finding, recorded in
   `docs/guide/lints.md` `aod-burn-in`), so a design has to be safe under
   both rules.
2. **Real burn-in is differential cumulative wear**, not a rule. An OLED
   subpixel ages roughly with the current it has carried over its life.
   Burn-in shows where one region has aged more than its neighbours.
   Garmin's rules are proxies for that; neither of them *is* it. This is
   general OLED knowledge, not something this project measured
   (**UNVERIFIED** here).

"Lit" means any colour other than pure black (FAQ, research 11 §1.1). A
mask pixel is therefore either free or costed; there is nothing in
between.

---

## 2. What a mask does, by construction

Let the mask cycle through P phases, one per minute, with each pixel lit
in k of them, consecutively. Then, **for any image**:

- **No pixel is lit for more than k consecutive minutes.** This is a
  property of the mask alone, in screen coordinates, so no image content
  can break it. With k ≤ 3 the 3-minute rule holds by construction.
  **VERIFIED** (§3, `longest_run`).
- **The lit-pixel fraction and the luminance both scale by the duty
  k/P**, up to aliasing on features smaller than the tile. Measured
  retention was within ±0.1% of the duty in every run (**VERIFIED**, §3).
  That is the one thing `dim:` cannot do: `dim` darkens pixels but never
  turns one black, so it never lowers the lit-pixel count (plan 14 §7 D2
  data).
- **The duty is exact on average for every tile, every minute**, so a
  large uniform area has constant average luminance. That is the "stable
  average luminance" property of example 2. It holds for every pattern
  below.

Jitter has neither guarantee. It moves the image by ≤4 px, so any feature
thicker than about twice the jitter range keeps an interior that is lit
every minute.

---

## 3. Measurements

Probe: `sim.py`. Frames were rendered minute by minute from 10:00, so the
clock digits change as they would on the watch. Fractions are inside the
round display mask.

**`examples/features/aod/face.yaml`** (clock, battery ring, dot; `dim:
0.6`), 60 minutes, remeasured 2026-09-23 alongside the shipped pattern
(`docs/research/probes/aod-pixel-masks/aod_nojitter.yaml`, this face
without `jitter:`):

| Treatment | Peak lit px | Peak luminance | Longest lit run | Lit pixels with a run > 3 min |
|---|---|---|---|---|
| nothing | 3.69% | 0.27% | 60 min | **81.3%** |
| `jitter: 3` (removed 2026-09-23) | 5.44% | 0.43% | 60 min | **31.8%** |
| rotated 2×2, 50% (example 1) | 1.87% | 0.14% | 2 min | 0% |
| checkerboard, 2 phases, 50% | 1.84% | 0.14% | 1 min | 0% |
| brick 2×4, 25% (example 2) | 0.92% | 0.068% | 1 min | 0% |
| **moving 2×2, 25% (shipped, plan 16)** | **0.93%** | **0.069%** | **1 min** | **0%** |
| queen-5, k=1 (20%) | 0.74% | 0.055% | 1 min | 0% |
| queen-5, k=2 (40%) | 1.48% | 0.11% | 2 min | 0% |
| queen-5, k=3 (60%) | 2.22% | 0.17% | 3 min | 0% |

The "queen-5" family is defined in §4. The `jitter:` row is the one figure
in this table that could not be remeasured (§ status note above): it is
kept from the original run, which measured a design that still carried
`jitter: 3` and so used a different `nothing` baseline (5.44%/0.43%) than
today's 3.69%/0.27%. Both are real measurements of the same fixture at
different times; the drift is the example's own restyling in the plan 14
slices between the two runs plus `d20b633`'s preview-pipeline unification,
not anything mask-related, and every non-jitter row above was remeasured
together in one run so the ratios between them (all ≈duty, per §2) are
internally consistent. The shipped pattern lands within noise of the other
25%-duty patterns, as §2's by-construction guarantee predicts.

**`examples/showcase`** with `aod: {default: show, dim: 0.4}` on
`fenix847mm` (the plan-14 D2 measurement copy), 30 minutes, also
remeasured 2026-09-23 (unchanged from the original run within rounding):

| Treatment | Peak lit px | Peak luminance | Lit pixels with a run > 3 min |
|---|---|---|---|
| nothing | **25.4%** (fails the Venu rule) | 1.33% | 92.6% |
| any 50% mask | 12.7–12.8% (still fails) | 0.67% | 0% |
| any 25% mask, incl. shipped (6.50% / 0.34%) | **6.35–6.50% (passes)** | 0.34% | 0% |

So a 25% mask brings the busiest example face under both 10% rules with
its whole design shown -- including the shipped pattern, which measures in
the same bucket as the others. No combination of `dim:` and jitter can do
that for the pixel-count rule.

---

## 4. The catch, and the queen-5 family: thin lines

A periodic mask aliases with any feature narrower than its tile. The worst
case is a 1 px line, the typical AOD tick mark or thin-font stroke.
`lines.py` tests 1 px horizontal, vertical, 45° and anti-diagonal lines
at every alignment against every phase (**VERIFIED**):

| Mask | Horizontal | Vertical | 45° | Anti-diagonal |
|---|---|---|---|---|
| rotated 2×2 (ex. 1) | **vanishes** in some minutes | **vanishes** | 50% | 50% |
| checkerboard | 50% | 50% | **vanishes** | **vanishes** |
| brick 2×4 (ex. 2) | 25% | **vanishes** | 25% | 25% |
| **moving 2×2, single pixel (shipped, plan 16)** | **vanishes** | **vanishes** | **vanishes** | **vanishes** |
| queen-5, k lit phases | ≈k/5 | ≈k/5 | ≈k/5 | ≈k/5, never vanishes (measured minimum 19%/38%/58% for k = 1/2/3 on a 48 px line) |

"Vanishes" means some alignment of the line is entirely black for a whole
minute: a tick mark or hand edge that blinks out. The example 1 rotation
puts every pixel through lit-lit-off-off (a longest run of 2, which is
good), but a 1 px horizontal line on an off row is gone for that minute.
The shipped pattern is the worst case in this table by this one measure:
because only one of its 2×2 tile's four pixels is ever lit (never two, as
in the rotated tile), a 1 px line aligned with the tile vanishes in
**every** orientation, not just horizontal/vertical, in half of the
(alignment, minute) combinations `lines.py` tries. **This is a deliberate,
accepted tradeoff (plan 16 D1), not an oversight**: see §7.

**Queen-5.** Light pixel (x, y) in phase t when
`(x − 2y − t) mod 5 ∈ {0, …, k−1}`. The single-residue set
`{x − 2y ≡ c}` meets every row, every column and both diagonals of each
5×5 tile exactly once, because 2, 1, −1 and 3 are all invertible mod 5.
It is the toroidal 5-queens solution, which exists for n = 5 and not for
n = 2 or 4 (gcd(n, 6) = 1). Its properties:

- A 1 px line in any of the four directions keeps exactly k/5 of its
  pixels every minute.
- The phases are pure translations, so a single oversized overlay bitmap
  drawn at a per-minute offset produces all of them (§5).
- The longest lit run is k minutes.

Practical choices are k = 1 (20%), 2 (40%) and 3 (60%, a longest run of
exactly 3, which is the rule's edge).

**Visual cost** (`docs/research/data/aod-pixel-masks.png`, the clock at
3× zoom):

- **Stripes** (example 1) read as a hatching texture.
- **Checkerboard and queen-5** read as an even, dimmer fill with a faint
  diagonal grain.

At the real density the grain may be hard to see. The fēnix 8 47 mm has a
454 px round panel about 35.6 mm across, so the pixel pitch is about
0.078 mm (from `compiler.json` resolution and the published size). The
lattice spacing is √2 px, about 0.11 mm, for the checkerboard and √5 px,
about 0.175 mm, for queen-5. At a 35 cm reading distance those are about
1.1 and 1.7 arcminutes, close to the ~1 arcminute acuity limit. So the
checkerboard should look like plain dimming and queen-5 like a very fine
grain. **UNVERIFIED**: this is an estimate. Two unknowns remain:

- the panel's subpixel layout (a diamond/PenTile arrangement could turn a
  1 px pattern into colour fringing or moiré);
- whether the once-a-minute phase change is visible as a "crawl".

Both need eyes on a real watch.

---

## 5. Can the device draw it? Implementation routes

There is no pixel write in Monkey C beyond `Dc.drawPoint`, and 40–60% of
a 454 px disc is roughly 70,000 points a minute, which is not an option.
The candidate routes, with their symbols checked in `bin/api.debug.xml`
and in `fenix847mm`/`fenix947mm` `*.api.debug.xml` (**VERIFIED present**
on both, as is `alphaBlendingSupport: true` in their `compiler.json`):

**M1 — black primitives over the finished frame.** Stripes are about 227
`drawLine` calls on a 454 px screen. A checkerboard's black half is 45°
lines, about 450 of them. Queen-5 is *not* line-drawable: each residue
class steps two pixels in x per row, which no Bresenham line reproduces.
This route also needs antialiasing off and exact 45° rasterisation.
**UNVERIFIED.**

**M2 — one overlay bitmap with alpha, recommended.** This is a
`BufferedBitmap`, or a bitmap resource baked at build time. It is
opaque black where the mask is off and transparent where it is on. It
measures (W + P) × (H + P) and is drawn once per AOD frame at offset
`(−(t mod P), 0)`, after everything else. Every pattern above is a pure
translation between phases except the example-1 rotation, which would
need two bitmaps. So one bitmap covers all P phases.
- **Runtime construction** is cheap: draw one tile, then double it by
  blitting the bitmap into itself, about 2·log₂(460/P) blits.
- **Alpha on AMOLED:** `alphaBlendingSupport` is true there. The default
  blend (`BLEND_MODE_SOURCE_OVER`, API 4.2.1; `BLEND_MODE_DEFAULT` alias
  4.0.0, `Toybox/Graphics.html`) should composite the transparent holes.
  **UNVERIFIED** until a probe builds and runs it.
- **Unknowns:** memory in the 1 MB graphics pool (constraint 11) depends
  on the bitmap's colour format and is **UNVERIFIED**. So is the cost of
  one full-screen blit per minute.

**M3 — `BLEND_MODE_MULTIPLY` with a black/white bitmap.** It has the same
shape as M2 without needing an alpha channel. `Toybox/Graphics.html`
marks MULTIPLY "Only supported on devices with GPU". The symbol is
present on the fēnix 8, but constraint 6b says presence does not prove
support, so this is **UNVERIFIED** and a fallback at best.

**M4 — `BitmapTexture` as the fill or stroke tool.** `Dc.setFill` and
`Dc.setStroke` take a `BitmapTexture` (API 4.0.0), with a `setOffset`
that could step the phase. But:
- Texture pixels carry their own colour, so every distinct AOD colour
  needs its own texture.
- The docs scope it to "primitive" draws. Whether `drawText`,
  `drawAngledText` or `drawRadialText` honour it is **UNVERIFIED**, and
  text is most of a typical AOD frame.

It is rejected unless a probe shows text honours it.

**Built instead: a fifth route, simpler than all four above, for the
pattern actually shipped.** §7's chosen pattern -- one lit pixel per 2×2
tile, moving by one 4-neighbour step each minute -- has a black set that is
exactly every other row **union** every other column, so it is two loops of
1 px `Dc.fillRectangle` strips (`runtime-lib/WfbAodMask.mc`), about
`(w + h) / 2` calls (454 on a 454 px panel), needing no bitmap, no alpha,
no `BufferedBitmap` and no graphics-pool memory at all -- it runs on every
device, not just the two with `alphaBlendingSupport`. M1's row/column
argument above didn't apply to it because M1 was evaluated against
queen-5's diagonal residue classes, which are not axis-aligned; this
pattern's tile is. See §7 for why this pattern, not queen-5, is what
shipped.

---

## 6. Compared with jitter and `dim:`

| | `jitter:` (removed 2026-09-23) | `dim:` (shipped) | Pixel mask (shipped, plan 16: moving 2×2, 25%) |
|---|---|---|---|
| 3-minute rule (original Venu) | not guaranteed; 31.8% of the example's lit pixels still fail | no effect | **guaranteed for any image**; longest run = 1 min |
| Pixel-count rule (original Venu) | no effect | no effect | ×¼ (showcase 25.4% → 6.50%, measured) |
| Luminance rule (Venu 2+, fēnix 8/9) | no effect | ×≈dim^2.2 in linear light | ×¼; stacks with `dim` (measured example lit-fraction: `aod-burn-in` 4.0% → 1.0%, luminance 0.3% → 0.1%) |
| Differential wear (real burn-in) | blurs edges over ±N px; interiors unchanged | lowers the wear rate everywhere | lowers the wear rate everywhere; no edge blur |
| Image fidelity | exact image, moved ≤4 px | exact image, darker | textured; a 1 px line vanishes in half of (alignment, minute) pairs (§4) -- accepted, not fixed, since AMOLED panels are high-DPI (plan 16 D1) |
| Generated code | offsets on every coordinate of every jittered element: +338 B for 3 elements on the example, growing with element count | per-colour constants or `WfbColor.dim` calls | constant: one barrel call (`WfbAodMask.apply`), whatever the element count -- +279 B on the example (2,447 B → 2,726 B on `fenix847mm`) |
| Device route | offset arguments threaded through every emitter | per-colour constants, computed at build time | two loops of 1 px `Dc.fillRectangle` strips, ~454 calls/minute on a 454 px panel -- no bitmap, no alpha, no graphics-pool memory (§5) |
| Per-frame work | ~0: a few integer ops | ~0 | ~454 `fillRectangle` calls a minute (**UNVERIFIED** watchdog/per-frame cost, plan 16 §3) |
| Display power | unchanged | lower | lower, ∝ lit pixels × brightness (**UNVERIFIED** magnitude) |
| Preview and lint | exact (implemented) | exact | exact and cheap: `wfb.aod_mask.apply` host-side, the same phase table as the device (`wfb.preview.render`, `aod-burn-in`) |

On the user's hypothesis:

- **"100% pass on the 3-minute rule regardless of the image":** **true,
  by construction**, verified for the shipped pattern (longest run = 1
  minute, measured 0% violations on both example faces, against 31.8%
  (example, with jitter) and 92.6% (showcase, with nothing) without a
  mask). The caveat is §1: that rule is enforced only on
  original-Venu-class devices. On the fēnix 8/9 the mask's enforceable
  benefit is the luminance cut, which `dim:` already offers at full
  fidelity but cannot combine with a hard 3-minute guarantee the way the
  mask does.
- **"Less computationally intense":** **half true**, and now measured on
  the device side too (plan 16 slice 1's real `monkeyc` build, warning-free
  on all four targets):
  - It is simpler and smaller in code: O(1), with no change to any
    emitter or to layout constants, where jitter touched every emitter
    and grows with the element count. The shipped device route (§5) needs
    no `BufferedBitmap`, no alpha and no graphics-pool memory -- simpler
    than every route this document originally proposed (M1-M4).
  - Per frame it does more pixel work (~454 `fillRectangle` calls) than
    jitter's handful of additions. At one frame a minute that is very
    likely negligible, especially against the display power it saves, but
    the watchdog budget and the real per-frame cost are still
    **UNVERIFIED** -- the user checks these on the watch and in the host
    simulator's Screen Heat Map (§7, plan 16 §6).

---

## 7. Decision (2026-09-23) and what shipped

This section originally recommended queen-5 at k=2 (40%), opt-in, drawn as
an M2 overlay bitmap. **The user decided differently on all three points,
recorded as plan 16 §1 D1/D2 and built as plan 16 (slice 1 `3c2b40d`, slice
2 `965518a`):**

1. **Pattern: the 2×2 tile `((1,0),(0,0))`, not queen-5.** One pixel per
   2×2 tile is lit and the other three are forced black, stepping
   `(0,0) → (1,0) → (1,1) → (0,1)` with the clock minute mod 4 (§2's own
   4-neighbour argument, unchanged). Duty is a fixed 25%, not queen-5's
   tunable k/5. **This document's own §4 finding stands**: a 1 px line
   aligned with the tile vanishes for a whole minute, in every one of the
   four orientations tested (worse than the rotated-2×2 example, which
   only loses horizontal/vertical) -- queen-5 was specifically recommended
   above to avoid exactly this. **The user's call, not a correction of
   this research:** fēnix 8/9-class AMOLED panels are high-DPI enough
   (§4's own arcminute estimate) that a thin line losing pixels, or
   blinking out for a minute, is not judged a real problem worth queen-5's
   extra complexity (a diagonal residue class, not axis-aligned -- see §5's
   note on why that also ruled out the M1 primitives route for queen-5).
   Queen-5 was not built.
2. **On by default, not opt-in.** `aod: {mask: false}` opts out; omitting
   `mask:` and writing `mask: true` mean the same thing (masked). This
   document's §7 (as originally written) recommended opt-in because the
   pattern was still a research proposal; ADR 0006's 2026-09-23 amendment
   records the reasoning for making it the default instead -- burn-in
   protection should not depend on the author remembering to ask for it.
3. **Device route: black `fillRectangle` strips, not an overlay bitmap.**
   This pattern's black set is the union of every other row and every
   other column (axis-aligned, unlike queen-5's diagonal residue classes),
   so M1's row/column argument -- rejected above only for queen-5 -- applies
   cleanly here: two loops of 1 px strips, no bitmap, no alpha, no
   graphics-pool memory (§5). This made M2's whole apparatus (tile
   construction, doubling, alpha compositing, the graphics-pool question)
   moot for the pattern actually shipped; none of M2-M4 were built.
4. **Format:** `aod: {mask: ...}`, face level only, a boolean rather than
   a duty -- since the pattern is fixed, there is nothing to parametrise.
   The burn-in lint and the preview apply the identical mask (`wfb.aod_mask`,
   the host-side twin of `WfbAodMask.mc`), computed exactly, matching §7's
   original format sketch's intent.
5. **Gate:** AMOLED only (plan 14 D1 and D5) -- but, because the shipped
   route needs only `Dc.fillRectangle`/`setColor`/`getWidth`/`getHeight`
   and `System.getClockTime`, all universal symbols, there is no
   `alphaBlendingSupport`/`Graphics.createBufferedBitmap` runtime gate: the
   `_aod` branch itself (already AMOLED-only) is the only guard needed.
6. **Probed and built, not merely probed:** a real `monkeyc` build of
   `examples/features/aod/face.yaml` on `fenix847mm`, warning-free, with
   `--build-stats` before (2,447 B) and after (2,726 B, +279 B) -- more of
   §5's step 1 than a probe. Steps 2-3 (the host simulator's Screen Heat
   Map, and eyes on a real watch) are still **UNVERIFIED**, for the user
   to check (plan 16 §6, `docs/limitations.md`).

---

## 8. Open questions

**Resolved by the decision in §7:** transparent `BufferedBitmap`
compositing and its memory format (M2) are moot -- the shipped route uses
neither a bitmap nor alpha (§5, §7 point 3).

**Still open, for the user to check (plan 16 §6):**

- The cost of ~454 `Dc.fillRectangle` calls a minute in the AOD frame, and
  whether the AOD update has an execution budget. The FAQ states none that
  was found.
- Subpixel layout, moiré, and whether the minute-to-minute phase change
  is visible.
- Whether Garmin's heat-map tool (and any on-device enforcement) treats
  "3 minutes" as more than 3 consecutive one-minute frames. That is how
  this document and the jitter test read it; the FAQ says "longer than 3
  minutes".
- No real AMOLED hardware, and no simulator, has run any of this
  (`docs/limitations.md` "AOD, more broadly, has no real AMOLED hardware
  behind any of it").
