import Toybox.Graphics;
import Toybox.Lang;

//! A 1px `outline:` ring for a polygon, line or outlined circle (research
//! 19): the part transformed **once**, then drawn at the four points one
//! pixel away (`wfb.ir.RING_OFFSETS`, in its order).  Its own module, apart
//! from `WfbGeom`, so a face that draws no ring compiles none of it -- the
//! barrel copies in only the modules the generated code calls
//! (`wfb.emit.usage.barrel_modules`).
//!
//! Rotation is `WfbGeom`'s own (`x' = x cos - y sin`, `y' = x sin + y cos`).
module WfbRing {

    //! A polygon part's 1px `outline:` ring (research 19): the four fills
    //! one pixel left, up, down and right of it.  Rotates the vertices
    //! once and shifts that one array between fills, where a stamp through
    //! `WfbGeom.fillRotated` would rotate and allocate a fresh array per offset --
    //! measured on a fenix 8 at twice the cost of the fills themselves
    //! (research 19 §4.5).
    function rotated(dc as Dc, points as Array<Graphics.Point2D>,
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
        polygon(dc, out);
    }

    //! `rotated` for a linear pattern's (or a shape's own) polygon:
    //! translated by `(ox, oy)` instead of rotated.
    function translated(dc as Dc, points as Array<Graphics.Point2D>,
                        ox as Number, oy as Number) as Void {
        var n = points.size();
        var out = new Array<Graphics.Point2D>[n];
        for (var i = 0; i < n; i++) {
            var p = points[i];
            out[i] = [ox + p[0], oy + p[1]];
        }
        polygon(dc, out);
    }

    //! Fill ``out`` at the four offsets, shifting it in place: (-1, 0),
    //! (0, -1), (0, 1), (1, 0) -- `wfb.ir.RING_OFFSETS`'s order.
    function polygon(dc as Dc, out as Array<Graphics.Point2D>) as Void {
        shift(out, -1, 0);
        dc.fillPolygon(out);
        shift(out, 1, -1);
        dc.fillPolygon(out);
        shift(out, 0, 2);
        dc.fillPolygon(out);
        shift(out, 1, -1);
        dc.fillPolygon(out);
    }

    function shift(out as Array<Graphics.Point2D>, dx as Number, dy as Number) as Void {
        for (var i = 0; i < out.size(); i++) {
            var p = out[i];
            p[0] = p[0] + dx;
            p[1] = p[1] + dy;
        }
    }

    //! A line part's 1px ring: both ends rotated once, then four lines one
    //! pixel off; the pen width is the caller's.
    function lineRotated(dc as Dc, x1 as Number, y1 as Number,
                         x2 as Number, y2 as Number,
                         cx as Number, cy as Number,
                         sin as Decimal, cos as Decimal) as Void {
        var ax = cx + x1 * cos - y1 * sin;
        var ay = cy + x1 * sin + y1 * cos;
        var bx = cx + x2 * cos - y2 * sin;
        var by = cy + x2 * sin + y2 * cos;
        dc.drawLine(ax - 1, ay, bx - 1, by);
        dc.drawLine(ax, ay - 1, bx, by - 1);
        dc.drawLine(ax, ay + 1, bx, by + 1);
        dc.drawLine(ax + 1, ay, bx + 1, by);
    }

    //! An outlined circle part's 1px ring: the centre rotated once, then
    //! four circles one pixel off; the pen width is the caller's.
    function circleRotated(dc as Dc, x as Number, y as Number, r as Number,
                           cx as Number, cy as Number,
                           sin as Decimal, cos as Decimal) as Void {
        var px = cx + x * cos - y * sin;
        var py = cy + x * sin + y * cos;
        dc.drawCircle(px - 1, py, r);
        dc.drawCircle(px, py - 1, r);
        dc.drawCircle(px, py + 1, r);
        dc.drawCircle(px + 1, py, r);
    }

}
