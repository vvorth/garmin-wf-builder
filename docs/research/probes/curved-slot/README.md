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

## The two variants

| variant | `ProbePair` draws |
|---|---|
| `variant-baseline` | what `type: data` draws today: a baked icon glyph and a `FONT_SMALL` reading, upright, centred together from their measured widths |
| `variant-curved` | three fixed readings, `1`, `1234` and `12345678`, each with `drawRadialText` in `RobotoCondensedBold` 28 px, clockwise from 150° (Garmin's convention) on circles of 80%, 60% and 40% of the half-width; after each, the icon at the angle the reading's measured width puts it, rotated to stand on the circle through a full-colour `BufferedBitmap` (no `:palette`: see **d**) and `drawBitmap2`'s `:transform` |

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

The open behavioural questions (research 35 §6) are answered by running the
`curved` variant on `fenix8solar47mm` in the host simulator:

```sh
monkeyc -f curved.jungle -d fenix8solar47mm -o curved.prg -y ~/ciq/developer_key.der -w
connectiq && monkeydo curved.prg fenix8solar47mm
```

One still frame answers it. Look for:

- **The gap.** Each of the three rows draws its digits round a circle,
  then an `8` where the compiler predicts the run ends, plus a 6 px gap.
  If the watch lays a run out to the length `getTextWidthInPixels`
  measures, the gap between the last digit and the `8` is the same on all
  three rows. If the `8` overlaps the last digit, or the gap grows with
  the length of the row, the run's drawn length differs from the measured
  width.
- The `8`'s background drawn transparent, not a white or black square.
- The `8` standing on the circle (its top towards the edge), not upright.
