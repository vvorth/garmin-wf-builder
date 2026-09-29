# 19 — An outline on every drawable

`outline:` exists today on `text` elements and on a pattern's `shape: text`
parts only (research 13, 14; `docs/guide/text.md`). This document asks
whether the same idea can reach **every** drawable: shapes, icons (openings
included), hands, pattern and progress parts, and a whole `group` outlined
as one silhouette. It also asks whether one mechanism should serve them all.
The goal is a ring of 1–3 px. It is **not** a general stroke of any width.

**Status: built** (plan 23, whose record is
`git show 96462ed:docs/plans/23-outline-everything.md`; the author-facing
reference is `docs/guide/outlines.md`). The decisions are in §7. Where the
build departed from this document:

- A partly static group cannot be written in format 2 (`static:` is a
  block), so §5's static question did not arise.
- The `contrast` lint now wants the ring to read against the backdrop only
  when the interior does not.
- `data`, `graph`, `segments`/`scale` gauges, and a ringed text part inside
  a ringed pattern are refused for now (`docs/limitations.md` §2).

**Short answer.**

1. **Yes, for every kind.** Two techniques cover them all, and neither
   needs anything the platform lacks:
   - **the stamp**: draw the element's own silhouette at the
     `disc-perimeter` offsets in the ring colour, then draw the element
     normally. This is today's text `outline:`. It works on anything whose
     draw call takes a screen-space anchor, and every kind's draw call does.
     It is an exact dilation of the pixels actually drawn, so **openings get
     a ring too** (§4.3).
   - **analytic dilation**: draw one grown copy of the primitive (radius
     + w, pen + 2w, a polygon offset outwards at build time), then the
     primitive. It costs one extra draw instead of N, but it is only
     reliable at **w ≥ 2**. At w = 1 the two independently rasterised edges
     leave visible gaps (§4.1).
2. **A group outline is the union's outline, done in two passes:** every
   member's ring first, then every member. Dilation distributes over union,
   so this is exactly the outline of the group's silhouette, with no seams
   between members. The probe checks this pixel for pixel (§4.4). It needs
   no colour forcing and no offscreen buffer, only a "draw my ring" op per
   member kind.
3. **One unified `outline:` is the better format.** It uses the grammar
   text already has (`none` | a colour | `{color, width: 1–3}`), is
   accepted on every drawable and on `group`, and each kind chooses its
   technique behind it. The text implementation becomes the glyph branch of
   that table and is not replaced (§6).
4. **Nothing here has run on a watch or in the simulator** (root
   `CLAUDE.md` §3). Every measured number comes from a Pillow model of the
   rasteriser (§4), which is not Garmin's. The claims most in need of an
   on-device check are listed in §8.

Every behavioural claim is marked **VERIFIED** or **UNVERIFIED**, following
`docs/CLAUDE.md`. The probe is
`docs/research/probes/outline-everything/probe.py`. Its output is
`results.txt`, `icons.png` and `group.png` next to it. No compiler code
changed.

---

## 1. What the platform offers (and does not)

- **No stroke-an-outline primitive of any kind (VERIFIED).** `Dc` has
  `fill*`/`draw*` pairs for rectangles, rounded rectangles, circles and
  ellipses, plus `drawLine`, `drawArc` and `fillPolygon`
  (`$CIQ_SDK/doc/Toybox/Graphics/Dc.html`). A `draw*` variant strokes the
  shape's own edge at the pen width. It does not ring a filled shape in a
  second colour. There is no `drawPolygon` (`docs/limitations.md`).
  Research 13 already showed that text has no outline mode reachable from
  Monkey C.
- **`fillPolygon` takes at most 64 points (VERIFIED, `Dc.html`).** An offset
  polygon can gain a vertex at every bevelled corner (§3.2), so a polygon
  near the limit may not have an analytic ring.
- **`Dc` has no translate or origin (VERIFIED: no such symbol in
  `bin/api.debug.xml`).** A stamp therefore shifts each draw call's own
  coordinates. It cannot shift the canvas. Every kind already draws from a
  small number of anchor expressions, so this is cheap in practice (§5).
- **`setStroke`/`setFill` (API 4.0.0) set a draw/fill tool (a colour or a
  `BitmapTexture`) (VERIFIED, `Dc.html`).** They do not outline anything.
  They are not relevant here.
- **`drawBitmap2` has a `:tintColor` option (VERIFIED, `Dc.html`).** It is
  present on 20 of the 33 installed devices (both `fenix8solar47mm` and
  `fr955`) and absent on `fenix5`, per each device's `api.debug.xml`. The
  docs do not say how the tint combines with the source pixels
  (**UNVERIFIED**). It would allow "render the silhouette once, blit it
  tinted N times" (§3.3), but only as a later optimisation.

## 2. What exists: the text stamp

`wfb.emit.monkeyc.shapes.emit_outline_loop` sets the ring colour once, loops
over `Layout.OUTLINE_OFFSETS_<W>` (the exact `disc-perimeter` set: 4, 8 or
16 offsets at w = 1, 2, 3) and calls a per-anchor draw callback at each
shifted anchor. The interior pass is the element's ordinary draw. Research
14 measured it:

- an exact dilation at every width (IoU 1.000, §1);
- valid under rotation, for angled and radial text (§3.2);
- +209 B for the loop at N = 8 on `fenix8solar47mm` (§4.3).

Nothing in that callback is specific to text. It already takes "an anchor
in, the draw lines out". That is the seam every other kind can plug into.

## 3. Techniques

### 3.1 The stamp (universal)

Draw the element's silhouette N times, shifted by `(dx, dy)`, in the ring
colour. Then draw the element.

- **Exact** at every width, because it dilates the *rasterised* shape
  (research 14 §1 for glyphs; for any other shape it is the same
  arithmetic). **VERIFIED in the model.**
- **Openings are ringed** whenever they are wider than 2w. Narrower ones
  fill with ring colour (§4.3). **VERIFIED in the model.**
- **Cost: N extra draws per primitive**, where N is 4, 8 or 16 at w = 1, 2,
  3. The CPU cost is unmeasured (research 14 §4.2 still stands). Code size
  is one loop per element, flat in N.
- **The silhouette must be drawn in one colour.** For single-colour kinds
  (a shape, an icon, one hand part) that is trivial: set the ring colour
  once and skip the element's own `setColor` inside the loop. This is
  already how the text loop works. For multi-colour kinds (a hand with
  differently coloured parts, a progress track and fill), the ring pass
  draws each part's geometry with the colour lines left out. **No runtime
  colour override is needed**, because the ring code is separate emitted
  code, not a re-run of the element's method.

### 3.2 Analytic dilation (primitives, w ≥ 2)

Draw one grown copy of the primitive in the ring colour, then the primitive.

| Primitive | Grown copy | Exactness |
|---|---|---|
| `circle` (filled) | `fillCircle(r + w)` | exact up to rasterisation |
| `circle` stroked, `arc` | pen + 2w; an arc also extends start and end by `w / r` rad | caps: `drawArc`'s end shape is undocumented (**UNVERIFIED**, assumed square) |
| `ellipse` | radii + w | close to exact (an offset ellipse is not an ellipse; the error is sub-pixel at these sizes) |
| `rectangle` | x, y − w; size + 2w | a square structuring element, so each corner gets 1 px more than a disc gives |
| `rounded_rectangle` | as `rectangle`, corner radius + w | exact up to rasterisation |
| `line` | pen + 2w, both ends extended by w along the line | caps as above |
| `polygon` (shape, hand or pattern part) | mitred offset computed at **build time** and baked as a second `_POINTS` constant; a hand rotates it with the same `WfbGeom.fillRotated` | a mitre is bevelled past 2w (a sharp hand tip), which adds one vertex |

- **Cost: one extra draw per primitive**, plus one more constant for a
  polygon.
- **Openings:** a stroked circle or arc rings its inside edge for free,
  because its pen grows both ways. A filled polygon has no openings.
  Glyphs cannot be dilated analytically.
- **The limit is 1 px** (§4.1). The grown copy and the original are
  rasterised independently, so a 1 px ring rounds onto the original's own
  edge pixels at some angles and simply disappears there.

### 3.3 Offscreen silhouette, blitted N times (not recommended now)

Draw the element or group once into a 2-colour, palette'd `BufferedBitmap`
(transparent plus ring colour), `drawBitmap` it at the N offsets, then draw
normally. This has the stamp's exactness, and the per-offset cost is a blit
rather than a redraw. Against it:

- it is new allocation machinery (research 14 §5.1);
- the buffer's memory sits in the graphics pool (constraint 11);
- whether drawing an off-palette colour into a palette'd buffer maps to the
  nearest entry is **UNVERIFIED**;
- whether a blit is cheaper than a draw is **UNVERIFIED**;
- `drawBitmap2`'s tint semantics are undocumented (§1).

Keep it as the answer if the stamp ever proves too slow for a large group.

### 3.4 A baked dilated glyph (icons and baked fonts only)

At build time, add a second glyph to the baked font: the dilation of the
first. The ring then costs one `drawText` instead of N, with exact openings.
The ring width is fixed at bake time, and every dilated glyph adds resource
bytes. Research 14 §5.2 weighed this for text and kept it in reserve. The
same verdict applies to icons.

## 4. Measurements (Pillow model, `probe.py`)

### 4.1 Hand polygon, analytic offset, 60 rotations

The hand is a sword, 8 px wide and 100 px long with a sharp tip, rotated to
every minute. "Gap" counts pixels that touch the hand but are left
background by the ring, which means the outline visibly breaks there.
**VERIFIED in the model.**

| offset | ring | vertices | gap px/frame (mean / worst) | IoU vs. true dilation (mean) |
|---|---|---|---|---|
| 1 | 1 px | 6 (from 5) | **12.9 / 69** | 0.76 |
| 1.5 | ~1 px | 6 | 1.1 / 3 | 0.60 (uneven 1–2 px) |
| 2 | 2 px | 6 | 0.9 / 2 | 0.83 |
| 3 | 3 px | 6 | 0.6 / 2 | 0.89 |

A 1 px analytic ring breaks up badly. Offsetting by 1.5 closes the gaps but
gives a ring that wobbles between 1 and 2 px. From 2 px on it is usable. A
**1 px ring on a primitive should use the stamp**: 4 draws, exact.

### 4.2 Line part, pen + 2w, ends extended

Gap pixels per frame, over 60 rotations:

| pen | w = 1 | w = 2 |
|---|---|---|
| 2 | 20.8 | 1.3 |
| 3 | 29.9 | 1.7 |
| 5 | 22.4 | 0.9 |

The same pattern: unusable at 1 px, fine at 2 px.

### 4.3 Icons with openings: the stamp

The icons were rendered with the vendored Nerd Font, 1-bit, and dilated
exactly (the stamp's result, research 14 §1). The table gives, for each
enclosed opening, the pixels still open after the ring, out of the pixels
open before it. **VERIFIED in the model**; see `icons.png`.

| icon | 20 px, w = 1 | 20 px, w = 2 | 28 px, w = 1 | 28 px, w = 2 | 40 px, w = 1 | 40 px, w = 2 |
|---|---|---|---|---|---|---|
| alarm (clock face) | 52/103 | 14/103 | 115/185 | 57/185 | 278/384 | 182/384 |
| sunrise (small gap) | 3/13 | 0/13 | 8/22 | 0/22 | 19/39 | 5/39 |

The alarm's face gets a clean inner ring at every size. At 20 px the alarm
has a second, 2 px notch, which closes: an opening narrower than about 2w
fills with ring colour. So "openings are outlined" holds whenever the
opening is wider than the ring is thick. That argues for w = 1 on small
icons, and the stamp gives exactly that. A lint can warn when an opening
closes, because the preview can compute the same dilation.

### 4.4 A group: two passes vs. per member

A circle and a bar overlap, with w = 2:

- **drawing each member's ring and then that member** paints **160 ring
  pixels inside the group's own silhouette**, because the bar's ring cuts
  into the circle;
- **two passes** (every ring, then every member) paint **0**, and the ring
  equals the true dilation of the union exactly.

**VERIFIED in the model**; see `group.png`. This holds for any mix of
techniques, as long as each member's ring op is a dilation of that member.

## 5. Per kind

| kind | ring op | openings | notes |
|---|---|---|---|
| `text` | stamp (built) | yes | unchanged |
| `icon` | stamp; the same `emit_plain_text_call` as text | yes, if wider than 2w | nearly free to build: icon already draws with `drawText` |
| `shape` circle, ellipse, rectangle, rounded rectangle, arc, line | stamp at w = 1; analytic at w ≥ 2 | stroked forms: both edges | `Layout.<P>_CX + dx` and so on in the stamp loop |
| `shape: polygon` | stamp (`WfbGeom.fillTranslated(points, dx, dy)` already exists); analytic at w ≥ 2 if the offset fits in 64 points | — | a bevel can add a vertex |
| `hands` | per hand: every part's ring, then the parts (a union across parts, so no seams inside a hand) | — | stamp by shifting `cx`/`cy`; analytic offset baked in local coordinates and rotated as-is |
| `pattern` parts | the same, per copy | text parts: yes | `outline:` on parts is already reserved vocabulary (format 2) |
| `progress` arc, bar, segments, needle | as shape arcs, rectangles and polygons | stroked arcs: yes | the ring follows the lit length at runtime: the track and fill silhouettes are drawn every frame anyway |
| `complication_slot` | composite: icon + text + progress, each as above | as parts | lower priority |
| `graph` | stamp the polyline or bars | — | lowest priority; a data-dependent draw loop run N times |
| `group` | two passes over its members' ring ops | per member | §4.4; a member without a ring op is a build error |

**Group details still to decide (§7):**

- **Guards.** A member hidden by `visible:` or by absence must be skipped
  in the ring pass too, so pass 1 runs the member's guards. Generating a
  small `ring<Id>` method per member, with the same guard preamble, keeps
  this in one place.
- **A member's own `outline:` inside an outlined group.** The simplest rule
  is that the group ring dilates members as they are drawn, own rings
  included (width w_group + w_member).
- **`static:` groups.** Both passes go into the buffer, unchanged.

## 6. Cost and constraints

- **CPU (UNVERIFIED, as in research 14 §4.2).** The stamp costs N + 1 draws
  and analytic dilation 2 draws. No per-call cost is known on this
  platform.
- **`onPartialUpdate` (constraint 4).** An outlined second hand grows the
  clip by w on every side and multiplies its draws by N + 1 (stamp) or by 2
  (analytic, w ≥ 2). An overrun is permanent. So `low_power` elements
  should either prefer analytic dilation or feed the multiplier into the
  existing `check_partial_update_budget` lint. The safe default is to treat
  the multiplier as data, not to forbid the ring.
- **Code size (VERIFIED for text, research 14 §4.3):** about 200 B per
  stamped element (the loop). An analytic ring is one call plus, for a
  polygon, one constant array of about 10 B per vertex (the
  `pattern-cost` rate).
- **AOD (constraint 5).** A ring adds lit pixels, and `aod: {outline: ...}`
  already exists for text. It should carry over as-is. The ring on
  primitives is also the natural way to get "the hollow idiom" (research
  14 §4.1) for shapes on AMOLED, where it cuts lit pixels.
- **Colour (constraint 13).** The ring colour follows `color:`'s grammar and
  lint, exactly as text's does.
- **Preview.** `wfb/preview.py` already stamps text. For any other kind,
  redrawing the silhouette at the same offsets reproduces the device's
  stamp exactly. The analytic branch has a Pillow twin (grown primitives).

## 7. Decisions

**Decided by the user on 2026-09-29, and being built (`docs/plans/23-outline-everything.md`):**

- D1: one key everywhere.
- D2: the enlarged copy only where it is mathematically the dilation:
  - a filled circle;
  - a filled rectangle (whose dilation has corners of radius `w`);
  - a rounded rectangle (corner radius `r + w`).

  Everything else is stamped, polygons included, because a sharp angle has
  no one-draw dilation.
- D3: each hand is outlined whole.
- D4: the order as recommended.
- D5: members' own rings are included in the group's.

The options as they were put:

- **D1. One key, or one per kind?** Recommendation: **one `outline:` key**
  with text's grammar (`none` | colour | `{color, width: 1–3}`), accepted
  on every drawable and on `group`. The key stays the same, and only the
  technique behind it varies. This reuses the colour, AOD and lint rules
  text already has, and it retires the "`outline:` on parts" reserved entry
  into the general case.
- **D2. Technique default.** Recommendation: **the stamp everywhere at
  w = 1** (the only exact 1 px option). At w ≥ 2 use **analytic dilation
  for primitives**, the stamp for glyphs, and the stamp as a fallback when
  an offset polygon would exceed 64 points. The alternative is the stamp
  everywhere: simpler, one code path, more draws.
- **D3. Hands.** Should the unit be the whole hand (a union across its
  parts) or each part? Recommendation: **per hand**, element-level
  `outline:`, which is the classic look where each hand is ringed against
  the one beneath it. Per-part `outline:` can come later under the same
  grammar.
- **D4. Scope of the first cut.** Recommendation, in order:
  1. `icon`, which is almost only schema and preview;
  2. `shape`;
  3. `hands`;
  4. `group`;
  5. `pattern` and `progress` parts.

  `complication_slot` and `graph` would be deferred, each with a friendly
  "not implemented" error.
- **D5. Group semantics.** Recommendation: the union, with members' own
  rings included (§5).

This is a format change (root `CLAUDE.md` §7), so it needs a plan and these
decisions before anything is built.

## 8. What needs an on-device check

1. **Rasterisation of grown primitives.** The Pillow model's gap numbers
   (§4.1–4.2) are a proxy for Garmin's rasteriser. The w ≥ 2 verdict needs
   a look on a real screen, at a few hand angles.
2. **End shapes of `drawArc` and wide `drawLine`** (square, butt or round).
   These decide the end extension in §3.2.
3. **Stamp CPU on a second hand under `onPartialUpdate`**: the one place a
   multiplier can kill the face for its lifetime.

Items 1 and 2 need one probe face sideloaded or run in the user's host
simulator (the simulator cannot run apps in this sandbox).

## Sources

- `$CIQ_SDK/doc/Toybox/Graphics/Dc.html` (SDK 9.2.0): `fillPolygon`'s
  64-point limit, `drawBitmap2` options, `setStroke`/`setFill`,
  `setPenWidth`.
- `$CIQ_SDK/bin/api.debug.xml`: no translate or origin on `Dc`;
  `~/.Garmin/ConnectIQ/Devices/*/*.api.debug.xml` for per-device
  `drawBitmap2`.
- `docs/research/13-outline-vector-text.md`,
  `docs/research/14-stamped-ring-text.md` (offset sets, cost, alternatives).
- `wfb/emit/monkeyc/shapes.py` (`emit_outline_loop`),
  `runtime-lib/WfbGeom.mc` (`fillRotated`, `fillTranslated`).
- `docs/research/probes/outline-everything/` (this document's model).
