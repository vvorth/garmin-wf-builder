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
nothing about heap or graphics-pool occupancy while these three variants
run. Answer (d) is therefore an inference from the build figures plus the
SDK's statement that font resources load into the graphics pool from API
4.0.0, not a measurement of the pool. None of the three variants here uses
`curve:` — they draw straight, upright text — so this probe has nothing to
say about `drawAngledText`/`drawRadialText` or glyph facing; that question
is answered separately, below.

## Radial glyph-facing: confirmed against the real simulator, both directions (2026-09-21)

`wfb preview`'s radial glyph-facing model — `direction: clockwise` faces
glyphs outward, `counter_clockwise` faces inward, so text along the bottom
of a dial reads right-side up — was, until now, an inference from
text-on-a-path convention and Garmin's own `TrueTypeFontsRadialText.mc`
sample, never checked against a real device or simulator (full derivation:
`docs/research/12-vector-fonts.md`, `wfb/preview.py`'s
`_draw_radial_vector_text`).

The user ran the real Connect IQ simulator on their macOS host, on
`fenix8solar47mm`, against `examples/features/vector-text/face.yaml` — the
shipped example, which now authors **both** directions: `wordmark`
(`curve: {style: radial, direction: counter_clockwise}`), `left_cw`
(`clockwise`), and the pair `top_ccw`/`top_cw` at the *same* `angle:` and
`radius:`, opposite `direction:` — the controlled comparison that isolates
facing from position, since the two texts occupy the same spot on the dial
and differ in nothing else.

`radial-facing-simulator-vs-preview.png` (original, `counter_clockwise`
only) and `radial-facing-both-directions.png` (current: full dials,
simulator left half, `wfb preview` right half, both cropped to the display
and scaled to the same dial diameter) are both in this directory;
`radial-facing-top-pair.png` magnifies just the `top_cw`/`top_ccw` pair,
simulator above and preview below. They agree on:

- **glyph facing, both directions** — `clockwise` (`left_cw`, `top_cw`)
  faces glyphs outward: "TOP CW" reads normally over the top of the dial,
  "WORLD'S END" runs bottom-to-top up the left side; `counter_clockwise`
  (`wordmark`, `top_ccw`) faces glyphs inward: "FIELD TRACK" reads normally
  along the bottom, "TOP CCW" is inverted at the top;
- the `top_cw`/`top_ccw` pair's shared angular position and radius, direction
  isolated as the only variable;
- the twelve hour numerals' tangent phase (`12` upright at top, `3`/`9` on
  their side, `6` inverted);
- the `SOLAR` angled badge's position and tilt.

The one visible difference is glyph *shape* — the simulator draws the real
`BionicSemiBold`, `wfb preview` a located stand-in — which is the
pre-existing "glyph rendering is approximate" caveat, unrelated to facing.

This is evidence for one device (`fenix8solar47mm`), in the simulator (not
physical hardware). Both `direction:` branches are now directly exercised.

## Radial vertical alignment (`top`/`bottom`): baseline-on-the-circle, measured 2026-09-21

The facing comparison above never varied `vertical_align:`, so it said
nothing about *where along the radius* a curved run actually sits — that
gap is what a follow-up pixel measurement on the same `top_cw`/`top_ccw`
pair (against the centred `wordmark`/`left_cw`) closed, still on
`fenix8solar47mm`, `radius: 60%r` = 78px:

| run | `vertical_align:` | device ink radii (px) |
|---|---|---|
| `wordmark`/`left_cw` | `center` | 73–82 |
| `top_cw`/`top_ccw` (as then emitted: bare radius, no `TEXT_JUSTIFY_VCENTER`) | `top` | clockwise 77.7–86.7; counter_clockwise 68.8–76.9 |

That is `Dc.drawRadialText` putting the text's **baseline**, not the line
box, on the circle when `TEXT_JUSTIFY_VCENTER` is absent — each glyph grows
toward its own "up" (outward under `clockwise`, inward under
`counter_clockwise`). `wfb preview` and `wfb.layout`'s lint band had `top`
hanging the *opposite* way at the time (predicted clockwise 65.5–73.9,
counter_clockwise 82.2–90.7): a real bug, not a rendering-fidelity gap —
`top` was landing outside the ring the compiler thought it occupied. Fixed
by changing what codegen emits, not the lint model: `top` now asks the
device for `Layout.<P>_RADIUS -/+ Graphics.getFontAscent(font)` rather than
the bare radius (`wfb.emit.monkeyc.shapes._radial_radius_expr`), which
walks the baseline one ascent toward the glyphs' "down" side so the *line
box's* top edge, not its baseline, lands on the circle — matching what the
preview and lint band already assumed. `bottom` (previously rejected as a
build error under any `curve:`) is accepted under `style: radial` as of
the same fix, using the device's native no-`VCENTER` placement measured
here directly, with no radius offset needed. Full derivation and the
`ascent`/`descent` split: `docs/research/12-vector-fonts.md` §5.3. **The
new `top` offset itself has not yet been rebuilt and reloaded on the
simulator** — this table's `top` row is the *pre-fix* emission; only the
diagnosis is device-measured, not yet the fix's own output.
