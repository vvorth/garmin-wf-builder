# Probe: a curved slot reading with a rotated icon

Backs `docs/research/35-curved-slot-reading.md`. Two builds of one minimal
watch face that differ in **exactly one class**, `ProbePair`, so the
`--build-stats` delta is the cost of the curved path and nothing else.

**Answers, up front.**

| | question | answer |
|---|---|---|
| **a** | does a radial reading in a vector font, measured with `Dc.getTextWidthInPixels(text, VectorFont)`, plus a baked glyph drawn into a `BufferedBitmap` and blitted through `Dc.drawBitmap2(..., {:transform => AffineTransform})`, compile warning-free under `-l 3`, `typecheck = strict`? | **Yes**, on `fenix8solar47mm`, `fenix8solar51mm` and `fr955`, SDK 9.2.0. |
| **b** | does the same guarded source build for a device with none of those APIs? | **Yes**, warning-free on `fenix6`. The `has` guards fold at compile time and the curved code is dropped: code is *smaller* than the baseline there (514 B against 643 B). |
| **c** | what does the curved path cost? | **+70 B data / +486 B code** on `fenix8solar47mm` and `fr955` (baseline 508 / 494, curved 578 / 980). `.prg` +1,008 B. |
| **d** | does it draw right? | **Partly.** On the user's host simulator (`fenix8solar47mm`, 2026-10-18) the first version crashed: `drawBitmap2` throws `Source must not use a color palette` for a `BufferedBitmap` created with `:palette`. The buffer is now full-colour. The gap question ("On the host" below) is still open. |

## The variants

| variant | `ProbePair` draws |
|---|---|
| `variant-baseline` | what `type: data` draws today: a baked icon glyph and a `FONT_SMALL` reading, upright, centred together from their measured widths |
| `variant-curved` | three fixed readings, `1`, `1234` and `12345678`, each with `drawRadialText` in `RobotoCondensedBold` 28 px, clockwise from 150° (Garmin's convention) on circles of 80%, 60% and 40% of the half-width; after each, the icon at the angle the reading's measured width puts it, rotated to stand on the circle through a full-colour `BufferedBitmap` (no `:palette`: see **d**) and `drawBitmap2`'s `:transform` |

| `variant-gap` (`gap.jungle`) | the gap question alone: the same three readings, and two thin red radial ticks just outside each, at the angles its measured width predicts for the run's start and end. No bitmap, no transform. Not part of the cost comparison |

The "icon" is the `Clock` sheet from `../vector-fonts` (glyph `8`): any baked
font exercises the same draw path, so the probe does not vendor the icon font.

## Build

```sh
cd docs/research/probes/curved-slot
for v in baseline curved; do for d in fenix8solar47mm fenix8solar51mm fr955 fenix6; do
  $CIQ_SDK/bin/monkeyc -f $v.jungle -d $d -o /tmp/$v-$d.prg \
      -y ~/ciq/developer_key.der -w -l 3 --build-stats 0
done; done
```

## On the host

The gap question is answered by the `gap` variant, one still frame on
`fenix8solar47mm` in the host simulator:

```sh
monkeyc -f gap.jungle -d fenix8solar47mm -o gap.prg -y ~/ciq/developer_key.der -w
connectiq && monkeydo gap.prg fenix8solar47mm
```

Each row's digits should sit exactly between its two red ticks. If the
digits stop short of the second tick, or run past it, and more so on the
longer rows, the device lays a run out to a different length than
`getTextWidthInPixels` measures.

The `curved` variant (an icon turned at runtime through `drawBitmap2`)
cannot answer it: its 68 px marker hides the runs, and where
`drawBitmap2`'s `:transform` places a bitmap is itself undocumented. Its
own questions, run the same way with `curved.jungle`:

- The `8`'s background drawn transparent, not a square.
- The `8` standing on the circle (its top towards the edge), not upright.
