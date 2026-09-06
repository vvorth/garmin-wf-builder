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
//! which half of `wfb.icons._WEATHER_GLYPH_NIGHT` applies on-device (see
//! docs/limitations.md).
module WfbWeather {

    //! `condition` null or out of the documented 0-53 range both resolve to
    //! the "unknown" glyph, matching `weather_icon_for_condition(None)`.
    function iconGlyph(condition as Number?) as String {
        if (condition == null) {
            return "";
        }
        switch (condition) {
            case 0: return "";  // sunny
            case 1: return "";  // cloudy_light
            case 2: return "";  // cloudy_heavy
            case 3: return "";  // rain
            case 4: return "";  // snow
            case 5: return "";  // windy
            case 6: return "";  // thunderstorm
            case 7: return "";  // wintry_mix
            case 8: return "";  // fog
            case 9: return "";  // haze
            case 10: return "";  // hail
            case 11: return "";  // rain_heavy
            case 12: return "";  // thunderstorm_showers
            case 13: return "";  // rain
            case 14: return "";  // rain_light
            case 15: return "";  // rain_heavy
            case 16: return "";  // snow
            case 17: return "";  // snow_heavy
            case 18: return "";  // wintry_mix
            case 19: return "";  // wintry_mix
            case 20: return "";  // cloudy
            case 21: return "";  // wintry_mix
            case 22: return "";  // sunny_overcast
            case 23: return "";  // sunny_overcast
            case 24: return "";  // rain_light
            case 25: return "";  // rain_heavy
            case 26: return "";  // rain_heavy
            case 27: return "";  // rain_light
            case 28: return "";  // lightning
            case 29: return "";  // fog
            case 30: return "";  // dust
            case 31: return "";  // rain_light
            case 32: return "";  // tornado
            case 33: return "";  // smoke
            case 34: return "";  // ice
            case 35: return "";  // sandstorm
            case 36: return "";  // strong_wind
            case 37: return "";  // sandstorm
            case 38: return "";  // volcano
            case 39: return "";  // haze
            case 40: return "";  // sunny_overcast
            case 41: return "";  // hurricane
            case 42: return "";  // hurricane_warning
            case 43: return "";  // snow
            case 44: return "";  // wintry_mix
            case 45: return "";  // rain
            case 46: return "";  // snow
            case 47: return "";  // wintry_mix
            case 48: return "";  // snow
            case 49: return "";  // sleet
            case 50: return "";  // sleet
            case 51: return "";  // snow
            case 52: return "";  // cloudy_light
            case 53: return "";  // unknown
            default: return "";
        }
    }
}
