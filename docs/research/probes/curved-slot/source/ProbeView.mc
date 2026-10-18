import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;

//! Probe: curved-slot. The two build variants differ only in `ProbePair`
//! (variant-baseline / variant-curved), so the `--build-stats` delta is the
//! cost of a curved reading with a rotated icon and nothing else.
class ProbeView extends WatchUi.WatchFace {
    private var _pair as ProbePair;

    function initialize() {
        WatchFace.initialize();
        _pair = new ProbePair();
    }

    function onLayout(dc as Dc) as Void {
        _pair.load();
    }

    function onUpdate(dc as Dc) as Void {
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);

        // A reading whose width is only known at runtime, as a slot's is.
        var clock = System.getClockTime();
        var reading = (clock.min * 173).toString();

        _pair.draw(dc, dc.getWidth() / 2, dc.getHeight() / 2, reading, "8");
    }
}
