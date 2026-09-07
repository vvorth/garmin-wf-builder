import Toybox.Lang;

//! The glyph for a `Toybox.Weather.CONDITION_*` value, for a dynamic
//! (`icon_for:`) weather icon.
//!
//! The on-device twin of `wfb.icons.weather_icon_for_condition()` -- kept in
//! sync with it deliberately (tests/test_weather_barrel.py checks the two
//! tables agree, glyph for glyph), not by generating this file, because the
//! mapping is fixed and shared across every design that uses `icon_for:`,
//! the same reasoning that keeps WfbArc.mc and WfbTime.mc hand-written.
//!
//! Day glyphs only for now -- there is no sunrise/sunset source yet to know
//! which half of wfb.icons' `weather_*_night` entries applies on-device (see
//! docs/limitations.md).
module WfbWeather {

    //! `condition` null or out of the documented 0-53 range both resolve to
    //! the "unknown" glyph, matching `weather_icon_for_condition(None)`.
    function iconGlyph(condition as Number?) as String {
        if (condition == null) {
            return "";
        }
        switch (condition) {
            case 0: return "";  // weather_sunny
            case 1: return "";  // weather_cloudy_light
            case 2: return "";  // weather_cloudy_heavy
            case 3: return "";  // weather_rain
            case 4: return "";  // weather_snow
            case 5: return "";  // weather_windy
            case 6: return "";  // weather_thunderstorm
            case 7: return "";  // weather_wintry_mix
            case 8: return "";  // weather_fog
            case 9: return "";  // weather_haze
            case 10: return "";  // weather_hail
            case 11: return "";  // weather_rain_heavy
            case 12: return "";  // weather_thunderstorm_showers
            case 13: return "";  // weather_rain
            case 14: return "";  // weather_rain_light
            case 15: return "";  // weather_rain_heavy
            case 16: return "";  // weather_snow
            case 17: return "";  // weather_snow_heavy
            case 18: return "";  // weather_wintry_mix
            case 19: return "";  // weather_wintry_mix
            case 20: return "";  // weather_cloudy
            case 21: return "";  // weather_wintry_mix
            case 22: return "";  // weather_sunny_overcast
            case 23: return "";  // weather_sunny_overcast
            case 24: return "";  // weather_rain_light
            case 25: return "";  // weather_rain_heavy
            case 26: return "";  // weather_rain_heavy
            case 27: return "";  // weather_rain_light
            case 28: return "";  // weather_lightning
            case 29: return "";  // weather_fog
            case 30: return "";  // weather_dust
            case 31: return "";  // weather_rain_light
            case 32: return "";  // weather_tornado
            case 33: return "";  // weather_smoke
            case 34: return "";  // weather_ice
            case 35: return "";  // weather_sandstorm
            case 36: return "";  // weather_strong_wind
            case 37: return "";  // weather_sandstorm
            case 38: return "";  // weather_volcano
            case 39: return "";  // weather_haze
            case 40: return "";  // weather_sunny_overcast
            case 41: return "";  // weather_hurricane
            case 42: return "";  // weather_hurricane_warning
            case 43: return "";  // weather_snow
            case 44: return "";  // weather_wintry_mix
            case 45: return "";  // weather_rain
            case 46: return "";  // weather_snow
            case 47: return "";  // weather_wintry_mix
            case 48: return "";  // weather_snow
            case 49: return "";  // weather_sleet
            case 50: return "";  // weather_sleet
            case 51: return "";  // weather_snow
            case 52: return "";  // weather_cloudy_light
            case 53: return "";  // weather_unknown
            default: return "";
        }
    }
}
