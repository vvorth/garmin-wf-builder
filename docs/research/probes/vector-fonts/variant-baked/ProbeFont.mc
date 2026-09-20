import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

//! Baked variant: what wfb ships today -- a BMFont sheet rasterised from a
//! TTF at build time (here ChivoMono-Bold at 68 px, glyphs "0123456789:",
//! baked by `wfb.fonts.bmfont`) and compiled into the .prg as a resource.
class ProbeFont {
    private var _baked as FontResource?;

    function load() as Void {
        _baked = WatchUi.loadResource($.Rez.Fonts.Clock) as FontResource;
    }

    function draw(dc as Dc, x as Number, y as Number, text as String) as Void {
        var font = _baked;
        if (font != null) {
            dc.drawText(x, y, font, text,
                        Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
        }
    }
}
