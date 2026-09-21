# 13 — A vintage roman-numeral layout for the showcase

**Status:** proposed, 2026-09-21. User-requested; the numeral route was a
user decision (§2.1).

`examples/showcase/face.yaml` demonstrates the format by example. It has two
layouts, `analog` and `digital`. This plan adds a third, `roman`: a classy,
vintage dial with big roman numerals curved around the rim, period-looking
hands, and a mechanical day/date aperture over and under the axle.

---

## 1. What already exists, and must not be disturbed

- `config: style: entries:` names every `(layout, colors)` pair. `analog`
  and `digital` each appear with several schemes. The new layout adds its
  own entries; the existing ones keep their ids and labels.
- **Shared `static:` and `elements:` draw underneath *every* layout.** The
  showcase's shared set is `background`, `left_card`, `right_card` and the
  two `complication_slot` registers at `dx: ±50%r, dy: -23%r/-30%r`. There
  is no per-layout opt-out, so the roman dial is designed **around** them,
  not as if they were absent.
- `hands: classic:` is the existing hand set. The new set is added beside
  it; `classic` is left exactly as it is, because the `analog` layout uses
  it.
- **`examples/dashboard/face.yaml` is the user's playground — do not touch
  it** (`examples/CLAUDE.md`).

---

## 2. R1 — the numeral ring

### 2.1 The route, decided

**User decision (2026-09-21): vector text, `RobotoCondensedBold`.** A serif
face is impossible here and the alternatives were weighed and rejected:
`Graphics.getVectorFont` only ever offers Garmin's own device-resident
faces (root `CLAUDE.md` constraint 15), and the only ones **all three
targets publish** are `RobotoCondensedBold`, `RobotoCondensedRegular` and
`RobotoCondensedRegularItalic` (checked against each device's
`scalable_faces`). A baked serif cannot rotate at all.

### 2.2 The shape it takes

**VERIFIED by rendering** (a probe built and previewed on
`fenix8solar47mm`, 2026-09-21): one radial `pattern` with a single
`shape: text` part, `curve: {style: angled, angle: 0deg}`, puts every
numeral tangent to its own radius with **its baseline toward the centre** —
level at XII, on its side at III and IX, inverted at VI — which is the
requested "font bottom towards center", from one authored angle.

```yaml
fonts:
  romandial:
    face: [RobotoCondensedBold]
    size: 20%r            # R1.4 — tune by rendering
elements:
  numerals:
    type: pattern
    pattern: radial
    at: {anchor: center}
    count: 12
    parts:
      - shape: text
        value: >-
          copy == 0 ? "XII" : copy == 1 ? "I" : copy == 2 ? "II" :
          copy == 3 ? "III" : copy == 4 ? "IV" : copy == 5 ? "V" :
          copy == 6 ? "VI" : copy == 7 ? "VII" : copy == 8 ? "VIII" :
          copy == 9 ? "IX" : copy == 10 ? "X" : "XI"
        font: font.romandial
        at: {dy: -78%r}   # R1.4 — tune by rendering
        curve: {style: angled, angle: 0deg}
```

The chained ternary over `copy` is how a roman numeral is selected: the
expression language has string literals and nesting ternaries, and no
arrays or lookup tables (`wfb/expr.py`). It is verbose on purpose and
reads as a table.

R1.3 **`fr955` must render it too.** `RobotoCondensedBold` is published on
all three targets, so no `if_unavailable:` escape is needed — but the build
must be checked on all three, not just the fenix pair.

R1.4 **Size and radius are tuned by rendering, not asserted.** The
user asked for numerals at roughly 20–30 %r. The probe at `size: 22%r`,
`dy: -78%r` tripped `safe-area` on `fenix8solar47mm` — the ring reached
past the round panel's edge. Find the largest pair that is **warning-free
on all three targets** and says vintage rather than cramped; state the
chosen numbers and why in the example's own comments. The bar is
warning-free, not merely successful (root `CLAUDE.md` §7).

---

## 3. R2 — vintage hands

R2.1 A **new** named set under `hands:` (`vintage` is the suggested name),
authored pointing at 12 o'clock with the origin at the axis, exactly like
`classic`. `classic` is not modified.

R2.2 Period-correct shapes, built from the part kinds a hand actually has
(`polygon`, `rectangle`, `circle`, `line` — `docs/format.md` "Analog
hands"). What "vintage" means concretely here, and any of these is a
defensible reading:

- **Breguet / moon hands** — a slim shaft with an open circle set near the
  tip and a small pointed tip beyond it.
- **Spade or leaf hands** — a narrow shaft opening into a wide lozenge in
  the outer third, tapering back to a point.
- A **counterweight tail** past the axis on the minute and second hands,
  which is what reads as mechanical more than anything else.

R2.3 The hour hand must be clearly shorter and visually heavier than the
minute hand, and both must stay legible against the numeral ring — a
vintage hand is thinner than `classic`'s, so check it does not vanish.

R2.4 The second hand keeps the existing convention: `config.accent_color`
for its tip, `seconds: awake` on the element, so the sleeping frame drops
it. A thin needle with a counterweight suits the period.

R2.5 `antialias: true` on the hands element, with the same
`lint: allow: [antialias-dither]` reason the `analog` layout already
carries — a soft edge on the 64-colour MIP panel dithers, and that is
accepted so rotated hands do not stair-step.

---

## 4. R3 — the mechanical day/date apertures

R4 in the user's words: "a mechanical looking opening with day of the week
over the axle and day of the month below the axle".

R3.1 **Two apertures on the vertical centre line**, one above the axis
(day of week, `date.today` formatted `{:%a}`) and one below it (day of
month, `{:%e}` or `{:%d}`). They sit inside the numeral ring and clear of
the shared register cards, which are at `dx: ±50%r` — the centre column is
free.

R3.2 **"Mechanical opening" without alpha.** `alphaBlendingSupport` is
false (root `CLAUDE.md` constraint 10), so an aperture is drawn, not cut:
a dark `rounded_rectangle` for the window well, a 1 px frame in a lighter
tone for the bevel, and the text on top. The frame is what sells it — a
plain dark rectangle reads as a box, a framed one reads as a cut in the
dial plate.

R3.3 The windows must not collide with the hands' hub or with each other,
and the hands draw **over** them (a real date window sits under the hands).
Ordering follows the file: a layout's `static:` draws before its
`elements:`, and the hands are an element.

R3.4 Day-of-week text is uppercase and tracked if the format allows it; the
date is the larger of the two. Both use a system font (`FONT_XTINY` /
`FONT_TINY`) unless a baked font measurably reads better — a new baked
font costs `.prg` size and needs a reason.

R3.5 Whatever `lint:` suppressions this needs (`static-overlap` against the
full-dial numeral pattern's bounding disc is the likely one — the existing
registers already carry exactly that suppression, with a written reason)
must carry a **specific** reason naming why the flagged overlap is a
bounding-box overstatement and not real ink. A blanket `allow:` with a
vague reason is not acceptable.

---

## 5. R4 — wiring, colours and proof

R4.1 New `config: style: entries:` for the layout — at minimum
`roman_dark`; add a second scheme if it reads well. Existing entry ids are
untouched.

R4.2 Colours come from `config.colors.*` and `config.accent_color` like
every other layout, so the new entries work under each scheme rather than
hard-coding a palette entry. Every literal colour that *is* used must be
MIP-safe: each channel `00`/`55`/`AA`/`FF` (constraint 13).

R4.3 **Proof it works, on all three targets:**

```sh
./.venv/bin/python wfb.py build examples/showcase/face.yaml      # warning-free, 3 signed .prg
./.venv/bin/python wfb.py preview examples/showcase/face.yaml --all-styles
```

Look at the rendered PNGs. "It compiled" is not the bar; the dial has to
look like the thing that was asked for.

R4.4 The showcase's own tests (`tests/`) and any golden files that cover it
are updated in the same pass. `docs/screenshots/` has `showcase-*.png`
regenerated by `tools/readme-shots.py`; if the README shows the showcase's
styles, regenerate and say so.

R4.5 Bump `face: version:` in the example, since the style entry set
changes.

---

## 6. Out of scope

- Any change to the compiler, the schema or the format. This is an example;
  if it cannot be expressed, say so rather than extending the format.
- `examples/dashboard/face.yaml`.
- Removing or restyling the shared registers.
