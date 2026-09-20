import Toybox.Application;
import Toybox.Lang;
import Toybox.WatchUi;

//! Probe: vector-fonts. Hand-written entry point -- see
//! docs/research/probes/vector-fonts/README.md.
class ProbeApp extends Application.AppBase {
    function initialize() {
        AppBase.initialize();
    }

    function getInitialView() as [Views] or [Views, InputDelegates] {
        return [ new ProbeView() ];
    }
}
