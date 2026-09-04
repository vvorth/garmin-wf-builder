import Toybox.Lang;

//! Clock arithmetic that follows the user's device settings.
//!
//! `onSettingsChanged` does not fire for on-watch edits, so nothing here caches:
//! every call reads the value it was handed.  The cost is a few comparisons per
//! frame; the alternative is a face that shows 24-hour time until it is
//! restarted.
module WfbTime {

    //! A 0..23 hour as a 1..12 hour.
    function hour12(hour as Number) as Number {
        var h = hour % 12;
        return (h == 0) ? 12 : h;
    }

    //! The hour as the user has asked to see it: zero-padded 24-hour, or
    //! unpadded 12-hour.  This is the `%h` format code.
    function displayHour(hour as Number, is24Hour as Boolean) as String {
        if (is24Hour) {
            return hour.format("%02d");
        }
        return hour12(hour).format("%d");
    }

    //! "AM" or "PM" for a 0..23 hour.
    function meridiem(hour as Number) as String {
        return (hour < 12) ? "AM" : "PM";
    }
}
