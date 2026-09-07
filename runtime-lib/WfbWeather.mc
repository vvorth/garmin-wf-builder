import Toybox.Lang;

//! Which catalogue *name* a `Toybox.Weather.CONDITION_*` value maps to, for a
//! dynamic (`icon_for:`) weather icon.
//!
//! The on-device twin of `wfb.icons.GARMIN_WEATHER_CONDITION_ICON` -- kept in
//! sync with it deliberately (tests/test_weather_barrel.py checks the two agree,
//! name for name), not by generating this file, because the mapping is fixed
//! and shared across every design that uses `icon_for:`, the same reasoning
//! that keeps WfbArc.mc and WfbTime.mc hand-written.
//!
//! Deliberately returns a *name*, never a glyph: `source/IconGlyphs.mc`
//! (generated per project from `wfb.icon_catalog.CATALOG`) is the one place a
//! catalogue name becomes an actual drawn character, for every icon -- a
//! weather condition or otherwise -- not just this one. See wfb/icons.py's
//! module docstring for the fuller reasoning.
//!
//! Day names only for now -- there is no sunrise/sunset source yet to know
//! whether the `_night` variant applies on-device (see docs/limitations.md).
module WfbWeather {

    //! `condition` null or out of the documented 0-53 range both resolve to
    //! "weather_unknown", matching `wfb.icons.weather_icon_for_condition(None)`.
    function chooseIcon(condition as Number?) as String {
        if (condition == null) {
            return "weather_unknown";
        }
        switch (condition) {
            case 0: return "weather_sunny";  // CONDITION_CLEAR
            case 1: return "weather_cloudy_light";  // CONDITION_PARTLY_CLOUDY
            case 2: return "weather_cloudy_heavy";  // CONDITION_MOSTLY_CLOUDY
            case 3: return "weather_rain";  // CONDITION_RAIN
            case 4: return "weather_snow";  // CONDITION_SNOW
            case 5: return "weather_windy";  // CONDITION_WINDY
            case 6: return "weather_thunderstorm";  // CONDITION_THUNDERSTORMS
            case 7: return "weather_wintry_mix";  // CONDITION_WINTRY_MIX
            case 8: return "weather_fog";  // CONDITION_FOG
            case 9: return "weather_haze";  // CONDITION_HAZY
            case 10: return "weather_hail";  // CONDITION_HAIL
            case 11: return "weather_rain_heavy";  // CONDITION_SCATTERED_SHOWERS
            case 12: return "weather_thunderstorm_showers";  // CONDITION_SCATTERED_THUNDERSTORMS
            case 13: return "weather_rain";  // CONDITION_UNKNOWN_PRECIPITATION -- no dedicated glyph; rain reads closest
            case 14: return "weather_rain_light";  // CONDITION_LIGHT_RAIN
            case 15: return "weather_rain_heavy";  // CONDITION_HEAVY_RAIN
            case 16: return "weather_snow";  // CONDITION_LIGHT_SNOW
            case 17: return "weather_snow_heavy";  // CONDITION_HEAVY_SNOW
            case 18: return "weather_wintry_mix";  // CONDITION_LIGHT_RAIN_SNOW
            case 19: return "weather_wintry_mix";  // CONDITION_HEAVY_RAIN_SNOW
            case 20: return "weather_cloudy";  // CONDITION_CLOUDY
            case 21: return "weather_wintry_mix";  // CONDITION_RAIN_SNOW
            case 22: return "weather_sunny_overcast";  // CONDITION_PARTLY_CLEAR
            case 23: return "weather_sunny_overcast";  // CONDITION_MOSTLY_CLEAR
            case 24: return "weather_rain_light";  // CONDITION_LIGHT_SHOWERS
            case 25: return "weather_rain_heavy";  // CONDITION_SHOWERS
            case 26: return "weather_rain_heavy";  // CONDITION_HEAVY_SHOWERS
            case 27: return "weather_rain_light";  // CONDITION_CHANCE_OF_SHOWERS
            case 28: return "weather_lightning";  // CONDITION_CHANCE_OF_THUNDERSTORMS
            case 29: return "weather_fog";  // CONDITION_MIST
            case 30: return "weather_dust";  // CONDITION_DUST
            case 31: return "weather_rain_light";  // CONDITION_DRIZZLE
            case 32: return "weather_tornado";  // CONDITION_TORNADO
            case 33: return "weather_smoke";  // CONDITION_SMOKE
            case 34: return "weather_ice";  // CONDITION_ICE
            case 35: return "weather_sandstorm";  // CONDITION_SAND
            case 36: return "weather_strong_wind";  // CONDITION_SQUALL
            case 37: return "weather_sandstorm";  // CONDITION_SANDSTORM
            case 38: return "weather_volcano";  // CONDITION_VOLCANIC_ASH
            case 39: return "weather_haze";  // CONDITION_HAZE
            case 40: return "weather_sunny_overcast";  // CONDITION_FAIR
            case 41: return "weather_hurricane";  // CONDITION_HURRICANE
            case 42: return "weather_hurricane_warning";  // CONDITION_TROPICAL_STORM
            case 43: return "weather_snow";  // CONDITION_CHANCE_OF_SNOW
            case 44: return "weather_wintry_mix";  // CONDITION_CHANCE_OF_RAIN_SNOW
            case 45: return "weather_rain";  // CONDITION_CLOUDY_CHANCE_OF_RAIN
            case 46: return "weather_snow";  // CONDITION_CLOUDY_CHANCE_OF_SNOW
            case 47: return "weather_wintry_mix";  // CONDITION_CLOUDY_CHANCE_OF_RAIN_SNOW
            case 48: return "weather_snow";  // CONDITION_FLURRIES
            case 49: return "weather_sleet";  // CONDITION_FREEZING_RAIN
            case 50: return "weather_sleet";  // CONDITION_SLEET
            case 51: return "weather_snow";  // CONDITION_ICE_SNOW
            case 52: return "weather_cloudy_light";  // CONDITION_THIN_CLOUDS -- lighter than CLOUDY(20)
            case 53: return "weather_unknown";  // CONDITION_UNKNOWN
            default: return "weather_unknown";
        }
    }
}
