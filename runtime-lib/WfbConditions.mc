import Toybox.Lang;
import Toybox.Weather;

//! The weather condition a slot's temperature icon follows. A temperature
//! complication's value carries no condition, so the icon reads one beside
//! it: the current temperature the current condition, today's high and low
//! today's overall forecast. Kept out of WfbWeather.mc so a face that only
//! maps conditions to icons does not carry these readers.
//!
//! Each read sits inside `Toybox has :Weather`, not after an early return on
//! its negation: SDK 9.3.0's monkeyc only accepts a symbol newer than a
//! device's API level inside an enclosing check (docs/lore/platform-constraints.md, 6d).
module WfbConditions {

    //! The current condition, or null.
    function current() as Number? {
        if (Toybox has :Weather) {
            var now = Weather.getCurrentConditions();
            return (now != null) ? now.condition : null;
        }
        return null;
    }

    //! Today's overall forecast condition, or null.
    function today() as Number? {
        if (Toybox has :Weather) {
            var days = Weather.getDailyForecast();
            return (days != null && days.size() > 0) ? days[0].condition : null;
        }
        return null;
    }

    //! `condition`'s icon name, or `fallback` when there is no condition.
    function iconOr(condition as Number?, fallback as String) as String {
        return (condition != null) ? WfbWeather.chooseIcon(condition) : fallback;
    }
}
