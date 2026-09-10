import Toybox.Application.WatchFaceConfig;
import Toybox.Complications;
import Toybox.Lang;
import Toybox.WatchUi;

class ProbeDelegate extends WatchUi.WatchFaceDelegate {
    private var _view as ProbeView;
    function initialize(view as ProbeView) {
        WatchFaceDelegate.initialize();
        _view = view;
    }

    function onWatchFaceConfigEdited(options as {
            :configId as $.Toybox.Application.WatchFaceConfig.Id,
            :type as WatchFaceConfigType?,
            :committed as $.Toybox.Lang.Boolean}) as Void {
        var id = options[:configId] as WatchFaceConfig.Id?;
        if (id != null) {
            var settings = WatchFaceConfig.getSettings(id);
            if (settings != null) { _view.apply(settings); }
        }
    }

    function onTap(clickEvent as ClickEvent) as Boolean {
        var coords = clickEvent.getCoordinates();
        if (coords[0] < 130) {
            setSelectedComplication(1);
            return true;
        }
        return false;
    }

    function onPress(clickEvent as ClickEvent) as Boolean {
        return false;
    }
}
