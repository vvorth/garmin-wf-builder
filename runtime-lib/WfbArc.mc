import Toybox.Graphics;
import Toybox.Lang;

//! Progress arcs.
//!
//! Garmin has no filled-sector primitive -- there is no `fillArc`, `fillSector`
//! or `drawSector` anywhere in the API.  A ring is `setPenWidth` plus `drawArc`
//! and nothing else, which is why thickness is a pen width, cap style is not
//! selectable, and true annuli and gradient sweeps are not offered.
module WfbArc {

    //! Draw `fraction` (0..1) of an arc.
    //!
    //! @param startDegrees Garmin convention: 3 o'clock is 0, counter-clockwise
    //!        positive.  The generator has already converted from the author's
    //!        clockwise-from-12 angles.
    //! @param sweepDegrees Signed sweep in the author's clockwise sense.
    function drawProgress(
        dc as Graphics.Dc,
        cx as Number, cy as Number, radius as Number, penWidth as Number,
        startDegrees as Float, sweepDegrees as Float, fraction as Float
    ) as Void {
        if (fraction <= 0.0 || radius <= 0) { return; }
        // A fill under half a degree draws nothing; see drawSpan.
        var swept = sweepDegrees * ((fraction > 1.0) ? 1.0 : fraction);
        drawSpan(dc, cx, cy, radius, penWidth, startDegrees, swept);
    }

    //! Draw a fixed span, used for a progress element's unfilled track.
    function drawSpan(
        dc as Graphics.Dc,
        cx as Number, cy as Number, radius as Number, penWidth as Number,
        startDegrees as Float, sweepDegrees as Float
    ) as Void {
        if (radius <= 0) { return; }

        // drawArc takes whole degrees and draws a COMPLETE CIRCLE when start
        // and end are equal.  So the decision is made on the whole-degree
        // sweep, not the Float one: rounding start and end separately let a
        // sub-degree progress fill (a few steps into the day) truncate to
        // start == end and paint the whole ring in the fill colour.
        var sweep = roundAway(sweepDegrees);
        if (sweep == 0) { return; }
        if (sweep > 360) { sweep = 360; }
        if (sweep < -360) { sweep = -360; }

        // Garmin's degrees increase counter-clockwise (0 is 3 o'clock, 90 is
        // 12 o'clock), so an author's clockwise sweep *subtracts* from the start
        // angle and travels in the ARC_CLOCKWISE direction.
        var start = roundAway(startDegrees) % 360;
        if (start < 0) { start += 360; }
        var end = (start - sweep) % 360;
        if (end < 0) { end += 360; }
        // |sweep| == 360 lands end back on start: the one case where the full
        // circle is what the author asked for.
        var direction = (sweep > 0)
            ? Graphics.ARC_CLOCKWISE
            : Graphics.ARC_COUNTER_CLOCKWISE;

        dc.setPenWidth(penWidth);
        dc.drawArc(cx, cy, radius, direction, start, end);
        dc.setPenWidth(1);
    }

    //! Round half away from zero.  `toNumber` alone truncates towards zero,
    //! which would make a clockwise and an anticlockwise sweep of the same
    //! size round differently.
    function roundAway(degrees as Float) as Number {
        return (degrees < 0.0)
            ? (degrees - 0.5).toNumber()
            : (degrees + 0.5).toNumber();
    }
}
