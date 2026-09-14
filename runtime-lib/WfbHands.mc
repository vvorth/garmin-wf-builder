//! Analog hands (plan 04): convert the current time into each hand's own
//! rotation angle.
//!
//! Drawing itself -- turning a hand's build-time-resolved geometry by that
//! angle, or (for a pattern, plan 05) turning or translating a template's --
//! lives in WfbGeom.mc, the "one convention, one helper" precedent WfbArc.mc
//! already set for arcs (plan 05 §6.3).

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
}
