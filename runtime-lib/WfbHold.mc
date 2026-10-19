import Toybox.Lang;
import Toybox.Math;

//! A touch and hold on a curved reading: whether it lands on the arc the
//! reading covers, not on the box round every reading it could show.
//!
//! The delegate computes the arc from the width the view drew last frame
//! (`ts/src/kinds/data.ts`'s `radialRunArc` is the host twin).
module WfbHold {

    //! Whether `(x, y)` lies in the band `r0sq <= d^2 <= r1sq` about
    //! `(cx, cy)` and within the arc that starts at `from` (Garmin degrees:
    //! counter-clockwise from 3 o'clock) and turns through `sweep` degrees,
    //! counter-clockwise when positive, clockwise when negative.
    function inArc(x as Number, y as Number, cx as Number, cy as Number, r0sq as Number, r1sq as Number,
                   from as Numeric, sweep as Numeric) as Boolean {
        var dx = x - cx;
        var dy = cy - y;
        var d2 = dx * dx + dy * dy;
        if (d2 < r0sq || d2 > r1sq) {
            return false;
        }
        var size = (sweep < 0) ? -sweep : sweep;
        if (size >= 360) {
            return true;
        }
        var angle = Math.toDegrees(Math.atan2(dy, dx));
        var turn = (sweep < 0) ? from - angle : angle - from;
        while (turn < 0) {
            turn += 360;
        }
        while (turn >= 360) {
            turn -= 360;
        }
        return turn <= size;
    }
}
