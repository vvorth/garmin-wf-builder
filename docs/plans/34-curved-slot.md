# 34 — A curved slot: turned icons, `slot:` on an icon, a curved reading

**Status: in progress. Slices 1–5 done. D1–D8 decided (2026-10-18); D7 refined while building slice 5.** Delete this file once every slice has shipped
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
- **D7: a pinned radial icon gets one exact turn per device; only a
  free-end icon would snap to 3° steps.** (Refined while building slice
  5.) A pinned icon's centre is at a build-time angle, θ₀ ∓ (gap +
  reference advance / 2) / R, every other choice's glyph centred on the
  same point, so there is exactly one turn to bake and no step to pick on
  the watch. R, the gap and the reference glyph's advance are per device,
  so the turn is too, and the generated view is one file shared by every
  target: the font therefore has **one resource name on every device**
  (an element-specific key with no angle in it), and each device's bake
  resolves the turn itself (`PinnedTurn` in `ts/src/icons.ts`, read by
  both `iconFontSpecs` and the layout). Steps remain the plan for slice
  6's free end, whose angle is only known on the watch: the worst error
  is 1.5°, about 0.3 px at the edge of a 24 px glyph, and only the steps
  the icon's centre can reach across the slot's widest reading are baked.
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

### Slice 6 — the free end and a centred radial pair (step 3)

**Gated on §5 check 2.** The icon's angle here comes from
`getTextWidthInPixels / R`, and the device must lay the run out to the
same length, or the gap drifts with the reading's length.

- Lift slice 5's error for the remaining radial pairings. The step range
  now spans the widest reading (about 11 steps for a 75 px reading on a
  150 px radius).
- If check 2 finds a constant ratio between the measured width and the
  drawn arc, apply it in the mapping and record the measurement in
  `docs/lore/rendering.md`. If it finds no usable rule, this slice stops
  and the free end stays an error.

### Slice 7 — example, screenshots, docs

- `examples/features/curved-slot/face.yaml`: the format in §2 (free
  placement), plus one pinned radial pair and one angled pair.
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
2. **Before slice 6:** the probe's `curved` variant
   (`docs/research/probes/curved-slot/README.md`, "On the host"). As the
   minute changes the reading's width, does the gap between its last digit
   and the glyph stay constant?
3. **After slice 5:** the pinned pair turned on `fenix8solar47mm` and
   `fr955`, compared with `wfb preview` frame for frame.
4. **After slice 4:** touch and hold anywhere in the slot group opens the
   picked metric's glance, and still does after re-picking.
