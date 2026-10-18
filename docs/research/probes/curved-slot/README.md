# Probe: a curved slot reading with a rotated icon

Backs `docs/research/35-curved-slot-reading.md`. Two builds of one minimal
watch face that differ in **exactly one class**, `ProbePair`, so the
`--build-stats` delta is the cost of the curved path and nothing else.

**Answers, up front.**

| | question | answer |
|---|---|---|
| **a** | does a radial reading in a vector font, measured with `Dc.getTextWidthInPixels(text, VectorFont)`, plus a baked glyph drawn into a `BufferedBitmap` and blitted through `Dc.drawBitmap2(..., {:transform => AffineTransform})`, compile warning-free under `-l 3`, `typecheck = strict`? | **Yes**, on `fenix8solar47mm`, `fenix8solar51mm` and `fr955`, SDK 9.2.0. |
| **b** | does the same guarded source build for a device with none of those APIs? | **Yes**, warning-free on `fenix6`. The `has` guards fold at compile time and the curved code is dropped: code is *smaller* than the baseline there (447 B against 554 B). |
| **c** | what does the curved path cost? | **+70 B data / +509 B code** on `fenix8solar47mm` and `fr955` (baseline 483 / 416, curved 553 / 925). `.prg` +1,072 B. |
| **d** | does it draw right? | **Not answered.** The simulator crashes in this container (`CLAUDE.md` §3). See "On the host" below. |

## The two variants

| variant | `ProbePair` draws |
|---|---|
| `variant-baseline` | what `type: data` draws today: a baked icon glyph and a `FONT_SMALL` reading, upright, centred together from their measured widths |
| `variant-curved` | the reading with `drawRadialText` in `RobotoCondensedBold` 28 px, clockwise from 136° (Garmin's convention); then the icon *after* the run, at the angle the measured width puts it, rotated to stand on the circle through a 2-colour (`COLOR_TRANSPARENT`, `COLOR_WHITE`) `BufferedBitmap` and `drawBitmap2`'s `:transform` |

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

Look for: the glyph's background drawn transparent (not a white or black
square); the glyph upright at 12 o'clock and standing on the circle
elsewhere; and the gap between the run's last digit and the glyph staying
the same as the minute (and so the reading's width) changes.
