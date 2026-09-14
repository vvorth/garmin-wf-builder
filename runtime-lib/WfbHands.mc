//! Analog hands (plan 04): rotate a hand's build-time geometry by the time,
//! then draw it.
//!
//! A hand is authored pointing at 12 o'clock, in a frame whose origin IS the
//! axis (screen convention: +x right, +y down, so the tip of a hand has a
//! negative y).  Everything about that shape is resolved at build time into a
//! per-device Layout constant (`wfb/layout.py`, `wfb/emit/monkeyc.py`); the
//! only arithmetic left for the watch is the rotation, because the angle is
//! the time (ADR 0004, amended).
//!
//! Rotating clockwise by theta on a y-down screen:
//!     x' = x cos(theta) - y sin(theta)
//!     y' = x sin(theta) + y cos(theta)
//! the same transform as the SDK's own Analog sample
//! ($CIQ_SDK/samples/Analog/source/AnalogView.mc, generateHandCoordinates),
//! and verified against a real build in
//! docs/research/probes/analog-hands/, which this file starts from.

import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Math;
import Toybox.System;

module WfbHands {

    //! Hour hand: 30 degrees an hour plus half a degree a minute, so it sits
    //! between numerals at half past rather than jumping on the hour.
    function hourAngle(clock as System.ClockTime) as Float {
        return ((clock.hour % 12) * 60 + clock.min) * (Math.PI / 360.0);
    }

    //! Minute hand: whole minutes, 6 degrees each.
    function minuteAngle(clock as System.ClockTime) as Float {
        return clock.min * (Math.PI / 30.0);
    }

    //! Second hand: whole seconds, 6 degrees each.
    function secondAngle(clock as System.ClockTime) as Float {
        return clock.sec * (Math.PI / 30.0);
    }

    //! A polygon part (a rectangle part is already folded into one at build
    //! time): rotate every vertex about the axis, then fill.  `sin`/`cos`
    //! are typed `Decimal` (`Float or Double`), not `Float` -- Math.sin/cos
    //! are declared to return that union, and a `Float`-typed parameter
    //! fails strict typing (probe finding 2).
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

    //! An outlined circle part (`filled: false`) -- the counterpart to
    //! `fillCircleRotated` added for plan 04; the probe covered only the
    //! filled case.  The caller sets the pen width around this call, the
    //! same convention every other outlined shape in this project follows.
    function drawCircleRotated(dc as Dc, x as Number, y as Number, r as Number,
                               cx as Number, cy as Number,
                               sin as Decimal, cos as Decimal) as Void {
        dc.drawCircle(cx + x * cos - y * sin, cy + x * sin + y * cos, r);
    }
}
