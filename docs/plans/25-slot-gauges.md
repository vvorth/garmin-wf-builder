# 25 — Gauges on a slot, scaled by the picked metric

**Status: in progress. Slice 1 done (2026-10-01). D1, D2, D4–D8 are
decided; D3 (zone colouring) is deferred to a later plan (§6).** Delete this file once every slice has shipped
(`docs/CLAUDE.md`).

Research: `docs/research/24-complication-full-scale.md`. In short:

* A gauge cannot be bound to a `config: slots:` slot today, and has no
  idea of a complication's limit: `max:` is always hand-written.
* `Complication.ranges` is null for every native type, on an fr955 and in
  the simulator (research 24 §2.4). The scale and band edges must come from
  a per-type table in the compiler (§3, §7), with `ranges` read only for
  an app's complication.
* That table gives each type one of three things: **band edges** (heart
  rate, Body Battery, stress, sleep score, VO2 max), **a full scale only**
  (battery, pulse ox, solar, steps, floors, intensity minutes, wheelchair
  pushes, sunrise/sunset), or **nothing** (everything else, strings
  included).
* In the simulator, steps past 10,000 arrive as `12.569` with the unit
  `"K"` (§5). A gauge must unscale them, rounding, and so must every
  `complication.*` read today.

The face this is for (the user's example): one slot showing date or
weather as icon and text, or steps, floors, VO2 max, heart rate, battery,
Body Battery and so on as an arc or bar the author designed — filled
against that metric's own scale, and nothing at all where Garmin defines
none. Segmenting and colour-coding by Garmin's bands is the deferred
follow-up (§6); this plan builds everything it stands on.

## 1. Decisions

### Decided

- **D5: option A (2026-10-01).** A gauge names `slot:` itself, as its own
  element beside the slot's `data` element. The gauge's `style:` and
  geometry stay the author's. The alternative, a `gauge:` part inside
  `type: data`, belongs to the reserved data widget (`parts:`) and is not
  pursued.
- **D6: heart rate's scale is on by default (2026-10-01).** A gauge that
  can show `heart_rate` or a VO2 max type adds the `UserProfile`
  permission, derived like every other permission (constraint 7).
- **D7: VO2 max (2026-10-01).** Ratings from the Cooper Institute table in
  Garmin's manual (research 24 §7.1). The scale's ends are derived: the
  Poor and Superior bands each get the average width of the three inner
  bands. Age is `current year − birthYear`, approximate by up to a year.
  No birth year, no gender, `GENDER_UNSPECIFIED`, or an age outside 20–79
  hides the gauge, as missing data. Cycling uses the same table.
- **D8 (recorded, no decision needed): band boundaries.** Every table
  stores *lower bounds*, and a value belongs to the highest band whose
  lower bound it reaches:
  - Body Battery and stress: 0, 26, 51, 76 (Garmin's 0–25 / 26–50 /
    51–75 / 76–100);
  - sleep score: 0, 60, 80, 90 (Garmin gives 60 to both poor and fair; it
    is read as fair, the band that starts there);
  - heart rate: `getHeartRateZones(HR_ZONE_SPORT_GENERIC)` returns zone 1's
    minimum then each zone's *maximum*, so zone n+1 starts at zone n's
    maximum + 1 (whole bpm). The scale runs from zone 1's minimum to zone
    5's maximum;
  - VO2 max: the table's figures already are lower bounds.

- **D1: `slot:` means an automatic scale (2026-10-01).** `value:`,
  `max:` and `bands:` are refused beside `slot:`. A slot's metric is
  chosen on the watch, so one hand-written `max:` cannot fit every
  choice; a type the table cannot scale hides (D2).
- **D2: a pick with no scale hides the whole gauge, track included
  (2026-10-01).** That is the user's "or hide it entirely": the date or
  weather is what the slot shows then, through its `data` element. A
  *momentarily* absent reading of a scalable pick (heart rate between
  readings) keeps today's `absent:` behaviour, track drawn. The generated
  code tells the two states apart.
- **D3: zone colouring is deferred (2026-10-01).** No `zones:` key in
  this plan. A pick with band edges draws like any scaled pick: today's
  styles, in `color:`, against its automatic min and max, and `style:
  segments` keeps the author's `count:`. The band edges stay in the
  host-side table (slice 2), tested and documented, and are not emitted
  to the watch until something draws them. The proposal that was on the
  table is kept in §6 for the follow-up plan.
- **D4: `max: auto` on a fixed complication binding (2026-10-01).**
  `value: complication.vo2max_run` with `max: auto` gets the same
  automatic scale, with the type known at build time, so only that one
  case is emitted (slice 5).

## 2. The format

```yaml
config:
  slots:
    top: { default: steps,
           choices: [date, current_weather, steps, floors_climbed, heart_rate,
                     vo2max_run, battery, body_battery, stress, sleep_score] }

elements:
  top_ring:
    type: gauge
    slot: top                     # instead of value:/max: (D1)
    style: segments               # the author's
    at: { anchor: center }
    radius: 46%r
    thickness: 5px
    start_angle: 150deg
    sweep: 240deg
    count: 10
    color: color.accent
    track_color: color.track
    absent: hide                  # a reading absent for now (D2)
  top_text:
    type: data
    slot: top
    icon: { size: 18px }
```

With `steps` picked, the ring is 10 cells against the step goal; with
`heart_rate`, 10 cells from the wearer's zone 1 minimum to their zone 5
maximum; with `vo2max_run`, 10 cells across their age and sex column's
derived range; with `date`, no ring at all, and `top_text` alone draws.

## 3. What changes, by slice

Each slice ships warning-free on the three verification devices, with
the fast suite green, and with every new diagnostic driven red.

### Slice 1 — unscale `"K"` in every numeric complication read: done

Built as below, plus the user's addition (2026-10-01): a slot's count
from 10,000 up always carries one decimal (`10.0K`, not `10K`).

A bug fix with no format change, so it goes first. Where a numeric
`complication.*` source is read (`wfb/catalog.py`'s generated sources,
emitted in `wfb/emit/monkeyc/`), a String unit `"K"` multiplies the value
by 1000 and **rounds** (`(v * 1000 + 0.5).toNumber()`, or `Math.round`):
truncating reads 1 low for 1,384 counts from 10,000 to 199,999, the first
being 16,001 (research 24 §5).

- `SlotText` keeps the device's own `"12.6K"`: the slot's text is
  unchanged.
- Test: the emitted read, and a host twin checked on 16,001 and 12,569.
- `docs/limitations.md`: the steps bullet says reads are unscaled, and
  that the watch side is still unseen.

### Slice 2 — the per-type scale table, on the host and the watch

- **`wfb/complications.py`** gains `SCALE`: for each type, either
  - `fixed(min, max)`;
  - `goal(field)`: `stepGoal`, `floorsClimbedGoal`, `pushGoal`,
    `activeMinutesWeekGoal`;
  - `day` (0–86,400 s);
  - `bands(lower_bounds, max)`: Body Battery, stress, sleep score;
  - `heart_rate_zones`;
  - `vo2max`;
  - or absent (no scale).
  
  Each entry cites its source (research 24 §3, §7), and records its band
  lower bounds (D8) even though this plan only draws the scale (D3). It
  sits beside `READING`, so the two tables cannot drift.
- **`runtime-lib/WfbScale.mc`**, the watch side. It returns
  `[min, max]` (or `null`) for a type and a pulled `Complication`, no band
  edges yet (D3):
  - VO2 max: only each column's derived `min`/`max` (2 × 6 × 2 = 24
    numbers, research 24 §7.1), with the age and gender rules of D7;
  - heart rate: zone 1's minimum to zone 5's maximum (D8);
  - the goals;
  - `ranges` for `COMPLICATION_TYPE_INVALID` (an app's complication):
    first value min, last value max (research 24 §2.2, inferred).
- **A generated `SlotScale.mc`** switches on the pick's type, with a case
  only for the types the design's gauge slots can show, as `SlotText.mc`
  does.
- **The Python twin** (`wfb.complications.scale_for`) drives the preview.
  The preview uses a fixed sample profile (male, 30–39) for VO2 max and
  fixed sample zones for heart rate, and says so in its own legend line.
- **Tests:** every table entry against its cited figure; VO2's derived
  ends recomputed from the four edges; each D7 hiding case.
- **Permissions:** `UserProfile` is derived when a gauge can show
  `heart_rate` or VO2 max (`choices: any` included) (D6).
- **Memory:** measured with `--build-stats` before and after on
  `examples/features/slots/`, recorded in `docs/limitations.md`.

### Slice 3 — `slot:` on a gauge

- **Schema and guide:**
  - `gaugeElement` gains `slot:`;
  - `value:`, `max:` and `bands:` are refused beside `slot:` (D1);
  - `docs/guide/progress-and-graphs.md` gains a "Gauges on a slot"
    section;
  - `configuration.md` links to it.
- **`wfb/lower.py`, `wfb/ir/model.py`:** `Progress.slot`. The slot
  reference resolves through `_resolve_slot_reference`'s cascade, moved
  somewhere both kinds can use.
- **The rule that slots are face-wide extends to slot gauges.** A slot
  gauge inside a `layouts:` body is an error, the same as a `data`
  element (`docs/guide/styles-and-layouts.md`).
- **`wfb/kinds/progress.py` emit** gains a slot path:
  - pull the chosen id, unscaled as slice 1 does;
  - `SlotScale` for the scale. No scale hides everything, track
    included (D2); a scale with an absent value follows `absent:`;
  - the fraction is `(value − min) / (max − min)`, clamped. Today's
    fraction assumes a minimum of 0; heart rate's and VO2 max's are not.
  
  Then every style draws as today from that fraction. `style: scale`
  beside `slot:` draws the track and the pointer only, since its
  `bands:` are refused (D1).
- **Preview** draws the slot's `default:` pick with
  `_COMPLICATION_SLOT_SAMPLE` against the slice 2 twin.
- **Tests:** each D1 refusal, D2's two states (hidden whole vs. track
  kept), a non-zero minimum on a host twin, and a layouts-body refusal,
  each driven red.

### Slice 4 — the editor sees every element of a slot

Today `_editor_slot_pairs` (`wfb/emit/monkeyc/common.py`) keeps the
*first* element per slot. So a second element on one slot is never
redrawn during the editor's animation (its `_pulsing` check still hides
it), and is never hit by `onTap`. That is already true of two `data`
elements; a slot gauge makes it the normal case.

- **Grouping:** elements are grouped by slot, across kinds. `data` and
  slot gauges both qualify, so `complication_slots(face)` becomes "every
  slot-bound element".
- **`drawSlot`** calls every element of the slot.
- **`onTap`** hit-tests the union of their boxes.
- **`drawableFor`** gets the union box. An arc's box is its whole
  circle, so the highlight is that large too, which is the honest
  extent.
- **Unchecked so far:** the fenix 8 editor's animation broke once before
  (the `drawSlot` comment). The host cannot check this slice; §5 lists
  the sideload check.

### Slice 5 — `max: auto` on a fixed binding (D4)

- `max: auto` is allowed when `value:` is a bare `complication.<type>`
  (anything else is an error naming why).
- The build knows the type, so it emits `WfbScale` for that one type and
  no `SlotScale` switch.
- A type with no scale is a build error here, not a hidden gauge: the
  build knows the type, and a fixed binding that can never draw is a
  mistake rather than a runtime state.

### Slice 6 — example, screenshots, docs

- **Example:** `examples/features/slot-gauge/face.yaml`, the face from §2
  for the three verification devices, with one `--all-styles` screenshot
  per pick class (banded, scale only, hidden) in the guide.
- **Doc sweep:** root `CLAUDE.md` §6 "Shipped", `docs/lore/roadmap.md`,
  `docs/limitations.md` (the table's sources, the derived VO2 ends, the
  zone-colour order), `docs/README.md` if the hub needs a row.
- **Close-out:** delete this plan and add its row to
  `docs/plans/README.md`.

## 4. Docs, in the same commits

The guide and the schema move together (each slice's own keys).
`docs/limitations.md` gets, as each lands:
- the scale table's sources, Garmin's manuals among them, with the
  derived VO2 ends called derived;
- that native `ranges` is null;
- the steps unscale;
- in §2 "not implemented": segmenting and colour-coding a gauge by its
  metric's bands (D3).

The guide and schema cite neither this plan nor research 24 (`docs/CLAUDE.md`).

## 5. Checks only the user can run

1. **The fenix 8 editor, after slice 4:** in the native editor, select the
   top slot by tapping the ring and by tapping the text. The highlight
   should pulse over both, and each pick should preview in both elements
   while scrolling. Then pick `date` and see the ring vanish.
2. **The fr955 settings menu, after slice 3:** pick heart rate, then
   Body Battery, then the date from the menu, and see two filled gauges
   on their own scales, then none.
3. **Steps past 10,000 on a watch**, any slice: rerun the probe
   (`docs/research/probes/complication-ranges/`) or wear the slice 1 build
   past 10,000 steps, and see the gauge full rather than empty. This is
   also the last open fact in research 24.
4. **VO2 max on the watch:** the fill should sit inside the column the
   watch's own VO2 max glance rates the wearer by.

## 6. Deferred: zone colouring (D3)

Not part of this plan; a follow-up plan, built on slice 2's band edges.
The proposal as it stood when deferred:

- **A `zones:` key:** a list of 2–8 colours, lowest band first. A pick
  with *n* bands uses the first *n* (heart rate and VO2 max have 5; Body
  Battery, stress and sleep score 4; an app's `ranges` `size − 1`). Fewer
  colours than bands, or no `zones:`, draws as a plain fill.
- **Per style:**
  - arc/bar: the fill in the colour of the value's band;
  - segments: one cell per band, each as long as its band, lit up to the
    value's band in their own colours;
  - scale: the bands from the edges, with the pointer;
  - needle: unchanged.
- **The cost:** band geometry computed on the watch each frame. Today
  `bands:` start/sweep are `Layout` constants.
- **Open:** colours run low to high, not good to bad (high stress and
  high Body Battery both take the last colour); per-metric colour lists
  would fix that at the cost of a mapping key.
