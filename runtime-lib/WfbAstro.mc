import Toybox.Lang;
import Toybox.Position;
import Toybox.Weather;

//! The wearer's position, read off the weather report: `CurrentConditions`
//! carries where its conditions were observed (`observationLocationPosition`,
//! API 3.2.0), which is null until the face holds the Positioning permission
//! and the watch has a report. Astronomy derived from it lands here too.
//!
//! Every read sits inside its own `has` checks for the Weather module and
//! the field: SDK 9.3.0's monkeyc accepts a symbol newer than a device's API
//! level only inside an enclosing check, and a check in the caller does not
//! count (docs/lore/platform-constraints.md, 6d). Toybox.Position itself is
//! on every device this project has a file for, so it is not checked.
module WfbAstro {

    //! Latitude of the observation in degrees, north positive; null when the
    //! report carries no location. `toDegrees` answers Doubles; the catalogue
    //! value is a Float like every other reading.
    function latitude(conditions as Weather.CurrentConditions) as Float? {
        if ((Toybox has :Weather) && (conditions has :observationLocationPosition)) {
            var location = conditions.observationLocationPosition;
            return (location != null) ? location.toDegrees()[0].toFloat() : null;
        }
        return null;
    }

    //! Longitude of the observation in degrees, east positive; null when the
    //! report carries no location.
    function longitude(conditions as Weather.CurrentConditions) as Float? {
        if ((Toybox has :Weather) && (conditions has :observationLocationPosition)) {
            var location = conditions.observationLocationPosition;
            return (location != null) ? location.toDegrees()[1].toFloat() : null;
        }
        return null;
    }
}
