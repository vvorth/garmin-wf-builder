# garmin-raster: the probe faces for Garmin's pixel model

Seventeen faces, one per primitive family the preview draws and size range, each a grid or nest of
sizes, odd and even, white on black, so a capture shows exactly which
pixels the simulator lights:

| Face | What it draws |
|---|---|
| `circles` | `fillCircle` radii 1–12; `drawCircle` pens 1–4 on radii 8 and 9 |
| `arcs` | `drawArc`, pens 1 and 3, start angles 0/45/100/270°, sweeps 30° and 135° |
| `lines` | `drawLine`, widths 1–4, at 0/15/30/45/60/90° |
| `polygons` | `fillPolygon`: triangles, a quad, a thin and a sliver |
| `rects` | rounded rectangles filled and drawn (radii 2/3/5, 20×14 and 21×15), `drawRectangle` pens 1–4 |
| `text` | `drawText` of a baked sheet, plain and anti-aliased |
| `swatches` | sixteen colours, on and off the 64 MIP colours |
| `ellipses` | `fillEllipse` at six sizes, odd and even radii; `drawEllipse` pens 1–3 |
| `lines2` | `drawLine` widths 1 and 3 drawn left and down; widths 2 and 4 at 15/30/45/60/135/225/315° |
| `rects2` | `drawRoundedRectangle` pens 1, 3 and 4 (radii 2/3/5 at 20×14, radius 3 at 21×15) |
| `rotated` | a radial pattern's polygons and lines, turned at runtime: `fillPolygon` and `drawLine` given Float points |
| `big_circles` | `drawCircle` radii 20–120, pens 1–3, nested about the centre |
| `big_fills` | `fillCircle` radii 37 and 44, `fillEllipse` semi-axes 44×22 and 21×41, `fillRoundedRectangle` radius 14 |
| `big_ellipses` | `drawEllipse` semi-axes 30×10 to 110×50, pens 1–3, nested |
| `big_lines` | `drawLine` 88 px long at 24 angles, pens 1–4, drawn outward and inward |
| `big_rects` | `drawRoundedRectangle` 40×28 to 196×142, corner radii 8–44, pens 1–3, nested |
| `big_arcs` | `drawArc` radii 30–120, pens 1–3, odd starts and sweeps, nested |

Each small face targets `fenix8solar47mm`, `fenix8solar51mm`, `fr955`
and `fenix847mm`; the `big_` faces, which ask whether a rule fitted on
small shapes holds out to the rim, target `fr955` alone (the MIP devices
agreed to the pixel on every small face) and are compared over the whole
round screen rather than the central square. `make_faces.ts` writes them (`node make_faces.ts`); every face
builds with no `monkeyc` warning on all four (2026-10-06; the last four
2026-10-07). The lint warnings
they draw (`aod-empty`, and `palette-dither` and `contrast` on the swatches)
are what the probes are for.

## Capturing (on the Mac)

```sh
./docs/research/probes/garmin-raster/capture.sh            # every face, every device
./docs/research/probes/garmin-raster/capture.sh circles    # one family
```

It runs `wfb simulate` per face and device and saves a window capture to
`captures/<family>-<device>.png`. Keep the simulator at 100% zoom.

## Comparing

```sh
node docs/research/probes/garmin-raster/compare.ts [family]
```

It overlays each capture on the TypeScript preview's frame of the same face
and device (scale 1, no screen mask), prints a line per capture and writes
`diffs/<family>-<device>.png`: the central 200 px square at 4x, **white**
where both light a pixel, **red** where only the preview does, **green**
where only the simulator does, **orange** where both light it in different
colours.

How a capture maps onto the watch, VERIFIED on the 28 captures of
2026-10-06 (SDK 9.2.0 simulator 6.0.2, macOS, Retina):

- **The screen is drawn at exactly 2x** (one device pixel is 2x2 capture
  pixels) and smoothed: an edge has one or two grey capture pixels. A
  fitted scale came out 2.016-2.019, pulled by the very differences below;
  at 2 the 1 px circles overlay exactly. The device pixel is read at its
  block's centre.
- **The screen cannot be found by its black.** The screen is 0-3 and the
  bezel's inner ring 7-10 per channel, so the offset is fitted to the
  content instead.
- **Colours are not comparable.** macOS converts the capture to the
  display's profile: `#00FF00` comes out about `#75FB4C` (Display P3's
  pure green). Only lit-or-not is compared reliably; a colour mismatch
  under 96 per channel is ignored.

## Findings (2026-10-06)

Differing pixels in the central square on `fr955`, before and after the
fitted rules below (the two fēnix 8 Solar captures agree with it to the
pixel; `fenix847mm` is the same geometry with grey edges, below):

| Family | Before the fit (preview only, simulator only) | After |
|---|---|---:|
| circles | 484, 420 | 0 |
| arcs | 135, 195 | 27 |
| lines | 52, 553 | 0 |
| polygons | 0, 88 | 0 |
| rects | 314, 450 | 0 |
| text | 0, 0 | 0 |
| swatches | 0, 0 | colour only (the profile, above) |
| ellipses (2026-10-07) | 264, 182 | 0 |
| lines2 (2026-10-07) | 160, 160 | 0 |
| rects2 (2026-10-07) | 0, 0 | 0 |
| rotated (2026-10-07) | 44, 51 | 0 |

The large faces, on `fr955` (2026-10-07), after the fit:

| Family | Differing pixels |
|---|---:|
| big_lines | 0 |
| big_rects | 0 |
| big_fills | 12: 8 on the radius-44 disc, 4 on the 44x22 ellipse, each a pixel just past r² |
| big_ellipses | 20 |
| big_circles | 144, over 16 rings to radius 120 |
| big_arcs | 47 (569 before an even pen's ring was centred on r) |

The circle misses fit no single threshold on x² + y²: ring by ring, the
largest lit and smallest dark d² beyond r² contradict each other (at
radius 73, 106 and 120 the intervals are empty). Garmin steps the circle
incrementally, and the preview keeps the distance test.

The screen fit (`fitScreen`) now tries two starts and keeps the one with
fewer misses: the lit boxes' centres, and a search of the whole window for
the offset where a sample of the preview's lit and dark pixels agrees
most. The first alone misplaced every large face (the bezel's white ticks
and lettering widen the capture's lit box) and the `fenix8solar51mm`
captures of `lines2` and `rotated`; with both, every capture overlays.

What each primitive did differently from the preview's Pillow
conventions, read off the diff images. Each is VERIFIED as a difference;
the exact rule Garmin follows is UNVERIFIED until a fitted model reproduces
the capture:

1. **`fillCircle`** lights a disc about one pixel smaller in radius than
   Pillow's ellipse on `(cx-r, cy-r, cx+r, cy+r)`, on every side.
2. **`drawCircle`**: a 1 px pen matches. A 2-4 px pen grows the ring
   *outward* from the radius, where the preview grows it inward.
3. **`drawArc`**: a 1 px pen matches but for single pixels along the curve;
   a 3 px pen is offset outward as `drawCircle`'s is.
4. **`drawLine`**: a 1 px line matches. A wider line is wider than the
   preview's on both sides, has square ends that extend past its end points
   (the vertical lines grow at both ends), and an even width sits one pixel
   up (the horizontal 2 px and 4 px lines).
5. **`fillPolygon`** lights one more pixel along right-hand and bottom
   edges: the simulator includes the far boundary, Pillow does not.
6. **Rectangles**: `fillRoundedRectangle` matches but for corner pixels.
   `drawRoundedRectangle` reaches one pixel further left and up.
   `drawRectangle` with a 1 px pen matches; a 2-4 px pen grows outward.
7. **Text** from a baked sheet matches pixel for pixel.
8. **The AMOLED `fenix847mm`** draws the same shapes, with grey partial
   pixels along every edge where the MIP devices draw hard ones: the
   AMOLED anti-aliases primitives the face does not ask to anti-alias
   (UNVERIFIED on a watch).

## Fitted rules

`ts/test/garmin-raster.test.ts` holds each family's count on `fr955` at
or under the table's. The preview draws by these rules
(`ts/src/raster/garmin.ts`), each
VERIFIED on 2026-10-06's captures on the three MIP devices to the pixel
counts given. A device pixel's capture block reads
175-255 when lit and at most 56 when not, so the threshold is 110.

- **`fillCircle(cx, cy, r)`** (exact) lights every pixel with x² + y² <= r² from the
  centre, except the right, top and bottom axis points `(r, 0)`, `(0, ±r)`;
  the left one, `(-r, 0)`, stays lit. Radii 1-12.
- **`drawCircle(cx, cy, r)` with pen p** (exact) lights the `fillCircle` disc of
  radius r + p/2 less the disc of r - p/2, the same axis exceptions
  applying at a whole radius. So an odd pen is centred on r, and an even
  pen's ring sits half a pixel out on the left. Radii 8 and 9, pens 1-4.

- **`fillEllipse(cx, cy, rx, ry)`** is `fillCircle`'s rule stretched:
  x²/rx² + y²/ry² <= 1, less the right, top and bottom axis points.
  **`drawEllipse` with pen p** is the ellipse of semi-axes + p/2 less the
  one of semi-axes - p/2, as `drawCircle`. Semi-axes 5x3 to 11x7, pens 1-3.
- **`drawRectangle(x, y, w, h)` with pen p** stamps a p x p square brush
  on each pixel of the 1 px outline, reaching ⌊p/2⌋ left and up and
  p - 1 - ⌊p/2⌋ right and down. Pens 1-4.
- **`fillRoundedRectangle(x, y, w, h, r)`** lights the pixels whose centre
  lies in the rectangle x..x+w, y..y+h with corners of radius r. Radii 2, 3
  and 5, at 20x14 and 21x15.
- **`drawRoundedRectangle(x, y, w, h, r)` with pen p** is `drawRectangle`'s
  stroke with each corner square replaced by `drawCircle`'s ring of radius
  r about the corner's centre (x + r, y + r), (x + w - 1 - r, y + r) and
  their mirrors below, axis exceptions included. A left corner's square
  ends before its centre column, a right one's takes it in; top and bottom
  squares end before their centre row. Exact at pens 1-4 on radii 2, 3
  and 5 at 20x14 and 21x15 (recaptured 2026-10-07, after layout's
  half-up rounding made the 21x15 shapes 21x15).
- **`drawLine` with pen p** lights the pixels whose centre lies in the
  segment swept by a p x p square centred on it: the hexagon that is the
  convex hull of the squares at both ends. A centre exactly on the outline
  counts when that edge faces left, or straight up (a right, bottom or
  down-right-facing edge does not). One rule for every pen and direction:
  exact over 50 lines, pens 1-4, at 0-345 degrees. A stamped brush on a
  stepped path fitted the odd pens but not a 2 or 4 px diagonal, whose
  thickness down a column is p + p·tan θ, the swept square's.
- **A Float coordinate is truncated toward zero** before drawing: a radial
  pattern's runtime-rotated polygons and lines (`WfbGeom.fillRotated`,
  `drawLineRotated`) are exact so, where rounding misses about 475 pixels.
- **`fillPolygon`** is the scanline fill plus every edge drawn as a 1 px
  `drawLine`: exact over six shapes and a radial pattern's rotated ones.
- **`drawArc`** is `drawCircle`'s ring at radius r - 1/2 for an odd pen
  and r for an even one, cut to the pixels whose angle from the centre
  lies in the span, both ends in: 0-5 pixels a shape, all at the ends,
  where the r ring missed 10-43 a shape at odd pens (the `arcs` face has
  pens 1 and 3; `big_arcs` showed the even pen).
- **Not fitted:** `drawArc`'s end pixels (27 over 16 arcs), and the
  incremental circle's few edge pixels from radius about 40 (above).

The AMOLED `fenix847mm` misses every rule by its grey edges: it needs a
coverage model.
