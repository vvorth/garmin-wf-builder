# Probe: what time series can a watch face actually plot?

**Answer: four families, and none of them is solar.** `BUILD SUCCESSFUL`,
warning-free, under `-l 3` on `fenix8solar47mm`, `fenix8solar51mm` and `fr955`,
SDK 9.2.0, at **417 B data + 1,482 B code** for all three acquisition
strategies and all three drawing styles together.

## The one that is closed, and why it matters

`Toybox.SensorHistory` -- heart rate, elevation, **pressure**, temperature,
oxygen saturation, stress and Body Battery, all as real iterators -- is not
available to a watch face. `Core_Topics/Manifest_and_Permissions.html`'s
permission table has a "Watch Face" column, and the `SensorHistory` row's cell
is **empty** (Data Field's is too; Widget, App and Audio Content Provider have
an `x`).

The trap is that this **compiles anyway**. A watchface manifest declaring
`<iq:uses-permission id="SensorHistory"/>` and calling
`SensorHistory.getPressureHistory({...})` builds warning-free on all three
targets. A permission a watch face may not hold fails *silently* at runtime
(CLAUDE.md constraint 7), so the only symptom would be an empty graph on the
wrist. Do not read that successful build as availability.

Corroborating evidence that the gate is real rather than a documentation slip:
Garmin duplicated heart-rate history into `ActivityMonitor.getHeartRateHistory`,
which needs **no permission at all** -- exactly the API you would add if
`SensorHistory` were closed to faces and heart rate still had to be reachable.

## Solar is not gated -- it does not exist

There is no solar *history* anywhere in Connect IQ. Grepping every module under
`$CIQ_SDK/doc/Toybox/` finds solar only as two current-value reads:

* `System.Stats.solarIntensity` -- "a Number value from 0-100 that describes
  the solar sensor's charge efficiency, if available";
* `Complications.COMPLICATION_TYPE_SOLAR_INPUT` (37, API 4.2.0) -- the same
  quantity through the complication door.

The solar chart on a stock fēnix face is native firmware. A Connect IQ face can
only get one by sampling `solarIntensity` itself and keeping its own buffer,
which is a separate design with its own unmeasurable risks (flash writes, and
coverage gaps whenever the face is not the active one).

## What is open

| Series | Call | Permission | Axis |
|---|---|---|---|
| heart rate | `ActivityMonitor.getHeartRateHistory(period, newestFirst)` | none | past |
| steps, calories, distance, floors, active minutes | `ActivityMonitor.getHistory()` | none | past, ≤ 7 days |
| temperature, precipitation chance, cloud cover, UV, wind, humidity | `Weather.getHourlyForecast()` | none | future hours |
| high/low temperature, precipitation chance | `Weather.getDailyForecast()` | none | future days |

Every one of them was checked against all three targets' own
`<id>.api.debug.xml` **and** its SDK page's own "Supported Devices" list before
being written down here.

`ActivityMonitor` and `Weather` appear nowhere in the permission table, the
same situation `Toybox.Activity` is already in -- see `wfb/catalog.py`'s
`weather_current` reader comment.

## What the probe pins down that a doc page does not

1. **`period` is genuinely two things.** `getHeartRateHistory` takes either a
   `Time.Duration` ("the last four hours") **or** a plain `Number` ("the last
   thirty samples"). Both compile; `hrByDuration` and `hrByCount` are the two
   shapes. This is what lets one `range:` key mean either.
2. **`newestFirst: false` gives oldest-first**, which is left-to-right on
   screen, so no reversal is needed in the drawing loop.
3. **The iterator carries its own `getMin()`/`getMax()`**, both
   `Number or Null`. That is automatic axis scaling for free -- and it is
   scoped to the samples in *this* iterator, not the whole history.
4. **`ActivityMonitor.INVALID_HR_SAMPLE` is 255**, and the SDK's own example
   checks it before use. `heartRate` can also be `null` outright. Both checks
   are needed; neither is sufficient alone.
5. **Time bucketing is integer arithmetic all the way.** `hrByDuration` bins by
   `age * buckets / span` with no float anywhere; the largest intermediate at a
   24-hour range and 60 buckets is about 5.2 million, comfortably inside a
   32-bit Number.
6. **The filled style is one `fillPolygon`,** because `Dc` has no other fill
   that follows a curve -- and it therefore inherits the SDK's own **64-point
   cap**, already recorded for `shape: polygon`. A filled graph closes its
   outline with two extra corner points, so the usable sample count is **62**,
   not 64. The cast `as Array<Graphics.Point2D>` is required for the same
   reason `docs/research/probes/polygon-const/` records: `Point2D` is a fixed
   size tuple type, not `Array<Number>`.
7. **`new [n]` compiles with an `as Array<Number>` annotation** and is how a
   fixed-size bucket array is allocated.

## What it deliberately does NOT settle

* Whether the per-frame cost of iterating a history is acceptable in
  `onPartialUpdate`. There is no simulator here (`docs/limitations.md` §2) and
  no watch, so CPU is unmeasured -- as it is for every other feature in this
  repo. The probe rebuilds the series only when `System.getClockTime().min`
  changes, which is one `Number` comparison per frame and is the shape the
  generator should emit; that is a cheap precaution, not a measurement.
* The device-dependent sample interval. `getHeartRateHistory` documents that
  "the time between each `HeartRateSample` in the iterator may be device
  dependent", so a duration range cannot be turned into a known sample count at
  build time. Binning by time, as `hrByDuration` does, is the answer; a lint
  cannot warn about a bucket count that will come out sparse.

## Rebuilding it

Source-only, like `../carousel/`. Drop `ProbeView.mc` into a minimal watch-face
project with an `AppBase` returning it, then:

```sh
$CIQ_SDK/bin/monkeyc -f monkey.jungle -d fenix8solar47mm \
    -o probe.prg -y ~/ciq/developer_key.der -w -l 3 --build-stats 0
```
