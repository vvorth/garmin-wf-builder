import Toybox.Lang;
import Toybox.Activity;
import Toybox.UserProfile;

//! Probe: does -l 3 reject a symbol that is absent from THIS DEVICE's own
//! api.debug.xml but present SDK-wide?  `getFunctionalThresholdPower` is on
//! fenix8solar47mm and not on fr955.
module ProbeGate {
    function ftp() as Number {
        var value = UserProfile.getFunctionalThresholdPower(Activity.SPORT_CYCLING);
        return (value != null) ? value : 0;
    }
}
