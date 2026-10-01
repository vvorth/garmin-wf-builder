import Toybox.Complications;
import Toybox.Lang;
import Toybox.Time;
import Toybox.Time.Gregorian;
import Toybox.UserProfile;

//! The parts of a gauge's automatic scale that read the wearer's profile:
//! their heart-rate zones and their VO2 max row.  Kept apart from `WfbScale`
//! because `monkeyc` refuses any reference to `Toybox.UserProfile` without
//! the `UserProfile` permission, and the barrel ships only the modules the
//! generated code names: a face whose gauges cannot show heart rate or VO2
//! max ships none of this, and declares no permission for it.
module WfbProfileScale {

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
}
