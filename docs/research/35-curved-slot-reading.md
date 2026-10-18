# 35 — A curved reading on `type: data`, with its icon

**Question.** Can a slot (`type: data`) draw its reading along a line or
round a circle (`curve: {style: angled | radial}`, as `type: text` does),
with the icon either kept beside the reading (following the curve, rotated
or upright) or placed freely? What does each option cost, what can the
platform not do, and what should be built?

**Short answer.** Yes, on the 44 of 136 watch-face devices that have vector
fonts, which is the same reach curved text already has. Every one of them
also has the API to rotate a bitmap at runtime. Three findings shape the
design:

1. **The reading must be a vector (`face:`) font.** `drawAngledText` and
   `drawRadialText` refuse resource fonts. `type: data` currently rejects
   `face:` fonts outright, so that error is the first thing to lift.
2. **The icon is a baked glyph, so it can only be turned by a bitmap
   transform or by baking it already turned.** Baking it turned is better
   on every axis that has been measured or reasoned through (§4). Snap
   the runtime angle to a few baked steps; the position stays exact.
3. **Free placement already has a home: `type: icon` with `slot:`**, the
   way `type: gauge` takes `slot:` today. Then one slot is a `group` of a
   gauge, an icon and a reading, each placed and turned on its own. That
   is the request in the pasted design (an icon at a fixed offset, a
   radial reading, a gauge), and it is the smallest piece to build.

---

## 1. What the platform gives

| Fact | Source | Status |
|---|---|---|
| `Dc.drawAngledText` and `Dc.drawRadialText` take scalable fonts only: "These APIs only support scalable fonts and do not support custom fonts loaded as resources" | `$CIQ_SDK/doc/docs/Core_Topics/Graphics.html` §Scalable Fonts; research 12 | VERIFIED (doc) |
| Both are API 4.2.1. Their *Supported Devices* lists name **44** of the 136 watch-face-capable devices in the reference | `$CIQ_SDK/doc/Toybox/Graphics/Dc.html`, counted against `.cache/device-reference/devices/*.json` | VERIFIED (count) |
| `Graphics.FontType` includes `Graphics.VectorFont`, so `Dc.getTextWidthInPixels(text, vectorFont)` measures a vector-font reading | `$CIQ_SDK/doc/Toybox/Graphics.html` (`FontType`); the probe compiles it under `typecheck = strict` | VERIFIED (doc + compile) |
| `Dc.drawBitmap2(x, y, bitmap, {:transform => AffineTransform, :tintColor, :filterMode})` is API 4.2.1 on **60** watch-face devices, a strict superset of the 44 | `Dc.html`, counted the same way | VERIFIED (count) |
| `Graphics.AffineTransform` (API 4.2.0) has `translate`, `rotate`, `scale`, `setMatrix` …; `rotate(theta)` post-multiplies `[cos −sin; sin cos]` | `$CIQ_SDK/doc/Toybox/Graphics/AffineTransform.html` | VERIFIED (doc) |
| What `drawBitmap2`'s `:transform` maps (source pixel → destination relative to `(x, y)`?) and how `FILTER_MODE_POINT` samples a rotated 1-bit glyph | not documented | **UNVERIFIED** |
| `drawBitmap2` refuses a palette'd source: a `BufferedBitmap` created with `:palette` throws `Source must not use a color palette`, so a transparent 2-colour buffer is out; whether a full-colour one blits with a transparent background on MIP is unknown | the user's host simulator, `fenix8solar47mm`, 2026-10-18 (`probes/curved-slot`) | VERIFIED (the throw); **UNVERIFIED** (the rest) |
| A baked font (resource) lands in the graphics pool, not the watch-face limit, since API 4.0.0 | constraint 11; research 12 probe (d) | VERIFIED (measured) |

The three verification targets have all of it.

## 2. What exists to build on

- **The pair is computed on the watch along one axis.** `generalPair` in
  `ts/src/kinds/data.ts` works in a 1-D "along" coordinate (`startX` or
  `startY`, the measured `textWidth`/`iconGlyphWidth`, `gap`) plus one
  "cross" coordinate, then emits upright `drawText` calls. The math does
  not care which way the axis points.
- **Curved text is already a draw-program op.** `Text` ops carry
  `style: angled | radial`, `angle`, `radius` and `direction`, and the
  printer emits `drawAngledText`/`drawRadialText`
  (`ts/src/draw/printer.ts`, `printText`). The preview evaluates the same
  ops, and has been matched against the simulator for radial facing in
  both directions (`docs/limitations.md`, vector fonts).
- **The curved run's shape for lints exists.** `radialTextAngleSpan` and
  the rotated-quad box in `ts/src/layout.ts` give `safe-area` the real
  annulus sector or rotated rectangle. A slot already sizes its lint box
  from its widest possible reading (`widest`).
- **The slot's reading is one string.** `label:` and `unit:` are joined
  into `text` before drawing (`printSlotText`), so curving it is one call.
- **The baker owns its rasteriser.** `ts/src/fonts/bake.ts` flattens each
  glyph's outline from opentype.js and rasterises it at 16x with its own
  code (`raster.ts`). Rotating the outline's points before rasterising is
  a few lines; the result is a properly anti-aliased-then-thresholded
  turned glyph, not a resampled bitmap. (Read from the code; not built.)
- **`slot:` on a non-`data` element has a precedent.** `type: gauge`
  takes `slot:` in place of `value:`/`max:` (`docs/guide/progress-and-graphs.md`,
  "Gauges on a slot").

## 3. Placing the icon: three models

### 3.1 Free: `type: icon` with `slot:` (recommended first)

```yaml
steps_slot:
  type: group
  size: { width: 100%, height: 100% }
  at: { anchor: center }
  children:
    ring:  { type: gauge, slot: top, style: segments, ... }
    glyph: { type: icon, slot: top, size: 10%r, rotate: -46deg,
             at: { anchor: center, dx: -64%r, dy: -48%r }, color: color.fg }
    value: { type: data, slot: top, font: font.steps,
             at: { anchor: center },
             curve: { style: radial, angle: -46deg, radius: 80%r },
             align: left, on_hold: auto }
```

- An icon element that takes `slot:` chooses its glyph on the watch from
  the picked type: the same `switch` the data element's icon already
  emits (`emitDataIconMethod`), and the same per-choice overrides.
- **Its angle is fixed at build time**, so a turned icon is baked turned
  (§4, option B), on every device, with no API gate. `rotate:` on a plain
  `type: icon` would be the same feature and is useful on its own.
- The data element then draws the reading only (no `icon:`), curved or
  not. Nothing about the pair has to change.
- **Cost of the freedom:** the reading no longer re-centres when the pick
  has no icon, and the icon does not move as the reading's width changes.
  For a bezel run that starts at a fixed angle (the pasted design), that
  is the desired behaviour anyway.

**Argument against putting free placement inside `data`**
(`icon: {at: ...}`): it would copy `at:`, `align:`, `size:`, `rotate:`,
`aod:` and `overrides:` into a sub-block, when an element already has all
of them. One binding (`slot:`) on a second element is less to learn and
less to build.

### 3.2 Relative, following the curve

Keep `icon: {position: left | right | top | bottom, gap:}` and define it
**in the text's own frame**:

| `position` | `angled` | `radial` |
|---|---|---|
| `left` / `right` | before / after the run, along the turned baseline | before / after the run, as an angle along the circle: `gap` and widths are arc lengths at `radius` |
| `top` / `bottom` | on the glyphs' "up" / "down" side, perpendicular to the baseline | outward / inward when the glyphs face out (clockwise), the reverse when they face in |

Then upright text is the special case of `angled` at `0deg`, and no new
words are needed. The existing 1-D pair math produces `(along, cross)`; one
mapping turns that into a screen point:

- `angled`: `x = cx + along·cos a − cross·sin a`, `y = cy + along·sin a +
  cross·cos a`. `a` is fixed, so `cos a`/`sin a` are build-time constants.
- `radial`: `θ = θ₀ ∓ along / R` (the sign from `direction:`), `r = R ±
  cross`, then `x = cx + r·cos θ`, `y = cy − r·sin θ`.

**Where the icon's angle is fixed and where it is not:**

| Curve | Icon angle known at build time? |
|---|---|
| `angled`, any `position`, any `align` | **yes**: the whole pair turns rigidly by `a` |
| `radial`, icon on the **pinned** end (`align: left` with `position: left`, `align: right` with `position: right`) | **yes, per glyph**: `θ₀ ∓ (gap + iconWidth/2) / R`, and each glyph's width is known when it is baked |
| `radial`, icon on the **free** end, or `align: center`, or `top`/`bottom` with an off-centre align | **no**: it depends on the reading's measured width, which is only known on the watch |

**One behavioural risk is specific to the free end.** The icon's angle
there is computed from `getTextWidthInPixels / R`, while the device lays
the run out along the circle by its own rules. If the two disagree, the gap
drifts with the reading's length. The text preview matched the simulator
on facing and angular *start*, never on a run's angular *length*. The
pinned end does not depend on this at all. **Answered** by the probe's
host check (§6, question 1): the run is spaced along its baseline circle, so the icon's angle divides by that radius instead of R.

### 3.3 Upright icon beside a curved reading

The icon is positioned on the curve (3.2) but drawn upright with plain
`drawText`, unturned. It is the cheapest option and works for any angle,
fixed or not. It reads well near 12 and 6 o'clock and looks wrong near 3
and 9. Offer it as `icon: {rotate: false}` (default `true`), not as the
only mode.

## 4. Turning the icon: three ways

| | A. Upright (`rotate: false`) | B. Baked turned | C. Turned at runtime |
|---|---|---|---|
| How | `drawText` at the curve point | the baker rotates the outline before rasterising; a fixed angle bakes 1 variant per glyph, a varying one bakes *N* snapped steps and the watch picks one | glyph → 2-colour `BufferedBitmap` → `drawBitmap2` with an `AffineTransform` |
| Devices | wherever the reading draws | wherever the reading draws | 60/136, a superset of the 44 |
| Quality | exact | the outline rasterised turned, at 16x: as good as an upright glyph | a 1-bit tile resampled with `POINT` or `BILINEAR` (off-palette greys on a 64-colour MIP screen; dithers per constraint 13) |
| `wfb preview` fidelity | exact | exact: it already draws baked sheets pixel for pixel | needs a model of `drawBitmap2`'s resampling, which is undocumented |
| Runtime cost | none | `drawText`, one index computation | buffer clear + `drawText` + transformed blit per frame; unmeasured |
| Memory | none | more glyphs in the sheet: `.prg` and graphics pool, not the face budget | +70 B data / +509 B code (probe), buffer in the graphics pool |
| Unknowns | — | free codepoints for the turned variants in the icon font (it uses the Private Use Area itself) | §1's two UNVERIFIED rows |

**Snapping B's angle costs nothing visible.** At a 3° step the worst
error is 1.5°. At the edge of a 24 px glyph (12 px from its centre) that
is 0.3 px, below one pixel. The *position* is computed exactly at runtime;
only the glyph's turn snaps.

**How many glyphs B adds.** The widest reading the slot can show is
already known at build time (`widest`). A 75 px reading on a 150 px radius
sweeps about 29°, so about 11 steps. Ten explicit choices give about 110
turned glyphs; `choices: any` (about 45 icons) gives about 500. Research
12 measured about 55 B of `.prg` per glyph on a 68 px sheet. Scaled by
area to about 24 px, that is roughly 10–20 B per glyph: about 2 KB and
10 KB respectively, in `.prg` and the graphics pool only.
**UNVERIFIED** (extrapolated, not baked).

**Recommendation: B, with A as the opt-out.** Keep C out unless B's glyph
count is ever measured to hurt. It would be a second drawing path with an
undocumented transform, worse glyph quality on MIP, and no faithful
preview. The probe shows it compiles and costs little, so it stays
available.

## 5. What else changes when the reading curves

- **Fonts.** The `complication-slot` error that refuses a `face:` font on
  `type: data` (`ts/src/kinds/data.ts`) goes. A `face:` font is resident
  on the device, so it also removes the slot's "bake every character any
  choice could draw" step. `curve:` on a baked or system font is the same
  build error `type: text` already gives.
- **The other 92 devices.** `unsupported: error | hide` behaves as it does
  on `type: text`. Under `hide` the whole reading disappears and the icon
  stays, which is the slot's existing `absent: hide` rule. An upright
  fallback in a baked font would need a second font per slot. Leave it as
  an open question.
- **`align:`.** Same rules as curved text: angled `bottom` is an error,
  radial accepts all three. `align:` now also decides which end of a
  radial run is pinned (§3.2).
- **Lints.** `safe-area` uses the existing sector or rotated-rectangle
  shape, sized from the widest reading, plus the icon's own box at each
  end it can reach.
- **Hold region and the native editor's highlight.** `on_hold: auto` and
  `SlotDrawable.boundingBox()` take a box. For a curved slot, use the
  sector's bounding box. A group's own `on_hold: auto` resolves from bound
  data sources at build time and knows nothing of slots, so in model 3.1
  the hold target is the data element's own box unless a group gains
  `on_hold: {slot: …}`. That is an open question, not part of the first
  piece.
- **AOD.** The `aod:` overrides apply unchanged. A turned glyph is just
  another glyph.

## 6. Open questions

1. **Does a radial run's angular length equal `getTextWidthInPixels / R`?**
   **Answered: no, it is `width / (R − (ascent − lineHeight/2))` under
   `VCENTER` on a clockwise run.** VERIFIED once, in the host simulator
   (`fenix8solar47mm`, 2026-10-18, the probe's `gap` variant): with
   RobotoCondensedBold 28 px (lineHeight 28, ascent 22) clockwise from
   150°, "1234" at R = 78 ran 4.6 px past its `width / R` end and
   "12345678" at R = 52 ran 16.1 px past it, against 5.5 and 17.5 px
   predicted by spacing the advances along the baseline circle, 8 px
   inside R. Not a constant factor (10% and 17%). UNVERIFIED:
   counter-clockwise, `top`/`bottom`, other faces and sizes. Recorded in
   `docs/lore/rendering.md`, "Text on a curve".
2. `drawBitmap2`'s transform origin, and whether a palette'd
   `BufferedBitmap` blits with a transparent background on MIP. This only
   matters if C is ever built; the same host run shows it.
3. Codepoints for B's turned variants inside the icon font's map.
4. An upright baked-font fallback for the 92 devices without vector fonts.
5. A slot-aware `on_hold:` on a group.

## 7. Recommended order

1. **`type: icon` with `slot:`, and `rotate:` on `type: icon`** (B, one
   variant per glyph), plus **`face:` fonts and `curve:` on `type: data`**
   with no `icon:`. Together these build the pasted design as one slot.
   There are no runtime angles, and the preview stays exact.
2. **A curved data pair with the icon on the pinned end** (§3.2), icon
   turned by B at a per-glyph fixed angle, or `rotate: false`.
3. **The free end and `align: center` on a radial pair**, B with snapped
   steps, after open question 1 is answered on the host.

## Evidence

- `docs/research/probes/curved-slot/` — the probe: warning-free on
  `fenix8solar47mm`, `fenix8solar51mm`, `fr955` and `fenix6`;
  +70 B data / +509 B code for the runtime-turned path.
- `$CIQ_SDK/doc/Toybox/Graphics/Dc.html`, `AffineTransform.html`,
  `BufferedBitmap.html`, `Graphics.html` (SDK 9.2.0).
- Device counts: each method's *Supported Devices* list in `Dc.html`,
  matched by name against `.cache/device-reference/devices/*.json`
  entries that list a `Watch Face` app type.
