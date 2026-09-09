import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

//! Probe: the exact shape `wfb` wants to generate for a static offscreen
//! buffer.  Nothing here is generated code; it is hand-written to answer
//! questions (a), (b) and (c) in docs/research/probes/static-buffer/README.md.
class ProbeView extends WatchUi.WatchFace {

    //! The nullable form the generator wants.  The Analog sample writes
    //! `as BufferedBitmap`; this asks whether `as BufferedBitmap?` is also
    //! accepted, since the field must hold null on a device that has no
    //! createBufferedBitmap at all.
    private var _static as BufferedBitmap?;

    function initialize() { WatchFace.initialize(); }

    function onLayout(dc as Dc) as Void {
        if (Graphics has :createBufferedBitmap) {
            _static = Graphics.createBufferedBitmap({
                :width => dc.getWidth(),
                :height => dc.getHeight()
            }).get() as BufferedBitmap?;
        } else {
            _static = null;
        }
        var buffer = _static;
        if (buffer != null) {
            renderStatic(buffer.getDc());
        }
    }

    function onUpdate(dc as Dc) as Void {
        dc.clearClip();
        var buffer = _static;
        if (buffer != null) {
            dc.drawBitmap(0, 0, buffer);
        } else {
            renderStatic(dc);
        }
        drawDynamic(dc);
    }

    //! Everything that never changes, drawn once into the buffer -- or
    //! straight onto the screen when there is no buffer.
    private function renderStatic(dc as Dc) as Void {
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(dc.getWidth() / 2, 40, Graphics.FONT_SMALL, "STEPS",
                    Graphics.TEXT_JUSTIFY_CENTER);
        dc.setPenWidth(4);
        dc.drawArc(dc.getWidth() / 2, dc.getHeight() / 2, 100,
                   Graphics.ARC_CLOCKWISE, 90.0, 270.0);
        dc.setPenWidth(1);
    }

    //! Question (a), compile side only: a buffer cleared to COLOR_TRANSPARENT.
    //! `Dc.clear()` is documented since 3.1.0 to honour COLOR_TRANSPARENT as a
    //! background colour, and this compiles -- but whether the unset pixels
    //! then blit *transparently* on a device whose compiler.json says
    //! `alphaBlendingSupport: false` cannot be observed here.  There is no
    //! simulator in this container (CLAUDE.md finding 11).  UNVERIFIED, and
    //! therefore not what shipped: see the README.
    private function renderTransparentProbe(dc as Dc) as Void {
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.clear();
    }

    private function drawDynamic(dc as Dc) as Void {
        dc.setColor(Graphics.COLOR_RED, Graphics.COLOR_TRANSPARENT);
        dc.fillCircle(dc.getWidth() / 2, dc.getHeight() / 2, 6);
    }
}
