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

    //! An alarm clock: a circle face, two "feet" ticks, and two hands.
    //!
    //! Pure outline, drawn with `drawCircle`/`drawLine` rather than a fill, so
    //! it reads correctly against any background colour.
    function drawAlarm(dc as Graphics.Dc, cx as Number, cy as Number, size as Number) as Void {
        var r = size.toFloat() / 2.0;
        var stroke = (r * 0.18).toNumber();
        if (stroke < 1) { stroke = 1; }
        dc.setPenWidth(stroke);

        var faceY = cy + (r * 0.1).toNumber();
        dc.drawCircle(cx, faceY, (r * 0.66).toNumber());
        dc.drawLine(cx - (r * 0.72).toNumber(), cy - (r * 0.44).toNumber(),
                    cx - (r * 0.40).toNumber(), cy - (r * 0.72).toNumber());
        dc.drawLine(cx + (r * 0.72).toNumber(), cy - (r * 0.44).toNumber(),
                    cx + (r * 0.40).toNumber(), cy - (r * 0.72).toNumber());
        dc.drawLine(cx, faceY, cx, cy - (r * 0.30).toNumber());
        dc.drawLine(cx, faceY, cx + (r * 0.34).toNumber(), cy + (r * 0.24).toNumber());
        dc.setPenWidth(1);
    }

    //! A bell with a diagonal slash through it, for "do not disturb".
    //!
    //! Drawn as outline strokes throughout, rather than a solid bell with a
    //! background-coloured gap punched through the slash: that trick (the
    //! reference face this catalogue was modelled on uses it) only reads
    //! correctly over the one background colour it was punched with. An
    //! outline bell needs no background colour at all, so it is correct behind
    //! anything the author draws underneath it.
    function drawDnd(dc as Graphics.Dc, cx as Number, cy as Number, size as Number) as Void {
        var r = size.toFloat() / 2.0;
        var stroke = (r * 0.16).toNumber();
        if (stroke < 1) { stroke = 1; }
        dc.setPenWidth(stroke);

        dc.drawCircle(cx, cy - (r * 0.14).toNumber(), (r * 0.44).toNumber());
        var left = cx - (r * 0.68).toNumber();
        var shoulderL = cx - (r * 0.44).toNumber();
        var shoulderR = cx + (r * 0.44).toNumber();
        var right = cx + (r * 0.68).toNumber();
        var shoulderY = cy + (r * 0.14).toNumber();
        var footY = cy + (r * 0.42).toNumber();
        dc.drawLine(left, footY, shoulderL, shoulderY);
        dc.drawLine(shoulderL, shoulderY, shoulderR, shoulderY);
        dc.drawLine(shoulderR, shoulderY, right, footY);
        dc.fillCircle(cx, cy - (r * 0.68).toNumber(), (r * 0.11).toNumber());
        dc.fillCircle(cx, cy + (r * 0.60).toNumber(), (r * 0.13).toNumber());
        dc.drawLine(cx - (r * 0.86).toNumber(), cy + (r * 0.86).toNumber(),
                    cx + (r * 0.86).toNumber(), cy - (r * 0.86).toNumber());
        dc.setPenWidth(1);
    }

    //! A speech-bubble badge.
    //!
    //! Solid fill only, so unlike `drawDnd` this one has no background
    //! dependency to avoid. The caller draws a count on top and colours it to
    //! match the background when the count is zero, so an idle badge shows an
    //! empty bubble rather than a stray "0".
    function drawNotification(dc as Graphics.Dc, cx as Number, cy as Number, size as Number) as Void {
        var r = size.toFloat() / 2.0;
        dc.fillRoundedRectangle(cx - (r * 0.85).toNumber(), cy - (r * 0.75).toNumber(),
                                (r * 1.7).toNumber(), (r * 1.2).toNumber(), (r * 0.30).toNumber());
        dc.fillPolygon([
            [cx - (r * 0.24).toNumber(), cy + (r * 0.40).toNumber()] as Point2D,
            [cx + (r * 0.24).toNumber(), cy + (r * 0.40).toNumber()] as Point2D,
            [cx - (r * 0.04).toNumber(), cy + (r * 0.85).toNumber()] as Point2D
        ] as Array<Point2D>);
    }
}
