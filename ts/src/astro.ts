// The host twin of runtime-lib/WfbAstro.mc's astronomy: the same formulas,
// in the same order of operations, so `wfb preview` draws the figures the
// watch computes. The watch does this arithmetic in Double (its Float has a
// 24-bit mantissa, too short for days since J2000 with a fraction of a day)
// and hands back a Float, which `Math.fround` reproduces here.
//
// Sun: Meeus, Astronomical Algorithms, ch. 25 (low accuracy: mean longitude,
// mean anomaly, equation of centre, mean obliquity) and ch. 28 (equation of
// time as mean longitude minus right ascension); sidereal time ch. 12.
// Moon: the Astronomical Almanac's low-precision longitude (six periodic
// terms, about 0.3 degrees), and the age as the elongation from the sun
// over the mean synodic month -- the mean cycle alone, anchored on one new
// moon, drifts up to 0.7 days from the true phase within a year.
import { WholeFloat } from "./edit/yaml.ts";
import type { ExprValue } from "./expr.ts";

/** Degrees to radians and back: the literals WfbAstro.mc spells, so both sides multiply by the same Double. */
export const RAD = 0.017453292519943295;
export const DEG = 57.29577951308232;
/** The mean synodic month in days. */
export const SYNODIC_MONTH = 29.530588853;

const idiv = (a: number, b: number): number => Math.trunc(a / b);

/** `x` reduced to [0, 360) as the watch does it: a truncated quotient, then one correction for a negative remainder. */
export function wrap360(x: number): number {
  let w = x - 360 * Math.trunc(x / 360);
  if (w < 0) w += 360;
  return w;
}

/** Whole days from 2000-01-01 00:00 to the Gregorian date's midnight (exact 1901-2099). */
export function wholeDays(year: number, month: number, day: number): number {
  return 367 * year - idiv(7 * (year + idiv(month + 9, 12)), 4) + idiv(275 * month, 9) + day - 730531;
}

/** Day of the year, 1 = 1 January. */
export function dayOfYear(year: number, month: number, day: number): number {
  return wholeDays(year, month, day) - wholeDays(year, 1, 0);
}

/** Seconds of the UT day the local clock reading stands for; may be negative or past 86400. */
export function utSeconds(hour: number, minute: number, second: number, utcOffset: number): number {
  return hour * 3600 + minute * 60 + second - utcOffset;
}

/** Days since J2000.0 (2000-01-01 12:00 UT) at the local date and `utSeconds`. */
export function daysSinceJ2000(year: number, month: number, day: number, ut: number): number {
  return wholeDays(year, month, day) + ut / 86400 - 0.5;
}

/** The instant a date-only source is computed at: noon UT of the local date. */
export const noon = (year: number, month: number, day: number): number => wholeDays(year, month, day);

const century = (d: number): number => d / 36525;

/** The sun's geometric mean longitude, degrees. */
export function meanLongitude(d: number): number {
  const t = century(d);
  return wrap360(280.46646 + 36000.76983 * t + 0.0003032 * t * t);
}

/** The sun's mean anomaly, degrees. */
export function meanAnomaly(d: number): number {
  const t = century(d);
  return wrap360(357.52911 + 35999.05029 * t - 0.0001537 * t * t);
}

/** The equation of the centre, degrees. */
export function equationOfCentre(d: number): number {
  const t = century(d);
  const m = meanAnomaly(d) * RAD;
  return (1.914602 - 0.004817 * t - 0.000014 * t * t) * Math.sin(m) + (0.019993 - 0.000101 * t) * Math.sin(2 * m) + 0.000289 * Math.sin(3 * m);
}

/** The sun's true ecliptic longitude, degrees. */
export const trueLongitude = (d: number): number => wrap360(meanLongitude(d) + equationOfCentre(d));

/** The mean obliquity of the ecliptic, radians. */
export const obliquity = (d: number): number => (23.439291 - 0.0130042 * century(d)) * RAD;

/** The sun's right ascension, degrees 0-360. */
export function rightAscension(d: number): number {
  const lambda = trueLongitude(d) * RAD, eps = obliquity(d);
  return wrap360(Math.atan2(Math.cos(eps) * Math.sin(lambda), Math.cos(lambda)) * DEG);
}

/** The sun's declination, degrees. */
export function sunDeclination(d: number): number {
  const lambda = trueLongitude(d) * RAD, eps = obliquity(d);
  return Math.asin(Math.sin(eps) * Math.sin(lambda)) * DEG;
}

/** Apparent minus mean solar time, minutes: positive when a sundial runs fast. */
export function equationOfTime(d: number): number {
  let e = meanLongitude(d) - 0.0057183 - rightAscension(d);
  if (e > 180) e -= 360;
  if (e < -180) e += 360;
  return e * 4;
}

/** Greenwich mean sidereal time, degrees 0-360. */
export function gmst(d: number): number {
  const t = century(d);
  return wrap360(280.46061837 + 360.98564736629 * d + 0.000387933 * t * t - t * t * t / 38710000);
}

/** Local mean sidereal time in hours, 0-24, at `longitude` degrees east. */
export const siderealTime = (d: number, longitude: number): number => wrap360(gmst(d) + longitude) / 15;

/** The moon's ecliptic longitude, degrees (about 0.3 degrees). */
export function moonLongitude(d: number): number {
  const t = century(d);
  const term = (deg: number): number => Math.sin(wrap360(deg) * RAD);
  return wrap360(218.32 + 481267.881 * t + 6.29 * term(135.0 + 477198.87 * t) - 1.27 * term(259.3 - 413335.36 * t)
    + 0.66 * term(235.7 + 890534.22 * t) + 0.21 * term(269.9 + 954397.70 * t) - 0.19 * term(357.5 + 35999.05 * t)
    - 0.11 * term(186.5 + 966404.03 * t));
}

/** The moon's elongation from the sun, degrees 0-360 (0 new, 180 full). */
export const elongation = (d: number): number => wrap360(moonLongitude(d) - trueLongitude(d));

/** Days since the last new moon, 0 to 29.53. */
export const moonAge = (d: number): number => elongation(d) / 360 * SYNODIC_MONTH;

/** The illuminated fraction of the disc, 0-1. */
export const moonIllumination = (d: number): number => (1 - Math.cos(elongation(d) * RAD)) / 2;

/** The sun's local hour angle, radians. */
const hourAngle = (d: number, longitude: number): number => wrap360(gmst(d) + longitude - rightAscension(d)) * RAD;

/** The sun's altitude above the horizon, degrees, without refraction. */
export function sunAltitude(d: number, latitude: number, longitude: number): number {
  const phi = latitude * RAD, decl = sunDeclination(d) * RAD, h = hourAngle(d, longitude);
  return Math.asin(Math.sin(phi) * Math.sin(decl) + Math.cos(phi) * Math.cos(decl) * Math.cos(h)) * DEG;
}

/** The sun's azimuth, degrees clockwise from north, 0-360. */
export function sunAzimuth(d: number, latitude: number, longitude: number): number {
  const phi = latitude * RAD, decl = sunDeclination(d) * RAD, h = hourAngle(d, longitude);
  return wrap360(Math.atan2(Math.sin(h) * Math.cos(decl), Math.cos(h) * Math.sin(phi) * Math.cos(decl) - Math.sin(decl) * Math.cos(phi)) * DEG + 180);
}

/** The sun's altitude at culmination, degrees: 90 minus the distance from the latitude to the declination. */
export function sunNoonAltitude(d: number, latitude: number): number {
  let gap = latitude - sunDeclination(d);
  if (gap < 0) gap = -gap;
  return 90 - gap;
}

const num = (v: ExprValue | undefined): number | null => {
  if (v instanceof WholeFloat) return v.value;
  if (typeof v === "number") return v;
  if (typeof v === "bigint") return Number(v);
  return null;
};

/** A Float as the watch hands it back, in the preview's own shape (a whole value is a `WholeFloat`, never a Number). */
const asFloat = (x: number): ExprValue => {
  const f = Math.fround(x);
  return Number.isInteger(f) ? new WholeFloat(f) : f;
};

/**
 * Every `astro.*` reading derived from a frame's `date.*`, `time.*`,
 * `time.utc_offset` and `position.*` values, as the watch derives them from
 * its own readers; the position-dependent four are null without a position.
 */
export function astroValues(values: ReadonlyMap<string, ExprValue>): Map<string, ExprValue> {
  const year = num(values.get("date.year")) ?? 2000, month = num(values.get("date.month_number")) ?? 1, day = num(values.get("date.day")) ?? 1;
  const ut = utSeconds(num(values.get("time.hour")) ?? 0, num(values.get("time.minute")) ?? 0, num(values.get("time.second")) ?? 0,
    num(values.get("time.utc_offset")) ?? 0);
  const now = daysSinceJ2000(year, month, day, ut), today = noon(year, month, day);
  // The watch narrows the position to a Float first (`WfbAstro.latitude` answers `toDegrees()[0].toFloat()`), so the twin does too.
  const narrowed = (path: string): number | null => { const x = num(values.get(path)); return x === null ? null : Math.fround(x); };
  const latitude = narrowed("position.latitude"), longitude = narrowed("position.longitude");
  const placed = (f: (lat: number, lon: number) => number): ExprValue => latitude === null || longitude === null ? null : asFloat(f(latitude, longitude));
  return new Map<string, ExprValue>([
    ["astro.day_of_year", dayOfYear(year, month, day)],
    ["astro.days_since_j2000", asFloat(now)],
    ["astro.moon_age", asFloat(moonAge(now))],
    ["astro.moon_illumination", asFloat(moonIllumination(now))],
    ["astro.equation_of_time", asFloat(equationOfTime(today))],
    ["astro.sun_declination", asFloat(sunDeclination(today))],
    ["astro.sidereal_time", placed((_, lon) => siderealTime(now, lon))],
    ["astro.sun_altitude", placed((lat, lon) => sunAltitude(now, lat, lon))],
    ["astro.sun_azimuth", placed((lat, lon) => sunAzimuth(now, lat, lon))],
    ["astro.sun_noon_altitude", latitude === null ? null : asFloat(sunNoonAltitude(today, latitude))],
  ]);
}
