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

Differing pixels in the central square, on `fr955` (the two fēnix 8 Solar
captures agree with it to the pixel; `fenix847mm` is the same geometry with
grey edges, below):

| Family | Lit in both | Preview only | Simulator only | What differs |
|---|---:|---:|---:|---|
| circles | 2668 | 484 | 420 | below |
| arcs | 465 | 135 | 195 | below |
| lines | 1287 | 52 | 553 | below |
| polygons | 795 | 0 | 88 | below |
| rects | 2774 | 314 | 450 | below |
| text | 2392 | 0 | 0 | only anti-aliased edge greys |
| swatches | 9825 | 0 | 0 | colour only (the profile, above) |

What each primitive does differently from today's preview (Pillow's
conventions), read off the diff images. Each is VERIFIED as a difference;
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

Moving the preview onto these conventions (and refitting until the counts
reach zero) is the work left in this probe.
