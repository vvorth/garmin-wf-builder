import Toybox.Lang;
import Toybox.Weather;

//! The weather condition a slot's temperature icon follows. A temperature
//! complication's value carries no condition, so the icon reads one beside
//! it: the current temperature the current condition, today's high and low
//! today's overall forecast. Kept out of WfbWeather.mc so a face that only
//! maps conditions to icons does not carry these readers.
module WfbConditions {

    //! The current condition, or null.
    function current() as Number? {
        if (!(Toybox has :Weather)) {
            return null;
        }
        var now = Weather.getCurrentConditions();
        return (now != null) ? now.condition : null;
    }

    //! Today's overall forecast condition, or null.
    function today() as Number? {
        if (!(Toybox has :Weather)) {
            return null;
        }
        var days = Weather.getDailyForecast();
        return (days != null && days.size() > 0) ? days[0].condition : null;
    }

    //! `condition`'s icon name, or `fallback` when there is no condition.
    function iconOr(condition as Number?, fallback as String) as String {
        return (condition != null) ? WfbWeather.chooseIcon(condition) : fallback;
    }
}
