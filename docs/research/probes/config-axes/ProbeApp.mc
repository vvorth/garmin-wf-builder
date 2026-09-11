import Toybox.Application;
import Toybox.Lang;
import Toybox.WatchUi;

class ProbeApp extends Application.AppBase {
    private var _editMode as Boolean = false;

    function initialize() { AppBase.initialize(); }

    function onStart(state as Dictionary?) as Void {
        if (state != null) {
            var editing = state[:launchedFromWatchFaceSettingsEditor] as Boolean?;
            if (editing != null && editing) { _editMode = true; }
        }
    }

    function getInitialView() as [WatchUi.Views] or [WatchUi.Views, WatchUi.InputDelegates] {
        var view = new ProbeView(_editMode);
        return [ view, new ProbeDelegate(view) ];
    }
}
