import Toybox.Complications;
import Toybox.Lang;

//! The parts of a gauge's automatic scale that read the device: a goal, an
//! app complication's own `ranges`, and the fill.  Each scale returns
//! `[minimum, maximum]`, or null when the device has nothing to scale by,
//! which hides the gauge.  The figures themselves are generated into
//! `SlotScale` from the complication table's scales.  What reads the wearer's
//! profile is `WfbProfileScale`, a module of its own so a face that never
//! scales by it needs no `UserProfile` permission.
module WfbScale {

    //! 0 to a goal, or null while the goal is unset.
    function upTo(goal as Number?) as Array<Numeric>? {
        if (goal == null || goal <= 0) {
            return null;
        }
        return [0, goal] as Array<Numeric>;
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
        return share(reading, scale);
    }

    //! How full a gauge on `scale` is for a reading already in the scale's
    //! units, 0.0 to 1.0.
    function share(reading as Numeric, scale as Array<Numeric>) as Float {
        var low = scale[0].toFloat();
        var full = (reading.toFloat() - low) / (scale[1].toFloat() - low);
        if (full < 0.0) {
            return 0.0;
        }
        return (full > 1.0) ? 1.0 : full;
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
