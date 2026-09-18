import Toybox.Graphics;
import Toybox.Lang;

//! Shared rotate/translate-and-draw helpers for analog hands (plan 04) and
//! patterns (plan 05), plus a pattern's `shape: text` parts (plan 06).  Both
//! resolve a template's geometry once at build time, in a frame whose origin
//! is the axis (a hand) or the pattern's own `at:` (a pattern's template,
//! copy 0 as authored) -- and leave only the per-frame transform to the
//! watch: rotation for a hand or a radial pattern, translation for a linear
//! one.  A text part is the one shape whose *glyphs* never turn -- a bitmap
//! font cannot rotate -- so only its anchor point goes through the rotation;
//! `drawTextRotated` is `dc.drawText` with that same rotate-the-point step in
//! front of it.  Moved out of WfbHands.mc when patterns needed the same four
//! calls (plan 05 §6.3, "one convention, one helper", the precedent
//! WfbArc.mc already set for arcs) -- WfbHands.mc keeps only the three
//! clock-to-angle functions.
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

    //! A text part (plan 06): rotate only the anchor -- the glyphs stay
    //! upright, a bitmap font cannot turn -- round it half up, then draw.
    //!
    //! **Found 2026-09-18:** a single combined `drawTextRotated(dc, x, y,
    //! cx, cy, sin, cos, font, text, justify)` is 10 parameters wide, and
    //! CIQ 3.x rejects a function past 9 outright ("Too many arguments
    //! passed to method 'drawTextRotated'. Only 9 arguments are allowed.",
    //! seen on fenix6/fenix6xpro/fr245 -- `docs/lore/monkeyc.md`). Folding
    //! `cx`/`cy` or `sin`/`cos` into one argument was rejected instead of
    //! fixing this: either shape needs a fresh two-element array (a
    //! `Point2D` or similar) built *inside* this pattern's per-copy draw
    //! loop, which every other helper in this file avoids by taking plain
    //! `Number`/`Decimal` scalars. Splitting the rotate-the-point step from
    //! the draw keeps every argument a scalar and adds no allocation: the
    //! caller (`wfb.emit.monkeyc.rotated`) passes `rotatedX`/`rotatedY`'s
    //! results straight into `dc.drawText` as its own `x`/`y`, exactly the
    //! anchor this used to compute internally. Each axis still rounds half
    //! up (`(v + 0.5).toNumber()`), matching
    //! `wfb.layout.pattern_text_anchor`'s per-axis `math.floor(v + 0.5)`
    //! pixel for pixel, so the preview and the device still agree.
    //!
    //! `text` is typed `String` rather than `drawText`'s own wider `Object`
    //! because every caller here already has a `String`, from a literal or
    //! from `wfb.formatting.emit`'s own `.format(...)`/`.toString()` output
    //! (`docs/lore/monkeyc.md`'s narrowest-type rule).  `justify` keeps
    //! `Dc.drawText`'s own union type: a bitwise-OR'd pair of
    //! `Graphics.TEXT_JUSTIFY_*` flags typechecks as `Lang.Number`, not
    //! `Graphics.TextJustification`, under `-l 3`.
    function rotatedX(x as Number, y as Number, cx as Number,
                      sin as Decimal, cos as Decimal) as Number {
        return (cx + x * cos - y * sin + 0.5).toNumber();
    }

    function rotatedY(x as Number, y as Number, cy as Number,
                      sin as Decimal, cos as Decimal) as Number {
        return (cy + x * sin + y * cos + 0.5).toNumber();
    }
}
