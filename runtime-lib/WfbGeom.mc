import Toybox.Graphics;
import Toybox.Lang;

//! Shared rotate/translate-and-draw helpers for analog hands (plan 04) and
//! patterns (plan 05).  Both resolve a template's geometry once at build
//! time, in a frame whose origin is the axis (a hand) or the pattern's own
//! `at:` (a pattern's template, copy 0 as authored) -- and leave only the
//! per-frame transform to the watch: rotation for a hand or a radial
//! pattern, translation for a linear one.  Moved out of WfbHands.mc when
//! patterns needed the same four calls (plan 05 §6.3, "one convention, one
//! helper", the precedent WfbArc.mc already set for arcs) -- WfbHands.mc
//! keeps only the three clock-to-angle functions.
//!
//! Rotating clockwise by theta on a y-down screen:
//!     x' = x cos(theta) - y sin(theta)
//!     y' = x sin(theta) + y cos(theta)
//! the same transform as the SDK's own Analog sample
//! ($CIQ_SDK/samples/Analog/source/AnalogView.mc, generateHandCoordinates),
//! and verified against a real build in
//! docs/research/probes/analog-hands/, which this file started from.
//!
//! `sin`/`cos` are typed `Decimal` (`Float or Double`), not `Float` --
//! `Math.sin`/`Math.cos` are declared to return that union, and a
//! `Float`-typed parameter fails strict typing (docs/lore/monkeyc.md).
module WfbGeom {

    //! A polygon part (a rectangle part is already folded into one at build
    //! time): rotate every vertex about the centre, then fill.
    function fillRotated(dc as Dc, points as Array<Graphics.Point2D>,
                         cx as Number, cy as Number,
                         sin as Decimal, cos as Decimal) as Void {
        var n = points.size();
        var out = new Array<Graphics.Point2D>[n];
        for (var i = 0; i < n; i++) {
            var p = points[i];
            var x = p[0];
            var y = p[1];
            out[i] = [cx + x * cos - y * sin, cy + x * sin + y * cos];
        }
        dc.fillPolygon(out);
    }

    //! A line part: rotate both endpoints; the pen width is the caller's.
    function drawLineRotated(dc as Dc, x1 as Number, y1 as Number,
                             x2 as Number, y2 as Number,
                             cx as Number, cy as Number,
                             sin as Decimal, cos as Decimal) as Void {
        dc.drawLine(cx + x1 * cos - y1 * sin, cy + x1 * sin + y1 * cos,
                    cx + x2 * cos - y2 * sin, cy + x2 * sin + y2 * cos);
    }

    //! A filled circle part: only its centre moves; a circle is its own
    //! rotation.
    function fillCircleRotated(dc as Dc, x as Number, y as Number, r as Number,
                               cx as Number, cy as Number,
                               sin as Decimal, cos as Decimal) as Void {
        dc.fillCircle(cx + x * cos - y * sin, cy + x * sin + y * cos, r);
    }

    //! An outlined circle part (`filled: false`).  The caller sets the pen
    //! width around this call, the same convention every other outlined
    //! shape in this project follows.
    function drawCircleRotated(dc as Dc, x as Number, y as Number, r as Number,
                               cx as Number, cy as Number,
                               sin as Decimal, cos as Decimal) as Void {
        dc.drawCircle(cx + x * cos - y * sin, cy + x * sin + y * cos, r);
    }

    //! A polygon part in a *linear* pattern (plan 05 §6.4): no rotation, just
    //! translate every vertex by the current copy's own origin.  A hand
    //! never calls this -- only a linear pattern ever translates rather than
    //! rotates.
    function fillTranslated(dc as Dc, points as Array<Graphics.Point2D>,
                            ox as Number, oy as Number) as Void {
        var n = points.size();
        var out = new Array<Graphics.Point2D>[n];
        for (var i = 0; i < n; i++) {
            var p = points[i];
            out[i] = [ox + p[0], oy + p[1]];
        }
        dc.fillPolygon(out);
    }
}
