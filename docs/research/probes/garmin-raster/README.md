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
`captures/<family>-<device>.png`. Keep the simulator at 100% zoom. Whether a
capture's screen pixels map one to one onto the watch's is UNVERIFIED: the
compare step finds the screen in the capture and checks its size first.

The compare step (fitting each primitive's convention per device family,
the diff tables) is written once captures exist.
