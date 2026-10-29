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
through a new barrel file, `runtime-lib/WfbAstro.mc`, whose sun and
moon formulas (§5) back the ten computed `astro.*` sources.

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

The ten `astro.*` sources are computed in `runtime-lib/WfbAstro.mc` from
the three readers the watch already has -- `Gregorian.info(Time.now(),
FORMAT_SHORT)` for the date, `System.getClockTime()` for the time of day
and `timeZoneOffset`, `Weather.getCurrentConditions()` for the position --
with `ts/src/astro.ts` as the host twin: the same formulas in the same
order of operations, so `wfb preview` and the lints see what the watch
computes. `ts/test/astro.test.ts` holds the twin to the reference values
below and the `.mc` text to the twin, statement by statement.

### 5.1 The instant

- **Day count.** `wholeDays(y, m, d) = 367y - 7(y + (m+9)/12)/4 + 275m/9
  + d - 730531`, integer division truncating, is the number of days from
  2000-01-01 00:00 to the date's midnight (Schlyter's day number shifted
  by one; exact for 1901-2099, the span the Gregorian leap rule is simple
  in). Every term is positive, so Monkey C's truncating `/` is a floor.
  `astro.day_of_year` is `wholeDays(y, m, d) - wholeDays(y, 1, 0)`.
- **UT.** The clock reads local time; `utSeconds = hour*3600 + min*60 +
  sec - timeZoneOffset` may be negative or past 86400, which is fine as a
  fraction of a day. `d = wholeDays + utSeconds/86400 - 0.5` is then days
  since J2000.0 (2000-01-01 12:00 UT), the argument every formula takes;
  `astro.days_since_j2000` is this value as a Float.
- **Date-only sources** (`sun_declination`, `equation_of_time`,
  `sun_noon_altitude`) are computed at noon UT of the local date
  (`d = wholeDays`): their value moves at most 0.4 deg or 0.3 min across a
  day, inside the tolerances below, and they change once a day.

### 5.2 The sun (Meeus, *Astronomical Algorithms*, ch. 25 low accuracy, ch. 28, ch. 12)

With `T = d / 36525` (Julian centuries):

- mean longitude `L0 = 280.46646 + 36000.76983 T + 0.0003032 T^2`;
- mean anomaly `M = 357.52911 + 35999.05029 T - 0.0001537 T^2`;
- equation of the centre `C = (1.914602 - 0.004817 T - 0.000014 T^2) sin M
  + (0.019993 - 0.000101 T) sin 2M + 0.000289 sin 3M`;
- true longitude `lambda = L0 + C`; mean obliquity `eps = 23.439291 -
  0.0130042 T` (nutation and aberration left out: 0.005 deg);
- declination `sin delta = sin eps sin lambda`; right ascension
  `alpha = atan2(cos eps sin lambda, cos lambda)`;
- equation of time `E = L0 - 0.0057183 - alpha`, brought into
  (-180, 180] and times 4 for minutes: apparent minus mean, positive when
  a sundial runs fast (Meeus 28.1 without the nutation term, 1 s);
- GMST `theta = 280.46061837 + 360.98564736629 d + 0.000387933 T^2 -
  T^3/38710000` (Meeus 12.4), and local mean sidereal time
  `(theta + longitude) / 15` hours;
- hour angle `H = theta + longitude - alpha`; altitude `sin h = sin phi
  sin delta + cos phi cos delta cos H`; azimuth `A = atan2(sin H cos
  delta, cos H sin phi cos delta - sin delta cos phi) + 180`, clockwise
  from north (Meeus 13.5 and 13.6 with the denominator multiplied through
  by `cos delta`, so no tangent is taken);
- noon altitude `90 - |phi - delta|`.

Refraction is not applied (`ephem`'s figures include it; it lifts a sun at
15 deg by 0.06 deg and one at the horizon by 0.5 deg), nor parallax
(0.002 deg).

### 5.3 The moon

The moon's longitude is the Astronomical Almanac's low-precision series
(six periodic terms, about 0.3 deg): `218.32 + 481267.881 T + 6.29 sin(135.0
+ 477198.87 T) - 1.27 sin(259.3 - 413335.36 T) + 0.66 sin(235.7 +
890534.22 T) + 0.21 sin(269.9 + 954397.70 T) - 0.19 sin(357.5 + 35999.05 T)
- 0.11 sin(186.5 + 966404.03 T)`, each angle reduced to [0, 360) before
its sine so no large argument reaches `Math.sin`. The **age** is the
elongation from the sun, `(lambda_moon - lambda_sun) mod 360`, over the
mean synodic month: `age = elongation / 360 * 29.530588853` days. The
**illuminated fraction** is `(1 - cos elongation) / 2`, the phase angle
taken as 180 deg minus the elongation (the moon's distance ignored).

The alternative, a mean synodic cycle anchored on one known new moon
(2000-01-06 18:14 UT, Meeus ch. 49's example), was prototyped and
rejected: the true phases wander up to about 0.6 d either side of the mean
cycle (the moon's anomaly term alone is 0.41 d), and against the ten
reference phases of 2026 below it was off by 0.36, 0.39, -0.59, -0.71,
-0.73, -0.42, -0.34, 0.09, 0.08 and 0.03 d -- eight of ten outside the
0.3 d tolerance, and the error grows with no bound across the years since
it is a periodic term, not a drift. The elongation form costs six more
sines and is within 0.012 d. The test keeps the anchored form as the
rejected twin, seen to fail.

### 5.4 Achieved accuracy (`ephem`, Royal Observatory Greenwich 51.4769 N, -0.0005 E, UT)

| Instant | declination | altitude | azimuth | equation of time |
|---|---|---|---|---|
| 2026-03-20 12:00 | -0.042 (ref -0.047) | 38.457 (38.452) | 177.612 (177.625) | -7.48 (-7.44) |
| 2026-06-21 12:00 | 23.436 (23.437) | 61.957 (61.958) | 179.096 (179.112) | -1.85 (-1.82) |
| 2026-09-03 09:09 | 7.477 (7.478) | 33.803 (33.805) | 126.125 (126.129) | 0.58 (0.64) |
| 2026-09-23 12:00 | -0.193 (-0.195) | 38.305 (38.303) | 182.427 (182.430) | 7.62 (7.62) |
| 2026-12-21 12:00 | -23.435 (-23.439) | 15.087 (15.083) | 180.453 (180.459) | 1.91 (1.93) |
| 2026-02-11 12:00 | -13.923 (-13.929) | 24.527 (24.521) | 176.207 (176.218) | -14.22 (-14.18) |
| 2026-11-03 12:00 | -15.151 (-15.153) | 23.276 (23.273) | 184.313 (184.320) | 16.42 (16.44) |

Largest errors: declination 0.006 deg (tolerance 0.3), altitude 0.006 deg
and azimuth 0.016 deg (tolerance 1), equation of time 0.06 min (tolerance
0.5). GMST at 2026-09-03 09:09 UT: 7:59:04.86 against 7:59:05. The moon:
the five new moons (2026-02-17 12:01, 03-19 01:23, 08-12 17:37, 09-11
03:27, 10-10 15:50) and five full moons (03-03 11:38, 04-02 02:12, 08-28
04:18, 09-26 16:49, 10-26 04:12) are reproduced within 0.012 d (tolerance
0.3), and the illuminated fraction at 2026-09-03 09:09 UT is 0.608 against
0.609. The test asserts the achieved figures too (0.01 deg, 0.02 deg,
0.07 min, 0.02 d), so a regression inside the plan's tolerances is seen.

### 5.5 Precision on the watch: Double in, Float out

Monkey C's `Float` is IEEE single precision, 24 significant bits. Days
since J2000 are about 9.7e3 in 2026, so a Float holds them to 2^-10 d
(84 s) -- enough for a day count, hopeless as an argument: the sidereal
term `360.98564736629 d` would be good to 0.35 deg, the moon's
`481267.881 T` to a degree. So every function in `WfbAstro.mc` converts
its Number inputs with `.toDouble()`, writes every literal with the `d`
suffix (`360d`, `0.5d`), and keeps the Decimal that `Math.sin`/`cos`/
`asin`/`atan2` answer through `.toDouble()` helpers (`sinD` and friends),
so no intermediate is ever a Float; `Math.PI` is a Float and is not used
(the Double `RAD`/`DEG` constants are). Only the final reading is
`.toFloat()`, the type every catalogue value has. The twin mirrors this
with `Math.fround` on the result, so both sides round the same Double to
the same Float.

What that final rounding costs each source (relative 6e-8):
`days_since_j2000` 84 s, the one source where the Float itself is the
limit; `sun_declination`, `sun_altitude`, `sun_noon_altitude` 2e-6 deg;
`sun_azimuth` 2e-5 deg; `sidereal_time` 1.4e-6 h (5 ms);
`equation_of_time` 1e-6 min; `moon_age` 2e-6 d; `moon_illumination` 6e-8.
All far below the formulas' own errors above. The inputs bound the rest:
the clock reads whole seconds (sidereal time moves 1.0027 s per second,
the azimuth up to 0.25 deg per minute), and the position is the weather
observation's, not the wearer's.

### 5.6 Measured

`examples/features/astro/face.yaml` (every `astro.*` and `position.*`
reading as text, a needle gauge on `astro.sun_altitude`, a static dial and
label) through `./wfb build`, SDK 9.3.0, `-l 3`, warning-free: 7,506 B /
131,072 B on `fenix8solar47mm` and `fr955`, 7,508 B on `fenix8solar51mm`.
The preview at the sample instant (10:09:42 at UTC+2 on 3 September 2026,
Greenwich) draws `DOY 246`, `J2K 9741.84`, `DEC 7.43`, `EOT 0.6m`, `AGE
21.1d`, `LIT 61%`, `LST 6.99h`, `ALT 25.7`, `AZ 111.9`, `NOON 46.0`; with
`--date 2026-03-20 --time 12:00:00 --sample time.utc_offset=0` it draws
`DOY 79`, `J2K 9575.00`, `DEC -0.04`, `EOT -7.5m`, `AGE 1.6d`, `LIT 3%`,
`LST 23.87h`, `ALT 38.5`, `AZ 177.6`, `NOON 38.5`.

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
- That the watch's `Math.sin`/`cos`/`asin`/`atan2` on a `Double` compute
  in double precision and agree with the host's to the last digit: the SDK
  says each returns "Double if input is Long or Double", and the twin
  assumes it. A difference would sit far below the Float every reading is
  rounded to (§5.5), so it could not be seen on the screen in any case.
- That `timeZoneOffset` is signed east-positive so that `local - offset`
  is UT: the SDK says only "the time offset from UTC in seconds". The sun's
  azimuth is the reading that would show a wrong sign at once (it would
  run four hours off at UTC+2).
- That `Gregorian.info(..., FORMAT_SHORT).month` is a `Number` on every
  device: the SDK types it `Number or String` and `date.month_number`
  already relies on the short format answering a Number.

## Sources

* `$CIQ_SDK/doc/Toybox/Weather/CurrentConditions.html`,
  `$CIQ_SDK/doc/Toybox/Weather.html`, `$CIQ_SDK/doc/Toybox/Position.html`,
  `$CIQ_SDK/doc/Toybox/Position/Location.html`,
  `$CIQ_SDK/doc/Toybox/System/ClockTime.html`, `$CIQ_SDK/doc/Toybox/Math.html`
  (SDK 9.3.0)
* `~/.Garmin/ConnectIQ/Devices/<id>/<id>.api.debug.xml` for the 34 installed
  devices (2026-10-29)
* `ts/src/data/catalog.json` (`watchface_permissions`)
* Jean Meeus, *Astronomical Algorithms*, 2nd ed. (1998): ch. 12 (sidereal
  time, 12.4), ch. 13 (13.5, 13.6: altitude and azimuth), ch. 25 (the sun,
  low accuracy), ch. 28 (equation of time, 28.1), ch. 49 (the 2000-01-06
  new moon)
* *The Astronomical Almanac*, section D, low-precision formulae for the
  moon's position
* Reference values from the `ephem` library (PyEphem), Royal Observatory
  Greenwich, 2026, supplied with the requirements
