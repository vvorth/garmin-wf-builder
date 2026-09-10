# 08 — Graphs and user configuration

- **Date:** 2026-09-10
- **Asks:** (A) a graph element — size, data source, time range, drawn as a
  line, a filled area or bars, with an automatic or manual value axis;
  (B) user configuration of a face — none at all (today's behaviour), or the
  native on-watch editor the fēnix 8 provides.
- **Backed by:** `probes/graph-series/`, `probes/watchface-config/`,
  `probes/device-symbol-gate/`. Every claim below that says "verified" was
  built with real `monkeyc` on all three targets.

---

## 1. A watch face can plot four series, and solar is not one of them

The obvious API is `Toybox.SensorHistory` — heart rate, elevation, pressure,
temperature, oxygen saturation, stress and Body Battery, each a real iterator
with a period and an order. **A watch face may not use it.**
`Core_Topics/Manifest_and_Permissions.html`'s permission table has a "Watch
Face" column and the `SensorHistory` row's cell is empty.

It compiles anyway. A watchface manifest declaring the permission and calling
`getPressureHistory` builds warning-free on all three targets — and a
permission a face may not hold fails *silently* (constraint 7), so the only
symptom would be an empty graph on the wrist. That trap is why this is written
down rather than left implicit.

**Solar is a different and stronger negative: no history API exists at all.**
Grepping every module under `$CIQ_SDK/doc/Toybox/` finds solar as two
current-value reads only — `System.Stats.solarIntensity` (0–100, "if
available") and `COMPLICATION_TYPE_SOLAR_INPUT`. The solar chart on a stock
fēnix face is native firmware. No permission would unlock it.

What is open, all needing **no permission** and all present on all three
targets (checked against each device's own `api.debug.xml` *and* each SDK
page's "Supported Devices" list):

| Series | Call | Axis |
|---|---|---|
| heart rate | `ActivityMonitor.getHeartRateHistory(period, newestFirst)` | past |
| steps, calories, distance, floors, active minutes | `ActivityMonitor.getHistory()` | past, ≤ 7 days |
| temperature, precipitation chance, cloud cover, UV index, wind, humidity | `Weather.getHourlyForecast()` | future hours |
| high/low temperature, precipitation chance | `Weather.getDailyForecast()` | future days |

`getHeartRateHistory`'s `period` is genuinely two things — a `Time.Duration`
("the last four hours") or a bare `Number` ("the last thirty samples") — which
is what lets one authored `range:` key mean either. The iterator carries its
own `getMin()`/`getMax()`, so an automatic value axis costs nothing.

**The remaining route to solar, deferred by decision:** the face samples
`solarIntensity` itself into a rolling buffer. That is a separate design with
unmeasurable risks here — flash-write frequency, and coverage gaps whenever the
face is not the active one — and it gets its own pass rather than riding along.

### Consequences for the element

* **A filled graph is one `fillPolygon`**, the only fill `Dc` offers that
  follows a curve, so it inherits the SDK's 64-point cap already recorded for
  `shape: polygon`. Closing the outline costs two corners, so the usable sample
  count is **62**. That is a build-time check, exactly like the polygon one.
* **A duration cannot be turned into a sample count at build time.**
  `getHeartRateHistory` documents that the interval between samples "may be
  device dependent", so the generated code bins by time rather than trusting a
  count.
* **`INVALID_HR_SAMPLE` (255) and a null `heartRate` are different failures**
  and both occur; the SDK's own example checks the first.
* CPU is unmeasured, as it is for every feature in this repo. The probe rebuilds
  its series only when `System.getClockTime().min` changes — one `Number`
  comparison per frame. That is a cheap precaution, not a measurement, and
  nothing should claim otherwise.

---

## 2. `monkeyc` does not gate on the device's symbol table

This came out of the configuration work and matters well beyond it.

`UserProfile.getFunctionalThresholdPower` is one of 34 `functionEntry` symbols
present in `fenix8solar47mm.api.debug.xml` and **absent from**
`fr955.api.debug.xml`. Calling it builds `BUILD SUCCESSFUL`, warning-free,
under `-l 3`, **for `fr955`**. The typechecker is live in the same build: a
typo is `Undefined symbol`, a missing argument is a wrong-arity error, and a
missing permission is a permission error.

So `monkeyc` checks names, arities, types and permissions against the
**SDK-wide** API, and does not check per-device availability at all. A device's
symbol table describes *runtime* availability.

**`Device.has_symbol` keeps every one of its current uses.** `check_hold_targets`
warns that a hold will never fire on a device without `onPress` — a runtime
fact, which is precisely what the table reports. What is corrected is a
corollary the project had drifted into, stated in `CLAUDE.md`'s anti-aliasing
note: that a call to an absent symbol "would not typecheck under `-l 3`". It
does typecheck. The conclusion that note reaches — guard at runtime with
`Graphics has :setAntiAlias` — is still right, because the failure is a runtime
one.

The practical payoff: **one shared generated view may reference an API only
some targets have, guarded at runtime.** No per-device source split, no jungle
`sourcePath` gymnastics, no stub modules. That is what keeps §3 small.

---

## 3. The native editor: four axes, and what each is good for

API 5.1.0, fēnix 8 and newer. At most **four saved configurations** per face.
`$CIQ_SDK/samples/ConfigurableWatchFace/` is Garmin's own working example and
`resources.xsd`'s `watchfaceConfigType` is the exact grammar.

| Axis | Resource | Read back as | Useful for |
|---|---|---|---|
| Styles | `<styles>` | `Settings.styleId as Number?` | **anything the author wants** — Garmin gives the number no meaning |
| Data | `<data><complication>` | `Array<ComplicationRef>?` | choosing a Garmin **complication type** per slot |
| Data Colour | `<dataColors>` | `Settings.complicationColor as Color?` | one colour |
| Accent Colour | `<accentColors>` | `Settings.accentColor as Color?` | one colour |

Verified in the probe, at **622 B data + 972 B code** for all four together:

* a single shared view handles every target, guarded by
  `Application has :WatchFaceConfig` — `fr955` compiles it and simply keeps the
  compiled-in defaults;
* every value arrives nullable twice over (`accentColor` is `Color?`, and its
  `.color` is `ColorType?` again), so compiled-in defaults are not a fallback
  path but *the* path, which is also what makes `fr955` degrade correctly
  rather than specially;
* a slot's chosen complication reads through the existing
  `WfbComplications.valueOf(...).value as Number?` pull, unchanged;
* `<watchface-config>` forces no `minApiLevel` bump, so it belongs in
  `resources-<device>/` for the devices that support the editor rather than
  raising the floor for all of them.

### `onTap` comes back, in the one place it was always real

Research 07 §1 established that `WatchFaceDelegate.onTap` never fires on a live
watch face — "Only available in WatchFace config mode" — and the handler was
deleted as dead code. **This is that config mode.** Inside the editor, `onTap`
plus `setSelectedComplication(id)` is how the face tells the editor which slot
the wearer pointed at. Emitting it for a face that declares complication slots
is the other half of that finding, not a reversal of it: a face with no slots
still emits none, and no `onTap` is ever emitted for a live gesture.

### `getComplicationDrawable` is deliberately not implemented

It lets the editor animate a preview of the selected slot. Its return type
allows `Null`, the SDK calls it "allows you to provide", and this project's
generated view draws straight to the `Dc` rather than through `Drawable`
subclasses — so supplying one is real work for an effect nothing in this
container can observe. Recorded as a gap in `docs/limitations.md`.

---

## 4. Author-defined selectable content must ride Styles, not Data

The user's framing is the right one: rather than "the wearer picks a
complication type for this slot", let the wearer pick **which authored group**
occupies an area — a graph, a progress ring with a label, an icon and two
readings, anything the format can already express.

**The Data axis cannot do this.** `<complication>` accepts only
`Complications.COMPLICATION_TYPE_*` values or `allowAny`; there is no way to
put author-defined content in that list. Data stays what it is: a way to let
the wearer repoint one reading at a different Garmin metric.

**The Styles axis can, and it is better than it first looks.** `styleId` is an
opaque `Number` the face interprets however it likes. The naïve reading — "one
`styleId`, therefore only one selectable area per face" — is wrong, because a
style is *global*: every area on the face can respond to the same number
independently. So `styles:` becomes a face-wide list of named variants, and
each `variant` element says what it shows **per style**. Three areas × four
styles is four entries in the editor's list and twelve authored groups, not
sixty-four styles.

That also gives element-level `styles: [minimal, rich]` for free — the same
shape as the existing `modes:`, gated by the same guard machinery `visible:`
already uses.

**`select: fixed` is the other half**, and exists for a different reason:
combined with per-device `overrides:`, it lets a 51 mm screen show a richer
group than a 47 mm one, with the whole switch folded away at build time.

**Hold-to-cycle was considered and declined by the user.** It would work —
`onPress` is on all three targets and the carousel already proves the
persistence machinery — but it is a second, invisible selection mechanism
competing with the editor's own, and the format is better with one story.

---

## 5. What this does not answer

Every behavioural question about the editor. No simulator runs here
(`docs/limitations.md` §2) and there is no watch, so whether the editor lists
slots without `getComplicationDrawable`, whether `onTap`'s hit regions read
correctly, and whether a saved configuration behaves as expected are all
**UNVERIFIED** — the same standing this project already gives the
complication-pull freshness question and the static buffer's transparency
question. What is verified is that it compiles, what it costs, and that it
cannot crash a device without the editor.
