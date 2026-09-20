import Toybox.Graphics;
import Toybox.Lang;

//! Baseline variant: a system bitmap font (`FONT_NUMBER_HOT`). It costs the
//! app nothing -- the glyphs are already on the watch -- so this build is the
//! zero point the other two variants are measured against.
class ProbeFont {
    function load() as Void {
    }

    function draw(dc as Dc, x as Number, y as Number, text as String) as Void {
        dc.drawText(x, y, Graphics.FONT_NUMBER_HOT, text,
                    Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
    }
}
