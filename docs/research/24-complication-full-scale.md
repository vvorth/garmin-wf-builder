# 24 — A complication's full scale: gauges without a hand-written `max:`

**Status:** research, 2026-09-30 / 10-01. Nothing here is built. The
probe (§2.3) has run twice in the simulator (`fenix8solar47mm`) and once on
a real **fr955**: every native complication reported `ranges` as null, in
both. The per-type table (§3) is the mechanism; `ranges` only covers what
the table cannot know. Still owed: steps past 10,000 on a watch (§5), and
a fēnix 8 on a watch. Built on by `docs/plans/25-slot-gauges.md`.

## The question

A `gauge` needs `value:` and `max:`. For `complication.body_battery` the
author writes `max: 100`; for `complication.steps`, `max:
activity.step_goal`. That is fine for a fixed binding, but it blocks two
things:

1. **A gauge as a universal complication renderer:** bind a gauge to any
   complication and have it fill against that complication's own limit.
2. **A gauge on a selectable slot** (`config: slots:`, the Data axis):
   the wearer picks the metric on the watch, so the build cannot know the
   limit, and one hand-written `max:` cannot fit every choice.

## 1. Summary

| Question | Answer | Confidence |
|---|---|---|
| Does the platform carry a limit with a complication? | **Yes, in principle:** `Complication.ranges`, an array of numbers, API 4.2.0, beside `value`/`unit` | VERIFIED (SDK docs, and a `-l 3` build, §2) |
| Do Garmin's *native* complications (steps, Body Battery, ...) fill `ranges`? | **No:** all 40 native types a real fr955 offered, and all 41 the simulator offered, reported `ranges` null (§2.4). Nothing in the SDK, the samples or the forums says otherwise. | VERIFIED on an fr955 and in the simulator (`fenix8solar47mm`); a fēnix 8 watch and app complications untested |
| Can the compiler supply a limit itself when `ranges` is null? | **Yes, for 13 of the 42 types**, from a per-type table: a fixed 0–100, a device goal, or a day (§3) | VERIFIED (each source cited) |
| Can a gauge on a *selectable* slot find its limit? | **Yes:** the same runtime `switch` on `Id.getType()` the slot's text already uses (§4) | VERIFIED pattern (`config-axes` probe); the gauge path itself unbuilt |
| Is a gauge on a slot fed by the complication's value correct? | **Not for steps past 10,000** unless the value is unscaled first, with rounding (§5) | VERIFIED in the simulator (§2.4); UNVERIFIED on a watch (the fr955 run had 150 steps) |

**Recommendation:** `max: auto` on a gauge, meaning *author value, else
the per-type table, else `ranges`, else absent*; a gauge may name a
`slot:` instead of a `value:`; and the per-type table lives beside
`wfb.complications.READING`. Section 6 sketches it. Native complications
do not fill `ranges`, on a watch or in the simulator (§2.4), so the table
carries every native type; `ranges` is kept only for a pick the table
cannot know, an *app's* complication.

## 2. `Complication.ranges`

### 2.1 What the SDK says

`$CIQ_SDK/doc/Toybox/Complications/Complication.html` (API 4.2.0):

```
var ranges as Complications.Ranges or Null
```

`$CIQ_SDK/doc/Toybox/Complications.html`:

```
Ranges     as Lang.Array<Complications.RangeValue>
RangeValue as Lang.Number or Lang.Float or Lang.Long or Lang.Double
```

`$CIQ_SDK/doc/docs/Core_Topics/Complications.html`, the only prose:

> **Complication.ranges** — An optional array of numeric values. Ranges
> allow breakdowns of sets of values that can be integrated into the
> display.

> The optional `range` element allows you to provide an ordered set of
> numeric values that define different ranges for your value.

and, for a *publisher* (`Complications.updateComplication`):

```
// Array<Numeric> with at least 3 elements
:ranges => newRanges,
```

with a `complications.xml` example:

```xml
<range>
    <value>0</value> <value>24</value> <value>33</value>
    <value>41</value> <value>50</value> <value>53</value>
</range>
```

### 2.2 What that means, and what it does not say

`ranges` is **ordered, at least three values**. The reading that fits both
the prose ("breakdowns of sets of values") and the example is the one
Garmin uses elsewhere for the same shape: `UserProfile.getHeartRateZones`
returns "min zone 1, max zone 1, max zone 2, ... max zone 5"
(`Toybox/UserProfile.html`) — six values, a floor then each band's upper
edge. So, **inferred, not documented**:

* `ranges[0]` is the scale's minimum, `ranges[size-1]` its maximum;
* the values in between are band edges, which is exactly a `style: scale`
  gauge's `bands:` (and Face It's colour-zone radial complications).

Nothing documents whether **native** types fill it. Searched: the SDK's
docs and samples (`samples/ConfigurableWatchFace` never reads it), the
device files (`simulator.json` has no complication data), the simulator
binary's strings (no per-type range table), and
[forums.garmin.com](https://forums.garmin.com/developer/connect-iq/f/discussion/349460/stupid-complications-questions/1696149)
(one thread logs `.ranges` for battery and never reports the output). The
binary does surface one related limit: **"Complication subscriptions count
exceeded limit (10)"** — relevant to §4, since a pull via
`getComplication` does not subscribe.

### 2.3 The probe

`probes/complication-ranges/` is a complete watch face project.
`BUILD SUCCESSFUL`, warning-free, `-l 3`, on `fenix8solar47mm`,
`fenix8solar51mm` and `fr955` (SDK 9.2.0). **Negative control:** renaming
`c.ranges` to `c.rangez` fails with `Undefined symbol ':rangez' detected.`

It walks `Complications.getComplications()` — every complication the
device offers, native and app, with no subscription — and for each one
logs `t<type>|v=<value>|u=<unit>|r=<ranges>` once on load, preceded by
the ActivityMonitor goals (`stepGoal`, `floorsClimbedGoal`,
`activeMinutesWeekGoal`) so a `ranges` maximum can be compared against
them. On screen it shows the same rows, seven per page, turning the page
each minute. Type numbers are `Complications.COMPLICATION_TYPE_*` values;
`t0` is a Connect IQ app's complication, logged with its long label.

What to record, per type: is `r=` `null`? If not, is its last value the
goal (steps, floors, intensity minutes) or a fixed 100 (battery, Body
Battery, stress)? Does it change when the goal does? And does a steps
count past 10,000 arrive as `v=12.879|u=K` on the watch, as it does in the
simulator (§5)?

The source is device-independent, but a `.prg` is not: build one per
device (any device in the manifest, or add one with API 4.2.0 or later):

```sh
cd docs/research/probes/complication-ranges
$CIQ_SDK/bin/monkeyc -f monkey.jungle -d fr955 \
    -o probe-ranges-fr955.prg -y ~/ciq/developer_key.der -w -l 3
```

On a watch, `System.println` output goes to `GARMIN/APPS/LOGS/<NAME>.TXT`
only if that file already exists, and `<NAME>` must match the `.prg`'s
file name (`Core_Topics/Debugging.html`: `/GARMIN/APPS/MYAPP.PRG` logs to
`/GARMIN/APPS/LOGS/MYAPP.TXT`). So `probe-ranges-fr955.prg` needs an empty
`PROBE-RANGES-FR955.TXT`. Or read the rows off the screen.

### 2.4 Result: `ranges` is null for every native type

Run by the user in the **Connect IQ simulator** on the host, device
`fenix8solar47mm`, 2026-09-30. The values are the simulator's stand-ins
(zero steps and floors, all four race predictions 0, every weather
condition 1, a golf score), so this says what the simulator does, not the
firmware. **A watch run is still owed.** Goals reported:
`stepGoal=5000`, `floorsClimbedGoal=10`, `activeMinutesWeekGoal=150`.

**All 41 types listed reported `r=null`**, types 1–39, 41 and 42. Type 40
(`wheelchair_pushes`) was not offered at all, which fits its "only
available in wheelchair mode". No app complication (`t0`) was present, so
whether an app's `<range>` reaches a face is untested.

Other things the log settles:

| Finding | Evidence (`t<type>\|v=\|u=`) | Consequence |
|---|---|---|
| Body Battery carries the unit `"%"`; stress carries none | `t23\|v=16\|u=%`, `t22\|v=85\|u=null` | in the simulator, Body Battery's 0–100 rests on its own unit; stress's is still Garmin's definition only |
| Battery, pulse ox and solar carry `"%"` too | `t1`, `t35`, `t37` | matches the Type table's "0 to 100" |
| Native units come back as either a `Complications.Unit` number or a string | altitude `u=3` (`UNIT_HEIGHT`, not `UNIT_ELEVATION`), weekly distances `u=1` (`UNIT_DISTANCE`), race paces `u=4` (`UNIT_SPEED`), temperature `u=5` (`UNIT_TEMPERATURE`); sunrise/sunset and race times `"s"`, pressure `"Pa"` | `UNIT_SUFFIX` already maps both height and elevation to "m" |
| Floats print with six decimals | `t15\|v=3993.003662`, `t16\|v=99074.000000` | already handled by `WfbReading.formatValue` |
| Steps past 10,000 in thousands | second run, below | §5 |

**Second run**, same simulator and device, 2026-09-30, with the activity
data moved on: `stepGoal=8000` (was 5000), `steps=12569`,
`floorsClimbed=13` (goal 10).

| Finding | Evidence | Consequence |
|---|---|---|
| `ranges` stays null with the value past its goal and after the goal changed | every row `r=null`; `t2` steps 12 569 > 8000, `t4\|v=13` floors > 10, `t5\|v=240` intensity minutes > 150 | no hidden goal-tracking scale; the table's goal lookups are needed |
| Steps past 10,000 arrive in thousands, to the step | `t2\|v=12.569000\|u=K` against ActivityMonitor `steps=12569` | §5: unscale, and round |
| Floors and intensity minutes arrive as whole counts, unscaled | `t4\|v=13` = `floorsClimbed=13`; `t5\|v=240` | only `"K"` needs undoing |
| The complication and ActivityMonitor agree | steps and floors identical | a gauge may read either |
| Values past the goal are normal | three of three goal types over | the gauge's fraction must clamp at 1 (it already does) |

**Third run: a real fr955**, 2026-10-01 (firmware's own data: real race
predictions, weather, date). Goals: `stepGoal=8000`,
`floorsClimbedGoal=10`, `activeMinutesWeekGoal=150`; `steps=150`. The log
holds the block twice: `onLayout` ran twice, which is harmless here.

**Every type reported `r=null`.** The device offered types 1–39 and 41: no
40 (`wheelchair_pushes`, wheelchair mode off) and no 42 (`sleep_score`,
API 6.0.2, above the fr955's 5.2.0), as expected. Where the watch differs
from the simulator:

| Type | Simulator (fenix8solar47mm) | fr955 watch | Consequence |
|---|---|---|---|
| `body_battery` (23) | `v=16\|u=%` | `v=72\|u=null` | Body Battery's 0–100 does **not** come from a unit on a watch; it rests on Garmin's definition, like stress |
| `sunrise`/`sunset` (13/14) | `u=s` | `u=null` | the unit cannot be relied on; the per-type rule, not the unit, says "seconds" |
| `altitude` (15) | `u=3` (`UNIT_HEIGHT`) | `u=2` (`UNIT_ELEVATION`), `v=461.971893` | both map to "m" already |
| `training_status` (26) | `Productive` | `PRODUCTIVE` | the short-form lookup is case-insensitive either way |
| `high_low_temperature` (39) | `19/6` | `H 19 / L 13` | the watch matches the SDK's documented format |
| `calendar_events` (12) | `1:00` | `null` | no event today reads as **null** on a watch |
| `pulse_ox` (35), `notification_count` (36), `weekly_bike_distance` (20), `last_golf_round_score` (41) | values | `null` | absence is normal (constraint 8) |
| `current_temperature` (38) | `19.000000` | `17.777779` | = 64 °F in Celsius: the watch keeps whole Fahrenheit, so rounding Celsius is right and °F reads back exact |
| `vo2max_bike` (25) | `40` | `0` | consistent with "0 = nothing recorded", alongside a run VO2 max of 49 |
| race predictors (27–30), paces (31–34) | `0` | `1466`…`15783` s, `3.41`…`2.67` m/s | real values, units as documented |

**The simulator's answer is not the watch's.** The simulator supplies its
own stand-in values; `ranges` there says nothing about firmware. Both are
worth recording, the watch's decides.

## 3. The per-type full scale, when `ranges` is null

For each of the 42 types, the limit the compiler can supply itself
(`wfb/complications.py` names; units per `READING`):

| Full scale | Types | Source |
|---|---|---|
| **fixed 0–100** | `battery`, `body_battery`, `pulse_ox`, `solar_input`, `sleep_score`, `stress` | the SDK's own Type table says "0 to 100" for battery, pulse ox, solar input and sleep score; Body Battery and stress are not in that table, but Garmin's manuals state "from 0 to 100" for both (§7), VERIFIED; on an fr955 neither carries a unit (§2.4) |
| **today's goal** | `steps` → `ActivityMonitor.Info.stepGoal`; `floors_climbed` → `floorsClimbedGoal`; `wheelchair_pushes` → `pushGoal` | `Toybox/ActivityMonitor/Info.html`; all three nullable |
| **this week's goal** | `intensity_minutes` → `activeMinutesWeekGoal` | same; the type "resets weekly" |
| **a day** | `sunrise`, `sunset` → 86 400 s | "seconds since midnight local time"; a gauge reads as time of day |
| **max heart rate** | `heart_rate` → `UserProfile.getHeartRateZones(...)` last element; min is element 0 | `Toybox/UserProfile.html`; needs the `UserProfile` permission, added by default (user decision, §6) |
| **none: author must supply** | `calories` (no calorie goal in `ActivityMonitor.Info`), `notification_count`, `altitude`, `sea_level_pressure`, `current_temperature`, `respiration_rate`, `recovery_time`, `vo2max_run`/`_bike`, the four race predictors, the four race paces, `weekly_run_distance`/`_bike_distance` | no documented limit; a made-up one (say 96 h recovery) would be an invented fact |
| **not numeric: cannot be a gauge** | `date`, `weekday_monthday`, `calendar_events`, `training_status`, `high_low_temperature`, `last_golf_round_score`, and the four weather conditions (numbers, but an enum, not a quantity) | the Type table's value types |
| **not offered to a face at all** | training readiness, HRV status (the device's own face fields `TRAINING_READINESS`, `HRV_STATUS`, seen in the simulator binary) | no `COMPLICATION_TYPE_*`, and no symbol in `$CIQ_SDK/bin/api.debug.xml` (VERIFIED, SDK 9.2.0) |

Thirteen types get a limit for free (six fixed, four goals, two days, and
heart rate); nineteen numeric types have none; ten cannot be a
gauge at all.

## 4. A gauge on a selectable slot

Today a slot is drawn by one `type: data` element. The generated
`SlotText.mc` `switch`es on `Complications.Id.getType()` of the wearer's
pick, with a case only for the types the slot's `choices:` allow — the
pattern the `config-axes` probe verified buildable under `-l 3`.

A gauge on a slot is the same shape with a different output: a generated
`SlotScale.mc` (name illustrative) returning `[min, max]` (or `null`) for
the picked type from the §3 table. Native types leave `ranges` null in
the simulator (§2.4), so it is read only for a pick the table does not
know:

```monkeyc
// per frame, per gauge slot
var scale = SlotScale.fullScale(slotId.getType());  // switch over choices; null if none
if (scale == null) {
    var c = Complications.getComplication(slotId);  // pull, no subscription
    var r = c.ranges;
    if (r != null && r.size() >= 2) { scale = [r[0], r[r.size() - 1]]; }
}
```

What that settles and what it leaves:

* **`choices:` decides what the build can check.** With a closed list, the
  compiler knows every type the slot can show, so it can reject one that
  cannot be a gauge (§3's last row) at build time and require an author
  `max:` for one with no limit (§3's "none" row) — or accept it and draw the
  track with no fill, the same as `absent: hide`.
* **`choices: any` cannot be checked at build time.** The editor offers
  every type, including strings, and app complications (`getType()` is
  `COMPLICATION_TYPE_INVALID`) that only `ranges` can describe. The honest
  behaviour is "track, no fill" for a pick with no scale, plus a build-time
  warning that the slot allows picks a gauge cannot show.
* **One slot, several elements.** A useful gauge slot is a ring *plus* the
  reading *plus* the icon. That means letting a `gauge` and a `data`
  element name the same `slot:`, and the editor's highlight box
  (`getComplicationDrawable`, hit-testing in `onTap`) becoming the union of
  their boxes. How the existing slot code keys its one drawing element per
  slot needs reading before this is planned.
* **Bands.** Native types carry no band edges (§2.4), so there is nothing
  to map onto a `style: scale` gauge's `bands:` automatically; the
  author's `bands:` fractions stay as they are.

## 5. A value the gauge must not trust: steps in thousands

The host simulator hands `COMPLICATION_TYPE_STEPS` past 10,000 over as a
Float in thousands with the unit `"K"`: `v=12.569000|u=K` while
`ActivityMonitor` read `steps=12569` (§2.4, second run; first seen
2026-09-28 and recorded in `docs/limitations.md` and
`runtime-lib/WfbReading.mc`). The slot's *text* is fine — `WfbReading`
keeps the device's scaling. A *gauge* is not: `12.569 / 8000` is a fill of
0.16%.

So a gauge fed from a complication must **unscale a String unit `"K"`**
(×1000) before dividing, and must **round, not truncate**. Modelled in
IEEE single precision (Monkey C's `Float`), `n / 1000` then `× 1000`
comes back just under `n` for 1 384 of the counts from 10 000 to 199 999
(the first is 16 001), so `toNumber()` would read one step low; rounding
recovers every one of them exactly. That model assumes the device forms
the Float as `n / 1000` in single precision, which the six-decimal print
fits but does not prove.

This bites the fixed binding today too: `value: complication.steps` with
`max: activity.step_goal` draws an almost empty ring past 10,000 steps in
the simulator. (`activity.steps`, read from `ActivityMonitor`, is
unaffected.) Whether a watch does the same is still owed: the fr955 run
(§2.4) had only 150 steps, which arrived as the plain Number `150`.

## 6. Recommended shape (for a plan, not decided)

```yaml
config:
  slots:
    left: { default: steps, choices: [steps, body_battery, stress, floors_climbed] }

elements:
  left_ring:
    type: gauge
    style: arc
    slot: left            # instead of value:
    max: auto             # the default when slot: is given
    # ...radius, thickness, angles, colours as today...
    absent: hide
  left_text: { type: data, slot: left, icon: auto }
```

* `max: auto` resolves, in order: the §3 table for a native type, else
  `ranges`' last value (an app complication, or a native type the table
  has no limit for, if a watch fills it), else absent
  (track only). `min` likewise: 0, `heart_rate`'s zone-1 floor, or
  `ranges[0]`. The gauge has no `min:` today, so the fraction becomes
  `(value - min) / (max - min)`.
* `max: auto` is also allowed on a fixed `value: complication.<type>`,
  where the build knows the type and emits just that one case — the
  "universal complication renderer" of the question, with no slot.
* An author `max:` still wins, and is what makes a no-limit type
  (`calories`, `altitude`) usable.
* Build-time checks, each driven red: a slot `choices:` entry that cannot
  be a gauge (error), one with no limit and no author `max:` (warning, it
  draws as absent), `choices: any` on a gauge slot (warning).
* The "K" unscale (§5) goes in the shared read, for both paths.
* The preview gets the §3 table too, so `wfb preview` fills a gauge with
  its stand-in value against a real-shaped limit.

**User decision (2026-10-01):** heart rate's full scale is on **by
default**: a gauge that can show `heart_rate` adds the `UserProfile`
permission, derived like every other permission (constraint 7).

**User decision (2026-10-01): option A.** A gauge names `slot:` itself,
beside the slot's `data` element; the gauge's style stays the author's
choice. On top of §6's sketch, the gauge picks its own *form* per picked
type from what is known about that type (§7): segmented when band edges
are known, a plain fill when only a full scale is, hidden when neither is.
The editor wiring keys every element of a slot, not the first (§4). The
alternative, a `gauge:` part inside `type: data`, belongs to the reserved
data widget (`parts:`) and is not pursued here.

## 7. Band edges: which metrics have zones, ratings or levels

A segmented or colour-coded gauge needs band edges, not just a full scale.
Where they can come from, best first:

| Source | Metric | Edges | Evidence |
|---|---|---|---|
| **The device, per wearer, live** | `heart_rate` | `UserProfile.getHeartRateZones(sport)`: min zone 1, then the top of zones 1–5 (6 values, 5 zones). `getHeartRateZones2(Activity.Sport)` is the newer form | `Toybox/UserProfile.html`, VERIFIED (SDK); not yet read on a watch |
| | `activity.move_bar_level` (a catalogue source, **not** a complication, so no slot) | `MOVE_BAR_LEVEL_MIN` 0 to `MOVE_BAR_LEVEL_MAX` 5: already segments | `Toybox/ActivityMonitor.html`, VERIFIED (SDK) |
| **`Complication.ranges`** | none native | null for every native type | §2.4, VERIFIED (fr955 and simulator); only an app's complication could carry edges |
| **Garmin's owner's manuals, fixed** (not the SDK: a compiler table, citing the manual) | `body_battery` | 0–25 low, 26–50 medium, 51–75 high, 76–100 very high reserve energy | Forerunner 255 manual, "Body Battery", fetched 2026-10-01: *"0 to 25 is low reserve energy, 26 to 50 is medium reserve energy, 51 to 75 is high reserve energy, and 76 to 100 is very high reserve energy"* |
| | `stress` | 0–25 resting, 26–50 low, 51–75 medium, 76–100 high | Lily manual, "Heart Rate Variability and Stress Level", fetched 2026-10-01: *"0 to 25 is a resting state, 26 to 50 is low stress, 51 to 75 is medium stress, and 76 to 100 is a high stress state"* |
| | `sleep_score` | 0–59 poor, 60–79 fair, 80–89 good, 90–100 excellent | Garmin blog, fetched 2026-10-01: *"Excellent (90-100), Good (80-89), Fair (60-79) or Poor (0-60)"* ("New Data Examines Quality of Garmin Users' Sleep") and *"excellent (90-100), good (80-89), fair (60-79) and poor (0-60)"* ("How well do you sleep?"). Both give 60 to two bands; it is read as fair, the band that starts there. Not in the fēnix 8 manual's "Sleep Tracking" page |
| **Garmin's manuals, per wearer** | `vo2max_run`, `vo2max_bike` | five ratings by sex and age decade: §7.1 | fēnix 8 manual, "VO2 Max. Standard Ratings", fetched and transcribed 2026-10-01. Computable on the watch from `UserProfile.Profile.gender` and `birthYear` (`Toybox/UserProfile/Profile.html`) |
| **None anywhere** | `battery`, `pulse_ox`, `solar_input`, `steps`, `floors_climbed`, `intensity_minutes`, `wheelchair_pushes`, `sunrise`/`sunset` | a full scale only (§3): a plain fill, or author bands | — |
| | `training_status` | a String category, no number. Segments would need a status-to-step table keyed on English capitals, and a localised watch may report other words | §2.4 (`PRODUCTIVE` on the fr955) |
| | training readiness, HRV status | not offered to a face at all | §3 |

So a reworked gauge can know, per picked type: **edges** (heart rate,
Body Battery, stress, sleep score, VO2 max), **a full scale only** (the
rest of §3's 13), or **nothing** (§3's "none" and "not numeric" rows, and
an app's complication without `ranges`) — which is exactly the
segmented / plain / hidden choice.

### 7.1 VO2 max standard ratings

Transcribed from the fēnix 8 Series Owner's Manual, appendix "VO2 Max.
Standard Ratings" (`www8.garmin.com/manuals/webhelp/GUID-EECCAC99-90D6-4AB1-9A3A-EC433D3365E2/EN-US/GUID-1FBCCD9E-19E1-4E4C-BD60-1793B5B97EB3.html`,
page dated September 2026), fetched 2026-10-01. *"Data reprinted with
permission from The Cooper Institute®."* Values in mL/kg/min; each figure
is the lowest value of that rating, at that percentile.

**Males**

| Rating | Percentile | 20–29 | 30–39 | 40–49 | 50–59 | 60–69 | 70–79 |
|---|---|---|---|---|---|---|---|
| Superior | 95 | 55.4 | 54 | 52.5 | 48.9 | 45.7 | 42.1 |
| Excellent | 80 | 51.1 | 48.3 | 46.4 | 43.4 | 39.5 | 36.7 |
| Good | 60 | 45.4 | 44 | 42.4 | 39.2 | 35.5 | 32.3 |
| Fair | 40 | 41.7 | 40.5 | 38.5 | 35.6 | 32.3 | 29.4 |
| Poor | 0–40 | <41.7 | <40.5 | <38.5 | <35.6 | <32.3 | <29.4 |

**Females**

| Rating | Percentile | 20–29 | 30–39 | 40–49 | 50–59 | 60–69 | 70–79 |
|---|---|---|---|---|---|---|---|
| Superior | 95 | 49.6 | 47.4 | 45.3 | 41.1 | 37.8 | 36.7 |
| Excellent | 80 | 43.9 | 42.4 | 39.7 | 36.7 | 33 | 30.9 |
| Good | 60 | 39.5 | 37.8 | 36.3 | 33 | 30 | 28.1 |
| Fair | 40 | 36.1 | 34.4 | 33 | 30.1 | 27.5 | 25.9 |
| Poor | 0–40 | <36.1 | <34.4 | <33 | <30.1 | <27.5 | <25.9 |

**User decisions (2026-10-01)** on applying it:

* **Reading it:** the rating is the highest row whose figure the value
  reaches (Poor below Fair). One column's four figures (Fair, Good,
  Excellent, Superior) are the edges between the five bands.
* **The ends of the scale are derived, not Garmin's.** The table has no
  ceiling (Superior is a 95th percentile) and no floor. The Poor and
  Superior bands are each given **the average width of the three inner
  bands**, `w = (Superior − Fair) / 3`, so `min = Fair − w` and
  `max = Superior + w`. Computed from the table, rounded to 0.1:

  | mL/kg/min | 20–29 | 30–39 | 40–49 | 50–59 | 60–69 | 70–79 |
  |---|---|---|---|---|---|---|
  | Males `min` | 37.1 | 36.0 | 33.8 | 31.2 | 27.8 | 25.2 |
  | Males `max` | 60.0 | 58.5 | 57.2 | 53.3 | 50.2 | 46.3 |
  | Females `min` | 31.6 | 30.1 | 28.9 | 26.4 | 24.1 | 22.3 |
  | Females `max` | 54.1 | 51.7 | 49.4 | 44.8 | 41.2 | 40.3 |

  A value outside `[min, max]` clamps to the end, as every gauge does.
* **Age is approximate:** `current year − birthYear`. The profile has no
  birth date, so for part of a year the wearer reads one column early.
  Accepted.
* **Missing information hides the gauge.** No `birthYear`, no `gender`,
  or `GENDER_UNSPECIFIED` (2, API 4.2.3): hidden, as an absent reading.
* **An age with no column hides the gauge.** Under 20, or 80 and over:
  hidden, as missing data. No nearest-column fallback.
* **The cycling VO2 max uses the same table.** The manual gives one table
  for "VO2 max. estimates" without naming a sport.
* The table plus the derived ends are 2 × 6 × 6 = 72 numbers, a small
  constant array on the watch.

Garmin's colours for these bands (its blues for Body Battery, oranges for
stress) are not documented as values anywhere found, so band *colours*
stay the author's: a face gives one colour per band position, or a
palette default.


## Sources

* Garmin owner's manuals (www8.garmin.com/manuals), fetched 2026-10-01: fēnix 8 "VO2 Max. Standard Ratings" (§7.1) and "Sleep Tracking" (no bands), Forerunner 255 "Body Battery", Lily "Heart Rate Variability and Stress Level"
* Garmin blog (www.garmin.com/en-US/blog), fetched 2026-10-01: "New Data Examines Quality of Garmin Users' Sleep" and "How well do you sleep? New data examines Garmin users' sleep" (sleep-score bands); "How Garmin watches track your sleep, calculate sleep score" (only the excellent band, 90–100, stated)

* `$CIQ_SDK/doc/Toybox/Complications.html`, `.../Complications/Complication.html` (SDK 9.2.0)
* `$CIQ_SDK/doc/docs/Core_Topics/Complications.html`
* `$CIQ_SDK/doc/Toybox/ActivityMonitor/Info.html`, `$CIQ_SDK/doc/Toybox/UserProfile.html`
* `$CIQ_SDK/bin/simulator` (strings), `~/.Garmin/ConnectIQ/Devices/fenix8solar47mm/simulator.json`
* `probes/config-axes/` (`getType()` switch), `probes/complication-pull/` (pull without a field)
* [forums.garmin.com: "Stupid complications questions"](https://forums.garmin.com/developer/connect-iq/f/discussion/349460/stupid-complications-questions/1696149)
