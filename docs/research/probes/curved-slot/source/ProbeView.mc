import Toybox.Graphics;
import Toybox.Lang;
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

        // Three fixed readings of very different widths, each followed by the
        // glyph at the angle its measured width predicts: one still frame
        // shows whether the gap after a radial run stays the same.
        var cx = dc.getWidth() / 2;
        var cy = dc.getHeight() / 2;
        _pair.draw(dc, cx, cy, "1", "8", 150.0, 80);
        _pair.draw(dc, cx, cy, "1234", "8", 150.0, 60);
        _pair.draw(dc, cx, cy, "12345678", "8", 150.0, 40);
    }
}
