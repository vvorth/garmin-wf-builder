import Toybox.Lang;
import Toybox.Complications;

//! A `complication_slot`'s reading as display text: the arithmetic behind the
//! generated `SlotText.reading`, which picks one of these per complication
//! type.  Each function has a Python twin in `wfb/complications.py`
//! (`format_reading` and its helpers), which the host preview draws with.
//!
//! Only the slot calls these, so a face that reads `complication.*` through
//! an ordinary `text` element does not carry them.
module WfbReading {

    //! A pulled value with no per-type rule: a Number, Long or String
    //! through `toString()`, a Float or Double through `decimalText`, because
    //! `Float.toString()` always prints six decimals.
    function formatValue(value as Complications.Value) as String {
        if (value instanceof Lang.Float) {
            return decimalText(value.toDouble());
        }
        if (value instanceof Lang.Double) {
            return decimalText(value);
        }
        return value.toString();
    }

    //! Three significant figures without ever dropping an integer digit,
    //! then trailing zeros removed: 12.879 -> "12.9", 9.876 -> "9.88",
    //! 21.5 -> "21.5", 101325.0 -> "101325", 10.0 -> "10".
    function decimalText(value as Lang.Double) as String {
        var magnitude = (value < 0) ? -value : value;
        var decimals = 2;
        if (magnitude >= 100) {
            decimals = 0;
        } else if (magnitude >= 10) {
            decimals = 1;
        }
        var text = value.format("%." + decimals + "f");
        if (decimals == 0) {
            return text;
        }
        var chars = text.toCharArray();
        var keep = chars.size();
        while (keep > 0 && chars[keep - 1] == '0') {
            keep -= 1;
        }
        if (keep > 0 && chars[keep - 1] == '.') {
            keep -= 1;
        }
        var trimmed = text.substring(0, keep);
        return (trimmed != null) ? trimmed : text;
    }

    //! `Complication.unit` as a suffix, for a type with no rule of its own
    //! (an app's complication): a String is used as written, the SDK's
    //! `Unit` enum through its documented meaning, anything else as "".
    //! `wfb.complications.UNIT_SUFFIX` is the Python twin.
    function unitSuffix(unit as Complications.Unit or Lang.String or Null) as String {
        if (unit == null) {
            return "";
        }
        if (unit instanceof Lang.String) {
            return unit;
        }
        switch (unit) {
            case Complications.UNIT_DISTANCE: return "m";
            case Complications.UNIT_ELEVATION: return "m";
            case Complications.UNIT_HEIGHT: return "m";
            case Complications.UNIT_SPEED: return "m/s";
            case Complications.UNIT_TEMPERATURE: return "°C";
            case Complications.UNIT_WEIGHT: return "g";
            default: return "";
        }
    }

    //! Nearest whole number, halves away from zero.
    function rounded(value as Numeric) as Number {
        var real = value.toDouble();
        if (real < 0) {
            return -((-real + 0.5).toNumber());
        }
        return (real + 0.5).toNumber();
    }

    //! A count.  The device may already have scaled it to thousands (seen in
    //! the simulator: steps past 10,000 arrive as the Float 12.879 with the
    //! unit "K"), so a String unit on a Float is kept; a whole count of
    //! 10,000 or more is scaled here the same way.  Thousands always carry
    //! one decimal, "10.0K" as well as "12.9K", so the reading keeps its
    //! shape as the count grows.
    function count(value as Numeric, unit as Complications.Unit or Lang.String or Null) as String {
        if (value instanceof Lang.Float || value instanceof Lang.Double) {
            if (unit instanceof Lang.String && unit.equals("K")) {
                return value.format("%.1f") + "K";
            }
            return decimalText(value.toDouble()) + ((unit instanceof Lang.String) ? unit : "");
        }
        var whole = value.toNumber();
        if (whole >= 10000 || whole <= -10000) {
            return (whole.toDouble() / 1000.0d).format("%.1f") + "K";
        }
        return whole.toString();
    }

    //! Seconds since local midnight as the clock the wearer reads: "06:15"
    //! or "18:12" on a 24-hour watch, "6:15" and "6:12" on a 12-hour one.
    function clock(seconds as Numeric, is24Hour as Boolean) as String {
        var minutes = (seconds.toNumber() / 60) % 1440;
        if (minutes < 0) {
            minutes += 1440;
        }
        var hour = minutes / 60;
        var shown = is24Hour ? hour.format("%02d") : ((hour % 12 == 0) ? 12 : hour % 12).toString();
        return shown + ":" + (minutes % 60).format("%02d");
    }

    //! Seconds as a duration: "24:40", or "1:43:12" from an hour up.
    function duration(seconds as Numeric) as String {
        var total = seconds.toNumber();
        if (total < 0) {
            total = 0;
        }
        var hours = total / 3600;
        var tail = ((total / 60) % 60).format(hours > 0 ? "%02d" : "%d") + ":" + (total % 60).format("%02d");
        return (hours > 0) ? hours + ":" + tail : tail;
    }

    //! Minutes as whole hours, rounded up so that time still left never reads
    //! as none: 1 minute is "1h", 0 is "0h".
    function hours(minutes as Numeric) as String {
        var total = minutes.toNumber();
        if (total < 0) {
            total = 0;
        }
        return ((total + 59) / 60) + "h";
    }

    //! `number` then `suffix`, unless `short` and the two together would pass
    //! seven characters: then the number alone.
    function suffixed(number as String, suffix as String, short as Boolean) as String {
        if (short && number.length() + suffix.length() > 7) {
            return number;
        }
        return number + suffix;
    }

    //! A percentage: bare, or "%" after it with `unit`.
    function percent(value as Numeric, unit as Boolean) as String {
        return rounded(value).toString() + (unit ? "%" : "");
    }

    //! Degrees Celsius, in Fahrenheit when `statute`, always with "°", and
    //! "°C"/"°F" with `unit`: "24°", "24°C".
    function temperature(celsius as Numeric, statute as Boolean, unit as Boolean) as String {
        var degrees = statute ? celsius.toDouble() * 1.8d + 32.0d : celsius.toDouble();
        return rounded(degrees).toString() + (unit ? (statute ? "°F" : "°C") : "°");
    }

    //! An elevation in metres as whole metres or, when `statute`, feet.
    function elevation(metres as Numeric, statute as Boolean, unit as Boolean,
                       short as Boolean) as String {
        var shown = statute ? metres.toDouble() / 0.3048d : metres.toDouble();
        return suffixed(rounded(shown).toString(), unit ? (statute ? "ft" : "m") : "", short);
    }

    //! A distance in metres as kilometres or, when `statute`, miles, to one
    //! decimal: "12.3".
    function distance(metres as Numeric, statute as Boolean, unit as Boolean,
                      short as Boolean) as String {
        var shown = metres.toDouble() / (statute ? 1609.344d : 1000.0d);
        return suffixed(shown.format("%.1f"), unit ? (statute ? "mi" : "km") : "", short);
    }

    //! Pascals as whole hectopascals: 101675 -> "1017".
    function pressure(pascals as Numeric, unit as Boolean, short as Boolean) as String {
        return suffixed(rounded(pascals.toDouble() / 100.0d).toString(), unit ? "hPa" : "", short);
    }

    //! A speed in metres per second as a pace per kilometre or, when
    //! `statute`, per mile: "4:56", "4:56/km".  Null for a speed of zero,
    //! which has no pace.
    function pace(speed as Numeric, statute as Boolean, unit as Boolean,
                  short as Boolean) as String? {
        var mps = speed.toDouble();
        if (mps <= 0) {
            return null;
        }
        var seconds = rounded((statute ? 1609.344d : 1000.0d) / mps);
        return suffixed(duration(seconds), unit ? (statute ? "/mi" : "/km") : "", short);
    }

    //! "H 26 / L 17" as "26/17": the first two whole numbers in the text,
    //! each with its minus sign.  Text that does not hold exactly two is
    //! returned unchanged.
    function highLowShort(text as String) as String {
        var found = [] as Array<String>;
        var current = "";
        var chars = text.toCharArray();
        for (var i = 0; i <= chars.size(); i++) {
            var code = (i < chars.size()) ? chars[i].toNumber() : 0;
            if (code >= 48 && code <= 57) {
                current += chars[i].toString();
            } else if (code == 45 && current.length() == 0) {
                current = "-";
            } else {
                if (current.length() > 0 && !current.equals("-")) {
                    found.add(current);
                }
                current = "";
            }
        }
        if (found.size() != 2) {
            return text;
        }
        return found[0] + "/" + found[1];
    }

    //! Entry `index` of `names`, a table of entries padded with "|" to
    //! `width` characters each; an index outside it reads as the last entry.
    //! One string in place of a `switch` over every entry, which costs far
    //! more code.
    function packed(names as String, width as Number, index as Number) as String {
        var count = names.length() / width;
        if (index < 0 || index >= count) {
            index = count - 1;
        }
        var entry = names.substring(index * width, index * width + width);
        if (entry == null) {
            return "";
        }
        var end = entry.find("|");
        var name = (end != null) ? entry.substring(0, end) : entry;
        return (name != null) ? name : entry;
    }

    //! `short` in the case `reported` uses: all capitals when the device
    //! reported all capitals ("MAINTAINING" -> "MAINT"), as written otherwise.
    function inCaseOf(short as String, reported as String) as String {
        return reported.equals(reported.toUpper()) ? short.toUpper() : short;
    }
}
