import Toybox.Graphics;
import Toybox.Lang;

//! A 2px or 3px `outline:` ring for a polygon, line or outlined circle
//! (research 19): `WfbRing`'s 1px functions, walking the build's
//! `Layout.OUTLINE_OFFSETS_<W>` table (`discPerimeterOffsets`) for
//! the points instead of spelling four out.  Its own module, so a face
//! whose rings are all 1px compiles none of it.
//!
//! Rotation is `WfbGeom`'s own (`x' = x cos - y sin`, `y' = x sin + y cos`).
module WfbRingWide {

    //! A polygon part's ring: rotated once, then filled at every ``offsets``
    //! point (flat `[dx0, dy0, dx1, dy1, ...]`).
    function rotated(dc as Dc, points as Array<Graphics.Point2D>,
                     cx as Number, cy as Number,
                     sin as Decimal, cos as Decimal,
                     offsets as Array<Number>) as Void {
        var n = points.size();
        var out = new Array<Graphics.Point2D>[n];
        for (var i = 0; i < n; i++) {
            var p = points[i];
            var x = p[0];
            var y = p[1];
            out[i] = [cx + x * cos - y * sin, cy + x * sin + y * cos];
        }
        polygon(dc, out, offsets);
    }

    //! `rotated` for a linear pattern's polygon: translated by `(ox, oy)`.
    function translated(dc as Dc, points as Array<Graphics.Point2D>,
                        ox as Number, oy as Number,
                        offsets as Array<Number>) as Void {
        var n = points.size();
        var out = new Array<Graphics.Point2D>[n];
        for (var i = 0; i < n; i++) {
            var p = points[i];
            out[i] = [ox + p[0], oy + p[1]];
        }
        polygon(dc, out, offsets);
    }

    //! Fill ``out`` at every ``offsets`` point, shifting it in place from
    //! one point to the next.
    function polygon(dc as Dc, out as Array<Graphics.Point2D>,
                     offsets as Array<Number>) as Void {
        var px = 0;
        var py = 0;
        for (var i = 0; i < offsets.size(); i += 2) {
            shift(out, offsets[i] - px, offsets[i + 1] - py);
            px = offsets[i];
            py = offsets[i + 1];
            dc.fillPolygon(out);
        }
    }

    //! A line part's ring: both ends rotated once, then one line per point;
    //! the pen width is the caller's.  The line's ends come as one
    //! `[x1, y1, x2, y2]`, keeping the call within the nine parameters a
    //! barrel function may take.
    function lineRotated(dc as Dc, ends as Array<Number>,
                         cx as Number, cy as Number,
                         sin as Decimal, cos as Decimal,
                         offsets as Array<Number>) as Void {
        var x1 = ends[0];
        var y1 = ends[1];
        var x2 = ends[2];
        var y2 = ends[3];
        var ax = cx + x1 * cos - y1 * sin;
        var ay = cy + x1 * sin + y1 * cos;
        var bx = cx + x2 * cos - y2 * sin;
        var by = cy + x2 * sin + y2 * cos;
        for (var i = 0; i < offsets.size(); i += 2) {
            var dx = offsets[i];
            var dy = offsets[i + 1];
            dc.drawLine(ax + dx, ay + dy, bx + dx, by + dy);
        }
    }

    //! An outlined circle part's ring: the centre rotated once, then one
    //! circle per point; the pen width is the caller's.
    function circleRotated(dc as Dc, x as Number, y as Number, r as Number,
                           cx as Number, cy as Number,
                           sin as Decimal, cos as Decimal,
                           offsets as Array<Number>) as Void {
        var px = cx + x * cos - y * sin;
        var py = cy + x * sin + y * cos;
        for (var i = 0; i < offsets.size(); i += 2) {
            dc.drawCircle(px + offsets[i], py + offsets[i + 1], r);
        }
    }

    function shift(out as Array<Graphics.Point2D>, dx as Number, dy as Number) as Void {
        for (var i = 0; i < out.size(); i++) {
            var p = out[i];
            p[0] = p[0] + dx;
            p[1] = p[1] + dy;
        }
    }

}
