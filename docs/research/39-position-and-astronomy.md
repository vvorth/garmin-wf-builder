# 39 — The wearer's position, and astronomy from it

**Question.** Can a watch face know where the wearer is, and what does it
take to compute the sun and moon from that on the watch? Which symbols
exist on which of the 34 installed devices, what does the SDK say about
each, and what remains unverified until a face runs on a real watch?

**Short answer.** A watch face reads its position off the weather report:
`Weather.CurrentConditions.observationLocationPosition` (API 3.2.0) is a
`Position.Location` the face turns into degrees with `toDegrees()`, and
it is null unless the manifest declares the `Positioning` permission.
The field is on 32 of the 34 installed devices; the two without it
(`fenix5`, `fenix5x`, ConnectIQ 3.1.6) have no `Toybox.Weather` at all.
The time-zone offset and the trigonometry an astronomy helper needs
(`ClockTime.timeZoneOffset`, `Math.sin/cos/asin/acos/atan2`) are on all
34. Built as the catalogue's `position.latitude`/`position.longitude`
through a new barrel file, `runtime-lib/WfbAstro.mc`, which this note's
sun and moon formulas extend (§5, appended when they are built).

SDK: Connect IQ 9.3.0 at `$CIQ_SDK` (`/root/ciq/sdks/9.3.0`); the
device files at `~/.Garmin/ConnectIQ/Devices/<id>/<id>.api.debug.xml`,
34 devices, surveyed 2026-10-29.

## 1. The symbols, device by device

Every claim here is a `grep` of the device's own `api.debug.xml`
(`<entry field="true" symbol="...">` for a field, `<functionEntry
name="..." parent="...">` for a function, `<dataEntry type="module"
symbolId="...">` for a module), the same rows `Device.hasField`,
`hasSymbol` and `hasModule` in `ts/src/devices/device.ts` read.

| Symbol | Kind | On | Missing on |
|---|---|---|---|
| `Toybox.Weather` | module | 32 | `fenix5`, `fenix5x` |
| `CurrentConditions.observationLocationPosition` | field | 32 | `fenix5`, `fenix5x` |
| `Toybox.Position` | module | 34 | — |
| `Position.Location.toDegrees` | function | 34 | — |
| `Lang.Double.toFloat` | function | 34 | — |
| `System.ClockTime.timeZoneOffset` | field | 34 | — |
| `Math.sin`, `Math.cos`, `Math.asin`, `Math.acos`, `Math.atan2` | function | 34 | — |

The 34: enduro3, enduro4, epix2, fenix5, fenix5x, fenix6, fenix6xpro,
fenix7pro, fenix7x, fenix7xpro, fenix7xpronowifi, fenix847mm,
fenix8solar47mm, fenix8solar51mm, fenix947mm, fenix9prosolar47mm,
fenix9prosolar51mm, fenixe, fr245, fr255, fr955, instinct2, instinct2x,
instinct3amoled50mm, instinct3solar45mm, instinctcrossoveramoled,
instincte45mm, venu, venusq, venusq2, venux1, vivoactive4, vivoactive4s,
vivoactive6.

Consequences for the generated code:

- `Toybox.Position` needs no `has` guard: no installed device lacks the
  module, so `WfbAstro.mc` imports it and calls `toDegrees()` unguarded.
  (`Device.hasModule` would report a device that lacked it, and the
  `weather_current` reader's module check would not cover it; if such a
  device file ever arrives, the barrel gains a `Toybox has :Position`
  check beside its Weather one.)
- The field is newer (3.2.0) than `fenix5`'s level (3.1.6), so a build
  naming `fenix5` guards the read with `weatherCurrent has
  :observationLocationPosition` beside `Toybox has :Weather`
  (constraint 6d: SDK 9.3.0's `monkeyc` rejects the symbol otherwise),
  and `WfbAstro.latitude`/`longitude` carry the same two checks
  themselves (a check in the caller does not count,
  `docs/lore/monkeyc.md`). VERIFIED by a real build: a face binding both
  sources compiles warning-free under `-l 3` on `fenix5`,
  `fenix8solar47mm` and `fr955` in one build (§4).

## 2. What the SDK says, in its own words

- `$CIQ_SDK/doc/Toybox/Weather/CurrentConditions.html`:
  `observationLocationPosition as Position.Location or Null` — "Location
  where the conditions were observed. If the app does not have the
  position permission then this will be null." Since API Level 3.2.0.
- `$CIQ_SDK/doc/Toybox/Weather.html`: `getCurrentConditions() as
  Weather.CurrentConditions or Null` — "Get the most recently cached
  weather conditions."
- `$CIQ_SDK/doc/Toybox/Position/Location.html`: `toDegrees() as [
  Lang.Double, Lang.Double ]` — "Get a Location object's coordinates in
  degrees. … An Array containing the latitude and longitude as Doubles in
  a degree format"; the page's own example prints `myLocation[0]` as the
  latitude (38.856147) and `myLocation[1]` as the longitude (-94.800953).
  Since API Level 1.0.0.
- `$CIQ_SDK/doc/Toybox/System/ClockTime.html`: `timeZoneOffset as
  Lang.Number` — "The time offset from UTC in seconds." Since API Level
  1.0.0. The page says nothing about daylight-saving time; a separate
  `dst as Lang.Number` ("The daylight savings time offset") sits beside it.
- `$CIQ_SDK/doc/Toybox/Math.html`: `sin`, `cos`, `asin`, `acos`, `atan2`
  each take `Lang.Numeric` and return `Lang.Decimal` (`Float or Double`),
  the typing `docs/lore/monkeyc.md` already records for `sin`/`cos`.
- `ts/src/data/catalog.json`'s `watchface_permissions` lists
  `Positioning` among the permissions a watch face may declare
  (`Core_Topics/Manifest_and_Permissions.html`'s "Watch Face" column).

## 3. What was built

- Two catalogue sources, `position.latitude` and `position.longitude`
  (`ts/src/data/catalog.json`): float, degrees, nullable, reader
  `weather_current`, `field_name: observationLocationPosition` (the key of
  the per-device field check), `permissions: ["Positioning"]`, read through
  `call: WfbAstro.latitude` / `WfbAstro.longitude`. The `call:` mechanism
  itself is described in `docs/lore/codegen.md`.
- `runtime-lib/WfbAstro.mc`: `latitude(conditions as
  Weather.CurrentConditions) as Float?` and `longitude(...)`, each inside
  `(Toybox has :Weather) && (conditions has :observationLocationPosition)`,
  returning `toDegrees()[0]`/`[1]` as a `Float` (`Double.toFloat`, on all
  34), or null when the report carries no location. The generated read is
  `(weatherCurrent != null) ? WfbAstro.latitude(weatherCurrent) : null`,
  the manifest gains `<iq:uses-permission id="Positioning"/>`.
- Sample values 51.4769, -0.0005 (the Royal Observatory, Greenwich:
  nobody's own, and local sidereal time there is GMST), overridable with
  `--sample position.latitude=<deg>`.
- The guide paragraph in `docs/guide/data.md`; the tests in
  `ts/test/position.test.ts`.

## 4. Measured

A scratch face (a clock plus `"lat {position.latitude:.4f}"` and `"lon
{position.longitude:.4f}"`, both `absent: {text: "--"}`) through
`./wfb build`, SDK 9.3.0, `-l 3`:

| Build | Result |
|---|---|
| `fenix8solar47mm`, `fenix8solar51mm`, `fr955` | warning-free; 1,283 B / 131,072 B on each |
| the same with `-d fenix5` added | compiles on all three (fenix5 2,185 B / 98,304 B; the others 1,354 B: the two `has` checks); two `api-gated` warnings, one per binding, "needs module Toybox.Weather, which fenix5 lacks" |

The preview renders the sample as `lat 51.4769` / `lon -0.0005`, and
`--sample position.latitude=48.8566,position.longitude=2.3522` as
`lat 48.8566` / `lon 2.3522`.

## 5. Astronomy

Appended when the `astro.*` sources are built: the formulas, the host
twin, and the accuracy achieved in single precision.

## 6. UNVERIFIED on a watch

- That a sideloaded face declaring `Positioning` actually receives
  `observationLocationPosition`: the SDK states the rule, and the
  simulator does not run in this container (root `CLAUDE.md` §3). The
  value stays null until the watch has a weather report in any case.
- Whether `timeZoneOffset` includes daylight-saving time when it is in
  force: the SDK does not say, and `dst` is a separate field.
  `time.utc_offset` is whatever `timeZoneOffset` holds.
- That `toDegrees()` answers `[latitude, longitude]` in that order on a
  watch: the SDK's example says so; not observed here.

## Sources

* `$CIQ_SDK/doc/Toybox/Weather/CurrentConditions.html`,
  `$CIQ_SDK/doc/Toybox/Weather.html`, `$CIQ_SDK/doc/Toybox/Position.html`,
  `$CIQ_SDK/doc/Toybox/Position/Location.html`,
  `$CIQ_SDK/doc/Toybox/System/ClockTime.html`, `$CIQ_SDK/doc/Toybox/Math.html`
  (SDK 9.3.0)
* `~/.Garmin/ConnectIQ/Devices/<id>/<id>.api.debug.xml` for the 34 installed
  devices (2026-10-29)
* `ts/src/data/catalog.json` (`watchface_permissions`)
