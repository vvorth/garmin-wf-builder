# Handoff: where does a watch draw a baked icon font? (simulator test runs)

For a Claude Code session (or a person) **with the Connect IQ simulator**:
the user's Mac, or Windows. The cloud container that wrote this cannot run
the simulator: it segfaults there. Your job is to run the probe in this
folder on several screen sizes, measure the screenshots with the script
here, and decide the compiler's icon placement from the numbers. Read the
whole file before starting.

Repository: `vvorth/garmin-wf-builder`. The fix described below is on
`main` (commit `c3b8d98`). The probe tools in this folder (portable
`face.yaml`, `build.sh` taking `DEVICES`, `measure.ts`, this file) were
committed on top of it, on branch `claude/eloquent-rubin-suzh1w`; check
`git log --oneline -3 -- docs/research/probes/icon-vcenter/` to find them.

---

## 1. The problem

The user's face `fenix-sectors` (repo `vvorth/wfb-watchfaces`, file
`fenix-sectors.yaml`; in this repository it is the `examples/other`
submodule) has two "pockets" above and below the clock. Each pocket is a
`type: data` element showing a slot: an icon beside a short reading.

```yaml
pocket_top:
  type: data
  slot: pocket_top
  font: font.pocket          # face: [RobotoCondensedBold, ...], size: 20%r (a device vector font)
  icon: { size: 20%r, gap: 4%r, color: color.fg }
  at: { anchor: center, dy: -67%r }
```

In the simulator (`fenix8solar51mm`), every pocket icon (battery, heart,
pressure gauge) looked low next to the digits. The battery looked worst
because it is the tallest glyph and a solid block under a thin cap.

## 2. What was measured

All values are watch pixels (rows) on `fenix8solar51mm`. The user's
screenshots are 2 screenshot px per watch px. The mapping was taken from the
pocket's orange (later blue) frame lines, which the preview and the
simulator draw identically: watch row 23 ↔ screenshot rows 358–359, so
`row = 23 + (screenshot_y − 358) / 2`.

The baked slot icon font: `icon_20pctr_slot_pocket_top.fnt`, `lineHeight=41
base=32`. Glyphs: battery `yoffset 7 height 28`, heart `yoffset 9 height
23`, gauge `yoffset 7 height 28`. The pocket's centre row is
`POCKET_TOP_CY = 46`.

| Top pocket | Ink rows (inclusive) | Centre vs digits |
|---|---|---|
| digits "90" (vector font, `TEXT_JUSTIFY_VCENTER`) | 37–53 in the preview and the simulator | — |
| battery, **before** the fix (simulator, icon drawn with `TEXT_JUSTIFY_VCENTER` at 46) | 34–61 | 2.5 px low |
| battery, preview's model before and after the fix | 32–59 | 0.5 px low |
| battery, **after** the fix (simulator, icon drawn top-justified at 46 − 21 = 25) | 33–60 | 1.5 px low |

The heart and the gauge moved exactly like the battery in both captures.

**Finding A.** The vector-font reading lands exactly where the compiler
predicts it.

**Finding B.** After the fix, a top-justified baked glyph lands exactly
**1 px lower** than `top + yoffset`.

**Hypothesis H1** (fits both captures, from one font at one size): the
simulator draws every baked (BMFont) glyph 1 px below where its `.fnt`
places it, and `TEXT_JUSTIFY_VCENTER` puts a BMFont's line top at
`y − floor(lineHeight / 2)`.
- Before: 46 − 20 = 26, then 26 + 7 + 1 = 34. ✓
- After: 25 + 7 + 1 = 33. ✓

## 3. Why not just subtract 1 px now

The user's concern, and it is right. A constant −1 is only safe if the drop
is constant. It could instead:
- depend on the line height or its parity (odd lines round one way, even
  the other), so small icons end up too high;
- scale with screen resolution, so 390–454 px AMOLED screens drop 2 px;
- depend on the font's `base` or the glyph's own metrics;
- be a simulator artefact that a real watch does not have;
- also affect baked **text** fonts, which still use `TEXT_JUSTIFY_VCENTER`.

So: measure several line heights on several resolutions first, then decide.

## 4. What the compiler does now (the fix on `main`)

A centred baked icon is drawn **top-justified at `y − ceil(lineHeight/2)`**,
a per-device build-time number, instead of with `TEXT_JUSTIFY_VCENTER`. The
preview draws the same top, so the preview and the generated code agree by
construction.
- `ts/src/layout.ts`: `iconHalfLine(lineHeight)` returns
  `Math.ceil(lineHeight / 2)`. **This is the one place to add a
  compensation** (e.g. `+ 1`), and the preview follows automatically.
- `ts/src/kinds/icon.ts` (`type: icon`): `Layout.<ID>_TOP` replaces
  `<ID>_CY`; the outline ring uses the same top.
- `ts/src/kinds/data.ts` (`type: data` icon beside, angled, pinned or
  tracked radial): `y − Layout.<ID>_ICON_HALF`, or `_ICON_HALVES[step]` for
  stepped turned fonts.
- `docs/lore/rendering.md` ("Baked fonts and `VCENTER`") and
  `docs/limitations.md` record it.
- Not changed: stacked icons and `align: top`/`bottom` (they never used
  VCENTER); baked text fonts.

For `fenix-sectors` on `fenix8solar51mm` the generated call is:

```
dc.drawText(startX, Layout.POCKET_TOP_CY - Layout.POCKET_TOP_ICON_HALF, iconFont, iconGlyph, Graphics.TEXT_JUSTIFY_LEFT);
// Layout.mc: POCKET_TOP_CY = 46, POCKET_TOP_ICON_HALF = 21 (41 px line, rounded up)
```

## 5. The probe (this folder)

- **`face.yaml`**: five rows (icon sizes `10%r`, `15%r`, `20%r`, `25%r`,
  `30px`). Each row is centred on a 1 px **red** reference line. On each row:
  - `new_` heart: the compiler's placement;
  - `old_` heart: patched to the old `TEXT_JUSTIFY_VCENTER` call;
  - `text_` "H8": a baked text font (Open Sans), drawn with VCENTER.

  Positions are in `%r`, so it fits 218–454 px screens. The monochrome
  Instinct screens cannot show red, so leave them out.
- **`build.sh`**: generates, patches the five `old_` draws (and fails unless
  exactly five were patched), compiles with `monkeyc -w -l 3`, and prints
  each font's metrics. `DEVICES="…"` picks the devices.
- **`measure.ts`**: reads a screenshot and prints a table per row:
  - the model and seen ink rows of `new_`, and `new Δ` (seen − model;
    positive means the watch draws lower);
  - the line top implied for `old_` and `text_` under VCENTER, as `y − top`
    next to the model `y − ceil(lineHeight/2)`.

  It needs only Node (the repository's own PNG decoder). It works out the
  scale from the red lines' known width, so Retina 2× or any zoom is fine.
  It was validated on `wfb preview` output of all nine devices below:
  `new Δ = 0` everywhere. In the preview, `old_` is drawn unpatched, so its
  column is meaningless there; in the simulator it is real.

## 6. Run it

Prerequisites on the host: the SDK (`CIQ_SDK`), the developer key
(`~/ciq/developer_key.der`, or `CIQ_KEY`), the device files, and Node ≥
24.22.1 (`./tools/setup-env.sh` on Linux; on macOS the SDK Manager
provides the SDK and devices). `docs/lore/toolchain.md` covers the
details; on Windows, the repository's `simulator-control` skill drives the
simulator.

```sh
git fetch origin && git checkout claude/eloquent-rubin-suzh1w   # or main once merged
DEVICES="vivoactive4s fr245 fenix8solar47mm fr955 fenix8solar51mm venusq2 venu epix2 fenix847mm" \
  sh docs/research/probes/icon-vcenter/build.sh build/icon-vcenter
P=$(dirname "$(ls build/icon-vcenter/*/monkey.jungle)")    # the generated project
connectiq &                                                # the simulator (macOS: open the SDK's ConnectIQ.app)
monkeydo build/icon-vcenter/icon-vcenter-fenix8solar51mm.prg fenix8solar51mm
# screenshot the simulator window (macOS: Cmd+Shift+4, Space, click the window) to e.g. shots/fenix8solar51mm.png
node docs/research/probes/icon-vcenter/measure.ts shots/fenix8solar51mm.png "$P" fenix8solar51mm
```

Repeat `monkeydo` + screenshot + `measure.ts` for every device. All nine
build warning-free under `-l 3` with SDK 9.3.0 (checked 2026-11-13). The
probe's own lint warnings (`off-screen`/`safe-area` on the smallest screens,
`aod-empty` on AMOLED) are expected and harmless.

The test matrix and what each device adds:

| Device | Screen | Why |
|---|---|---|
| vivoactive4s | 218 round MIP | smallest colour screen: small line heights (15–43) |
| fr245 | 240 round MIP | small |
| fenix8solar47mm, fr955 | 260 round MIP | the user's watches (47 mm is the user's; fr955 too) |
| fenix8solar51mm | 280 round MIP | the user's watch; the face that showed the bug |
| venusq2 | 320×360 rectangular AMOLED | non-round, mid resolution |
| venu | 390 round AMOLED | high resolution |
| epix2 | 416 round AMOLED | high resolution |
| fenix847mm | 454 round AMOLED | highest resolution installed (line heights up to 82) |

## 7. Decide from the numbers

Collect, for every device and row: the line height, `new Δ`, `old: y − top`
(with the model next to it) and `text: y − top`. Then:

1. **`new Δ` is +1 on every row of every device.** H1 holds for top-justified
   glyphs. Change `iconHalfLine` to `Math.ceil(lineHeight / 2) + 1`. That
   draws icons 1 px higher, and the preview must model the same top, which
   it does by construction. Then:
   - regenerate the goldens (`cd ts && node tools/goldens.ts`, after
     reviewing the diff);
   - update the probe README's expectations and `docs/lore/rendering.md`;
   - re-run the probe once to see `new Δ = 0`;
   - rebuild `fenix-sectors` for the user to check the pockets.
2. **`new Δ` varies** with line height, parity, `base` or resolution. Fit the
   rule from the table (e.g. `+1` on odd lines only, or `round(scale)` on
   high-res), put it in `iconHalfLine` (or a sibling that also takes the
   device or `base`), and say in the lore which rows prove it. If it
   depends on the device, the value must stay a per-device `Layout.mc`
   constant, as it already is.
3. **`new Δ` is 0 everywhere.** The fix is already exact in the simulator,
   and the user's capture had something else going on. Re-capture
   `fenix-sectors`.
4. **`text: y − top` differs from its model** in the same way as `old:`.
   Baked text fonts share the problem; extend the same top-justified
   placement to baked text drawn with VCENTER (`ts/src/kinds/text.ts`, the
   data reading, pattern text parts). Leave vector (`face:`) fonts alone:
   Finding A.
5. **Real hardware**, optional but best: sideload the probe to the user's
   fēnix 8 / fr955 and photograph it. A simulator-only artefact would show
   as `Δ = 0` on the watch.

## 8. Report back

Paste each device's `measure.ts` table, the device list, the SDK and
simulator versions, and the screenshots. Record the result in the probe
README ("Evidence so far": VERIFIED/UNVERIFIED per docs/CLAUDE.md research
rules) and in `docs/lore/rendering.md`. Any compiler change goes in its own
commit with the evidence in the message. The project's working agreement
(root `CLAUDE.md` §7) applies: the build bar is warning-free, and the fast
suite (`cd ts && npm test`) must stay green.
