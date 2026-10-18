import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

//! Upright icon + reading, centred together at runtime: what `type: data`
//! draws today.
class ProbePair {
    private var _icon as FontResource?;

    function initialize() {
    }

    function load() as Void {
        _icon = WatchUi.loadResource($.Rez.Fonts.Clock) as FontResource;
    }

    function draw(dc as Dc, cx as Number, cy as Number, reading as String, glyph as String) as Void {
        var icon = _icon;
        if (icon == null) {
            return;
        }
        var font = Graphics.FONT_SMALL;
        var gap = 4;
        var iw = dc.getTextWidthInPixels(glyph, icon);
        var w = dc.getTextWidthInPixels(reading, font);
        var left = cx - (iw + gap + w) / 2;
        dc.drawText(left, cy, icon, glyph, Graphics.TEXT_JUSTIFY_LEFT | Graphics.TEXT_JUSTIFY_VCENTER);
        dc.drawText(left + iw + gap, cy, font, reading, Graphics.TEXT_JUSTIFY_LEFT | Graphics.TEXT_JUSTIFY_VCENTER);
    }
}
