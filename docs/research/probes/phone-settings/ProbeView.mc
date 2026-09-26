import Toybox.Application;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;

class ProbeView extends WatchUi.WatchFace {
    private var _showSeconds as Boolean = true;

    function initialize() {
        WatchFace.initialize();
        applySettings();
    }

    // Variants B and C.  A property read is null-checked and type-checked:
    // Garmin Connect has been known to push a value of the wrong type.
    (:settings)
    function applySettings() as Void {
        var value = Properties.getValue("ShowSeconds");
        _showSeconds = (value instanceof Boolean) ? value : true;
    }

    // Variant A: no properties at all.
    (:nosettings)
    function applySettings() as Void {}

    function onUpdate(dc as Dc) as Void {
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();
        var t = System.getClockTime();
        var s = t.hour.format("%02d") + ":" + t.min.format("%02d");
        if (_showSeconds) { s += ":" + t.sec.format("%02d"); }
        dc.drawText(dc.getWidth() / 2, dc.getHeight() / 2, Graphics.FONT_MEDIUM, s,
                    Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
    }
}
