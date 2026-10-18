import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Math;
import Toybox.WatchUi;

//! The gap question alone: a radial reading, and two thin radial ticks just
//! outside it at the angles its measured width predicts for the run's start
//! and end. If the device lays a run out to getTextWidthInPixels, the
//! digits sit exactly between the two ticks, on every row.
class ProbePair {
    private var _vector as VectorFont?;

    function initialize() {
    }

    function load() as Void {
        if (Graphics has :getVectorFont) {
            _vector = Graphics.getVectorFont({:face => "RobotoCondensedBold", :size => 28});
        }
    }

    function draw(dc as Dc, cx as Number, cy as Number, reading as String, glyph as String, start as Float, percent as Number) as Void {
        var vector = _vector;
        if (vector == null) {
            return;
        }
        var radius = cx * percent / 100;    // start: Garmin degrees, 3 o'clock = 0, counter-clockwise positive
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawRadialText(cx, cy, vector, reading,
            Graphics.TEXT_JUSTIFY_LEFT | Graphics.TEXT_JUSTIFY_VCENTER,
            start, radius, Graphics.RADIAL_TEXT_DIRECTION_CLOCKWISE);

        // Clockwise runs toward smaller Garmin angles; arc length = advance.
        var w = dc.getTextWidthInPixels(reading, vector);
        var end = (start - Math.toDegrees(w.toFloat() / radius)).toFloat();
        dc.setColor(Graphics.COLOR_RED, Graphics.COLOR_TRANSPARENT);
        dc.setPenWidth(2);
        tick(dc, cx, cy, start, radius + 16);
        tick(dc, cx, cy, end, radius + 16);
    }

    //! A short radial line from `inner` to `inner + 10` px at Garmin angle `degrees`.
    private function tick(dc as Dc, cx as Number, cy as Number, degrees as Float, inner as Number) as Void {
        var t = Math.toRadians(degrees);
        var c = Math.cos(t), s = Math.sin(t);
        dc.drawLine(cx + inner * c, cy - inner * s, cx + (inner + 10) * c, cy - (inner + 10) * s);
    }
}
