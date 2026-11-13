# Probe: where `TEXT_JUSTIFY_VCENTER` puts a baked font's line top

**Question.** When `Dc.drawText` draws a baked (BMFont `.fnt`) font with
`TEXT_JUSTIFY_VCENTER` at `y`, where does the font's line top land, as a
function of the font's `lineHeight` and `base`? The compiler's model was
`y - lineHeight/2`; the simulator disagrees by about 2 px for the one font
measured so far.

**What the compiler does meanwhile.** A centred baked icon (`type: icon`,
a `type: data` icon beside or curved with its reading, a ring font with its
glyph) is no longer drawn with `VCENTER`: it is drawn top-justified at
`y - ceil(lineHeight / 2)`, a per-device build-time number (`<ID>_TOP`, or
`<ID>_ICON_HALF` subtracted from the runtime `y`), and the preview draws the
same top. Baked *text* fonts still use `VCENTER`; this probe also measures
one, to tell whether they share the offset. The rule is in
`docs/lore/rendering.md` ("Baked fonts and `VCENTER`").

## Evidence so far

Observed in the user's Connect IQ simulator (macOS host, 2026-11-13), on
`fenix8solar51mm`, face `fenix-sectors`, its `pocket_top` data element:
reading in `RobotoCondensedBold` (a `face:` vector font, 20%r) and slot icon
`icon_20pctr_slot_pocket_top.fnt` (`lineHeight=41 base=32`; battery glyph
`yoffset 7 height 28`, heart `yoffset 9 height 23`, pressure gauge
`yoffset 7 height 28`), both drawn at `Layout.POCKET_TOP_CY = 46` with
`TEXT_JUSTIFY_LEFT | TEXT_JUSTIFY_VCENTER`. Screenshots at 2 px per watch
pixel, mapped through the orange pocket frame that preview and simulator
draw identically:

| | digits | battery ink | heart ink | gauge ink |
|---|---|---|---|---|
| `wfb preview` (line top at `46 - 20.5`) | 37-54 | 32-60 | 34-57 | 32-60 |
| simulator | 37.25-54.25 | 34.25-62.25 | 36.25-59.25 | 34.25-62.25 |

- VERIFIED (simulator, one capture): the vector-font reading lands where
  the compiler predicts it.
- VERIFIED (simulator, one capture): every icon lands about 2 px lower than
  the preview, consistent with a line top at about `y - 18.75` instead of
  `y - lineHeight/2 = y - 20.5`.
- UNVERIFIED: the rule behind it (`base`? `lineHeight - base`? a rounding
  of `lineHeight/2` plus a constant?), other line heights, odd against even,
  other devices, baked text fonts, and real hardware.

## The face

`face.yaml`, for `fenix8solar47mm`, `fenix8solar51mm` and `fr955`. Five
rows, one icon size each (`10%r`, `15%r`, `20%r`, `25%r`, `30px`), each
centred on a **1 px red reference line at a known row `y`**. On each row,
left to right, every glyph is white:

| element | x from centre | drawn as |
|---|---|---|
| `new_<row>` | -50 px | the compiler's placement: the heart icon, `drawText(cx, y - ceil(lineHeight/2), font, glyph, TEXT_JUSTIFY_CENTER)` |
| `old_<row>` | -10 px | the same glyph in the same font, patched by `build.sh` to the old call: `drawText(cx, y, font, glyph, TEXT_JUSTIFY_CENTER \| TEXT_JUSTIFY_VCENTER)` |
| `text_<row>` | +40 px | `"H8"` in a baked text font (Open Sans, 14%r, the test fixture's TTF), `drawText(x, y, font, "H8", TEXT_JUSTIFY_CENTER \| TEXT_JUSTIFY_VCENTER)` |

The rows, the fonts' metrics as baked (the `build.sh` printout) and where
the compiler's placement puts the heart's ink (rows inclusive: cell top
plus `yoffset`, through `+ height - 1`):

`fenix8solar47mm` and `fr955` (identical bakes):

| size | row `y` | lineHeight | base | heart yoffset, height | `new` cell top | `new` ink rows |
|---|---|---|---|---|---|---|
| 10%r | 35 | 18 | 14 | 3, 12 | 26 | 29-40 |
| 15%r | 68 | 28 | 22 | 4, 19 | 54 | 58-76 |
| 20%r | 110 | 38 | 30 | 6, 26 | 91 | 97-122 |
| 25%r | 162 | 46 | 36 | 7, 31 | 139 | 146-176 |
| 30px | 215 | 43 | 34 | 6, 29 | 193 | 199-227 |

`fenix8solar51mm`:

| size | row `y` | lineHeight | base | heart yoffset, height | `new` cell top | `new` ink rows |
|---|---|---|---|---|---|---|
| 10%r | 45 | 20 | 16 | 3, 14 | 35 | 38-51 |
| 15%r | 78 | 29 | 23 | 4, 20 | 63 | 67-86 |
| 20%r | 120 | 41 | 32 | 6, 28 | 99 | 105-132 |
| 25%r | 172 | 49 | 39 | 7, 33 | 147 | 154-186 |
| 30px | 225 | 43 | 34 | 6, 29 | 203 | 209-237 |

So the rows cover even line heights (18, 20, 28, 38, 46) and odd ones (29,
41, 43, 49), on both screen sizes. The text font is `lineHeight=26 base=20`
on the 260 px screens and `28 / 22` on `fenix8solar51mm` (`H` and `8`:
`yoffset 6`, `height 13` there; `yoffset 7`, `height 14`/`15` here).

## Build and run (on the user's host)

The container cannot run the simulator (it segfaults there), so the
measurement is the user's. From the repository root:

```sh
sh docs/research/probes/icon-vcenter/build.sh build/icon-vcenter
connectiq &
monkeydo build/icon-vcenter/icon-vcenter-fenix8solar51mm.prg fenix8solar51mm
monkeydo build/icon-vcenter/icon-vcenter-fenix8solar47mm.prg fenix8solar47mm
monkeydo build/icon-vcenter/icon-vcenter-fr955.prg fr955
```

`build.sh` runs `./wfb build face.yaml --no-compile`, adds
`TEXT_JUSTIFY_VCENTER` to the five `drawOld*` calls (and stops if it did
not patch exactly five), compiles each device with `monkeyc -w -l 3`
(`CIQ_SDK` set; the key is `~/ciq/developer_key.der` unless `CIQ_KEY` says
otherwise), and prints every font's `common` line and drawn glyphs. It
builds warning-free on all three in the container (SDK 9.3.0,
2026-11-13). `wfb preview` of `face.yaml` shows the unpatched face, the
`old_*` icons top-aligned; it is not the comparison.

## What to measure and report

For each device, save one screenshot, then for every row read, in watch
pixels (a capture is 2x on a Retina Mac; read a device pixel as its 2x2
block, as in `docs/lore/rendering.md`, "Reading a capture"):

1. the red line's row (expected: the row `y` above);
2. the first and last rows of the `new_` heart's ink (expected: the table's
   `new` ink rows, if the simulator draws a top-justified baked glyph at its
   cell top plus `yoffset`, as the preview does);
3. the first and last rows of the `old_` heart's ink; its line top under
   `VCENTER` is then `first ink row - yoffset`;
4. the first and last rows of the `text_` ink (`H` and `8`), and the line
   top that gives the same way.

Report, per row and device: `lineHeight`, `base`, the measured `VCENTER`
line top as an offset from `y` for the icon and for the text font, and
whether the `new_` heart's ink matched the table. The answer wanted is the
rule `top = y - f(lineHeight, base)` for both, which decides whether baked
text fonts need the same treatment and whether the icons' rule should
become something other than `ceil(lineHeight / 2)`.
