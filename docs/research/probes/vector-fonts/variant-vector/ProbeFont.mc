import Toybox.Graphics;
import Toybox.Lang;

//! Vector variant: a device-resident scalable face, asked for at an arbitrary
//! pixel size. Nothing is shipped in the .prg -- `RobotoCondensedBold` is one
//! of the faces the device itself publishes (`simulator.json`,
//! `type: "system_ttf"`).
//!
//! Both the module symbol and the returned font are guarded: `getVectorFont`
//! is absent on most watch-face-capable devices (CLAUDE.md constraint 6), and
//! it returns null for a face the device does not have.
class ProbeFont {
    private var _vector as VectorFont?;

    function load() as Void {
        if (Graphics has :getVectorFont) {
            _vector = Graphics.getVectorFont({
                :face => "RobotoCondensedBold",
                :size => 68
            });
        }
    }

    function draw(dc as Dc, x as Number, y as Number, text as String) as Void {
        var font = _vector;
        if (font != null) {
            dc.drawText(x, y, font, text,
                        Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
        } else {
            dc.drawText(x, y, Graphics.FONT_NUMBER_HOT, text,
                        Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
        }
    }
}
