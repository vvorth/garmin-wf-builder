import Toybox.Application;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

class ProbeDelegate extends WatchUi.WatchFaceDelegate {
    function initialize() { WatchFaceDelegate.initialize(); }

    // E1: an editor-only callback, its body guarded by the module check
    function onWatchFaceConfigEdited(options as {
        :configId as $.Toybox.Application.WatchFaceConfig.Id,
        :type as WatchFaceConfigType?,
        :committed as $.Toybox.Lang.Boolean}) as Void {
        if (Application has :WatchFaceConfig) {
            if (options[:type] != WatchUi.WATCH_FACE_CONFIG_TYPE_COMPLICATION) {
                return;
            }
            var id = options[:configId] as WatchFaceConfig.Id?;
            if (id != null) {
                WatchFaceConfig.getSettings(id);
            }
        }
    }

    // E2: an editor-only callback with no guard at all
    function onTap(clickEvent as ClickEvent) as Boolean {
        setSelectedComplication(1);
        return true;
    }

    // E3: a WatchUi constant under its own check
    function e3(type as WatchFaceConfigType?) as Boolean {
        return (WatchUi has :WATCH_FACE_CONFIG_TYPE_COMPLICATION) && type != WatchUi.WATCH_FACE_CONFIG_TYPE_COMPLICATION;
    }

    // E4: an inherited method under a check on self
    function e4() as Void {
        if (self has :setSelectedComplication) {
            setSelectedComplication(1);
        }
    }

    // E5: an inherited method under a check on its class
    function e5() as Void {
        if (WatchUi.WatchFaceDelegate has :setSelectedComplication) {
            setSelectedComplication(1);
        }
    }

    // E6: a class method under a check on the instance
    function e6() as Graphics.BoundingBox {
        var box = new Graphics.BoundingBox();
        if (box has :addRectangle) {
            box.addRectangle(0, 0, 10, 10);
        }
        return box;
    }

    // E7: a class constructor under a check on the class
    function e7(d as WatchUi.Drawable, box as Graphics.BoundingBox) as WatchUi.ComplicationDrawableRef? {
        if (WatchUi has :ComplicationDrawableRef) {
            return new WatchUi.ComplicationDrawableRef({ :drawable => d, :boundingBox => box });
        }
        return null;
    }

    // E8: a class method under the editor's module check (Application.WatchFaceConfig), a different module
    function e8() as Graphics.BoundingBox {
        var box = new Graphics.BoundingBox();
        if (Application has :WatchFaceConfig) {
            box.addRectangle(0, 0, 10, 10);
        }
        return box;
    }
}
