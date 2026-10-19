# 34 — A curved slot: turned icons, `slot:` on an icon, a curved reading

**Status: in progress. Slices 1–5 and most of 7 done; slice 6 built, not yet verified on a watch (§5 check 2 done, its gate passed by the baseline-spacing rule). D1–D8 decided (2026-10-18); D7 refined while building slices 5 and 6.** Delete this file once every slice has shipped
(`docs/CLAUDE.md`).

Research: `docs/research/35-curved-slot-reading.md`. In short:

* Curved text (`drawAngledText`/`drawRadialText`) needs a device-resident
  vector font, on 44 of 136 watch-face devices. `type: data` refuses
  `face:` fonts today.
* An icon is a baked glyph. It turns cleanly only if it is baked already
  turned: the baker rotates the outline before rasterising. Turning a
  bitmap at runtime (`drawBitmap2` + `AffineTransform`) compiles, but is
  rougher on MIP and has no faithful preview.
* A slot's pieces can already be separate elements: `type: gauge` takes
  `slot:`. `type: icon` can take it the same way.

The face this is for (the user's example): a segmented gauge round the
edge, an icon, and the reading along the bezel, all one wearer-picked
slot, with touch and hold opening whatever the slot shows.

## 1. Decisions

### Decided

- **D1: scope is the research's three steps (2026-10-18).** Free
  placement (`type: icon` + `slot:`, `rotate:`, a curved reading), a
  curved pair with the icon on the pinned end, then the free end and a
  centred pair.
- **D2: no automatic fallback (2026-10-18).** A curved reading on a
  device without vector fonts follows `unsupported: error | hide`, exactly
  as a curved `type: text` does. Nothing redraws it upright in another
  font.
- **D3: a group's `on_hold:` follows a slot (2026-10-18).** See D5 for
  the spelling.
- **D4: the runtime transform is not built (2026-10-18).** Every turned
  icon is baked turned (research 35 §4, option B). The probe stays as
  evidence.

### Decided as recommended (2026-10-18)

- **D5: `on_hold: auto` on a group follows the one slot inside it.**
  Recommended spelling: no new syntax. A group's `auto` looks at its
  descendants. If exactly one distinct slot is bound among them (`type:
  data`, or a gauge or icon with `slot:`), the hold calls
  `Complications.exitTo` on that slot's id, read fresh on every hold as a
  data element's own `auto` already does. Two different slots is
  `hold-auto-ambiguous`. No slot keeps today's rule (one fixed source, or
  `hold-auto-unresolved`). Fixed-source members of a slot group (a text
  bound to `time.hour`, say) do not count. *Alternative:* `on_hold:
  {slot: top}`, explicit but a second spelling for something `auto`
  already means everywhere else.
- **D6: each turned angle is its own baked font; the characters stay
  the icon's own.** A baked icon font is a table from character code to
  picture. A turned copy of an icon cannot share its code with the
  upright one in the same font. So either each angle is a separate font
  that reuses the same codes (recommended), or one font carries every
  angle and each turned copy gets an invented code. Separate fonts need
  no invented codes, keep `IconGlyphs` and the per-choice `codepoint:`
  overrides unchanged, and extend today's font key (size, glyph set,
  anti-aliasing) with an angle. The cost is one loaded font handle per
  angle. Slice 5 measured it: a pinned radial pair beside a same-size
  slot icon (two fonts) against the same pair `upright: true` (one shared
  font) on `fenix8solar47mm` is 6,404 B against 6,348 B, **+56 B** (18 B
  data, 38 B code) for the extra handle. Separate fonts stay. If that ever
  grows too costly, change to invented codes
  in the Unicode private-use planes (U+F0000–U+10FFFF), which the
  vendored icon font does not use.
- **D7: a pinned radial icon gets one exact turn per device; a free-end
  (or centred-pair) icon snaps to 3° steps, baked per device and named
  in `Layout.mc`.** (Refined while building slices 5 and 6.) A pinned
  icon's centre is at a build-time angle, θ₀ ∓ (gap + reference advance /
  2) / R, every other choice's glyph centred on the same point, so there
  is exactly one turn to bake and no step to pick on the watch. R, the gap
  and the reference glyph's advance are per device, so the turn is too,
  and the generated view is one file shared by every target: the font
  therefore has **one resource name on every device** (an
  element-specific key with no angle in it), and each device's bake
  resolves the turn itself (`PinnedTurn` in `ts/src/icons.ts`, read by
  both `iconFontSpecs` and the layout).

  A free-end icon's angle is only known on the watch: θ = θ₀' + k ·
  textWidth, with k = ±1/R_s (±1/(2 R_s) beside a centred run) and R_s the
  run's baseline radius (`radialSpacingRadius`, §5 check 2). Its glyph is
  baked at 3° steps from the shortest reading's angle to the widest's on
  each device (`SteppedTurn` in `ts/src/icons.ts`, again one function for
  the bake and the layout), and the watch draws step round(textWidth ·
  |k| / 3°), clamped to the last: at most 1.5° off, about 0.3 px at the edge
  of a 24 px glyph. **How the shared view names a per-device set of
  fonts:** the step count differs per device (R, the font and the widest
  reading all do), so the steps' `Rez.Fonts` ids are not in the view at
  all. Each device's `Layout.mc` holds them, `const <P>_ICON_STEPS as
  Array<ResourceId> = [Rez.Fonts.…S0, …]`, beside `<P>_ICON_LAST` and the
  arithmetic's constants; the view only indexes it. Chosen over a fixed
  step count N per element (option a): N would have to be bounded with
  no device list, over-baking every device to the worst one's range, while
  per-device arrays bake exactly each device's own range and cannot fall
  short of it. A bake and a layout that ever disagree on the count or a
  turn throw at resolve time (`DataKind.resolve`), rather than draw a
  wrong glyph. **Only the step in use is loaded**: one view field and its
  index per element, `WatchUi.loadResource` on the frame the step
  changes. Loading every step in `onLayout` would cost a font handle each
  (+56 B a handle, slice 5's measure; 31 steps for a slot with the
  weather is about 1.7 KB) and the steps would sit loaded all day.
  Measured on `fenix8solar47mm` (`--build-stats`), a free-end pair beside
  the same pair at the fixed end: with steps, floors, Body Battery,
  stress, heart rate and the weather (31 steps), 4,190 + 7,624 B against
  3,902 + 6,777 B, **+1,135 B** memory, `.prg` 156,092 against 114,348 B;
  without the weather (8 steps), 1,705 + 5,006 B against 1,624 + 4,665 B,
  **+422 B**, `.prg` 109,324 against 106,220 B. The weather's condition
  text is the widest reading any slot has, and each step carries every
  weather glyph.

  An angled curve and a fixed `rotate:` are one exact angle.
- **D8: the key names.** `rotate: <Angle>` on `type: icon` (clockwise,
  `0deg` upright, the same zero as `curve: {style: angled}`), and
  `icon: {upright: true}` on a curved `type: data` to keep the icon
  unturned (default `false`: it turns with the reading).

## 2. The format

```yaml
config:
  slots:
    left: { default: steps, choices: [steps, floors_climbed, body_battery, stress] }

elements:
  steps_slot:
    type: group
    size: { width: 100%, height: 100% }
    at: { anchor: center }
    on_hold: auto                     # follows the slot inside (D5)
    children:
      ring:
        type: gauge
        slot: left
        style: segments
        at: { anchor: center }
        radius: 93.5%r
        thickness: 6%r
        start_angle: 360deg
        sweep: -180deg
        count: 12
        gap: 5.0%r
        color: color.accent
        absent: hide
      glyph:                          # steps 1: free placement
        type: icon
        slot: left                    # the glyph follows the pick
        size: 10%r
        rotate: -46deg                # baked turned
        at: { anchor: center, dx: -64%r, dy: -48%r }
        color: color.fg
      value:
        type: data
        slot: left
        font: font.steps              # a face: font
        at: { anchor: center }
        curve: { style: radial, angle: -46deg, radius: 80%r }
        align: left
        absent: { text: "--" }
```

Steps 2 and 3 instead keep the icon in the data element, placed in the
text's own frame:

```yaml
      value:
        type: data
        slot: left
        font: font.steps
        at: { anchor: center }
        curve: { style: radial, angle: -46deg, radius: 80%r }
        align: left                   # the run starts at -46deg ...
        icon: { size: 10%r, position: left, gap: 2px }   # ... and the icon sits before it (pinned)
```

| `icon: {position:}` | `angled` | `radial` |
|---|---|---|
| `left` / `right` | before / after the run, along its turned baseline | before / after the run along the circle; `gap` and widths are arc lengths at `radius` |
| `top` / `bottom` | the glyphs' "up" / "down" side | outward / inward for a clockwise run (glyphs face out), the reverse for counter-clockwise |

Upright text is the angled case at `0deg`, so nothing in the table is
new vocabulary.

## 3. What changes, by slice

Each slice is warning-free on the three verification devices, keeps the
fast suite green, updates its docs in the same commit (§4), and has a
red-then-green test for each new diagnostic.

### Slice 1 — `rotate:` on `type: icon`: done

- Schema and IR: `rotate: <Angle>` on `type: icon`, any angle, static or
  dynamic icon (`icon: {for: weather...}` turns its whole glyph set).
- Bake: `ts/src/fonts/bake.ts` rotates each flattened outline about the
  glyph's ink centre before `rasterise`, then crops as today. The font key
  (`fontKey` in `ts/src/icons.ts`) gains the angle (D6), so a turned icon
  and an upright one never share a sheet.
- Placement: the anchor and `align:` act on the turned glyph's own box.
  Ink-height normalisation happens before turning, so an icon is the same
  size at every angle.
- Lints: `safe-area`/`off-screen` read the turned box.
- Tests: bake goldens at 0°, 45° and 90°, where 90° must equal the 0° tile
  transposed and mirrored (the contrast that catches a sign error). One
  build golden.
- Preview and `wfb studio` draw the baked sheet as they draw any sheet;
  the inspector gets `rotate:` from the schema.

### Slice 2 — `slot:` on `type: icon`: done

- `slot:` in place of `icon:`: the glyph is chosen on the watch from the
  picked type, by the same `switch` and per-choice overrides as the data
  element's icon (`emitDataIconMethod`), shared rather than copied.
  `icon:` beside `slot:` is an error naming why.
- The icon font is the slot's glyph set (with weather conditions), baked
  at this element's `size:` and `rotate:`.
- Absence: the icon follows the configured type, so it always draws, as a
  data element's icon does. A Connect IQ app's complication under
  `choices: any` draws nothing.
- `on_hold:` on such an icon accepts `auto` only, for the same reason as
  on `type: data`.
- The native editor's slot highlight (`SlotDrawable`) covers every
  element bound to the slot, as it already does for a slot gauge.

### Slice 3 — `face:` fonts and `curve:` on `type: data`: done

- Drop the `complication-slot` error that refuses a `face:` font. A
  vector font is resident on the device, so the "bake every character any
  choice could draw" step is skipped for it.
- `curve:` with the same keys and rules as on `type: text`: `style:`
  required, angled `bottom` an error, radial `top` shifted by the ascent,
  `unsupported: error | hide` (D2). `curve:` without a `face:` font is the
  same build error `type: text` gives.
- In this slice `curve:` beside `icon:` is an error ("a curved reading
  takes no icon here; use a separate `type: icon` with `slot:`"). Slice 5
  lifts it.
- `label:`, `unit:` and `short:` are unchanged: they build one string, and
  that string is drawn curved.
- Lints: `safe-area` reads the existing sector or rotated box
  (`radialTextAngleSpan`, `rotatedRectCorners`), sized from the slot's
  widest reading. The hold region and `SlotDrawable.boundingBox()` use
  that shape's bounding box.
- Draw program: a slot `Text` op carries `style`, `angle`, `radius` and
  `direction` as a curved text op does. The printer already emits both
  calls.

### Slice 4 — a group's `on_hold:` follows its slot (D3, D5): done

- `resolveHoldAuto` (`ts/src/ir/builder/tree.ts`) gains the group rule in
  D5. The group's hold region is its box, and the delegate's exit is the
  slot's field (`emitExitTo` with the slot's id, as a data element's
  hold).
- A member's own `on_hold:` inside such a group is the existing
  `hold-overlap` warning (regions are tested parents first); its message
  now names the slot whose pick the group opens.
- Tests: one slot (resolves); two slots (`hold-auto-ambiguous`); a slot
  plus a fixed-source text (resolves to the slot); no slot (unchanged).

### Slice 5 — a curved pair, icon on the pinned end (step 2): done

- `icon:` beside `curve:` is accepted when the icon's angle cannot
  depend on the reading's width: any `angled` pair; on `radial`, `align:
  left` with `position: left`, or `align: right` with `position: right`,
  with a `px`/`%r` radius. Every other radial pairing is an error naming
  the two pinned ones until slice 6.
- Angled: `generalPair` (and the fast path) keep computing the upright
  pair on the watch; each draw point is turned about the anchor by the
  build-time `<P>_COS`/`<P>_SIN`. The text draws with `drawAngledText`
  and the upright justify; the icon draws centred on its turned centre,
  from one font baked at `a`.
- Radial: the icon is drawn centred at build-time `<P>_ICON_X/_ICON_Y`
  (the middle of the run's band, at the angle in D7), from a font baked
  at that device's exact turn (D7). `icon: {upright: true}` draws the
  slot's unturned font at the same point.
- Measured (D6): +56 B for the extra font handle.
- Draw program: `DrawText` ops, as the upright pair's, so the evaluator
  justifies the icon as `drawText` does; no new op.

### Slice 6 — the free end and a centred radial pair (step 3): built, not yet verified on a watch

**Gate passed.** §5 check 2 found no constant ratio between the measured
width and the drawn arc, but a rule: a run's advances are laid out along
its baseline circle (`radialSpacingRadius` in `ts/src/layout.ts`, recorded
in `docs/lore/rendering.md`). The icon's angle divides the measured width
by that radius. The same rule now spaces every radial run in the lints and
the preview, which changed the preview of each shipped face with a centred
or `top` radial run (`vector-text`, `outline`, `curved-slot`, two
fixtures) and two corpus designs' lint boxes.

- `position: left`/`right` with any `align:` on a radial pair; `top`/
  `bottom` stay an error (stacking across the run would move it off its
  radius).
- Free end and centred pair: the angle, the point and the step are
  computed on the watch from `getTextWidthInPixels`, with per-device
  constants in `Layout.mc`; a centred pair's text is drawn centred at a
  build-time angle shifted by half the icon and gap, so the pair centres
  on `angle:`. Steps per D7.
- `icon: {upright: true}`: the slot's upright font at the computed point,
  no steps.
- Lints: the sector covers reading + gap + icon from the authored angle as
  the alignment lays it out; highlight and hold are its box. A data
  element's widest reading is now measured in its vector font (it was
  measured with no metrics, so the first choice's reading won).
- Still the user's: the free-end pair on a watch or in the simulator
  (§5 check 5).

### Slice 7 — example, screenshots, docs: done but for the angled pair

- `examples/features/curved-slot/face.yaml`: the format in §2 (free
  placement) on the left slot, a pinned radial pair on the right. Still
  open: an angled pair, covered by tests but not yet shown in an example;
  decide with slice 6 whether it joins this face or gets its own.
- Screenshots via `ts/tools/docs-shots.ts`; a gallery entry in
  `README.md` if it earns one.

## 4. Docs, in the same commits

| Slice | Docs |
|---|---|
| 1 | `docs/guide/icons.md` (`rotate:`), schema, `docs/lore/roadmap.md` |
| 2 | `docs/guide/icons.md` and `configuration.md` (Data axis: an icon on a slot), schema |
| 3 | `docs/guide/configuration.md` (`curve:` and `face:` on `data`), `text.md` (cross-reference), `docs/limitations.md` (44/136 reach, no fallback), schema |
| 4 | `docs/guide/modes-and-interaction.md` (`on_hold: auto` on a group), `elements.md` (`group`) |
| 5, 6 | `docs/guide/configuration.md` (the pair in the text's frame, which pairings are allowed), `docs/limitations.md` |
| 7 | `docs/README.md` hub, roadmap, root `CLAUDE.md` §1 table if the phase line changes |

## 5. Checks only the user can run

The simulator crashes in this container, so these run on the host:

1. **After slice 3:** `examples/features/curved-slot` on
   `fenix8solar47mm`. The radial reading starts at the authored angle and
   faces the right way for each pick; switching the pick in the native
   editor redraws it.
   Seen 2026-10-18 in the user's captures (`fenix8solar47mm`, `fr955`,
   `fenix947mm`): readings right, but a turned icon whose ink left its
   cell was cropped by the watch; the bake now grows turned cells to fit.
   Re-checked 2026-10-19: the icons are no longer cropped.
2. **Before slice 6: done (2026-10-18).** The probe's `gap` variant
   (`docs/research/probes/curved-slot/README.md`, "On the host") in the
   user's host simulator on `fenix8solar47mm`: "1234" at R = 78 ran
   4.6 px past its `width / R` end, "12345678" at R = 52 ran 16.1 px past
   it. Not a constant ratio; it fits advances spaced along the baseline
   circle, 8 px inside R under `VCENTER` (5.5 and 17.5 px predicted).
   Counter-clockwise, `top`/`bottom` and other faces are inferred.
3. **After slice 5: done (2026-10-19).** The pinned pair in the user's
   `fenix947mm` simulator matches `wfb preview` in place and turn.
4. **After slice 4: done (2026-10-19).** Touch and hold anywhere in the slot group opens the
   picked metric's glance, and still does after re-picking.
5. **After slice 6:** the free-end and centred pairs (a scratch face like
   slice 6's: clockwise free end, counter-clockwise free end, centred) on
   `fenix8solar47mm` and `fr955`: the gap between the reading's last glyph
   and the icon looks the same for a short and a long reading (switch the
   pick between heart rate and steps), and the icon faces the run.
   Run 2026-10-19 on `fenix947mm` (`scratch/free-end`): the reading's end
   matched `width / spacing` to a fraction of a degree, but at "20.9K"
   the clockwise icons overlapped it. The cause was the icon, not the
   run: the slot's font is sized by the default pick's glyph (heart), so
   the feet came out wider than the half-advance the gap was measured
   from. The user chose to place every slot icon by the slot's widest
   glyph (a narrow icon gets a wider gap). Re-check after that fix.
