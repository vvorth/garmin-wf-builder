import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Math;

//! The icon catalogue, drawn from `Dc` primitives.
//!
//! Icons are drawn rather than shipped as bitmaps: they cost no resource memory,
//! need no per-screen-size asset, and take their colour from whatever the caller
//! last set.  Each function draws inside a `size` x `size` square centred on
//! (cx, cy), so the generator can treat every icon identically.
//!
//! The caller sets the colour; these functions never do.
module WfbIcons {

    //! Two offset footprints.
    //!
    //! `fillEllipse` takes *semi*-axes, so the two soles must be at least
    //! `2 * soleWidth` apart or they merge into a blob at small sizes.
    function drawSteps(dc as Graphics.Dc, cx as Number, cy as Number, size as Number) as Void {
        var s = size.toFloat();
        var soleWidth = (s * 0.15).toNumber();
        var soleHeight = (s * 0.26).toNumber();
        var gap = (s * 0.24).toNumber();
        var lift = (s * 0.10).toNumber();
        var toeWidth = (s * 0.30).toNumber();
        var toeHeight = (s * 0.10).toNumber();

        // Back foot, slightly low; front foot, slightly high.
        drawFoot(dc, cx - gap, cy + lift, soleWidth, soleHeight, toeWidth, toeHeight);
        drawFoot(dc, cx + gap, cy - lift, soleWidth, soleHeight, toeWidth, toeHeight);
    }

    //! One footprint: an elliptical sole with a toe bar above it.
    //!
    //! Module members take no access modifier -- `hidden` and `private` are
    //! class-member keywords and the compiler rejects them here.
    function drawFoot(
        dc as Graphics.Dc, cx as Number, cy as Number,
        soleWidth as Number, soleHeight as Number, toeWidth as Number, toeHeight as Number
    ) as Void {
        dc.fillEllipse(cx, cy, soleWidth, soleHeight);
        dc.fillRoundedRectangle(cx - toeWidth / 2, cy - soleHeight - toeHeight - 1,
                                toeWidth, toeHeight, toeHeight / 2);
    }

    //! A heart: two lobes over a triangular point.
    function drawHeart(dc as Graphics.Dc, cx as Number, cy as Number, size as Number) as Void {
        var s = size.toFloat();
        var lobe = (s * 0.26).toNumber();
        var lobeY = cy - (s * 0.14).toNumber();
        var spread = (s * 0.22).toNumber();

        dc.fillCircle(cx - spread, lobeY, lobe);
        dc.fillCircle(cx + spread, lobeY, lobe);
        dc.fillPolygon([
            [cx - spread - lobe, lobeY] as Point2D,
            [cx + spread + lobe, lobeY] as Point2D,
            [cx, cy + (s * 0.46).toNumber()] as Point2D
        ] as Array<Point2D>);
    }

    //! A flame.
    function drawFlame(dc as Graphics.Dc, cx as Number, cy as Number, size as Number) as Void {
        var s = size.toFloat();
        var top = cy - (s * 0.48).toNumber();
        var bottom = cy + (s * 0.42).toNumber();
        var half = (s * 0.30).toNumber();

        dc.fillPolygon([
            [cx, top] as Point2D,
            [cx + half, cy - (s * 0.02).toNumber()] as Point2D,
            [cx + (half * 0.7).toNumber(), bottom] as Point2D,
            [cx - (half * 0.7).toNumber(), bottom] as Point2D,
            [cx - half, cy - (s * 0.02).toNumber()] as Point2D
        ] as Array<Point2D>);
    }
}
