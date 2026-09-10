import Toybox.Application;
import Toybox.Lang;
import Toybox.WatchUi;

class SliceApp extends Application.AppBase {
    private var _editMode as Boolean = false;
    function initialize() { AppBase.initialize(); }
    function onStart(state as Dictionary?) as Void {
        if (state != null) {
            var editing = state[:launchedFromWatchFaceSettingsEditor] as Boolean?;
            if (editing != null && editing) { _editMode = true; }
        }
    }
    function getInitialView() as [Views] or [Views, InputDelegates] {
        var view = new ProbeView(_editMode);
        return [ view, new ProbeDelegate(view) ];
    }
}
