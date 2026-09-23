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

**Status: research only. Nothing is implemented.** Every behavioural claim
is marked **VERIFIED** or **UNVERIFIED**, per `docs/CLAUDE.md`. Here
"VERIFIED" means one of:

- measured host-side, on frames from `wfb.preview.render` (the renderer
  that `wfb preview --aod` and the `aod-burn-in` lint use), at `fenix847mm`
  resolution;
- read from the SDK or the device files.

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
0.6`), 60 minutes:

| Treatment | Peak lit px | Peak luminance | Longest lit run | Lit pixels with a run > 3 min |
|---|---|---|---|---|
| nothing | 5.44% | 0.43% | 60 min | **78.3%** |
| `jitter: 3` (shipped) | 5.44% | 0.43% | 60 min | **31.8%** |
| rotated 2×2, 50% (example 1) | 2.72% | 0.21% | 2 min | 0% |
| checkerboard, 2 phases, 50% | 2.71% | 0.21% | 1 min | 0% |
| brick 2×4, 25% (example 2) | 1.36% | 0.11% | 1 min | 0% |
| queen-5, k=1 (20%) | 1.09% | 0.09% | 1 min | 0% |
| queen-5, k=2 (40%) | 2.17% | 0.17% | 2 min | 0% |
| queen-5, k=3 (60%) | 3.27% | 0.26% | 3 min | 0% |

The "queen-5" family is defined in §4. Jitter's residual 31.8% is the
digits' interiors. The shipped heatmap for the same face already showed a
100% max persistence (plan 14 slice 5 report), and these numbers are
consistent with it.

**`examples/showcase`** with `aod: {default: show, dim: 0.4}` on
`fenix847mm` (the plan-14 D2 measurement copy), 30 minutes:

| Treatment | Peak lit px | Peak luminance | Lit pixels with a run > 3 min |
|---|---|---|---|
| nothing | **25.4%** (fails the Venu rule) | 1.33% | 92.6% |
| any 50% mask | 12.7–12.8% (still fails) | 0.67% | 0% |
| any 25% mask | **6.35% (passes)** | 0.34% | 0% |

So a 25% mask brings the busiest example face under both 10% rules with
its whole design shown. No combination of `dim:` and jitter can do that
for the pixel-count rule.

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
| queen-5, k lit phases | ≈k/5 | ≈k/5 | ≈k/5 | ≈k/5, never vanishes (measured minimum 19%/38%/58% for k = 1/2/3 on a 48 px line) |

"Vanishes" means some alignment of the line is entirely black for a whole
minute: a tick mark or hand edge that blinks out. The example 1 rotation
puts every pixel through lit-lit-off-off (a longest run of 2, which is
good), but a 1 px horizontal line on an off row is gone for that minute.

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

---

## 6. Compared with jitter and `dim:`

| | `jitter:` (shipped) | `dim:` (shipped) | Pixel mask (M2, queen-5 k=2) |
|---|---|---|---|
| 3-minute rule (original Venu) | not guaranteed; 31.8% of the example's lit pixels still fail | no effect | **guaranteed for any image**; longest run = k |
| Pixel-count rule (original Venu) | no effect | no effect | ×duty (showcase 25.4% → 6.35% at 25%, measured; ≈10.2% at 40%, derived from the measured retention) |
| Luminance rule (Venu 2+, fēnix 8/9) | no effect | ×≈dim^2.2 in linear light | ×duty; stacks with `dim` |
| Differential wear (real burn-in) | blurs edges over ±N px; interiors unchanged | lowers the wear rate everywhere | lowers the wear rate everywhere; no edge blur |
| Image fidelity | exact image, moved ≤4 px | exact image, darker | textured; 1 px lines keep k/5 of their pixels |
| Generated code | offsets on every coordinate of every jittered element: +338 B for 3 elements on the example, growing with element count | per-colour constants or `WfbColor.dim` calls | constant: one bitmap, one draw call, one phase computation, whatever the element count |
| Per-frame work | ~0: a few integer ops | ~0 | one full-screen blit (**UNVERIFIED** cost) plus one-time construction |
| Display power | unchanged | lower | lower, ∝ lit pixels × brightness (**UNVERIFIED** magnitude) |
| Preview and lint | exact (implemented) | exact | exact and cheap: apply the same mask host-side |

On the user's hypothesis:

- **"100% pass on the 3-minute rule regardless of the image":** **true,
  by construction** for any mask with k ≤ 3 consecutive lit phases.
  Measured at 0% violations on both faces, against 31.8% (example) and
  92.6% (showcase) without it. The caveat is §1: that rule is enforced
  only on original-Venu-class devices. On the fēnix 8/9 the mask's
  enforceable benefit is the luminance cut, which `dim:` already offers
  at full fidelity.
- **"Less computationally intense":** **half true.**
  - It is simpler and smaller in code: O(1), with no change to any
    emitter or to layout constants, where jitter touched every emitter
    and grows with the element count.
  - Per frame it does more pixel work (one full-screen blit) than
    jitter's handful of additions. At one frame a minute that is very
    likely negligible, especially against the display power it saves.
    That is **UNVERIFIED** until measured.

---

## 7. Assessment and what a plan would need

1. **Worth building as an opt-in AOD treatment, not as a jitter
   replacement.** It fixes exactly what jitter and `dim` cannot: the
   pixel-count rule and a hard 3-minute guarantee. Jitter keeps a role in
   softening the edges of real differential wear, and the two compose
   because the mask lives in screen coordinates.
2. **Pattern:** queen-5, because no 1 px line in any direction ever
   vanishes. Duty k/5 with k ∈ {1, 2, 3}, and a recommended default of
   k = 2 (40%). Offer the checkerboard (50%) as an alternative only if
   the device test shows queen-5's grain is visible. Reject stripes
   (example 1) and the brick (example 2) for the vanishing-line cases in
   §4.
3. **A format sketch, not a decision:** `aod: {mask: 40%}`, face level
   only, since a mask per element would let neighbouring elements sit at
   different duties. Accept exactly 20/40/60%, or `mask: {duty: 2/5}`.
   The burn-in lint and the preview apply the same mask. The lint's lit
   and luminance figures become the masked ones, computed exactly.
4. **Gate:** AMOLED only (plan 14 D1 and D5), and per device on
   `alphaBlendingSupport` plus `Graphics.createBufferedBitmap` (constraint
   6e: runtime `has` guard).
5. **A probe before any plan** (`docs/research/probes/`), in this order:
   - a Monkey C build of M2 on `fenix847mm`: tile, doubling, one blit per
     minute, warning-free, with `--build-stats` and the graphics-pool
     size;
   - the user runs it in the host simulator's Screen Heat Map (research
     11 §1.5), which should show no pixel above 40% on-time;
   - on the watch: is the grain visible, is there moiré, is the phase
     change visible?

   Only the first step can happen in this sandbox.

---

## 8. Open questions

- Transparent `BufferedBitmap` compositing over the watch-face `Dc` on
  the fēnix 8 AMOLED, and its memory format. (M2)
- The cost of one full-screen blit in the AOD frame, and whether the AOD
  update has an execution budget. The FAQ states none that was found.
- Subpixel layout, moiré, and whether the minute-to-minute phase change
  is visible.
- Whether Garmin's heat-map tool (and any on-device enforcement) treats
  "3 minutes" as more than 3 consecutive one-minute frames. That is how
  this document and the jitter test read it; the FAQ says "longer than 3
  minutes".
