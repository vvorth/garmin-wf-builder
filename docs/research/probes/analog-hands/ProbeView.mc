//! Probe: what the generated view for a `type: hands` element could look like.
//!
//! Questions this build answers (compile-time only -- no simulator here):
//!  1. Do Float vertices satisfy fillPolygon's Array<Graphics.Point2D> under
//!     `-l 3` strict typing, when built in a loop into `new Array<Point2D>[n]`?
//!  2. Do Math.sin/Math.cos results (declared `Float or Double`) pass into a
//!     `Decimal` parameter without a cast?
//!  3. Do drawLine/fillCircle accept Float coordinates under strict typing?
//!  4. Does a `_sleeping` flag set by onEnterSleep/onExitSleep, gating only the
//!     second hand, build warning-free with no always_on mode in play?

import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Math;
import Toybox.System;
import Toybox.WatchUi;

class SliceView extends WatchUi.WatchFace {
    //! Whether the watch is asleep.  The second hand is drawn only while
    //! awake: asleep, onUpdate runs once a minute, and a second hand drawn
    //! then would sit frozen at whatever second that update happened to land on.
    private var _sleeping as Boolean = false;

    function initialize() {
        WatchFace.initialize();
    }

    function onLayout(dc as Dc) as Void {
    }

    function onUpdate(dc as Dc) as Void {
        dc.clearClip();
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();
        var clock = System.getClockTime();
        drawMainHands(dc, clock);
        drawSubSeconds(dc, clock);
    }

    function onExitSleep() as Void {
        _sleeping = false;
        WatchUi.requestUpdate();
    }

    function onEnterSleep() as Void {
        _sleeping = true;
        WatchUi.requestUpdate();
    }

    //! `main_hands` -- hands `classic`, axis at (130, 130).
    private function drawMainHands(dc as Dc, clock as System.ClockTime) as Void {
        var cx = Layout.MAIN_HANDS_CX;
        var cy = Layout.MAIN_HANDS_CY;

        // hour
        var angle = WfbHands.hourAngle(clock);
        var sin = Math.sin(angle);
        var cos = Math.cos(angle);
        dc.setColor(0xFFFFFF, Graphics.COLOR_TRANSPARENT);
        WfbHands.fillRotated(dc, Layout.MAIN_HANDS_HOUR_0_POINTS, cx, cy, sin, cos);

        // minute
        angle = WfbHands.minuteAngle(clock);
        sin = Math.sin(angle);
        cos = Math.cos(angle);
        dc.setColor(0xFFFFFF, Graphics.COLOR_TRANSPARENT);
        WfbHands.fillRotated(dc, Layout.MAIN_HANDS_MINUTE_0_POINTS, cx, cy, sin, cos);
        dc.setColor(0xAAAAAA, Graphics.COLOR_TRANSPARENT);
        WfbHands.fillCircleRotated(dc, Layout.MAIN_HANDS_MINUTE_1_X, Layout.MAIN_HANDS_MINUTE_1_Y,
                                   Layout.MAIN_HANDS_MINUTE_1_RADIUS, cx, cy, sin, cos);

        // second -- seconds: awake
        if (!_sleeping) {
            angle = WfbHands.secondAngle(clock);
            sin = Math.sin(angle);
            cos = Math.cos(angle);
            dc.setColor(0xFF5500, Graphics.COLOR_TRANSPARENT);
            dc.setPenWidth(Layout.MAIN_HANDS_SECOND_0_THICKNESS);
            WfbHands.drawLineRotated(dc, Layout.MAIN_HANDS_SECOND_0_X1, Layout.MAIN_HANDS_SECOND_0_Y1,
                                     Layout.MAIN_HANDS_SECOND_0_X2, Layout.MAIN_HANDS_SECOND_0_Y2,
                                     cx, cy, sin, cos);
            dc.setPenWidth(1);
            WfbHands.fillCircleRotated(dc, Layout.MAIN_HANDS_SECOND_1_X, Layout.MAIN_HANDS_SECOND_1_Y,
                                       Layout.MAIN_HANDS_SECOND_1_RADIUS, cx, cy, sin, cos);
        }
    }

    //! `sub_seconds` -- hands `small_seconds`, axis at (130, 195), off centre.
    private function drawSubSeconds(dc as Dc, clock as System.ClockTime) as Void {
        if (!_sleeping) {
            var angle = WfbHands.secondAngle(clock);
            dc.setColor(0xFFFFFF, Graphics.COLOR_TRANSPARENT);
            WfbHands.fillRotated(dc, Layout.SUB_SECONDS_SECOND_0_POINTS,
                                 Layout.SUB_SECONDS_CX, Layout.SUB_SECONDS_CY,
                                 Math.sin(angle), Math.cos(angle));
        }
    }
}
