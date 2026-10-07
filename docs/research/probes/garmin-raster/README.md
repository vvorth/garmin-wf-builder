# garmin-raster: the probe faces for Garmin's pixel model

Seven faces, one per primitive family the preview draws, each a grid of
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

Each targets `fenix8solar47mm`, `fenix8solar51mm`, `fr955` and
`fenix847mm`. `make_faces.ts` writes them (`node make_faces.ts`); every face
builds with no `monkeyc` warning on all four (2026-10-06). The lint warnings
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
| lines | 52, 553 | 224 |
| polygons | 0, 88 | 1 |
| rects | 314, 450 | 0 |
| text | 0, 0 | 0 |
| swatches | 0, 0 | colour only (the profile, above) |

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

- **`drawRectangle(x, y, w, h)` with pen p**, and every other stroke below,
  stamps a p x p square brush on each pixel of the 1 px path, reaching
  ⌊p/2⌋ left and up and p - 1 - ⌊p/2⌋ right and down. Pens 1-4.
- **`fillRoundedRectangle(x, y, w, h, r)`** lights the pixels whose centre
  lies in the rectangle x..x+w, y..y+h with corners of radius r. Radii 2, 3
  and 5, at 20x14 and 21x15.
- **`drawRoundedRectangle(x, y, w, h, r)` with pen p** is `drawRectangle`'s
  stroke with each corner square replaced by `drawCircle`'s ring of radius
  r about the corner's centre (x + r, y + r), (x + w - 1 - r, y + r) and
  their mirrors below, axis exceptions included. A left corner's square
  ends before its centre column, a right one's takes it in; top and bottom
  squares end before their centre row. Exact at a 2 px pen on radii 2, 3
  and 5 at 20x14 and 21x15 (recaptured 2026-10-07, after layout's
  half-up rounding made the 21x15 shapes 21x15).
- **`drawLine`**'s 1 px path is 4-connected: one x or one y step at a time,
  whichever lands nearer the true line, a tie stepping y first, both ends
  drawn (|dx| + |dy| + 1 pixels). With the brush this is exact at widths 1
  and 3 at 0-90 degrees, and at widths 2 and 4 horizontally and
  vertically. A 2 or 4 px diagonal is off by about 25 pixels: the
  simulator's extra row runs below and right of the path, where the brush
  puts it above and left, and no single offset fits.
- **`fillPolygon`** is the scanline fill plus every edge drawn as that
  1 px line: one pixel off over six shapes. Its edges run every way, so
  this also checks the line's tie rule beyond up-and-right.
- **`drawArc`** is `drawCircle`'s ring at radius r - 1/2, cut to the
  pixels whose angle from the centre lies in the span, both ends in: 0-5
  pixels a shape, all at the ends, where the r ring missed 10-43 a shape.
- **Not fitted:** 2 and 4 px diagonal lines. `drawRoundedRectangle` at
  pens other than 2 is unprobed.

The AMOLED `fenix847mm` misses every rule by its grey edges: it needs a
coverage model.
