import Toybox.Application;
import Toybox.Lang;
import Toybox.WatchUi;

(:menu)
class ProbeMenuDelegate extends WatchUi.Menu2InputDelegate {
    private var _app as ProbeApp;

    function initialize(app as ProbeApp) {
        Menu2InputDelegate.initialize();
        _app = app;
    }

    function onSelect(item as MenuItem) as Void {
        if (item instanceof ToggleMenuItem) {
            Properties.setValue(item.getId() as String, item.isEnabled());
            _app.onSettingsChanged();
        }
    }
}
