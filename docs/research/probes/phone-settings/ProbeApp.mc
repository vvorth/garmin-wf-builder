import Toybox.Application;
import Toybox.Lang;
import Toybox.WatchUi;

class ProbeApp extends Application.AppBase {
    private var _view as ProbeView?;

    function initialize() { AppBase.initialize(); }

    function getInitialView() as [Views] or [Views, InputDelegates] {
        var view = new ProbeView();
        _view = view;
        return [ view ];
    }

    // Variants B and C: Garmin Connect pushed a new property value.
    (:settings)
    function onSettingsChanged() as Void {
        var view = _view;
        if (view != null) { view.applySettings(); }
        WatchUi.requestUpdate();
    }

    // Variant C: the watch's own watch-face menu opens this.
    (:menu)
    function getSettingsView() as [Views] or [Views, InputDelegates] or Null {
        var on = Properties.getValue("ShowSeconds") as Boolean?;
        var menu = new WatchUi.Menu2({ :title => "Settings" });
        menu.addItem(new WatchUi.ToggleMenuItem("Seconds", null, "ShowSeconds",
                                                on == null || on, null));
        return [ menu, new ProbeMenuDelegate(self) ];
    }
}
