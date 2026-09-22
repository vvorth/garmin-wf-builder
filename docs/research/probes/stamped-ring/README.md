# Probe: the "stamped ring" outline technique -- offset sets, FreeType's
# stroker, radial-text geometry, AA stacking, and code size

Backs `docs/research/14-stamped-ring-text.md`. Two independent measurements:

1. **`stamp_experiment.py`** -- a host-side Pillow/numpy/scipy/freetype-py
   script, no `monkeyc` involved. Renders `"12:34"` with a real TTF already
   vendored in this repo
   (`examples/features/vector-text/assets/ChivoMono-Bold.ttf`), builds a
   binary glyph mask the way `wfb/fonts/bmfont.py`'s 1-bit default would,
   and compares four offset sets against a true morphological (Euclidean
   disc) dilation, FreeType's own stroker, and a rotation sweep.
2. **A `monkeyc --build-stats` comparison**, described in §5 below (not
   committed as a project -- built from a `wfb build` output directory the
   same way `../pattern-cost/` did, and reported here rather than kept as a
   tree of generated files).

## Running the Pillow half

```sh
./.venv/bin/pip install numpy scipy freetype-py   # not in requirements.txt -- see below
./.venv/bin/python docs/research/probes/stamped-ring/stamp_experiment.py
```

Writes `results.md` (the numbers, reproduced in the tables below) and every
PNG in this directory. `numpy`, `scipy` and `freetype-py` are host-only
research deps: nothing under `wfb/` imports them, so they are deliberately
**not** added to `requirements.txt`, only installed transiently into
`.venv` for this probe (`pillow` is already a project dependency and needed
no install).

## 1. Offset-set comparison (Part 1)

Glyph mask: 288x105 px, 5,321 lit px solid, 80px `ChivoMono-Bold`.

| r | offset set | draws | missing px | extra px | ring IoU | stamped ring px | ideal ring px | ring/solid ratio |
|---|---|---|---|---|---|---|---|---|
| 1 | square8 | 8 | 0 | 229 | 0.820 | 1,275 | 1,046 | 0.240 |
| 1 | cross4 | 4 | 0 | 0 | **1.000** | 1,046 | 1,046 | 0.197 |
| 1 | disc-filled | 4 | 0 | 0 | **1.000** | 1,046 | 1,046 | 0.197 |
| 1 | disc-perimeter | 4 | 0 | 0 | **1.000** | 1,046 | 1,046 | 0.197 |
| 2 | square8 | 8 | 0 | 480 | 0.814 | 2,583 | 2,103 | 0.485 |
| 2 | cross4 | 4 | 36 | 0 | 0.983 | 2,067 | 2,103 | 0.388 |
| 2 | disc-filled | 12 | 0 | 0 | **1.000** | 2,103 | 2,103 | 0.395 |
| 2 | disc-perimeter | 8 | 0 | 0 | **1.000** | 2,103 | 2,103 | 0.395 |
| 3 | square8 | 8 | 0 | 626 | 0.839 | 3,895 | 3,269 | 0.732 |
| 3 | cross4 | 4 | 213 | 0 | 0.935 | 3,056 | 3,269 | 0.574 |
| 3 | disc-filled | 28 | 0 | 0 | **1.000** | 3,269 | 3,269 | 0.614 |
| 3 | disc-perimeter | 16 | 0 | 0 | **1.000** | 3,269 | 3,269 | 0.614 |

`disc-perimeter` (the outer integer shell, `(r-1)^2 < dx^2+dy^2 <= r^2`)
reproduces the true dilation exactly, at every r tested, with fewer draws
than `disc-filled` (4/8/16 vs 4/12/28) -- the interior offsets are
redundant for these glyph strokes, confirmed rather than assumed.
`square8` (the common 8-direction game/UI trick, offsets fixed at exactly
radius r along the compass points and diagonals) **always overshoots and
never undershoots**: 0 missing px at every r, but the diagonal offsets sit
at Euclidean distance `r*sqrt(2)`, so they round the glyph's corners
outward past the ideal disc (visible as blue in
`diag-square8-r{1,2,3}.png`). `cross4` is the opposite failure: 0 extra px,
but it misses the disc entirely on the diagonal, and the miss grows with r
(0 -> 36 -> 213 px) -- visible as faint gaps in `diag-cross4-r{2,3}.png`
where the glyph's diagonal strokes meet the ring.

**Recommendation from this table alone: `disc-perimeter`.** Exact quality
at the lowest draw count of the three exact options, and cheaper than
`square8` in both draws and correctness.

PNGs: `glyph-original.png`, `ideal-dilation-r{1,2,3}.png`,
`diag-<set>-r{1,2,3}.png` (white = glyph, green = correctly-stamped ring,
red = missing, blue = extra).

## 2. FreeType's own stroker vs. raster dilation (Part 2)

Single glyph `"2"`, 80px, `FT_Glyph_Stroke` with `FT_STROKER_LINECAP_ROUND`/
`FT_STROKER_LINEJOIN_ROUND` -- the same two primitives research 13 S2.1
found Garmin's own TTF engine calling, at the same fixed radius class:

| radius px | FT stroke ring px | raster-dilation ring px | ring IoU |
|---|---|---|---|
| 1.0 | 269 | 244 | 0.907 |
| 2.0 | 539 | 487 | 0.904 |
| 3.0 | 811 | 771 | 0.951 |

Garmin's engine uses a **fixed 2.0px round-join stroke** (research 13
S2.1) -- the r=2.0 row is the directly comparable case. FreeType's real
outline stroker and this probe's raster (Euclidean-distance) dilation
agree to IoU ~0.90-0.95; the residual is curve-fitting on round joins
versus the raster's own pixel quantisation, not a different ring width.
**This means the raster-dilation numbers in §1 are a good stand-in for
what FreeType (and by extension Garmin's engine, on the one path this
project cannot reach -- research 13) would draw**, not a different notion
of "ring". PNGs: `ft-plain-r2.png`, `ft-stroked-r2.png`,
`ft-vs-raster-r2.png`.

## 3. Rotation sweep -- the radial-text question (Part 3)

Single glyph `"1"` (one dominant straight stroke), rotated 0-90 degrees in
15-degree steps, stamped with each offset set at r=2, compared against the
true dilation of the *same rotated mask* (rotation and a continuous disc
commute, so the true-dilation baseline itself does not drift with angle --
isolating whatever the discrete offset set's own directional bias is).

| offset set | min ring IoU | max ring IoU | spread |
|---|---|---|---|
| square8 | 0.536 | 0.929 | **0.393** |
| cross4 | 0.982 | 1.000 | 0.018 |
| disc-filled | 1.000 | 1.000 | 0.000 |
| disc-perimeter | 1.000 | 1.000 | 0.000 |

`square8`'s ring quality swings by nearly 40 IoU points depending on the
glyph's own rotation -- worst at 45 degrees (`rotation-square8-45deg.png`,
visible corner overshoot), best at 0/90 (`rotation-square8-0deg.png`,
clean). `cross4` stays nearly flat here (this one glyph's stroke always
has enough axis-aligned extent for 2 of its 4 offsets to catch it -- not a
general guarantee, see the main doc's caveat). `disc-filled`/
`disc-perimeter` are exactly rotation-invariant, as a true disc structuring
element must be.

**This is the direct evidence for the radial-text claim in the main
document**: a *rigid* screen-space translation of an already-composed
raster is mathematically a valid dilation contribution regardless of what
that raster contains (see the main doc's derivation for why re-invoking
`drawRadialText` with a shifted centre is exactly such a translation) --
but a coarse, direction-limited offset set's *approximation quality*
depends on how the underlying strokes are oriented relative to the fixed
offset directions, and different glyphs around a radial dial sit at
different rotations by construction. `square8` is the one to avoid there;
`disc-perimeter`/`disc-filled` (rotation-invariant by construction) are
not.

## 4. Anti-aliased stamping (Part 4)

`"12:34"` rendered anti-aliased (no 1-bit threshold), stamped at square8
r=2 with max-compositing (the model for N opaque, non-blended draws --
`alphaBlendingSupport: false` on MIP, constraint 10, so a later stamp's
opaque pixels simply overwrite, weighted only by that stamp's own
coverage, never summed):

| | edge pixels (0<alpha<1) | mean alpha there |
|---|---|---|
| original | 663 | 0.492 |
| stamped (max-composited) | 654 | 0.515 |

Fewer fractional-alpha pixels (more of the original soft edge is pushed to
full opacity by an overlapping stamp) and a higher mean alpha among what
remains fractional -- i.e. **the edge measurably hardens and thickens, it
never softens**, consistent with opaque overlapping draws. This is a model
of the compositing rule, not an on-device observation (no simulator here,
root `CLAUDE.md` S3); mark the *magnitude* UNVERIFIED against real
hardware, the *direction* (harder, not softer) as the only physically
possible outcome of overlapping opaque single-colour draws under
`alphaBlendingSupport: false`.

The 64-colour MIP angle (each channel quantised to `0x00`/`0x55`/`0xAA`/
`0xFF`, `docs/limitations.md` "64 colours, and everything else dithers")
is not re-derived here -- it is already measured in
`../antialias/README.md` S2 (antialiasing a font at all trades size for a
continuous grey ramp that then dithers on a 64-colour panel) and cited,
not repeated.

## 5. Code size: loop vs. unrolled, with a real `drawText` (`monkeyc --build-stats`)

Base project: `wfb build examples/features/vector-text/face.yaml -d
fenix8solar47mm`, `drawClock`'s body modified in place (baseline vs. two
alternative bodies), built with `$CIQ_SDK/bin/monkeyc -f monkey.jungle -d
fenix8solar47mm -y ~/ciq/developer_key.der -w -l 3 --build-stats 0`, SDK
9.2.0, 2026-09-22. All three (baseline, unrolled, loop) at N=8 and N=16
build **BUILD SUCCESSFUL, warning-free**.

| variant | N | data | code | foreground total | delta over baseline | Total PRG |
|---|---|---|---|---|---|---|
| baseline (1 `drawText`) | -- | 904 | 1,832 | 2,736 | -- | 97,004 B |
| unrolled (N ring + 1 fill `drawText`) | 8 | 904 | 2,061 | 2,965 | **+229 B** | 97,436 B |
| loop (flat offsets array + 1 `drawText` in the loop + 1 fill) | 8 | 1,012 | 1,933 | 2,945 | **+209 B** | 97,388 B |
| unrolled | 16 | 904 | 2,277 | 3,181 | **+445 B** | 97,788 B |
| loop | 16 | 1,092 | 1,933 | 3,025 | **+289 B** | 97,468 B |

The loop's **code is flat at 1,933 B for both N=8 and N=16** -- only its
data grew (1,012 -> 1,092 B, +80 B for 8 more `Number`s, ~5 B/coordinate,
~10 B/offset pair), matching `../pattern-cost/README.md` finding 4's "a
runtime loop's cost is in the array, not the loop body" almost exactly (it
measured ~5 B/coordinate for `drawLine`; this measures the same for
`drawText`). The unrolled variant costs ~27-29 B of code per **added**
`drawText` call (216 B for 8 more calls between N=8 and N=16), consistent
with each call differing only in two already-hoisted-local operands.

**Unlike `../pattern-cost/`'s dramatic 7-30x, the loop is close to a wash
at N=8** (229 vs 209 B, ~9% smaller) and only pulls ahead by ~35% at N=16
(445 vs 289 B). Reading both probes together: the loop's advantage scales
with N (flat code + ~5-10 B/offset data, vs. ~27-29 B/call for the
unrolled form), but at the *N=4-16 range a stamped ring actually needs*
(S1's exact-quality sets are 4/8/16 draws) the two are within the same
order of magnitude, unlike a 60-copy tick pattern. **Either is affordable**
(worst case here, unrolled N=16, is 445 B -- 0.34% of the 131,072 B MIP
budget on this device); the loop is the better default because it scales
better and is one array literal away from an author-configured ring width,
not a rewrite.

No CPU/frame-time figure exists anywhere in this repository or the SDK
docs for either form (`docs/research/00-summary.md` open question 1 is the
closest: an undocumented `watchdogCount: 240000` in `simulator.json`,
units unknown) -- this section is memory only, and the main document marks
per-call CPU cost UNVERIFIED accordingly.
