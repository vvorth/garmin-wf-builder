import Toybox.Lang;
import Toybox.Math;
import Toybox.Position;
import Toybox.System;
import Toybox.Time.Gregorian;
import Toybox.Weather;

//! The wearer's position, read off the weather report, and the astronomy
//! the catalogue's `astro.*` sources compute from the date, the clock and
//! that position. `CurrentConditions` carries where its conditions were
//! observed (`observationLocationPosition`, API 3.2.0), which is null until
//! the face holds the Positioning permission and the watch has a report.
//!
//! Every read of the field sits inside its own `has` checks for the Weather
//! module and the field: SDK 9.3.0's monkeyc accepts a symbol newer than a
//! device's API level only inside an enclosing check, and a check in the
//! caller does not count (docs/lore/platform-constraints.md, 6d).
//! Toybox.Position itself is on every device this project has a file for,
//! so it is not checked.
//!
//! The astronomy is Meeus's low-accuracy sun (mean longitude, mean anomaly,
//! equation of centre, mean obliquity), Greenwich mean sidereal time from
//! the same days-since-J2000 count, and the Astronomical Almanac's
//! low-precision moon longitude; the moon's age is its elongation from the
//! sun over the mean synodic month. ts/src/astro.ts is the host twin, the
//! same formulas in the same order, so the preview draws what the watch
//! draws. All of it runs in Double: a Float's 24-bit mantissa cannot hold
//! days since J2000 (about 1e4) together with a fraction of a day, and the
//! sidereal-time term 360.98564736629 * d needs more still. Only the final
//! reading is a Float, like every other catalogue value.
module WfbAstro {

    //! Latitude of the observation in degrees, north positive; null when the
    //! report carries no location. `toDegrees` answers Doubles; the catalogue
    //! value is a Float like every other reading.
    function latitude(conditions as Weather.CurrentConditions) as Float? {
        if ((Toybox has :Weather) && (conditions has :observationLocationPosition)) {
            var location = conditions.observationLocationPosition;
            return (location != null) ? location.toDegrees()[0].toFloat() : null;
        }
        return null;
    }

    //! Longitude of the observation in degrees, east positive; null when the
    //! report carries no location.
    function longitude(conditions as Weather.CurrentConditions) as Float? {
        if ((Toybox has :Weather) && (conditions has :observationLocationPosition)) {
            var location = conditions.observationLocationPosition;
            return (location != null) ? location.toDegrees()[1].toFloat() : null;
        }
        return null;
    }

    // -- the catalogue's astro.* sources. A position-dependent one takes the
    // weather report first: the catalogue's device-field check is keyed on
    // the primary reader, so the reader owning the gated field goes first. --

    //! Day of the year, 1 = 1 January .. 365 or 366.
    function dayOfYear(date as Gregorian.Info) as Number {
        return wholeDays(date.year, date.month as Number, date.day) - wholeDays(date.year, 1, 0);
    }

    //! Days since J2000.0 (2000-01-01 12:00 UT) at this instant, UT from the
    //! clock's offset. As a Float it resolves about a minute.
    function daysSinceJ2000(date as Gregorian.Info, clock as System.ClockTime) as Float {
        return instant(date, clock).toFloat();
    }

    //! Days since the last new moon, 0 to 29.53.
    function moonAge(date as Gregorian.Info, clock as System.ClockTime) as Float {
        return (elongation(instant(date, clock)) / 360d * 29.530588853d).toFloat();
    }

    //! The illuminated fraction of the moon's disc, 0 to 1.
    function moonIllumination(date as Gregorian.Info, clock as System.ClockTime) as Float {
        return ((1d - cosD(elongation(instant(date, clock)) * RAD)) / 2d).toFloat();
    }

    //! Apparent minus mean solar time in minutes at noon UT of the date:
    //! positive when a sundial runs fast.
    function equationOfTime(date as Gregorian.Info) as Float {
        var d = noon(date);
        var e = meanLongitude(d) - 0.0057183d - rightAscension(d);
        if (e > 180d) {
            e -= 360d;
        }
        if (e < -180d) {
            e += 360d;
        }
        return (e * 4d).toFloat();
    }

    //! The sun's declination in degrees at noon UT of the date.
    function sunDeclination(date as Gregorian.Info) as Float {
        return declinationAt(noon(date)).toFloat();
    }

    //! Local mean sidereal time in hours, 0 to 24: GMST plus the longitude.
    //! Null without a position.
    function siderealTime(conditions as Weather.CurrentConditions, date as Gregorian.Info, clock as System.ClockTime) as Float? {
        var lon = longitude(conditions);
        if (lon == null) {
            return null;
        }
        return (wrap360(gmstAt(instant(date, clock)) + lon.toDouble()) / 15d).toFloat();
    }

    //! The sun's altitude above the horizon now, degrees, without refraction.
    //! Null without a position.
    function sunAltitude(conditions as Weather.CurrentConditions, date as Gregorian.Info, clock as System.ClockTime) as Float? {
        var lat = latitude(conditions);
        var lon = longitude(conditions);
        if (lat == null || lon == null) {
            return null;
        }
        var d = instant(date, clock);
        var phi = lat.toDouble() * RAD;
        var decl = declinationAt(d) * RAD;
        var h = hourAngle(d, lon.toDouble());
        return (asinD(sinD(phi) * sinD(decl) + cosD(phi) * cosD(decl) * cosD(h)) * DEG).toFloat();
    }

    //! The sun's azimuth now, degrees clockwise from north, 0 to 360. Null
    //! without a position.
    function sunAzimuth(conditions as Weather.CurrentConditions, date as Gregorian.Info, clock as System.ClockTime) as Float? {
        var lat = latitude(conditions);
        var lon = longitude(conditions);
        if (lat == null || lon == null) {
            return null;
        }
        var d = instant(date, clock);
        var phi = lat.toDouble() * RAD;
        var decl = declinationAt(d) * RAD;
        var h = hourAngle(d, lon.toDouble());
        return wrap360(atan2D(sinD(h) * cosD(decl), cosD(h) * sinD(phi) * cosD(decl) - sinD(decl) * cosD(phi)) * DEG + 180d).toFloat();
    }

    //! The sun's altitude at today's culmination, degrees: 90 minus the
    //! distance from the latitude to the declination. Null without a position.
    function sunNoonAltitude(conditions as Weather.CurrentConditions, date as Gregorian.Info) as Float? {
        var lat = latitude(conditions);
        if (lat == null) {
            return null;
        }
        var gap = lat.toDouble() - declinationAt(noon(date));
        if (gap < 0) {
            gap = -gap;
        }
        return (90d - gap).toFloat();
    }

    // -- the arithmetic, in Double; ts/src/astro.ts spells each step the same way --

    //! Degrees to radians and back, as Doubles (Math.PI is a Float).
    const RAD = 0.017453292519943295d;
    const DEG = 57.29577951308232d;

    //! Whole days from 2000-01-01 00:00 to the Gregorian date's midnight
    //! (exact 1901-2099; Number division truncates, every term positive).
    function wholeDays(year as Number, month as Number, day as Number) as Number {
        return 367 * year - 7 * (year + (month + 9) / 12) / 4 + 275 * month / 9 + day - 730531;
    }

    //! Seconds of the UT day the local clock stands for; may be negative or past 86400.
    function utSeconds(clock as System.ClockTime) as Number {
        return clock.hour * 3600 + clock.min * 60 + clock.sec - clock.timeZoneOffset;
    }

    //! Days since J2000.0 at this instant.
    function instant(date as Gregorian.Info, clock as System.ClockTime) as Double {
        return wholeDays(date.year, date.month as Number, date.day).toDouble() + utSeconds(clock).toDouble() / 86400d - 0.5d;
    }

    //! Days since J2000.0 at noon UT of the local date: where a date-only source is computed.
    function noon(date as Gregorian.Info) as Double {
        return wholeDays(date.year, date.month as Number, date.day).toDouble();
    }

    //! `x` reduced to [0, 360): a truncated quotient, then one correction for a negative remainder.
    function wrap360(x as Double) as Double {
        var w = x - 360d * (x / 360d).toNumber();
        if (w < 0) {
            w += 360d;
        }
        return w;
    }

    //! Math.sin and friends answer `Float or Double`; these keep the Double.
    function sinD(x as Double) as Double {
        return Math.sin(x).toDouble();
    }

    function cosD(x as Double) as Double {
        return Math.cos(x).toDouble();
    }

    function asinD(x as Double) as Double {
        return Math.asin(x).toDouble();
    }

    function atan2D(y as Double, x as Double) as Double {
        return Math.atan2(y, x).toDouble();
    }

    function century(d as Double) as Double {
        return d / 36525d;
    }

    //! The sun's geometric mean longitude, degrees.
    function meanLongitude(d as Double) as Double {
        var t = century(d);
        return wrap360(280.46646d + 36000.76983d * t + 0.0003032d * t * t);
    }

    //! The sun's mean anomaly, degrees.
    function meanAnomaly(d as Double) as Double {
        var t = century(d);
        return wrap360(357.52911d + 35999.05029d * t - 0.0001537d * t * t);
    }

    //! The equation of the centre, degrees.
    function equationOfCentre(d as Double) as Double {
        var t = century(d);
        var m = meanAnomaly(d) * RAD;
        return (1.914602d - 0.004817d * t - 0.000014d * t * t) * sinD(m) + (0.019993d - 0.000101d * t) * sinD(2d * m) + 0.000289d * sinD(3d * m);
    }

    //! The sun's true ecliptic longitude, degrees.
    function trueLongitude(d as Double) as Double {
        return wrap360(meanLongitude(d) + equationOfCentre(d));
    }

    //! The mean obliquity of the ecliptic, radians.
    function obliquity(d as Double) as Double {
        return (23.439291d - 0.0130042d * century(d)) * RAD;
    }

    //! The sun's right ascension, degrees 0 to 360.
    function rightAscension(d as Double) as Double {
        var lambda = trueLongitude(d) * RAD;
        var eps = obliquity(d);
        return wrap360(atan2D(cosD(eps) * sinD(lambda), cosD(lambda)) * DEG);
    }

    //! The sun's declination, degrees.
    function declinationAt(d as Double) as Double {
        var lambda = trueLongitude(d) * RAD;
        var eps = obliquity(d);
        return asinD(sinD(eps) * sinD(lambda)) * DEG;
    }

    //! Greenwich mean sidereal time, degrees 0 to 360.
    function gmstAt(d as Double) as Double {
        var t = century(d);
        return wrap360(280.46061837d + 360.98564736629d * d + 0.000387933d * t * t - t * t * t / 38710000d);
    }

    //! The sun's local hour angle at `longitude` degrees east, radians.
    function hourAngle(d as Double, longitude as Double) as Double {
        return wrap360(gmstAt(d) + longitude - rightAscension(d)) * RAD;
    }

    //! The moon's ecliptic longitude, degrees (about 0.3 degrees). Each
    //! term's angle is reduced before the sine, so no large argument reaches it.
    function moonLongitude(d as Double) as Double {
        var t = century(d);
        return wrap360(218.32d + 481267.881d * t + 6.29d * sinD(wrap360(135.0d + 477198.87d * t) * RAD) - 1.27d * sinD(wrap360(259.3d - 413335.36d * t) * RAD)
            + 0.66d * sinD(wrap360(235.7d + 890534.22d * t) * RAD) + 0.21d * sinD(wrap360(269.9d + 954397.70d * t) * RAD) - 0.19d * sinD(wrap360(357.5d + 35999.05d * t) * RAD)
            - 0.11d * sinD(wrap360(186.5d + 966404.03d * t) * RAD));
    }

    //! The moon's elongation from the sun, degrees 0 to 360 (0 new, 180 full).
    function elongation(d as Double) as Double {
        return wrap360(moonLongitude(d) - trueLongitude(d));
    }
}
