import Toybox.Complications;
import Toybox.Lang;
import Toybox.Time;
import Toybox.Time.Gregorian;
import Toybox.UserProfile;

//! The parts of a gauge's automatic scale that read the device: a goal, the
//! wearer's heart-rate zones, their VO2 max row, an app complication's own
//! `ranges`.  Each returns `[minimum, maximum]`, or null when the device has
//! nothing to scale by, which hides the gauge.  The figures themselves are
//! generated into `SlotScale` from `wfb.complications.SCALE`.
module WfbScale {

    //! 0 to a goal, or null while the goal is unset.
    function upTo(goal as Number?) as Array<Numeric>? {
        if (goal == null || goal <= 0) {
            return null;
        }
        return [0, goal] as Array<Numeric>;
    }

    //! The wearer's own heart-rate zones: zone 1's minimum to zone 5's
    //! maximum (`getHeartRateZones` returns the minimum, then each zone's top).
    function heartRate() as Array<Numeric>? {
        var zones = UserProfile.getHeartRateZones(UserProfile.HR_ZONE_SPORT_GENERIC);
        if (zones.size() < 6 || zones[0] >= zones[5]) {
            return null;
        }
        return [zones[0], zones[5]] as Array<Numeric>;
    }

    //! The ends of the wearer's VO2 max row.  `ends` holds the female rows
    //! then the male rows, ages 20-29 to 70-79, each a minimum then a
    //! maximum.  Null without a birth year, or a sex the table has, or with
    //! an age outside 20-79; the age is this year less the birth year, so it
    //! can read one year high until the birthday.  Null too while `c` reads
    //! 0, which is how a watch reports no VO2 max recorded.
    function vo2max(ends as Array<Float>, c as Complications.Complication) as Array<Numeric>? {
        var value = c.value;
        if (value instanceof Lang.Number && value == 0) {
            return null;
        }
        var profile = UserProfile.getProfile();
        var gender = profile.gender;
        var born = profile.birthYear;
        if (gender == null || born == null) {
            return null;
        }
        var first;
        if (gender == UserProfile.GENDER_FEMALE) {
            first = 0;
        } else if (gender == UserProfile.GENDER_MALE) {
            first = 6;
        } else {
            return null;
        }
        var age = Gregorian.info(Time.now(), Time.FORMAT_SHORT).year - born;
        if (age < 20 || age > 79) {
            return null;
        }
        var i = (first + (age - 20) / 10) * 2;
        return [ends[i], ends[i + 1]] as Array<Numeric>;
    }

    //! How full a gauge on `scale` is for the pulled `c`, 0.0 to 1.0, or null
    //! while it has no numeric reading.  A count the device scaled to
    //! thousands (the String unit "K") is multiplied back first.
    function fraction(c as Complications.Complication, scale as Array<Numeric>) as Float? {
        var value = c.value;
        if (value == null || value instanceof Lang.String) {
            return null;
        }
        var reading = value.toFloat();
        var unit = c.unit;
        if (!(value instanceof Lang.Number) && unit instanceof Lang.String && unit.equals("K")) {
            reading = reading * 1000;
        }
        var low = scale[0].toFloat();
        var share = (reading - low) / (scale[1].toFloat() - low);
        if (share < 0.0) {
            return 0.0;
        }
        return (share > 1.0) ? 1.0 : share;
    }

    //! An app complication's own `ranges`, first value to last.  Garmin's
    //! native types leave `ranges` null.
    function ranges(c as Complications.Complication) as Array<Numeric>? {
        var r = c.ranges;
        if (r == null || r.size() < 2) {
            return null;
        }
        var last = r[r.size() - 1];
        if (r[0] >= last) {
            return null;
        }
        return [r[0], last] as Array<Numeric>;
    }
}
