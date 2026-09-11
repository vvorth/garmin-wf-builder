import Toybox.Application.WatchFaceConfig;
import Toybox.Complications;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

class ProbeDelegate extends WatchUi.WatchFaceDelegate {
    private var _view as ProbeView;

    function initialize(view as ProbeView) {
        WatchFaceDelegate.initialize();
        _view = view;
    }

    //! Only fires inside the editor.  Tells the editor which slot was pointed at.
    function onTap(clickEvent as ClickEvent) as Boolean {
        var coords = clickEvent.getCoordinates();
        var slot = _view.slotAt(coords[0], coords[1]);
        if (slot != null) { setSelectedComplication(slot); return true; }
        return false;
    }

    function getComplicationDrawable(complication as ComplicationRef)
            as Drawable or ComplicationDrawableRef or Null {
        var unique = complication.uniqueIdentifier;
        if (unique == null) { return null; }
        _view.setPulsing(unique);
        return _view.drawableFor(unique);
    }

    function onWatchFaceConfigEdited(
            options as {:configId as WatchFaceConfig.Id,
                        :type as WatchFaceConfigType?,
                        :committed as Boolean}) as Void {
        var id = options[:configId] as WatchFaceConfig.Id?;
        if (id != null) {
            var settings = WatchFaceConfig.getSettings(id);
            if (settings != null) { _view.applyConfig(settings); }
        }
    }
}
