import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Math;
import Toybox.WatchUi;

//! A radial reading with the icon placed after it, so the icon's angle
//! depends on the reading's measured width and its rotation must be applied
//! at runtime: a baked glyph drawn into a BufferedBitmap, then blitted
//! through drawBitmap2's :transform.
class ProbePair {
    private var _icon as FontResource?;
    private var _vector as VectorFont?;
    private var _buffer as BufferedBitmapReference?;

    function initialize() {
    }

    function load() as Void {
        _icon = WatchUi.loadResource($.Rez.Fonts.Clock) as FontResource;
        if (Graphics has :getVectorFont) {
            _vector = Graphics.getVectorFont({:face => "RobotoCondensedBold", :size => 28});
        }
    }

    function draw(dc as Dc, cx as Number, cy as Number, reading as String, glyph as String, start as Float, percent as Number) as Void {
        var icon = _icon;
        var vector = _vector;
        if (icon == null || vector == null) {
            return;
        }
        if (!(Graphics has :createBufferedBitmap) || !(Graphics has :AffineTransform) || !(dc has :drawBitmap2)) {
            return;
        }
        var radius = cx * percent / 100;    // start: Garmin degrees, 3 o'clock = 0, counter-clockwise positive
        var gap = 6;
        dc.drawRadialText(cx, cy, vector, reading,
            Graphics.TEXT_JUSTIFY_LEFT | Graphics.TEXT_JUSTIFY_VCENTER,
            start, radius, Graphics.RADIAL_TEXT_DIRECTION_CLOCKWISE);

        var iw = dc.getTextWidthInPixels(glyph, icon);
        var ih = Graphics.getFontHeight(icon);
        var w = dc.getTextWidthInPixels(reading, vector);
        // Clockwise runs toward smaller Garmin angles; arc length = advance.
        var degrees = start - Math.toDegrees((w + gap + iw / 2.0) / radius);
        var radians = Math.toRadians(degrees);
        var x = cx + radius * Math.cos(radians);
        var y = cy - radius * Math.sin(radians);

        var buffer = _buffer;
        if (buffer == null) {
            // No :palette: drawBitmap2 throws "Source must not use a color
            // palette" for one (simulator, fenix8solar47mm, 2026-10-18).
            buffer = Graphics.createBufferedBitmap({
                :width => iw,
                :height => ih,
            });
            _buffer = buffer;
        }
        var bitmap = buffer.get() as BufferedBitmap?;
        if (bitmap == null) {
            return;
        }
        var bdc = bitmap.getDc();
        bdc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        bdc.clear();
        bdc.drawText(iw / 2, ih / 2, icon, glyph, Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);

        // Rotate about the glyph's own centre so it stands on the circle,
        // facing outward as a clockwise run's glyphs do.
        var transform = new Graphics.AffineTransform();
        transform.translate(iw / 2.0, ih / 2.0);
        transform.rotate(Math.toRadians(90.0 - degrees).toFloat());
        transform.translate(-iw / 2.0, -ih / 2.0);
        dc.drawBitmap2(x - iw / 2.0, y - ih / 2.0, bitmap, {:transform => transform});
    }
}
