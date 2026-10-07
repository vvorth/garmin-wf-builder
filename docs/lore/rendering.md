# What the watch draws: simulator-verified rendering

How Garmin's `Dc` puts pixels on the screen, as measured in the Connect
IQ simulator (SDK 9.2.0, the user's macOS host), and how the preview
reproduces it (`ts/src/raster/garmin.ts`). Every fact here was measured,
not inferred; the probe named with it holds the captures. The simulator
is not a watch: nothing here has been checked on hardware.

Devices: the MIP `fenix8solar47mm`, `fenix8solar51mm` and `fr955` agree to
the pixel on every probe that ran on all three; the large-shape probe ran
on `fr955` alone. The AMOLED `fenix847mm` is in "AMOLED" below.

## Reading a capture

From `docs/research/probes/garmin-raster/` (README, "Capturing"):

- The simulator draws the screen at exactly **2x** on a Retina Mac, one
  device pixel a 2x2 block, and smooths it: an edge has one or two grey
  capture pixels, and a lone diagonal 1 px pixel reads grey (about 0x97).
  Read a device pixel as its block's mean; lit is above 127.
- **Colours are not comparable**: macOS converts a capture to the
  display's profile (`#00FF00` comes out about `#75FB4C`). Compare lit or
  not lit; treat a colour gap as the profile.
- The window has a white margin and the bezel has white ticks and
  lettering, so a capture is aligned to the preview by searching for the
  offset where the preview's lit and dark pixels agree most
  (`compare.ts`'s `fitScreen`), not by the lit content's box.

## Primitives

Each rule is exact (0 differing pixels) on the MIP devices over the range
given; `garmin.ts` implements each one.

| Call | Rule | Verified over |
|---|---|---|
| `fillCircle` | pixels with x² + y² <= r² from the centre, less the right, top and bottom axis points (the left one stays) | radii 1-12; within 1 px to 44, below |
| `drawCircle`, pen p | the `fillCircle` disc of r + p/2 less the one of r - p/2 | radii 8-9, pens 1-4; within 1 px to radius 120 |
| `fillEllipse`, `drawEllipse` | the same rules stretched to x²/rx² + y²/ry² | semi-axes 5x3 to 11x7, pens 1-3; within 1 px to 110x50 |
| `drawRectangle`, pen p | a p x p square stamped on each pixel of the 1 px outline, reaching ⌊p/2⌋ left and up | pens 1-4 |
| `fillRoundedRectangle` | the pixels whose centre is inside the rounded rectangle x..x+w, y..y+h | radii 2-14 |
| `drawRoundedRectangle`, pen p | `drawRectangle`'s stroke, each corner square replaced by `drawCircle`'s ring about the corner centre; a right corner's square takes in its centre column, a left one's does not | pens 1-4, radii 2-44, to 196x142 |
| `drawLine`, pen p | the pixels whose centre is inside the segment swept by a p x p square centred on it; a centre on the outline counts when that edge faces left or straight up | pens 1-4, every direction, 22-88 px long |
| `fillPolygon` | Pillow's scanline fill plus every edge drawn as a 1 px `drawLine` | triangles, a quad, slivers, runtime-rotated parts |
| `drawArc`, pen p | `drawCircle`'s ring of radius r - 1/2 (odd p) or r (even p), cut to the pixels whose angle lies in the span, both ends in | radii 14-120, pens 1-3; 0-5 px a shape off at its ends |
| `drawText`, baked sheet | the sheet's pixels, as baked | plain and anti-aliased sheets |

**A Float coordinate is truncated toward zero** before drawing, as
`toNumber` does: a radial pattern's runtime-rotated polygons and lines
(`WfbGeom.fillRotated`, `drawLineRotated`) match only so.

**Garmin's circle steps incrementally.** From radius about 40, a disc,
ellipse or ring lights or skips a few edge pixels (about 1-2% of a ring's;
8 on a radius-44 disc) where x² + y² <= r² would not: no single distance threshold fits
every ring, so the preview keeps the exact test and is a pixel off there
(`ts/test/garmin-raster.test.ts` holds each count). Lines and rectangles
show no such drift out to the rim.

**A corner radius of 1 is square** on the watch
(`docs/research/probes/ring-on-device/`), as the rules above draw it.

## Text on a curve (vector fonts)

From `docs/research/probes/vector-fonts/` (`fenix8solar47mm`,
`fenix8solar51mm`):

- `drawRadialText` with `RADIAL_TEXT_DIRECTION_CLOCKWISE` faces glyphs
  outward, counter-clockwise inward; each glyph is rotated on its own,
  its vertical midline on the radius through its own centre.
- Without `TEXT_JUSTIFY_VCENTER`, the text's **baseline** sits on the
  circle, each glyph growing toward its own "up".
- The glyph shapes of Garmin's device-resident faces are not reproduced:
  the preview draws a stand-in font.

## AMOLED

`fenix847mm` draws every primitive with grey partial pixels along its
edges, where the MIP devices draw hard ones, though the face asks for no
anti-aliasing. Its fully lit pixels are the MIP rules' to within a few
pixels a family; the grey edge is extra (hundreds of pixels a face), and
the preview does not model it.

## Values the watch prints

What text a value turns into (`Boolean.toString()` is `true`/`false`,
`Math.round` rounds a half up) is in `monkeyc.md`.
