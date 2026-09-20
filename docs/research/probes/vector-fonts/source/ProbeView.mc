import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;

//! Probe: vector-fonts. The three build variants differ only in `ProbeFont`
//! (variant-baseline / variant-vector / variant-baked), so the `--build-stats`
//! delta between two builds is the cost of the font mechanism alone.
class ProbeView extends WatchUi.WatchFace {
    private var _font as ProbeFont;

    function initialize() {
        WatchFace.initialize();
        _font = new ProbeFont();
    }

    function onLayout(dc as Dc) as Void {
        _font.load();
    }

    function onUpdate(dc as Dc) as Void {
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);

        var clock = System.getClockTime();
        var text = clock.hour.format("%02d") + ":" + clock.min.format("%02d");

        _font.draw(dc, dc.getWidth() / 2, dc.getHeight() / 2, text);
    }
}
