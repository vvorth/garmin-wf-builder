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
        // A complete circle is drawn when start and end are equal, so a full
        // sweep must not be allowed to wrap around to its own start angle.
        var sweep = sweepDegrees;
        if (sweep >= 360.0) { sweep = 359.9; }
        if (sweep <= -360.0) { sweep = -359.9; }
        if (sweep == 0.0) { return; }

        // Garmin's degrees increase counter-clockwise (0 is 3 o'clock, 90 is
        // 12 o'clock), so an author's clockwise sweep *subtracts* from the start
        // angle and travels in the ARC_CLOCKWISE direction.
        var endDegrees = startDegrees - sweep;
        while (endDegrees < 0.0) { endDegrees += 360.0; }
        while (endDegrees >= 360.0) { endDegrees -= 360.0; }
        var direction = (sweep > 0)
            ? Graphics.ARC_CLOCKWISE
            : Graphics.ARC_COUNTER_CLOCKWISE;

        dc.setPenWidth(penWidth);
        dc.drawArc(cx, cy, radius, direction, startDegrees.toNumber(), endDegrees.toNumber());
        dc.setPenWidth(1);
    }
}
