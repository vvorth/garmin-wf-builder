# Probe: where the watch draws a baked font's line

**Question.** When `Dc.drawText` draws a baked (BMFont `.fnt`) font, where
does the font's line land: top-justified at `top`, and centred with
`TEXT_JUSTIFY_VCENTER` at `y`, as a function of the font's `lineHeight`,
`base` and the screen?

**Answer** (simulator, nine devices, 2026-11-14):

- Every baked glyph lands **1 px below** its `.fnt` place: top-justified at
  `top`, its ink covers rows `top + yoffset + 1` to `top + yoffset + height`.
  The same on all 45 rows, at line heights 15 to 82 (odd and even), on
  218 to 454 px screens, MIP and AMOLED, round and rectangular.
- Under `VCENTER` a baked line's cell lands **1 or 2 px below**
  `y - ceil(lineHeight / 2)`, icons and text alike, by no rule that the
  line height, `base` or screen explains. The same 43 px font gave 1 px on
  some devices and 2 px on others.

**What the compiler does with it** (`docs/lore/rendering.md`, "Baked fonts
and `VCENTER`"): a centred line in a baked font (an icon, a text, a data
reading beside its icon, a pattern's text part) is drawn top-justified from
`y - ceil(lineHeight / 2) - 1` (`bakedHalfLine` in `ts/src/layout.ts`), a
per-device constant, so its cell lands at `y - ceil(lineHeight / 2)`. The
preview pastes every baked glyph 1 px low, as the watch does.

## Evidence

### 1. The first sighting (one capture)

The user's Connect IQ simulator (macOS host, 2026-11-13), on
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

### 2. This probe, nine devices

Connect IQ SDK 9.3.0 simulator on a Windows host, 2026-11-14, one capture
per device and build, read by `measure.ts`. "Before" is the build whose
`new_` icon was drawn top-justified at its cell top `cy - ceil(lineHeight/2)`
and whose `text_` used `VCENTER`; "after" draws both from 1 px higher (the
compiler's current placement). Each Δ is the seen row minus the centred
cell's row (`cy - ceil(lineHeight/2)` plus the glyph's `yoffset`); positive
means lower. `old` is the icon patched to `VCENTER` in both builds.

| Device | Screen | Icon line heights | Text line | new Δ before → after | text Δ before → after | old Δ (`VCENTER`) |
|---|---|---|---|---|---|---|
| vivoactive4s | 218 round MIP | 15, 24, 30, 39, 43 | 22 | +1 ×5 → 0 ×5 | +1 ×5 → 0 ×5 | +2 +1 +1 +2 +2 |
| fr245 | 240 round MIP | 17, 25, 34, 43, 43 | 24 | +1 ×5 → 0 ×5 | +1 ×5 → 0 ×5 | +2 +2 +1 +2 +2 |
| fenix8solar47mm | 260 round MIP | 18, 28, 38, 46, 43 | 26 | +1 ×5 → 0 ×5 | +1 ×5 → 0 ×5 | +1 +1 +1 +1 +2 |
| fr955 | 260 round MIP | 18, 28, 38, 46, 43 | 26 | +1 ×5 → 0 ×5 | +1 ×5 → 0 ×5 | +1 +1 +1 +1 +2 |
| fenix8solar51mm | 280 round MIP | 20, 29, 41, 49, 43 | 28 | +1 ×5 → 0 ×5 | +1 ×5 → 0 ×5 | +1 +2 +2 +2 +2 |
| venusq2 | 320×360 AMOLED | 24, 34, 45, 58, 43 | 31 | +1 ×5 → 0 ×5 | +2 ×5 → 0 ×5 | +1 +1 +2 +1 +2 |
| venu | 390 round AMOLED | 28, 42, 56, 69, 43 | 37 | +1 ×5 → 0 ×5 | +2 ×5 → 0 ×5 | +1 +1 +1 +2 +2 |
| epix2 | 416 round AMOLED | 29, 44, 61, 74, 43 | 40 | +1 ×5 → 0 ×5 | +1 ×5 → 0 ×5 | +2 +1 +2 +1 +2 |
| fenix847mm | 454 round AMOLED | 32, 48, 65, 82, 43 | 45 | +1 ×5 → 0 ×5 | +2 ×5 → 0 ×5 | +1 +1 +2 +1 +2 |

The captures are `captures/<device>-before.png` and `-after.png`, and
`captures/measure.txt` is `measure.ts`'s full output for all eighteen.
On `epix2` the skin's red START button shares a row with the first red
line, so its captures were measured with the button painted black
(`measure.ts` takes a row's leftmost to rightmost red pixel as the line).

- VERIFIED (simulator, nine devices): a baked glyph drawn top-justified
  lands 1 px below its `.fnt` place, at every line height measured.
- VERIFIED (simulator, nine devices): with the 1 px compensation, a centred
  baked icon and a centred baked text land exactly on
  `y - ceil(lineHeight / 2)` (Δ 0 on all 90 measurements).
- VERIFIED (simulator, nine devices): `VCENTER` on a baked font puts the
  cell 1 or 2 px below `y - ceil(lineHeight / 2)`, with no rule visible in
  line height, parity, `base` or screen.
- VERIFIED (simulator, one capture): a `face:` vector font under `VCENTER`
  lands where the compiler predicts.
- UNVERIFIED: real hardware (a simulator-only artefact would show as the
  "after" icons and text sitting 1 px high on a watch); system fonts
  (`FONT_*`) under `VCENTER`; a turned baked font's drop (assumed the same:
  the preview drops every baked glyph).

## The face

`face.yaml`, for any colour watch-face device (`build.sh` takes `DEVICES`;
the monochrome Instinct screens cannot show the red lines). Five rows, one
icon size each (`10%r`, `15%r`, `20%r`, `25%r`, `30px`), each centred on a
**1 px red reference line at row `y`** (its top; the glyphs centre on the
rounded `y + 1/2`). On each row, left to right, every glyph is white:

| element | x from centre | drawn as |
|---|---|---|
| `new_<row>` | -46%r | the compiler's placement: the heart icon, `drawText(cx, NEW_<ROW>_TOP, font, glyph, TEXT_JUSTIFY_CENTER)` |
| `old_<row>` | -9%r | the same glyph in the same font, patched by `build.sh` to `drawText(cx, cy, font, glyph, TEXT_JUSTIFY_CENTER \| TEXT_JUSTIFY_VCENTER)` |
| `text_<row>` | +33%r | `"H8"` in a baked text font (Open Sans, 14%r, the test fixture's TTF): the compiler's placement, `drawText(x, TEXT_<ROW>_Y - TEXT_<ROW>_HALF, font, "H8", TEXT_JUSTIFY_CENTER)` |

Rows and glyphs are placed in `%r`, so the same face fits every screen from
218 px to 454 px; each device bakes its own line heights (odd and even ones
on every screen). `build.sh` prints every font's `common` line and the
drawn glyphs' metrics per device, and `measure.ts` computes the expected
rows from the generated `Layout.mc` and `.fnt` files itself.

## Build, run and measure

On a host with the simulator (macOS, or Windows, where the repository's
`simulator-control` skill drives it). From the repository root:

```sh
DEVICES="vivoactive4s fr245 fenix8solar47mm fr955 fenix8solar51mm venusq2 venu epix2 fenix847mm" \
  sh docs/research/probes/icon-vcenter/build.sh build/icon-vcenter
P=$(dirname "$(ls build/icon-vcenter/*/monkey.jungle)")
connectiq &
monkeydo build/icon-vcenter/icon-vcenter-fenix8solar51mm.prg fenix8solar51mm
# screenshot the simulator window to shots/fenix8solar51mm.png
node docs/research/probes/icon-vcenter/measure.ts shots/fenix8solar51mm.png "$P" fenix8solar51mm
```

`build.sh` runs `./wfb build face.yaml --no-compile`, adds
`TEXT_JUSTIFY_VCENTER` to the five `drawOld*` calls (and stops if it did
not patch exactly five), compiles each device with `monkeyc -w -l 3`
(`CIQ_SDK` set; the key is `~/ciq/developer_key.der` unless `CIQ_KEY` says
otherwise), and prints every font's `common` line and drawn glyphs. All
nine build warning-free (SDK 9.3.0, 2026-11-14). `wfb preview` of
`face.yaml` shows the unpatched face, the `old_*` icons top-aligned; it is
not the comparison.

`measure.ts` finds each row's red line (its width in `Layout.mc` gives the
screenshot's scale, so any zoom works), reads the white ink in a window
round each glyph, and prints per row the `new_` icon's model and seen ink
rows and their Δ, and the line top and Δ of `old_` and `text_`. Each model
is the element's own centre less `ceil(lineHeight / 2)`; `text_`'s line top
is read from the higher of `H` and `8` (on `venu` the `8` sits a row above
the `H`).
