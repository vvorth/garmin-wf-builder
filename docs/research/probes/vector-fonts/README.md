# Probe: vector fonts vs. a baked bitmap sheet

Backs `docs/research/12-vector-fonts.md`. Three builds of one minimal watch
face that differ in **exactly one class**, so the `--build-stats` delta
between two of them is the cost of the font mechanism and nothing else.

**Answers, up front.**

| | question | answer |
|---|---|---|
| **a** | does `Graphics.getVectorFont({:face, :size})` compile warning-free under `-l 3`, `--typecheck strict`? | **Yes**, on `fenix8solar47mm`, `fenix8solar51mm` and `fr955`, SDK 9.2.0. |
| **b** | does the *same guarded source* still build for a device with no vector fonts at all? | **Yes**, warning-free on `fenix6` and `fr245`, for **+6 B data / +45 B code**. One source can serve the whole fleet. |
| **c** | what does each mechanism cost? | vector **+32 B data / +96 B code / +256 B `.prg`**; a baked 68 px sheet **+62 / +55 / +1,200** at 11 glyphs and **+62 / +55 / +5,792** at 95. |
| **d** | does a bigger baked sheet eat the 128 KB watch-face budget? | **No** — data and code were byte-identical at 11 and 95 glyphs; only `.prg` grew. Consistent with font resources loading into the separate graphics pool since API 4.0.0. |

## The three variants

`source/` holds everything shared (`ProbeApp.mc`, `ProbeView.mc`). Each
variant directory supplies one `ProbeFont` class with the same two methods,
and each jungle puts exactly one of them on the source path:

| variant | `ProbeFont` draws with | jungle |
|---|---|---|
| `variant-baseline` | `Graphics.FONT_NUMBER_HOT`, a system bitmap font that costs the app nothing | `baseline.jungle` |
| `variant-vector` | `Graphics.getVectorFont({:face => "RobotoCondensedBold", :size => 68})`, guarded by `Graphics has :getVectorFont` **and** a null check, falling back to `FONT_NUMBER_HOT` | `vector.jungle` |
| `variant-baked` | `WatchUi.loadResource($.Rez.Fonts.Clock)` over a BMFont sheet compiled into the `.prg` | `baked.jungle` (adds `resources-baked` to the resource path) |

The baseline is a *system* font rather than an empty draw so that all three
variants do the same work on screen; only the font mechanism differs.

`resources-baked/fonts/Clock.fnt` + `.png` were baked by this project's own
rasteriser from `examples/showcase/assets/ChivoMono-Bold.ttf` at 68 px, glyphs
`0123456789:` — regenerate with:

```python
from pathlib import Path
from wfb.fonts import bmfont
baked, sheet = bmfont.bake(Path('examples/showcase/assets/ChivoMono-Bold.ttf'),
                           name='Clock', size=68, glyphs='0123456789:')
bmfont.write(baked, sheet, Path('docs/research/probes/vector-fonts/resources-baked/fonts'))
```

The 95-glyph row in the results was the same call with
`glyphs=''.join(sorted(set(string.printable[:95])))`, built and then reverted;
only the 11-glyph sheet is committed.

The vector variant deliberately asks for `RobotoCondensedBold`, the only face
that is close to dependable across the fleet (41 of the 44 devices that have
any scalable face — `../../12-vector-fonts.md` §3.3).

## Rebuilding it

```sh
cd docs/research/probes/vector-fonts
for d in fenix8solar47mm fenix8solar51mm fr955 fenix6 fr245; do
  for v in baseline vector baked; do
    $CIQ_SDK/bin/monkeyc -f $v.jungle -d $d -o /tmp/$d-$v.prg \
        -y ~/ciq/developer_key.der -w -l 3 --build-stats 0
  done
done
```

`fenix6` and `fr245` are **negative controls**: neither publishes a scalable
font, and `grep -c 'name="getVectorFont"'` over each device's own
`api.debug.xml` returns `0` (it returns `1` for `fenix7pro`). They are in the
manifest so that the guarded-source claim (b) is actually built, not assumed.
The `baked` variant on those two is not part of the result — the point of the
controls is the vector path.

## Results — SDK 9.2.0, `-O 3z`, `--typecheck strict`, warning-free

| device | variant | data | code | `.prg` |
|---|---|---|---|---|
| `fenix8solar47mm` / `51mm` / `fr955` | baseline | 429 B | 304 B | 90,684 B |
| `fenix8solar47mm` / `51mm` / `fr955` | vector | 461 B | 400 B | 90,940 B |
| `fenix8solar47mm` / `51mm` / `fr955` | baked, 11 glyphs | 491 B | 359 B | 91,884 B |
| `fenix8solar47mm` | baked, 95 glyphs | 491 B | 359 B | 96,476 B |
| `fenix6` / `fr245` | baseline | 972 B | 413 B | 90,476 B |
| `fenix6` / `fr245` | vector (guarded, falls back) | 978 B | 458 B | 90,620 B |

All three test devices produced byte-identical figures, which is expected:
they share a `deviceFamily` resource path and none of the three variants
contains anything device-dependent.

## What this probe does *not* establish

**Runtime** behaviour. `--build-stats` reports static data and code; it says
nothing about heap or graphics-pool occupancy while the face runs, and
nothing about how the two fonts actually *look*. Answer (d) is therefore an
inference from the build figures plus the SDK's statement that font resources
load into the graphics pool from API 4.0.0, not a measurement of the pool.
Running it needs the simulator, which does not survive `monkeydo` in any
environment tried here (root `CLAUDE.md` §3).
