# 37 — The hold region and editor outline of a curved reading

**Question.** A `type: data` reading curved round the dial (`curve: {style:
radial}`) was held, and outlined in the editor, by one box: the box round
the run of the widest reading any of its slot's choices could draw. On a
face whose slot offers `choices: any`, that is huge. What should the hold
region and the outline be instead?

**Short answer.** Hold the arc the reading covers *as drawn*, sized on the
watch from the reading's measured width every frame, and outline the
reading the editor's frame shows. Keep the widest-choice shape for the
lints. Built; see the guide's "A curved reading" and `docs/limitations.md`
("A curved reading's hold").

---

## 1. Why the box was so large (VERIFIED)

A slot's reading can be any choice's, so the layout sizes the run from the
widest (`dataWidest`). With `choices: any` that is a weather condition name:
"Cloudy chance of rain snow" in a 14%r Bionic face on `fenix8solar47mm` is
160 px, 88° of a 104 px circle. A reading at `angle: -46deg`, `align: left`
then runs from 10:30 to about 1:30, and its box spans 177×60 px of a
260 px screen. The step count the wearer actually sees, "8432", covers 22°;
its ink, icon included, is 43×35 px. Measured with the probe face below.

## 2. Options

| | Region | Follows the pick | Cost | Verdict |
|---|---|---|---|---|
| A | the widest choice's box (as was) | no | none | far too large with `any` |
| B | the default choice's box, at build time | no | none | a long pick's tail is unholdable, a short pick holds blank dial |
| C | the widest choice's *arc*, not its box | no | a polar test | still 88° of dial with `any` |
| D | the arc of the reading drawn, its width measured each frame | yes | one `getTextWidthInPixels` a frame per held reading, and a polar test on a hold | **built** |
| E | D plus a finger margin | yes | as D | not built: the project inflates no hold region (Garmin publishes no touch size; a margin silently overlaps neighbours) |

What makes D possible (VERIFIED in `$CIQ_SDK/bin/api.debug.xml` and
`Toybox/Graphics.html`): `Dc.getTextWidthInPixels(text, font)` takes any
`Graphics.FontType`, which includes `VectorFont`, and `Math.atan2` and
`Math.toDegrees` exist from API 1.3.0. A delegate has no `Dc`, so the view
records the width when it draws and the delegate reads it.

## 3. The editor's outline

The editor's frame draws one pick's sample reading, so its outline is that
reading's arc box: "8432" with its icon is outlined in 50×47 px, against the
177×60 px box (`ts/test/hold-arc.test.ts` holds every drawn pixel inside it
and the outline within a line's band of the ink). Choosing another pick in
the editor's context redraws the reading and moves the outline with it. The
native editor's highlight keeps the widest-choice box: the wearer scrolls
every choice through it.

## 4. Open

Not seen on a watch: whether the width `getTextWidthInPixels` reports for a
vector font matches the arc `drawRadialText` lays the run out along (the
host's spacing-radius model, `docs/lore/rendering.md`, was measured on the
simulator), so whether a hold lands where the reading is.

Probe face: a 14%r `face:` reading at `-46deg` with `choices: any`, its icon
before the run, and a counter-clockwise centred one at `180deg`; the same
design is in `ts/test/hold-arc.test.ts`.
