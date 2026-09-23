import Toybox.Graphics;
import Toybox.Lang;

//! A moving 2x2 pixel mask over the AOD frame (`aod: {mask: ...}`, plan 16
//! slice 1, docs/guide/always-on-display.md).
module WfbAodMask {

    //! Force every pixel except one per on-screen 2x2 tile to black, moving
    //! which pixel of each tile stays lit once a minute.
    //!
    //! `phase = minute mod 4` selects `(dx, dy)` from the fixed 4-cycle
    //! `[(0,0), (1,0), (1,1), (0,1)]` -- each step moves to a 4-neighbour,
    //! never a diagonal jump, and 60/1440 are both multiples of 4 so the
    //! cycle stays continuous across the hour and the day. The pixel kept
    //! lit at device coordinate `(x, y)` is exactly the one with
    //! `x mod 2 == dx` and `y mod 2 == dy`; every other pixel is blacked
    //! out. The black set is `{y mod 2 != dy} union {x mod 2 != dx}` --
    //! every other row plus every other column -- so this is two loops of
    //! 1px `fillRectangle` strips, never a bitmap: no alpha, no
    //! `BufferedBitmap`, no graphics-pool memory, and it runs on every
    //! device (`Dc.fillRectangle`/`setColor`/`getWidth`/`getHeight` and
    //! `System.getClockTime` are universal). Anti-aliasing is turned off
    //! first so the 1px strips land on exact pixels, the same guard
    //! `applyAntiAlias` uses.
    //!
    //! Called once per AOD frame, after every element the frame draws, with
    //! `minute` from `System.getClockTime().min` (0-59).
    function apply(dc as Dc, minute as Number) as Void {
        var phase = minute % 4;
        var dx = (phase == 1 || phase == 2) ? 1 : 0;
        var dy = (phase >= 2) ? 1 : 0;
        if (dc has :setAntiAlias) {
            dc.setAntiAlias(false);
        }
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        var w = dc.getWidth();
        var h = dc.getHeight();
        for (var y = 1 - dy; y < h; y += 2) {
            dc.fillRectangle(0, y, w, 1);
        }
        for (var x = 1 - dx; x < w; x += 2) {
            dc.fillRectangle(x, 0, 1, h);
        }
    }
}
